from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "admin", "Адміністратор"
        EMPLOYEE = "employee", "Працівник"
        CLIENT = "client", "Клієнт"

    role = models.CharField(max_length=16, choices=Role.choices)
    email = models.EmailField(unique=True)

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"


class EmployeeProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="employee_profile")
    middle_name = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    photo = models.FileField(upload_to="employees/photos/", blank=True)
    position = models.CharField(max_length=150)
    department = models.CharField(max_length=150)
    work_phone = models.CharField(max_length=40, blank=True)
    start_date = models.DateField(null=True, blank=True)
    admin_note = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="created_employees")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.user.get_full_name() or self.user.username


class LoginAttempt(models.Model):
    username = models.CharField(max_length=150, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True, db_index=True)
    successful = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
