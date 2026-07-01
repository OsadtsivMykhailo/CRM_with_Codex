from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import generics, mixins, permissions, status, viewsets
from rest_framework.authtoken.models import Token
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from accounts.models import User
from accounts.permissions import IsAdmin
from accounts.serializers import UserSerializer
from .models import AuditLog, ClientProfile, DeletionRequest, DirectClientAccess, Notification
from .serializers import (
    AssignClientSerializer,
    AuditLogSerializer,
    ClientRegistrationSerializer,
    ClientSerializer,
    DeletionDecisionSerializer,
    DeletionRequestCreateSerializer,
    DeletionRequestSerializer,
    NotificationSerializer,
    RejectRegistrationSerializer,
    UnassignedClientSerializer,
)
from .services import (
    accessible_clients,
    audit,
    expire_stale_deletion_requests,
    grant_creator_access,
    notify,
    notify_admins,
)


class ClientViewSet(viewsets.ModelViewSet):
    serializer_class = ClientSerializer

    def get_queryset(self):
        return accessible_clients(self.request.user).order_by("-updated_at")

    def list(self, request, *args, **kwargs):
        if request.user.role == User.Role.CLIENT:
            raise PermissionDenied("Клієнту доступна лише власна анкета.")
        return super().list(request, *args, **kwargs)

    def perform_create(self, serializer):
        if self.request.user.role != User.Role.EMPLOYEE:
            raise PermissionDenied("Лише працівники можуть створювати анкети.")
        client = serializer.save(created_by=self.request.user)
        grant_creator_access(client, self.request.user)
        audit(self.request.user, "client.created", client, {"fields": list(serializer.validated_data)})

    def perform_update(self, serializer):
        client = serializer.save()
        action_name = "client.self_updated" if self.request.user.role == User.Role.CLIENT else "client.updated"
        audit(self.request.user, action_name, client, {"fields": list(serializer.validated_data)})

    def destroy(self, request, *args, **kwargs):
        return Response(
            {"detail": "Видалення доступне лише через погоджений запит."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    @action(detail=False, methods=["get"])
    def mine(self, request):
        if request.user.role != User.Role.CLIENT:
            raise PermissionDenied("Цей розділ призначений для клієнта.")
        client = self.get_queryset().first()
        if not client:
            raise NotFound("Анкету не знайдено.")
        return Response(self.get_serializer(client).data)

    @action(detail=False, methods=["get"], permission_classes=[IsAdmin])
    def unassigned(self, request):
        clients = ClientProfile.objects.filter(
            is_deleted=False,
        ).exclude(pool_reason=ClientProfile.PoolReason.NONE).order_by("created_at")
        return Response(UnassignedClientSerializer(clients, many=True).data)

    @action(detail=True, methods=["post"], permission_classes=[IsAdmin])
    @transaction.atomic
    def assign(self, request, pk=None):
        serializer = AssignClientSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            client = ClientProfile.objects.get(
                pk=pk,
                is_deleted=False,
            )
            if client.pool_reason == ClientProfile.PoolReason.NONE:
                raise ClientProfile.DoesNotExist
        except ClientProfile.DoesNotExist as exc:
            raise NotFound("Клієнта немає у пулі нерозподілених анкет.") from exc
        employee = User.objects.get(pk=serializer.validated_data["employee_id"])
        DirectClientAccess.objects.create(client=client, employee=employee, granted_by=request.user)
        client.pool_reason = ClientProfile.PoolReason.NONE
        client.save(update_fields=["pool_reason", "updated_at"])
        audit(request.user, "client.assigned", client, {"employee_id": employee.id})
        notify(
            employee,
            "client_assigned",
            "Вам призначено клієнта",
            f"Ви отримали доступ до анкети «{client.display_name}».",
            client,
        )
        Notification.objects.filter(
            user=request.user,
            kind="client_self_registered",
            entity_id=str(client.id),
            read_at__isnull=True,
        ).update(read_at=timezone.now())
        return Response(UnassignedClientSerializer(client).data)

    @action(detail=True, methods=["post"], permission_classes=[IsAdmin], url_path="reject-registration")
    @transaction.atomic
    def reject_registration(self, request, pk=None):
        serializer = RejectRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            client = ClientProfile.objects.select_related("user").get(
                pk=pk,
                is_deleted=False,
                created_by__isnull=True,
                user__isnull=False,
                pool_reason=ClientProfile.PoolReason.SELF_REGISTERED,
            )
        except ClientProfile.DoesNotExist as exc:
            raise NotFound("У пулі немає такої самостійної реєстрації.") from exc

        client.is_deleted = True
        client.pool_reason = ClientProfile.PoolReason.NONE
        client.save(update_fields=["is_deleted", "pool_reason", "updated_at"])
        client.user.is_active = False
        client.user.save(update_fields=["is_active"])
        Token.objects.filter(user=client.user).delete()
        reason = serializer.validated_data["reason"]
        audit(request.user, "client.registration_rejected", client, {"reason": reason})
        Notification.objects.filter(
            kind="client_self_registered", entity_id=str(client.id), read_at__isnull=True
        ).update(read_at=timezone.now())
        return Response(status=status.HTTP_204_NO_CONTENT)


class DeletionRequestViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = DeletionRequestSerializer

    def get_queryset(self):
        expire_stale_deletion_requests()
        queryset = DeletionRequest.objects.select_related("client", "requested_by", "decided_by")
        if self.request.user.role == User.Role.ADMIN:
            return queryset
        if self.request.user.role == User.Role.EMPLOYEE:
            return queryset.filter(requested_by=self.request.user)
        return queryset.none()

    def create(self, request, *args, **kwargs):
        if request.user.role != User.Role.EMPLOYEE:
            raise PermissionDenied("Запит може створити лише працівник із доступом до анкети.")
        input_serializer = DeletionRequestCreateSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        try:
            client = accessible_clients(request.user).get(pk=input_serializer.validated_data["client_id"])
        except ClientProfile.DoesNotExist as exc:
            raise PermissionDenied("У вас немає доступу до цієї анкети.") from exc

        if DeletionRequest.objects.filter(client=client, status=DeletionRequest.Status.PENDING).exists():
            raise ValidationError("Для цієї анкети вже є активний запит.")
        cooldown_start = timezone.now() - timedelta(days=3)
        if DeletionRequest.objects.filter(
            client=client,
            status=DeletionRequest.Status.REJECTED,
            decided_at__gt=cooldown_start,
        ).exists():
            raise ValidationError("Після ручного відхилення повторний запит доступний через три дні.")

        item = DeletionRequest.objects.create(
            client=client,
            requested_by=request.user,
            reason=input_serializer.validated_data["reason"],
            expires_at=timezone.now() + timedelta(days=7),
        )
        audit(request.user, "deletion_request.created", item, {"client_id": client.id})
        notify_admins(
            "deletion_request_created",
            "Новий запит на видалення анкети",
            f"{request.user.get_full_name() or request.user.username}: {client.display_name}",
            item,
        )
        return Response(self.get_serializer(item).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], permission_classes=[IsAdmin])
    @transaction.atomic
    def decision(self, request, pk=None):
        expire_stale_deletion_requests()
        item = self.get_object()
        if item.status != DeletionRequest.Status.PENDING:
            raise ValidationError("Рішення щодо цього запиту вже прийнято.")
        serializer = DeletionDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        decision = serializer.validated_data["decision"]
        item.status = decision
        item.decided_by = request.user
        item.decided_at = timezone.now()
        item.decision_note = serializer.validated_data.get("note", "")
        item.save(update_fields=["status", "decided_by", "decided_at", "decision_note"])

        if decision == DeletionRequest.Status.APPROVED:
            item.client.is_deleted = True
            item.client.save(update_fields=["is_deleted", "updated_at"])
            title = "Запит на видалення схвалено"
            message = f"Анкету «{item.client.display_name}» видалено."
            email = False
        else:
            title = "Запит на видалення відхилено"
            message = f"Запит щодо «{item.client.display_name}» відхилено."
            if item.decision_note:
                message += f"\nПричина відхилення: {item.decision_note}"
            email = True
        audit(request.user, f"deletion_request.{decision}", item, {"client_id": item.client_id})
        notify(item.requested_by, f"deletion_request_{decision}", title, message, item, email=email)
        Notification.objects.filter(
            kind="deletion_request_created", entity_id=str(item.id), read_at__isnull=True
        ).update(read_at=timezone.now())
        return Response(self.get_serializer(item).data)


class NotificationViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = NotificationSerializer

    def get_queryset(self):
        expire_stale_deletion_requests()
        return Notification.objects.filter(user=self.request.user)

    @action(detail=False, methods=["get"], url_path="unread-count")
    def unread_count(self, request):
        return Response({"count": self.get_queryset().filter(read_at__isnull=True).count()})

    @action(detail=True, methods=["post"], url_path="mark-read")
    def mark_read(self, request, pk=None):
        try:
            item = self.get_queryset().get(pk=pk)
        except Notification.DoesNotExist as exc:
            raise NotFound("Повідомлення не знайдено.") from exc
        if not item.read_at:
            item.read_at = timezone.now()
            item.save(update_fields=["read_at"])
        return Response(self.get_serializer(item).data)


class AuditLogPagination(PageNumberPagination):
    page_size = 30
    page_size_query_param = "page_size"
    max_page_size = 100


class AuditLogListView(generics.ListAPIView):
    serializer_class = AuditLogSerializer
    permission_classes = [IsAdmin]
    pagination_class = AuditLogPagination

    def get_queryset(self):
        queryset = AuditLog.objects.select_related("actor").all()
        actor_id = self.request.query_params.get("actor")
        client_id = self.request.query_params.get("client")
        action_name = self.request.query_params.get("action")
        search = self.request.query_params.get("search", "").strip()
        date_from = parse_date(self.request.query_params.get("date_from", ""))
        date_to = parse_date(self.request.query_params.get("date_to", ""))
        if actor_id:
            queryset = queryset.filter(actor_id=actor_id)
        if client_id:
            queryset = queryset.filter(entity_type="crm.ClientProfile", entity_id=str(client_id))
        if action_name:
            queryset = queryset.filter(action=action_name)
        if search:
            queryset = queryset.filter(
                Q(entity_label__icontains=search)
                | Q(action__icontains=search)
                | Q(actor__username__icontains=search)
                | Q(actor__first_name__icontains=search)
                | Q(actor__last_name__icontains=search)
            )
        if date_from:
            queryset = queryset.filter(created_at__date__gte=date_from)
        if date_to:
            queryset = queryset.filter(created_at__date__lte=date_to)
        return queryset


@api_view(["GET"])
@permission_classes([IsAdmin])
def audit_actions(request):
    actions = AuditLog.objects.order_by("action").values_list("action", flat=True).distinct()
    return Response(list(actions))


@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def register_client(request):
    serializer = ClientRegistrationSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    user, profile, token = serializer.save()
    audit(user, "client.self_registered", profile, {"fields": list(serializer.validated_data)})
    notify_admins(
        "client_self_registered",
        "Новий клієнт зареєструвався",
        f"Анкета «{profile.display_name}» очікує призначення працівника.",
        profile,
    )
    return Response({"token": token.key, "user": UserSerializer(user).data}, status=status.HTTP_201_CREATED)
