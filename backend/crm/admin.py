from django.contrib import admin
from .models import AuditLog, ClientGroup, ClientProfile, DirectClientAccess, EmployeeGroup, EmployeeGroupClientAccess

admin.site.register([ClientProfile, DirectClientAccess, EmployeeGroupClientAccess, EmployeeGroup, ClientGroup])


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ["created_at", "actor", "action", "entity_type", "entity_label"]
    readonly_fields = [field.name for field in AuditLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
