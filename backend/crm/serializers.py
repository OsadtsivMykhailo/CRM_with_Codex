from django.utils import timezone
from rest_framework import serializers

from accounts.models import User
from accounts.serializers import UserSerializer
from .email_security import encrypt_secret
from .mailing import sanitize_email_html, unknown_markers
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
    EmailCampaignRecipient,
    EmailServerConfiguration,
    EmailTemplate,
    Notification,
    SharedSender,
)
from .services import accessible_clients, responsible_employees


class ClientSerializer(serializers.ModelSerializer):
    display_name = serializers.CharField(read_only=True)
    responsible_employees = serializers.SerializerMethodField()
    has_direct_access = serializers.SerializerMethodField()
    client_group_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)

    class Meta:
        model = ClientProfile
        fields = [
            "id", "client_type", "first_name", "last_name", "company_name", "contact_person",
            "email", "phone", "website", "country", "city", "address", "preferred_contact",
            "business_description", "requested_service", "project_request", "desired_deadline",
            "estimated_budget", "status", "project_progress", "project_status_note", "project_updated_at",
            "internal_notes", "marketing_email_consent", "marketing_email_consent_updated_at",
            "created_at", "updated_at", "display_name", "responsible_employees",
            "has_direct_access", "client_group_id",
        ]
        read_only_fields = [
            "created_at", "updated_at", "project_updated_at",
            "marketing_email_consent", "marketing_email_consent_updated_at",
        ]

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

    def get_has_direct_access(self, obj):
        request = self.context.get("request")
        if not request or request.user.role != User.Role.EMPLOYEE:
            return False
        return DirectClientAccess.objects.filter(
            client=obj,
            employee=request.user,
            revoked_at__isnull=True,
        ).exists()

    def validate_project_progress(self, value):
        if value > 100:
            raise serializers.ValidationError("Прогрес не може перевищувати 100%.")
        return value

    def validate(self, attrs):
        group_id = attrs.pop("client_group_id", None)
        if self.instance is not None and "client_group_id" in self.initial_data:
            raise serializers.ValidationError({
                "client_group_id": "Групу можна вказати лише під час створення анкети."
            })
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
        if group_id is not None:
            if not request or request.user.role != User.Role.EMPLOYEE:
                raise serializers.ValidationError({"client_group_id": "Групу може обрати лише працівник."})
            try:
                group = ClientGroup.objects.get(pk=group_id, editors=request.user)
            except ClientGroup.DoesNotExist as exc:
                raise serializers.ValidationError({
                    "client_group_id": "Можна обрати лише групу, до якої ви маєте доступ."
                }) from exc
            attrs["_selected_client_group"] = group
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
        validated_data.pop("_selected_client_group", None)
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
    marketing_email_consent = serializers.BooleanField(required=False, default=False)

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


class EmailPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClientProfile
        fields = ["marketing_email_consent", "marketing_email_consent_updated_at"]
        read_only_fields = ["marketing_email_consent_updated_at"]


class UnassignedClientSerializer(serializers.ModelSerializer):
    display_name = serializers.CharField(read_only=True)
    pool_reason_label = serializers.CharField(source="get_pool_reason_display", read_only=True)

    class Meta:
        model = ClientProfile
        fields = ["id", "display_name", "created_at", "pool_reason", "pool_reason_label"]


class RejectRegistrationSerializer(serializers.Serializer):
    reason = serializers.CharField(min_length=10, max_length=1000)


class AssignClientSerializer(serializers.Serializer):
    assignee_type = serializers.ChoiceField(choices=["employee", "group"])
    assignee_id = serializers.IntegerField()

    def validate(self, attrs):
        assignee_id = attrs["assignee_id"]
        if attrs["assignee_type"] == "employee":
            if not User.objects.filter(pk=assignee_id, role=User.Role.EMPLOYEE, is_active=True).exists():
                raise serializers.ValidationError({"assignee_id": "Активного працівника не знайдено."})
        elif not ClientGroup.objects.filter(pk=assignee_id, editors__is_active=True).exists():
            raise serializers.ValidationError({
                "assignee_id": "Групу з активними відповідальними працівниками не знайдено."
            })
        return attrs


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


class ClientGroupAdditionRequestCreateSerializer(serializers.Serializer):
    client_id = serializers.IntegerField()
    group_id = serializers.IntegerField()
    reason = serializers.CharField(min_length=10, max_length=2000)


class ClientGroupRequestDecisionSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["approved", "rejected"])
    note = serializers.CharField(required=False, allow_blank=True, max_length=2000)


class ClientGroupAdditionRequestSerializer(serializers.ModelSerializer):
    requested_by = UserSerializer(read_only=True)
    decided_by = UserSerializer(read_only=True)
    client = serializers.SerializerMethodField()
    group = serializers.SerializerMethodField()

    class Meta:
        model = ClientGroupAdditionRequest
        fields = [
            "id", "client", "group", "requested_by", "reason", "status",
            "requested_at", "expires_at", "decided_by", "decided_at", "decision_note",
        ]

    def get_client(self, obj):
        return {"id": obj.client_id, "display_name": obj.client.display_name}

    def get_group(self, obj):
        return {"id": obj.group_id, "name": obj.group.name}


class ClientGroupCreationRequestCreateSerializer(serializers.Serializer):
    proposed_name = serializers.CharField(min_length=2, max_length=150)
    reason = serializers.CharField(min_length=10, max_length=2000)
    proposed_client_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, allow_empty=True, default=list
    )
    proposed_employee_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, allow_empty=True, default=list
    )


class ClientGroupCreationRequestSerializer(serializers.ModelSerializer):
    requested_by = UserSerializer(read_only=True)
    decided_by = UserSerializer(read_only=True)
    created_group_id = serializers.IntegerField(read_only=True)
    proposed_clients = serializers.SerializerMethodField()
    proposed_employees = serializers.SerializerMethodField()

    class Meta:
        model = ClientGroupCreationRequest
        fields = [
            "id", "proposed_name", "reason", "requested_by", "proposed_clients",
            "proposed_employees", "created_group_id", "status", "requested_at",
            "expires_at", "decided_by", "decided_at", "decision_note",
        ]

    def get_proposed_clients(self, obj):
        return [
            {"id": client.id, "display_name": client.display_name}
            for client in obj.proposed_clients.all()
        ]

    def get_proposed_employees(self, obj):
        return [
            {
                "id": employee.id,
                "username": employee.username,
                "first_name": employee.first_name,
                "last_name": employee.last_name,
            }
            for employee in obj.proposed_employees.all()
        ]


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ["id", "kind", "title", "message", "entity_type", "entity_id", "read_at", "created_at"]


class EmailServerConfigurationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)
    has_password = serializers.SerializerMethodField()

    class Meta:
        model = EmailServerConfiguration
        fields = [
            "name", "company_name", "host", "port", "username", "password", "has_password",
            "use_tls", "use_ssl", "is_active", "updated_at",
        ]
        read_only_fields = ["updated_at"]

    def get_has_password(self, obj):
        return bool(obj.encrypted_password)

    def validate(self, attrs):
        use_tls = attrs.get("use_tls", getattr(self.instance, "use_tls", False))
        use_ssl = attrs.get("use_ssl", getattr(self.instance, "use_ssl", False))
        if use_tls and use_ssl:
            raise serializers.ValidationError("TLS і SSL не можна вмикати одночасно.")
        return attrs

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        if password is not None:
            instance.encrypted_password = encrypt_secret(password)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.updated_by = self.context["request"].user
        instance.save()
        return instance


class SharedSenderSerializer(serializers.ModelSerializer):
    allowed_employee_ids = serializers.PrimaryKeyRelatedField(
        source="allowed_employees",
        queryset=User.objects.filter(role=User.Role.EMPLOYEE),
        many=True,
        required=False,
    )

    class Meta:
        model = SharedSender
        fields = [
            "id", "name", "email", "allowed_employee_ids", "is_active", "created_at", "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def create(self, validated_data):
        employees = validated_data.pop("allowed_employees", [])
        sender = SharedSender.objects.create(created_by=self.context["request"].user, **validated_data)
        sender.allowed_employees.set(employees)
        return sender

    def update(self, instance, validated_data):
        employees = validated_data.pop("allowed_employees", None)
        instance = super().update(instance, validated_data)
        if employees is not None:
            instance.allowed_employees.set(employees)
        return instance


class EmailTemplateSerializer(serializers.ModelSerializer):
    owner = UserSerializer(read_only=True)

    class Meta:
        model = EmailTemplate
        fields = [
            "id", "name", "scope", "message_type", "subject", "html_body", "text_body",
            "owner", "created_at", "updated_at",
        ]
        read_only_fields = ["owner", "created_at", "updated_at"]

    def validate_html_body(self, value):
        cleaned = sanitize_email_html(value)
        if not cleaned.strip():
            raise serializers.ValidationError("Текст шаблону не може бути порожнім.")
        return cleaned

    def validate(self, attrs):
        if self.instance and "scope" in attrs and attrs["scope"] != self.instance.scope:
            raise serializers.ValidationError({"scope": "Тип доступу шаблону не можна змінювати."})
        values = [
            attrs.get("subject", getattr(self.instance, "subject", "")),
            attrs.get("html_body", getattr(self.instance, "html_body", "")),
            attrs.get("text_body", getattr(self.instance, "text_body", "")),
        ]
        invalid = unknown_markers(*values)
        if invalid:
            raise serializers.ValidationError({"variables": f"Невідомі змінні: {', '.join(invalid)}."})
        return attrs


class ClientGroupSerializer(serializers.ModelSerializer):
    client_ids = serializers.PrimaryKeyRelatedField(
        source="clients", queryset=ClientProfile.objects.filter(is_deleted=False), many=True, required=False
    )
    editor_ids = serializers.PrimaryKeyRelatedField(
        source="editors",
        queryset=User.objects.filter(role=User.Role.EMPLOYEE, is_active=True),
        many=True,
        required=False,
    )

    class Meta:
        model = ClientGroup
        fields = ["id", "name", "client_ids", "editor_ids", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]

    def validate_editor_ids(self, value):
        if not value:
            raise serializers.ValidationError("Призначте групі хоча б одного відповідального працівника.")
        return value


class CampaignRecipientSerializer(serializers.ModelSerializer):
    consent = serializers.BooleanField(source="client.marketing_email_consent", read_only=True)

    class Meta:
        model = EmailCampaignRecipient
        fields = ["id", "client", "email", "display_name", "status", "error_message", "sent_at", "consent"]


class CampaignAttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmailCampaignAttachment
        fields = ["id", "original_name", "content_type", "size", "file", "created_at"]
        read_only_fields = fields


class EmailCampaignSerializer(serializers.ModelSerializer):
    recipients = CampaignRecipientSerializer(many=True, read_only=True)
    attachments = CampaignAttachmentSerializer(many=True, read_only=True)
    shared_sender = SharedSenderSerializer(read_only=True)
    shared_sender_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)
    client_ids = serializers.ListField(
        child=serializers.IntegerField(), write_only=True, required=False, allow_empty=True
    )
    client_group_ids = serializers.ListField(
        child=serializers.IntegerField(), write_only=True, required=False, allow_empty=True
    )
    include_all_accessible = serializers.BooleanField(write_only=True, required=False, default=False)

    class Meta:
        model = EmailCampaign
        fields = [
            "id", "template", "message_type", "sender_type", "shared_sender", "shared_sender_id",
            "from_name", "from_email", "subject", "html_body", "text_body", "status",
            "client_ids", "client_group_ids", "include_all_accessible", "recipients", "attachments",
            "total_recipients", "sent_count", "failed_count", "skipped_count",
            "created_at", "updated_at", "queued_at", "completed_at",
        ]
        read_only_fields = [
            "from_name", "from_email", "status", "total_recipients", "sent_count", "failed_count",
            "skipped_count", "created_at", "updated_at", "queued_at", "completed_at",
        ]

    def validate_html_body(self, value):
        cleaned = sanitize_email_html(value)
        if not cleaned.strip():
            raise serializers.ValidationError("Текст листа не може бути порожнім.")
        return cleaned

    def _sender(self, attrs):
        user = self.context["request"].user
        sender_type = attrs.get("sender_type", getattr(self.instance, "sender_type", None))
        if sender_type == EmailCampaign.SenderType.PERSONAL:
            if not user.email:
                raise serializers.ValidationError({"sender_type": "Працівнику не призначено корпоративний email."})
            return None, user.get_full_name() or user.username, user.email
        sender_id = attrs.pop("shared_sender_id", None)
        if sender_id is None and self.instance:
            sender_id = self.instance.shared_sender_id
        try:
            sender = SharedSender.objects.get(pk=sender_id, is_active=True, allowed_employees=user)
        except SharedSender.DoesNotExist as exc:
            raise serializers.ValidationError({"shared_sender_id": "Загальна адреса недоступна."}) from exc
        return sender, sender.name, sender.email

    def _recipients(self):
        user = self.context["request"].user
        base = accessible_clients(user).exclude(status=ClientProfile.Status.ARCHIVED)
        selected_ids = set()
        if self.initial_data.get("include_all_accessible") in (True, "true", "1", 1):
            selected_ids.update(base.values_list("id", flat=True))

        raw_client_ids = self.initial_data.get("client_ids", []) or []
        requested_client_ids = {int(value) for value in raw_client_ids}
        accessible_requested = set(base.filter(pk__in=requested_client_ids).values_list("id", flat=True))
        if accessible_requested != requested_client_ids:
            raise serializers.ValidationError({"client_ids": "Серед вибраних є недоступні або архівні клієнти."})
        selected_ids.update(accessible_requested)

        raw_group_ids = self.initial_data.get("client_group_ids", []) or []
        requested_group_ids = {int(value) for value in raw_group_ids}
        groups = ClientGroup.objects.filter(pk__in=requested_group_ids, editors=user)
        if set(groups.values_list("id", flat=True)) != requested_group_ids:
            raise serializers.ValidationError({"client_group_ids": "Серед вибраних є недоступні групи."})
        group_client_ids = ClientProfile.objects.filter(
            client_groups__in=groups,
            pk__in=base.values_list("id", flat=True),
        ).values_list("id", flat=True)
        selected_ids.update(group_client_ids)

        clients = list(base.filter(pk__in=selected_ids).order_by("id"))
        unique = {}
        for client in clients:
            unique.setdefault(client.email.strip().lower(), client)
        if not unique:
            raise serializers.ValidationError("Оберіть хоча б одного доступного клієнта.")
        if len(unique) > 100:
            raise serializers.ValidationError("Одна розсилка може містити не більше 100 унікальних адрес.")
        return list(unique.values())

    def validate(self, attrs):
        if self.instance and self.instance.status != EmailCampaign.Status.DRAFT:
            raise serializers.ValidationError("Після постановки в чергу розсилку не можна редагувати.")
        values = [
            attrs.get("subject", getattr(self.instance, "subject", "")),
            attrs.get("html_body", getattr(self.instance, "html_body", "")),
            attrs.get("text_body", getattr(self.instance, "text_body", "")),
        ]
        invalid = unknown_markers(*values)
        if invalid:
            raise serializers.ValidationError({"variables": f"Невідомі змінні: {', '.join(invalid)}."})
        template = attrs.get("template", getattr(self.instance, "template", None))
        user = self.context["request"].user
        if template and not (
            template.scope == EmailTemplate.Scope.COMPANY or template.owner_id == user.id
        ):
            raise serializers.ValidationError({"template": "Цей шаблон вам недоступний."})
        sender, from_name, from_email = self._sender(attrs)
        attrs["shared_sender"] = sender
        attrs["from_name"] = from_name
        attrs["from_email"] = from_email
        if not self.instance or any(
            key in self.initial_data for key in ("client_ids", "client_group_ids", "include_all_accessible")
        ):
            attrs["_recipient_clients"] = self._recipients()
        return attrs

    def _replace_recipients(self, campaign, clients):
        campaign.recipients.all().delete()
        EmailCampaignRecipient.objects.bulk_create([
            EmailCampaignRecipient(
                campaign=campaign,
                client=client,
                email=client.email.strip().lower(),
                display_name=client.display_name,
            )
            for client in clients
        ])
        campaign.total_recipients = len(clients)
        campaign.save(update_fields=["total_recipients", "updated_at"])

    def create(self, validated_data):
        clients = validated_data.pop("_recipient_clients")
        validated_data.pop("client_ids", None)
        validated_data.pop("client_group_ids", None)
        validated_data.pop("include_all_accessible", None)
        campaign = EmailCampaign.objects.create(created_by=self.context["request"].user, **validated_data)
        self._replace_recipients(campaign, clients)
        return campaign

    def update(self, instance, validated_data):
        clients = validated_data.pop("_recipient_clients", None)
        validated_data.pop("client_ids", None)
        validated_data.pop("client_group_ids", None)
        validated_data.pop("include_all_accessible", None)
        instance = super().update(instance, validated_data)
        if clients is not None:
            self._replace_recipients(instance, clients)
        return instance


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
