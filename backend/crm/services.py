from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounts.models import User
from .models import (
    AuditLog,
    ClientGroupAdditionRequest,
    ClientGroupCreationRequest,
    ClientProfile,
    DeletionRequest,
    DirectClientAccess,
    EmployeeGroupClientAccess,
    Notification,
)


def accessible_clients(user):
    base = ClientProfile.objects.filter(is_deleted=False)
    if user.role == User.Role.CLIENT:
        return base.filter(user=user)
    if user.role != User.Role.EMPLOYEE:
        return base.none()
    return base.filter(
        Q(direct_accesses__employee=user, direct_accesses__revoked_at__isnull=True)
        | Q(employee_group_accesses__employee_group__members=user)
        | Q(client_groups__editors=user)
    ).distinct()


def grant_creator_access(client, user):
    existing = DirectClientAccess.objects.filter(
        client=client, employee=user, revoked_at__isnull=True
    ).first()
    if existing:
        return existing
    return DirectClientAccess.objects.create(client=client, employee=user, granted_by=user)


def audit(actor, action, instance, changes=None):
    AuditLog.objects.create(
        actor=actor,
        action=action,
        entity_type=instance._meta.label,
        entity_id=str(instance.pk),
        entity_label=str(instance),
        changes=changes or {},
    )


def security_audit(actor, action, label, changes=None):
    AuditLog.objects.create(
        actor=actor,
        action=action,
        entity_type="security",
        entity_id=str(actor.pk) if actor else "anonymous",
        entity_label=label,
        changes=changes or {},
    )


def notify(user, kind, title, message, instance=None, email=False):
    notification = Notification.objects.create(
        user=user,
        kind=kind,
        title=title,
        message=message,
        entity_type=instance._meta.label if instance else "",
        entity_id=str(instance.pk) if instance else "",
    )
    if email and user.email:
        send_mail(title, message, settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=True)
    return notification


def notify_admins(kind, title, message, instance=None):
    for admin in User.objects.filter(role=User.Role.ADMIN, is_active=True):
        notify(admin, kind, title, message, instance)


def responsible_employees(client):
    return User.objects.filter(
        Q(direct_client_accesses__client=client, direct_client_accesses__revoked_at__isnull=True)
        | Q(employee_groups__client_accesses__client=client)
        | Q(editable_client_groups__clients=client),
        role=User.Role.EMPLOYEE,
        is_active=True,
    ).select_related("employee_profile").distinct()


def has_active_access(client):
    if DirectClientAccess.objects.filter(
        client=client, employee__is_active=True, revoked_at__isnull=True
    ).exists():
        return True
    if EmployeeGroupClientAccess.objects.filter(
        client=client, employee_group__members__is_active=True
    ).exists():
        return True
    return client.client_groups.filter(editors__is_active=True).exists()


@transaction.atomic
def deactivate_employee(employee, actor):
    affected_clients = list(accessible_clients(employee).select_for_update())
    now = timezone.now()
    DirectClientAccess.objects.filter(employee=employee, revoked_at__isnull=True).update(
        revoked_at=now,
        revoked_by=actor,
        revoke_reason="Працівника деактивовано",
    )
    employee.is_active = False
    employee.save(update_fields=["is_active"])

    returned_to_pool = 0
    archived = 0
    for client in affected_clients:
        audit(actor, "client.employee_access_revoked", client, {"employee_id": employee.id})
        if has_active_access(client):
            continue
        if client.status == ClientProfile.Status.COMPLETED:
            client.status = ClientProfile.Status.ARCHIVED
            client.pool_reason = ClientProfile.PoolReason.NONE
            client.save(update_fields=["status", "pool_reason", "updated_at"])
            audit(actor, "client.archived_after_deactivation", client, {"employee_id": employee.id})
            archived += 1
        elif client.status != ClientProfile.Status.ARCHIVED:
            client.pool_reason = ClientProfile.PoolReason.EMPLOYEE_DEACTIVATED
            client.save(update_fields=["pool_reason", "updated_at"])
            audit(actor, "client.returned_to_pool", client, {"employee_id": employee.id})
            notify_admins(
                "client_returned_to_pool",
                "Клієнту потрібне повторне призначення",
                f"«{client.display_name}» повернено до пулу після деактивації працівника.",
                client,
            )
            returned_to_pool += 1
    return {"returned_to_pool": returned_to_pool, "archived": archived}


def expire_stale_deletion_requests():
    now = timezone.now()
    stale = DeletionRequest.objects.filter(status=DeletionRequest.Status.PENDING, expires_at__lte=now)
    for item in stale.select_related("requested_by", "client"):
        item.status = DeletionRequest.Status.EXPIRED
        item.decided_at = now
        item.decision_note = "Рішення не прийнято протягом семи днів."
        item.save(update_fields=["status", "decided_at", "decision_note"])
        Notification.objects.filter(
            kind="deletion_request_created", entity_id=str(item.id), read_at__isnull=True
        ).update(read_at=now)
        audit(None, "deletion_request.expired", item, {"client_id": item.client_id})
        notify(
            item.requested_by,
            "deletion_request_expired",
            "Запит на видалення автоматично відхилено",
            f"Запит щодо «{item.client.display_name}» не розглянули протягом семи днів.",
            item,
            email=True,
        )


def expire_stale_client_group_addition_requests():
    now = timezone.now()
    stale = ClientGroupAdditionRequest.objects.filter(
        status=ClientGroupAdditionRequest.Status.PENDING,
        expires_at__lte=now,
    )
    for item in stale.select_related("requested_by", "client", "group"):
        item.status = ClientGroupAdditionRequest.Status.EXPIRED
        item.decided_at = now
        item.decision_note = "Рішення не прийнято протягом семи днів."
        item.save(update_fields=["status", "decided_at", "decision_note"])
        Notification.objects.filter(
            kind="client_group_addition_request_created",
            entity_id=str(item.id),
            read_at__isnull=True,
        ).update(read_at=now)
        audit(None, "client_group_addition_request.expired", item, {
            "client_id": item.client_id,
            "group_id": item.group_id,
        })
        notify(
            item.requested_by,
            "client_group_addition_request_expired",
            "Запит на додавання до групи автоматично відхилено",
            f"Запит щодо «{item.client.display_name}» і групи «{item.group.name}» "
            "не розглянули протягом семи днів.",
            item,
            email=True,
        )


def expire_stale_client_group_creation_requests():
    now = timezone.now()
    stale = ClientGroupCreationRequest.objects.filter(
        status=ClientGroupCreationRequest.Status.PENDING,
        expires_at__lte=now,
    )
    for item in stale.select_related("requested_by"):
        item.status = ClientGroupCreationRequest.Status.EXPIRED
        item.decided_at = now
        item.decision_note = "Рішення не прийнято протягом семи днів."
        item.save(update_fields=["status", "decided_at", "decision_note"])
        Notification.objects.filter(
            kind="client_group_creation_request_created",
            entity_id=str(item.id),
            read_at__isnull=True,
        ).update(read_at=now)
        audit(None, "client_group_creation_request.expired", item, {
            "proposed_name": item.proposed_name,
        })
        notify(
            item.requested_by,
            "client_group_creation_request_expired",
            "Запит на створення групи автоматично відхилено",
            f"Запит на створення групи «{item.proposed_name}» не розглянули протягом семи днів.",
            item,
            email=True,
        )


def expire_stale_requests():
    expire_stale_deletion_requests()
    expire_stale_client_group_addition_requests()
    expire_stale_client_group_creation_requests()
