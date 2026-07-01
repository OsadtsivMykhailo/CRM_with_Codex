from django.db import migrations
from django.utils import timezone


def repair_client_pool(apps, schema_editor):
    ClientProfile = apps.get_model("crm", "ClientProfile")
    DirectClientAccess = apps.get_model("crm", "DirectClientAccess")
    EmployeeGroupClientAccess = apps.get_model("crm", "EmployeeGroupClientAccess")
    ClientGroup = apps.get_model("crm", "ClientGroup")

    DirectClientAccess.objects.filter(
        employee__is_active=False,
        revoked_at__isnull=True,
    ).update(
        revoked_at=timezone.now(),
        revoke_reason="Працівника було деактивовано",
    )

    for client in ClientProfile.objects.filter(is_deleted=False):
        active_direct = DirectClientAccess.objects.filter(
            client_id=client.id,
            employee__is_active=True,
            revoked_at__isnull=True,
        ).exists()
        active_group = EmployeeGroupClientAccess.objects.filter(
            client_id=client.id,
            employee_group__members__is_active=True,
        ).exists()
        active_editor = ClientGroup.objects.filter(
            clients__id=client.id,
            editors__is_active=True,
        ).exists()
        if active_direct or active_group or active_editor:
            continue

        if client.status == "completed":
            client.status = "archived"
            client.pool_reason = ""
        elif client.status == "archived":
            client.pool_reason = ""
        elif DirectClientAccess.objects.filter(client_id=client.id, employee__is_active=False).exists():
            client.pool_reason = "employee_deactivated"
        elif client.created_by_id is None and client.user_id:
            client.pool_reason = "self_registered"
        else:
            client.pool_reason = "access_removed"
        client.save(update_fields=["status", "pool_reason"])


class Migration(migrations.Migration):
    dependencies = [("crm", "0003_remove_directclientaccess_unique_direct_client_access_and_more")]
    operations = [migrations.RunPython(repair_client_pool, migrations.RunPython.noop)]
