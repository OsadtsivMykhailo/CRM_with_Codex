from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class EmployeeGroup(models.Model):
    name = models.CharField(max_length=150, unique=True)
    members = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="employee_groups", blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_employee_groups")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class ClientProfile(models.Model):
    class ClientType(models.TextChoices):
        PERSON = "person", "Фізична особа"
        COMPANY = "company", "Компанія"

    class Status(models.TextChoices):
        NEW = "new", "Новий"
        ACTIVE = "active", "Активний"
        PAUSED = "paused", "Призупинений"
        COMPLETED = "completed", "Завершений"
        ARCHIVED = "archived", "Архівний"

    class PoolReason(models.TextChoices):
        NONE = "", "Не перебуває в пулі"
        SELF_REGISTERED = "self_registered", "Нова самостійна реєстрація"
        EMPLOYEE_DEACTIVATED = "employee_deactivated", "Повторне призначення"
        ACCESS_REMOVED = "access_removed", "Потрібне повторне призначення"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="client_profile")
    client_type = models.CharField(max_length=16, choices=ClientType.choices)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    company_name = models.CharField(max_length=255, blank=True)
    contact_person = models.CharField(max_length=255, blank=True)
    email = models.EmailField()
    phone = models.CharField(max_length=40)
    website = models.URLField(blank=True)
    country = models.CharField(max_length=100)
    city = models.CharField(max_length=100)
    address = models.CharField(max_length=255, blank=True)
    preferred_contact = models.CharField(max_length=16, choices=[("email", "Email"), ("phone", "Телефон")])
    business_description = models.TextField(blank=True)
    requested_service = models.CharField(max_length=255)
    project_request = models.TextField()
    desired_deadline = models.DateField(null=True, blank=True)
    estimated_budget = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.NEW)
    project_progress = models.PositiveSmallIntegerField(default=0)
    project_status_note = models.TextField(blank=True)
    project_updated_at = models.DateTimeField(null=True, blank=True)
    internal_notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="created_clients")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_deleted = models.BooleanField(default=False)
    pool_reason = models.CharField(max_length=32, choices=PoolReason.choices, blank=True, default=PoolReason.NONE)

    @property
    def display_name(self):
        return self.company_name if self.client_type == self.ClientType.COMPANY else f"{self.first_name} {self.last_name}".strip()

    def __str__(self):
        return self.display_name or f"Клієнт #{self.pk}"


class DirectClientAccess(models.Model):
    client = models.ForeignKey(ClientProfile, on_delete=models.CASCADE, related_name="direct_accesses")
    employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="direct_client_accesses")
    granted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="granted_client_accesses")
    created_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="revoked_client_accesses"
    )
    revoke_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["client", "employee"],
                condition=Q(revoked_at__isnull=True),
                name="unique_active_direct_client_access",
            )
        ]


class EmployeeGroupClientAccess(models.Model):
    client = models.ForeignKey(ClientProfile, on_delete=models.CASCADE, related_name="employee_group_accesses")
    employee_group = models.ForeignKey(EmployeeGroup, on_delete=models.CASCADE, related_name="client_accesses")
    granted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="granted_group_client_accesses")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["client", "employee_group"], name="unique_group_client_access")]


class ClientGroup(models.Model):
    name = models.CharField(max_length=150)
    clients = models.ManyToManyField(ClientProfile, related_name="client_groups", blank=True)
    editors = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="editable_client_groups")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_client_groups")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class Notification(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=64)
    title = models.CharField(max_length=255)
    message = models.TextField()
    entity_type = models.CharField(max_length=100, blank=True)
    entity_id = models.CharField(max_length=64, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class DeletionRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Очікує рішення"
        APPROVED = "approved", "Схвалено"
        REJECTED = "rejected", "Відхилено"
        EXPIRED = "expired", "Автоматично відхилено"

    client = models.ForeignKey(ClientProfile, on_delete=models.PROTECT, related_name="deletion_requests")
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_deletion_requests"
    )
    reason = models.TextField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    requested_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="decided_deletion_requests"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.TextField(blank=True)

    class Meta:
        ordering = ["-requested_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["client"], condition=Q(status="pending"), name="one_pending_deletion_request_per_client"
            )
        ]

    def __str__(self):
        return f"Запит #{self.pk}: {self.client.display_name}"


class AuditLog(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="audit_events")
    action = models.CharField(max_length=64)
    entity_type = models.CharField(max_length=100)
    entity_id = models.CharField(max_length=64)
    entity_label = models.CharField(max_length=255, blank=True)
    changes = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["action"], name="crm_audit_action_idx"),
            models.Index(fields=["entity_type", "entity_id"], name="crm_audit_entity_idx"),
            models.Index(fields=["actor", "created_at"], name="crm_audit_actor_time_idx"),
            models.Index(fields=["created_at"], name="crm_audit_created_idx"),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Записи аудиту не можна редагувати.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Записи аудиту не можна видаляти.")
