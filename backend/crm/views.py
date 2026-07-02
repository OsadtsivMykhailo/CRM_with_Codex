from datetime import timedelta

from pathlib import Path

from django.core.mail import EmailMultiAlternatives
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
from .mailing import email_connection, personalization_errors
from .models import (
    AuditLog,
    ClientGroup,
    ClientGroupAdditionRequest,
    ClientGroupCreationRequest,
    ClientProfile,
    DeletionRequest,
    DirectClientAccess,
    EmailCampaign,
    EmailCampaignAttachment,
    EmailServerConfiguration,
    EmailTemplate,
    Notification,
    SharedSender,
)
from .serializers import (
    AssignClientSerializer,
    AuditLogSerializer,
    ClientRegistrationSerializer,
    ClientSerializer,
    ClientGroupSerializer,
    ClientGroupAdditionRequestCreateSerializer,
    ClientGroupAdditionRequestSerializer,
    ClientGroupCreationRequestCreateSerializer,
    ClientGroupCreationRequestSerializer,
    ClientGroupRequestDecisionSerializer,
    DeletionDecisionSerializer,
    DeletionRequestCreateSerializer,
    DeletionRequestSerializer,
    NotificationSerializer,
    EmailCampaignSerializer,
    EmailPreferenceSerializer,
    EmailServerConfigurationSerializer,
    EmailTemplateSerializer,
    RejectRegistrationSerializer,
    UnassignedClientSerializer,
    SharedSenderSerializer,
)
from .services import (
    accessible_clients,
    audit,
    expire_stale_deletion_requests,
    expire_stale_requests,
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
        group = serializer.validated_data.pop("_selected_client_group", None)
        client = serializer.save(created_by=self.request.user)
        grant_creator_access(client, self.request.user)
        if group:
            group.clients.add(client)
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

    @action(detail=False, methods=["get", "patch"], url_path="email-preferences")
    def email_preferences(self, request):
        if request.user.role != User.Role.CLIENT:
            raise PermissionDenied("Цей розділ призначений для клієнта.")
        try:
            profile = ClientProfile.objects.get(user=request.user, is_deleted=False)
        except ClientProfile.DoesNotExist as exc:
            raise NotFound("Анкету не знайдено.") from exc
        if request.method == "GET":
            return Response(EmailPreferenceSerializer(profile).data)
        serializer = EmailPreferenceSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        old_value = profile.marketing_email_consent
        profile = serializer.save(marketing_email_consent_updated_at=timezone.now())
        audit(
            request.user,
            "client.email_preference_updated",
            profile,
            {"marketing_email_consent": [old_value, profile.marketing_email_consent]},
        )
        return Response(EmailPreferenceSerializer(profile).data)

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
        assignee_type = serializer.validated_data["assignee_type"]
        assignee_id = serializer.validated_data["assignee_id"]
        if assignee_type == "employee":
            employee = User.objects.get(pk=assignee_id)
            if not DirectClientAccess.objects.filter(
                client=client, employee=employee, revoked_at__isnull=True
            ).exists():
                DirectClientAccess.objects.create(client=client, employee=employee, granted_by=request.user)
            audit(request.user, "client.assigned", client, {"employee_id": employee.id})
            notify(
                employee,
                "client_assigned",
                "Вам призначено клієнта",
                f"Ви отримали доступ до анкети «{client.display_name}».",
                client,
            )
        else:
            group = ClientGroup.objects.get(pk=assignee_id)
            group.clients.add(client)
            audit(request.user, "client.assigned_to_group", client, {"group_id": group.id})
            for employee in group.editors.filter(role=User.Role.EMPLOYEE, is_active=True):
                notify(
                    employee,
                    "client_assigned_via_group",
                    "Групі призначено клієнта",
                    f"Групі «{group.name}» призначено клієнта «{client.display_name}».",
                    client,
                )
        client.pool_reason = ClientProfile.PoolReason.NONE
        client.save(update_fields=["pool_reason", "updated_at"])
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


class ClientGroupAdditionRequestViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = ClientGroupAdditionRequestSerializer

    def get_queryset(self):
        expire_stale_requests()
        queryset = ClientGroupAdditionRequest.objects.select_related(
            "client", "group", "requested_by", "decided_by"
        )
        if self.request.user.role == User.Role.ADMIN:
            return queryset
        if self.request.user.role == User.Role.EMPLOYEE:
            return queryset.filter(requested_by=self.request.user)
        return queryset.none()

    def create(self, request, *args, **kwargs):
        if request.user.role != User.Role.EMPLOYEE:
            raise PermissionDenied("Запит може створити лише працівник.")
        input_serializer = ClientGroupAdditionRequestCreateSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        try:
            client = ClientProfile.objects.get(
                pk=input_serializer.validated_data["client_id"],
                is_deleted=False,
                direct_accesses__employee=request.user,
                direct_accesses__revoked_at__isnull=True,
            )
        except ClientProfile.DoesNotExist as exc:
            raise PermissionDenied("Запит доступний лише для клієнта з вашим особистим доступом.") from exc
        try:
            group = ClientGroup.objects.get(
                pk=input_serializer.validated_data["group_id"],
                editors=request.user,
            )
        except ClientGroup.DoesNotExist as exc:
            raise PermissionDenied("Можна обрати лише групу, до якої ви маєте доступ.") from exc
        if group.clients.filter(pk=client.pk).exists():
            raise ValidationError("Клієнт уже входить до цієї групи.")
        if ClientGroupAdditionRequest.objects.filter(
            client=client,
            group=group,
            status=ClientGroupAdditionRequest.Status.PENDING,
        ).exists():
            raise ValidationError("Для цього клієнта і групи вже є активний запит.")
        cooldown_start = timezone.now() - timedelta(days=3)
        if ClientGroupAdditionRequest.objects.filter(
            client=client,
            group=group,
            status=ClientGroupAdditionRequest.Status.REJECTED,
            decided_at__gt=cooldown_start,
        ).exists():
            raise ValidationError("Після ручного відхилення повторний запит доступний через три дні.")
        item = ClientGroupAdditionRequest.objects.create(
            client=client,
            group=group,
            requested_by=request.user,
            reason=input_serializer.validated_data["reason"],
            expires_at=timezone.now() + timedelta(days=7),
        )
        audit(request.user, "client_group_addition_request.created", item, {
            "client_id": client.id,
            "group_id": group.id,
        })
        notify_admins(
            "client_group_addition_request_created",
            "Новий запит на додавання клієнта до групи",
            f"{client.display_name} → {group.name}. Причина: {item.reason}",
            item,
        )
        return Response(self.get_serializer(item).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], permission_classes=[IsAdmin])
    @transaction.atomic
    def decision(self, request, pk=None):
        expire_stale_requests()
        item = self.get_object()
        if item.status != ClientGroupAdditionRequest.Status.PENDING:
            raise ValidationError("Рішення щодо цього запиту вже прийнято.")
        serializer = ClientGroupRequestDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        decision = serializer.validated_data["decision"]
        item.status = decision
        item.decided_by = request.user
        item.decided_at = timezone.now()
        item.decision_note = serializer.validated_data.get("note", "")
        item.save(update_fields=["status", "decided_by", "decided_at", "decision_note"])
        if decision == ClientGroupAdditionRequest.Status.APPROVED:
            item.group.clients.add(item.client)
            title = "Додавання клієнта до групи схвалено"
            message = f"«{item.client.display_name}» додано до групи «{item.group.name}»."
            email = False
        else:
            title = "Додавання клієнта до групи відхилено"
            message = f"Запит щодо «{item.client.display_name}» і групи «{item.group.name}» відхилено."
            if item.decision_note:
                message += f"\nПричина відхилення: {item.decision_note}"
            email = True
        audit(request.user, f"client_group_addition_request.{decision}", item, {
            "client_id": item.client_id,
            "group_id": item.group_id,
        })
        notify(item.requested_by, f"client_group_addition_request_{decision}", title, message, item, email=email)
        Notification.objects.filter(
            kind="client_group_addition_request_created",
            entity_id=str(item.id),
            read_at__isnull=True,
        ).update(read_at=timezone.now())
        return Response(self.get_serializer(item).data)


class ClientGroupCreationRequestViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = ClientGroupCreationRequestSerializer

    def get_queryset(self):
        expire_stale_requests()
        queryset = ClientGroupCreationRequest.objects.select_related(
            "requested_by", "decided_by", "created_group"
        ).prefetch_related("proposed_clients", "proposed_employees")
        if self.request.user.role == User.Role.ADMIN:
            return queryset
        if self.request.user.role == User.Role.EMPLOYEE:
            return queryset.filter(requested_by=self.request.user)
        return queryset.none()

    @action(detail=False, methods=["get"])
    def options(self, request):
        if request.user.role != User.Role.EMPLOYEE:
            raise PermissionDenied("Варіанти доступні лише працівникам.")
        clients = [
            {"id": client.id, "display_name": client.display_name}
            for client in accessible_clients(request.user).order_by("company_name", "first_name", "last_name")
        ]
        employees = [
            {
                "id": employee.id,
                "username": employee.username,
                "first_name": employee.first_name,
                "last_name": employee.last_name,
            }
            for employee in User.objects.filter(role=User.Role.EMPLOYEE, is_active=True).order_by(
                "first_name", "last_name", "username"
            )
        ]
        return Response({"clients": clients, "employees": employees})

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        if request.user.role != User.Role.EMPLOYEE:
            raise PermissionDenied("Запит може створити лише працівник.")
        input_serializer = ClientGroupCreationRequestCreateSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        name = input_serializer.validated_data["proposed_name"].strip()
        if ClientGroup.objects.filter(name__iexact=name).exists():
            raise ValidationError({"proposed_name": "Група з такою назвою вже існує."})
        if ClientGroupCreationRequest.objects.filter(
            requested_by=request.user,
            proposed_name__iexact=name,
            status=ClientGroupCreationRequest.Status.PENDING,
        ).exists():
            raise ValidationError("У вас уже є активний запит на створення групи з такою назвою.")
        cooldown_start = timezone.now() - timedelta(days=3)
        if ClientGroupCreationRequest.objects.filter(
            requested_by=request.user,
            proposed_name__iexact=name,
            status=ClientGroupCreationRequest.Status.REJECTED,
            decided_at__gt=cooldown_start,
        ).exists():
            raise ValidationError("Після ручного відхилення повторний запит доступний через три дні.")
        client_ids = set(input_serializer.validated_data["proposed_client_ids"])
        clients = list(accessible_clients(request.user).filter(pk__in=client_ids))
        if {client.id for client in clients} != client_ids:
            raise PermissionDenied("Серед запропонованих є недоступні вам клієнти.")
        employee_ids = set(input_serializer.validated_data["proposed_employee_ids"])
        employees = list(User.objects.filter(
            pk__in=employee_ids,
            role=User.Role.EMPLOYEE,
            is_active=True,
        ))
        if {employee.id for employee in employees} != employee_ids:
            raise ValidationError({"proposed_employee_ids": "Серед вибраних є неактивні або невідомі працівники."})
        item = ClientGroupCreationRequest.objects.create(
            proposed_name=name,
            reason=input_serializer.validated_data["reason"],
            requested_by=request.user,
            expires_at=timezone.now() + timedelta(days=7),
        )
        item.proposed_clients.set(clients)
        item.proposed_employees.set(employees)
        audit(request.user, "client_group_creation_request.created", item, {
            "proposed_name": name,
            "client_ids": sorted(client_ids),
            "employee_ids": sorted(employee_ids),
        })
        notify_admins(
            "client_group_creation_request_created",
            "Новий запит на створення групи клієнтів",
            f"Запропонована група «{name}». Причина: {item.reason}",
            item,
        )
        return Response(self.get_serializer(item).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], permission_classes=[IsAdmin])
    @transaction.atomic
    def decision(self, request, pk=None):
        expire_stale_requests()
        item = self.get_object()
        if item.status != ClientGroupCreationRequest.Status.PENDING:
            raise ValidationError("Рішення щодо цього запиту вже прийнято.")
        serializer = ClientGroupRequestDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        decision = serializer.validated_data["decision"]
        if decision == ClientGroupCreationRequest.Status.APPROVED:
            if not item.requested_by.is_active or item.requested_by.role != User.Role.EMPLOYEE:
                raise ValidationError("Автор запиту більше не є активним працівником.")
            if ClientGroup.objects.filter(name__iexact=item.proposed_name).exists():
                raise ValidationError("Група з такою назвою вже існує.")
            group = ClientGroup.objects.create(name=item.proposed_name, created_by=request.user)
            editors = list(item.proposed_employees.filter(role=User.Role.EMPLOYEE, is_active=True))
            editors.append(item.requested_by)
            group.editors.set({employee.id: employee for employee in editors}.values())
            group.clients.set(item.proposed_clients.filter(is_deleted=False))
            item.created_group = group
            title = "Створення групи схвалено"
            message = f"Групу «{group.name}» створено. Ви призначені відповідальним працівником."
            email = False
        else:
            title = "Створення групи відхилено"
            message = f"Запит на створення групи «{item.proposed_name}» відхилено."
            if serializer.validated_data.get("note"):
                message += f"\nПричина відхилення: {serializer.validated_data['note']}"
            email = True
        item.status = decision
        item.decided_by = request.user
        item.decided_at = timezone.now()
        item.decision_note = serializer.validated_data.get("note", "")
        item.save(update_fields=[
            "status", "decided_by", "decided_at", "decision_note", "created_group"
        ])
        audit(request.user, f"client_group_creation_request.{decision}", item, {
            "proposed_name": item.proposed_name,
            "created_group_id": item.created_group_id,
        })
        notify(item.requested_by, f"client_group_creation_request_{decision}", title, message, item, email=email)
        Notification.objects.filter(
            kind="client_group_creation_request_created",
            entity_id=str(item.id),
            read_at__isnull=True,
        ).update(read_at=timezone.now())
        return Response(self.get_serializer(item).data)


class NotificationViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = NotificationSerializer

    def get_queryset(self):
        expire_stale_requests()
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


class EmailServerConfigurationView(generics.RetrieveUpdateAPIView):
    serializer_class = EmailServerConfigurationSerializer
    permission_classes = [IsAdmin]

    def get_object(self):
        configuration, _ = EmailServerConfiguration.objects.get_or_create(pk=1)
        return configuration

    def perform_update(self, serializer):
        configuration = serializer.save()
        audit(
            self.request.user,
            "email_server.updated",
            configuration,
            {"fields": list(serializer.validated_data.keys())},
        )


class EmailServerTestView(generics.GenericAPIView):
    permission_classes = [IsAdmin]

    def post(self, request):
        try:
            configuration = EmailServerConfiguration.objects.get(pk=1, is_active=True)
            connection = email_connection(configuration)
            message = EmailMultiAlternatives(
                subject="Multisoft CRM — перевірка SMTP",
                body="SMTP-підключення працює.",
                from_email=request.user.email,
                to=[request.user.email],
                connection=connection,
            )
            message.send(fail_silently=False)
        except Exception as exc:
            raise ValidationError(f"Не вдалося надіслати тестовий лист: {exc}") from exc
        audit(request.user, "email_server.test_succeeded", configuration, {})
        return Response({"detail": f"Тестовий лист надіслано на {request.user.email}."})


class SharedSenderViewSet(viewsets.ModelViewSet):
    serializer_class = SharedSenderSerializer

    def get_queryset(self):
        queryset = SharedSender.objects.prefetch_related("allowed_employees")
        if self.request.user.role == User.Role.ADMIN:
            return queryset.order_by("name")
        if self.request.user.role == User.Role.EMPLOYEE:
            return queryset.filter(is_active=True, allowed_employees=self.request.user).order_by("name")
        return queryset.none()

    def _admin_only(self):
        if self.request.user.role != User.Role.ADMIN:
            raise PermissionDenied("Загальні адреси налаштовує лише адміністратор.")

    def perform_create(self, serializer):
        self._admin_only()
        sender = serializer.save()
        audit(self.request.user, "shared_sender.created", sender, {"email": sender.email})

    def perform_update(self, serializer):
        self._admin_only()
        sender = serializer.save()
        audit(self.request.user, "shared_sender.updated", sender, {"fields": list(serializer.validated_data)})

    def perform_destroy(self, instance):
        self._admin_only()
        instance.is_active = False
        instance.save(update_fields=["is_active", "updated_at"])
        audit(self.request.user, "shared_sender.deactivated", instance, {})


class EmailTemplateViewSet(viewsets.ModelViewSet):
    serializer_class = EmailTemplateSerializer

    def get_queryset(self):
        if self.request.user.role == User.Role.ADMIN:
            return EmailTemplate.objects.filter(scope=EmailTemplate.Scope.COMPANY).select_related("owner")
        if self.request.user.role == User.Role.EMPLOYEE:
            return EmailTemplate.objects.filter(
                Q(scope=EmailTemplate.Scope.COMPANY) | Q(owner=self.request.user)
            ).select_related("owner")
        return EmailTemplate.objects.none()

    def perform_create(self, serializer):
        user = self.request.user
        if user.role == User.Role.ADMIN:
            if serializer.validated_data["scope"] != EmailTemplate.Scope.COMPANY:
                raise ValidationError("Адміністратор може створювати лише спільні шаблони.")
            template = serializer.save(owner=None, created_by=user)
        elif user.role == User.Role.EMPLOYEE:
            if serializer.validated_data["scope"] != EmailTemplate.Scope.PERSONAL:
                raise ValidationError("Працівник може створювати лише особисті шаблони.")
            template = serializer.save(owner=user, created_by=user)
        else:
            raise PermissionDenied("Шаблони недоступні.")
        audit(user, "email_template.created", template, {"scope": template.scope})

    def _assert_editable(self, template):
        user = self.request.user
        if user.role == User.Role.ADMIN and template.scope == EmailTemplate.Scope.COMPANY:
            return
        if user.role == User.Role.EMPLOYEE and template.owner_id == user.id:
            return
        raise PermissionDenied("Ви не можете редагувати цей шаблон.")

    def perform_update(self, serializer):
        self._assert_editable(serializer.instance)
        template = serializer.save()
        audit(self.request.user, "email_template.updated", template, {"fields": list(serializer.validated_data)})

    def perform_destroy(self, instance):
        self._assert_editable(instance)
        audit(self.request.user, "email_template.deleted", instance, {})
        instance.delete()


class ClientGroupViewSet(viewsets.ModelViewSet):
    serializer_class = ClientGroupSerializer

    def get_queryset(self):
        queryset = ClientGroup.objects.prefetch_related("clients", "editors")
        if self.request.user.role == User.Role.ADMIN:
            return queryset.order_by("name")
        if self.request.user.role == User.Role.EMPLOYEE:
            return queryset.filter(editors=self.request.user).order_by("name")
        return queryset.none()

    @action(detail=False, methods=["get"], permission_classes=[IsAdmin], url_path="client-options")
    def client_options(self, request):
        clients = ClientProfile.objects.filter(is_deleted=False).order_by(
            "company_name", "first_name", "last_name"
        )
        return Response([
            {
                "id": client.id,
                "display_name": client.display_name,
                "status": client.status,
            }
            for client in clients
        ])

    @transaction.atomic
    def perform_create(self, serializer):
        user = self.request.user
        if user.role != User.Role.ADMIN:
            raise PermissionDenied("Групи клієнтів створює лише адміністратор.")
        clients = serializer.validated_data.pop("clients", [])
        editors = serializer.validated_data.pop("editors", [])
        if not editors:
            raise ValidationError("Призначте групі хоча б одного працівника.")
        if ClientGroup.objects.filter(name__iexact=serializer.validated_data["name"].strip()).exists():
            raise ValidationError({"name": "Група з такою назвою вже існує."})
        group = serializer.save(created_by=user)
        group.editors.set(editors)
        group.clients.set(clients)
        audit(user, "client_group.created", group, {
            "editors": [item.id for item in editors],
            "clients": [item.id for item in clients],
        })

    @transaction.atomic
    def perform_update(self, serializer):
        if self.request.user.role != User.Role.ADMIN:
            raise PermissionDenied("Групи клієнтів редагує лише адміністратор.")
        clients = serializer.validated_data.pop("clients", None)
        editors = serializer.validated_data.pop("editors", None)
        if editors is not None and not editors:
            raise ValidationError("Призначте групі хоча б одного працівника.")
        name = serializer.validated_data.get("name")
        if name and ClientGroup.objects.filter(name__iexact=name.strip()).exclude(
            pk=serializer.instance.pk
        ).exists():
            raise ValidationError({"name": "Група з такою назвою вже існує."})
        group = serializer.save()
        if clients is not None:
            group.clients.set(clients)
        if editors is not None:
            group.editors.set(editors)
        audit(self.request.user, "client_group.updated", group, {
            "fields": list(serializer.validated_data),
            "clients": [item.id for item in clients] if clients is not None else None,
            "editors": [item.id for item in editors] if editors is not None else None,
        })

    def destroy(self, request, *args, **kwargs):
        return Response(
            {"detail": "Видалення груп буде додано разом із процесом погодження зміни доступів."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )


class EmailCampaignViewSet(viewsets.ModelViewSet):
    serializer_class = EmailCampaignSerializer

    def get_queryset(self):
        if self.request.user.role != User.Role.EMPLOYEE:
            return EmailCampaign.objects.none()
        return EmailCampaign.objects.filter(created_by=self.request.user).select_related(
            "template", "shared_sender"
        ).prefetch_related("recipients__client", "attachments")

    def perform_create(self, serializer):
        if self.request.user.role != User.Role.EMPLOYEE:
            raise PermissionDenied("Розсилки можуть створювати лише працівники.")
        campaign = serializer.save()
        audit(
            self.request.user,
            "email_campaign.draft_created",
            campaign,
            {"recipient_count": campaign.total_recipients, "message_type": campaign.message_type},
        )

    def perform_update(self, serializer):
        campaign = serializer.save()
        audit(self.request.user, "email_campaign.draft_updated", campaign, {"fields": list(serializer.validated_data)})

    def perform_destroy(self, instance):
        if instance.status != EmailCampaign.Status.DRAFT:
            raise ValidationError("Надіслану або поставлену в чергу розсилку видалити не можна.")
        audit(self.request.user, "email_campaign.draft_deleted", instance, {})
        instance.delete()

    @action(detail=True, methods=["post"])
    def attachment(self, request, pk=None):
        campaign = self.get_object()
        if campaign.status != EmailCampaign.Status.DRAFT:
            raise ValidationError("Вкладення можна додати лише до чернетки.")
        uploaded = request.FILES.get("file")
        if not uploaded:
            raise ValidationError("Оберіть файл.")
        allowed_extensions = {".pdf", ".docx", ".xlsx", ".png", ".jpg", ".jpeg", ".zip"}
        if Path(uploaded.name).suffix.lower() not in allowed_extensions:
            raise ValidationError("Дозволено PDF, DOCX, XLSX, PNG, JPG та ZIP.")
        current_size = sum(campaign.attachments.values_list("size", flat=True))
        if current_size + uploaded.size > 10 * 1024 * 1024:
            raise ValidationError("Сумарний розмір вкладень не може перевищувати 10 МБ.")
        attachment = EmailCampaignAttachment.objects.create(
            campaign=campaign,
            file=uploaded,
            original_name=uploaded.name,
            content_type=uploaded.content_type or "",
            size=uploaded.size,
        )
        audit(self.request.user, "email_campaign.attachment_added", campaign, {"name": uploaded.name})
        return Response({"id": attachment.id, "name": attachment.original_name}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def queue(self, request, pk=None):
        campaign = self.get_object()
        if campaign.status != EmailCampaign.Status.DRAFT:
            raise ValidationError("Розсилку вже поставлено в чергу.")
        if not campaign.recipients.exists():
            raise ValidationError("У розсилці немає одержувачів.")
        allowed_client_ids = set(
            accessible_clients(request.user)
            .exclude(status=ClientProfile.Status.ARCHIVED)
            .values_list("id", flat=True)
        )
        campaign_client_ids = set(campaign.recipients.values_list("client_id", flat=True))
        if not campaign_client_ids.issubset(allowed_client_ids):
            raise ValidationError("Доступ до одного або кількох одержувачів було втрачено.")
        if campaign.sender_type == EmailCampaign.SenderType.SHARED and not SharedSender.objects.filter(
            pk=campaign.shared_sender_id,
            is_active=True,
            allowed_employees=request.user,
        ).exists():
            raise ValidationError("Обрана загальна адреса більше не доступна.")
        if campaign.sender_type == EmailCampaign.SenderType.PERSONAL and (
            campaign.from_email.casefold() != request.user.email.casefold()
        ):
            raise ValidationError("Корпоративний email працівника змінився. Оновіть чернетку перед надсиланням.")
        configuration, _ = EmailServerConfiguration.objects.get_or_create(pk=1)
        errors = personalization_errors(
            campaign,
            campaign.recipients.select_related("client").all(),
            configuration.company_name,
        )
        if errors:
            raise ValidationError({"personalization": errors})
        campaign.status = EmailCampaign.Status.QUEUED
        campaign.queued_at = timezone.now()
        campaign.save(update_fields=["status", "queued_at", "updated_at"])
        audit(
            request.user,
            "email_campaign.queued",
            campaign,
            {"recipient_count": campaign.total_recipients, "from_email": campaign.from_email},
        )
        return Response(self.get_serializer(campaign).data)


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


@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def unsubscribe_marketing(request, token):
    try:
        profile = ClientProfile.objects.get(unsubscribe_token=token, is_deleted=False)
    except ClientProfile.DoesNotExist as exc:
        raise NotFound("Посилання для відписки недійсне.") from exc
    changed = profile.marketing_email_consent
    profile.marketing_email_consent = False
    profile.marketing_email_consent_updated_at = timezone.now()
    profile.save(update_fields=["marketing_email_consent", "marketing_email_consent_updated_at", "updated_at"])
    if changed:
        audit(None, "client.marketing_unsubscribed", profile, {"source": "email_link"})
    return Response({"detail": "Ви відписалися від рекламних розсилок."})
