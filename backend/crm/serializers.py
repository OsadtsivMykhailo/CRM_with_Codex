from django.utils import timezone
from rest_framework import serializers

from accounts.models import User
from accounts.serializers import UserSerializer
from .models import AuditLog, ClientProfile, DeletionRequest, Notification
from .services import responsible_employees


class ClientSerializer(serializers.ModelSerializer):
    display_name = serializers.CharField(read_only=True)
    responsible_employees = serializers.SerializerMethodField()

    class Meta:
        model = ClientProfile
        fields = [
            "id", "client_type", "first_name", "last_name", "company_name", "contact_person",
            "email", "phone", "website", "country", "city", "address", "preferred_contact",
            "business_description", "requested_service", "project_request", "desired_deadline",
            "estimated_budget", "status", "project_progress", "project_status_note", "project_updated_at",
            "internal_notes", "created_at", "updated_at", "display_name", "responsible_employees",
        ]
        read_only_fields = ["created_at", "updated_at", "project_updated_at"]

    def get_responsible_employees(self, obj):
        result = []
        for employee in responsible_employees(obj):
            profile = getattr(employee, "employee_profile", None)
            result.append({
                "id": employee.id,
                "first_name": employee.first_name,
                "last_name": employee.last_name,
                "email": employee.email,
                "position": profile.position if profile else "",
                "phone": profile.work_phone or profile.phone if profile else "",
            })
        return result

    def validate_project_progress(self, value):
        if value > 100:
            raise serializers.ValidationError("Прогрес не може перевищувати 100%.")
        return value

    def validate(self, attrs):
        client_type = attrs.get("client_type", getattr(self.instance, "client_type", None))
        if client_type == ClientProfile.ClientType.PERSON and not (
            attrs.get("first_name") or getattr(self.instance, "first_name", "")
        ):
            raise serializers.ValidationError({"first_name": "Вкажіть ім'я клієнта."})
        if client_type == ClientProfile.ClientType.COMPANY and not (
            attrs.get("company_name") or getattr(self.instance, "company_name", "")
        ):
            raise serializers.ValidationError({"company_name": "Вкажіть назву компанії."})

        request = self.context.get("request")
        if request and request.user.role == User.Role.CLIENT:
            forbidden = {"status", "project_progress", "project_status_note", "internal_notes"}.intersection(
                self.initial_data
            )
            if forbidden:
                raise serializers.ValidationError("Клієнт не може змінювати внутрішні поля CRM.")
            new_email = attrs.get("email")
            if new_email and User.objects.filter(email__iexact=new_email).exclude(pk=request.user.pk).exists():
                raise serializers.ValidationError({"email": "Такий email уже використовується."})
        return attrs

    def update(self, instance, validated_data):
        project_fields = {"status", "project_progress", "project_status_note"}
        if project_fields.intersection(validated_data):
            instance.project_updated_at = timezone.now()
        instance = super().update(instance, validated_data)
        request = self.context.get("request")
        if request and request.user.role == User.Role.CLIENT and "email" in validated_data:
            request.user.email = validated_data["email"]
            request.user.save(update_fields=["email"])
        return instance

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        if request and request.user.role == User.Role.CLIENT:
            data.pop("internal_notes", None)
        return data


class ClientRegistrationSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True, min_length=8)
    client_type = serializers.ChoiceField(choices=ClientProfile.ClientType.choices)
    first_name = serializers.CharField(required=False, allow_blank=True)
    last_name = serializers.CharField(required=False, allow_blank=True)
    company_name = serializers.CharField(required=False, allow_blank=True)
    contact_person = serializers.CharField(required=False, allow_blank=True)
    email = serializers.EmailField()
    phone = serializers.CharField()
    country = serializers.CharField()
    city = serializers.CharField()
    preferred_contact = serializers.ChoiceField(choices=["email", "phone"])
    requested_service = serializers.CharField()
    project_request = serializers.CharField()

    def validate_username(self, value):
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("Такий логін уже використовується.")
        return value

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("Такий email уже використовується.")
        return value

    def validate(self, attrs):
        if attrs["client_type"] == ClientProfile.ClientType.PERSON and not attrs.get("first_name"):
            raise serializers.ValidationError({"first_name": "Вкажіть ім'я клієнта."})
        if attrs["client_type"] == ClientProfile.ClientType.COMPANY and not attrs.get("company_name"):
            raise serializers.ValidationError({"company_name": "Вкажіть назву компанії."})
        return attrs

    def create(self, validated_data):
        username = validated_data.pop("username")
        password = validated_data.pop("password")
        email = validated_data["email"]
        user = User.objects.create_user(username=username, password=password, email=email, role=User.Role.CLIENT)
        profile = ClientProfile.objects.create(
            user=user,
            pool_reason=ClientProfile.PoolReason.SELF_REGISTERED,
            **validated_data,
        )
        from rest_framework.authtoken.models import Token
        token = Token.objects.create(user=user)
        return user, profile, token


class UnassignedClientSerializer(serializers.ModelSerializer):
    display_name = serializers.CharField(read_only=True)
    pool_reason_label = serializers.CharField(source="get_pool_reason_display", read_only=True)

    class Meta:
        model = ClientProfile
        fields = ["id", "display_name", "created_at", "pool_reason", "pool_reason_label"]


class RejectRegistrationSerializer(serializers.Serializer):
    reason = serializers.CharField(min_length=10, max_length=1000)


class AssignClientSerializer(serializers.Serializer):
    employee_id = serializers.IntegerField()

    def validate_employee_id(self, value):
        if not User.objects.filter(pk=value, role=User.Role.EMPLOYEE, is_active=True).exists():
            raise serializers.ValidationError("Активного працівника не знайдено.")
        return value


class DeletionRequestCreateSerializer(serializers.Serializer):
    client_id = serializers.IntegerField()
    reason = serializers.CharField(min_length=10)


class DeletionDecisionSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=[DeletionRequest.Status.APPROVED, DeletionRequest.Status.REJECTED])
    note = serializers.CharField(required=False, allow_blank=True)


class DeletionRequestSerializer(serializers.ModelSerializer):
    requested_by = UserSerializer(read_only=True)
    decided_by = UserSerializer(read_only=True)
    client = serializers.SerializerMethodField()

    class Meta:
        model = DeletionRequest
        fields = [
            "id", "client", "requested_by", "reason", "status", "requested_at", "expires_at",
            "decided_by", "decided_at", "decision_note",
        ]

    def get_client(self, obj):
        if obj.status == DeletionRequest.Status.PENDING:
            return ClientSerializer(obj.client, context=self.context).data
        return {"id": obj.client_id, "display_name": obj.client.display_name}


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ["id", "kind", "title", "message", "entity_type", "entity_id", "read_at", "created_at"]


class AuditLogSerializer(serializers.ModelSerializer):
    actor = UserSerializer(read_only=True)

    class Meta:
        model = AuditLog
        fields = ["id", "actor", "action", "entity_type", "entity_id", "entity_label", "changes", "created_at"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if instance.entity_type == "crm.ClientProfile":
            changes = instance.changes or {}
            if instance.action == "client.registration_rejected":
                data["changes"] = {"reason": changes.get("reason", "")}
            else:
                data["changes"] = {"fields": changes.get("fields", list(changes.keys()))}
        return data
