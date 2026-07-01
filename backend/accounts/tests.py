from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from crm.models import AuditLog, ClientProfile, DirectClientAccess
from .models import EmployeeProfile, LoginAttempt, User


class EmployeeApiTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user("admin", "admin@example.com", "test-pass-123", role="admin")
        self.employee = User.objects.create_user("worker", "worker@example.com", "test-pass-123", role="employee")

    def authenticate(self, user):
        token, _ = Token.objects.get_or_create(user=user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    def test_login_returns_user_and_token(self):
        response = self.client.post("/api/auth/login/", {"username": "worker", "password": "test-pass-123"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["user"]["role"], "employee")
        self.assertTrue(response.data["token"])

    def test_only_admin_can_create_employee(self):
        payload = {
            "username": "new-worker", "password": "strong-pass-123", "email": "new@example.com",
            "first_name": "Нова", "last_name": "Людина", "position": "PM", "department": "Delivery",
        }
        self.authenticate(self.employee)
        self.assertEqual(self.client.post("/api/auth/employees/", payload, format="json").status_code, 403)
        self.authenticate(self.admin)
        response = self.client.post("/api/auth/employees/", payload, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertTrue(EmployeeProfile.objects.filter(user__username="new-worker").exists())

    def test_admin_can_update_and_deactivate_employee(self):
        profile = EmployeeProfile.objects.create(
            user=self.employee, position="Developer", department="Engineering", created_by=self.admin
        )
        self.authenticate(self.admin)
        response = self.client.patch(
            f"/api/auth/employees/{profile.id}/",
            {"position": "Lead Developer", "first_name": "Updated"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        profile.refresh_from_db()
        self.employee.refresh_from_db()
        self.assertEqual(profile.position, "Lead Developer")
        self.assertEqual(self.employee.first_name, "Updated")

        response = self.client.delete(f"/api/auth/employees/{profile.id}/")
        self.assertEqual(response.status_code, 204)
        self.employee.refresh_from_db()
        self.assertFalse(self.employee.is_active)
        self.assertTrue(AuditLog.objects.filter(action="employee.deactivated").exists())

    def test_deactivation_returns_unfinished_client_to_pool_and_archives_completed(self):
        profile = EmployeeProfile.objects.create(
            user=self.employee, position="Developer", department="Engineering", created_by=self.admin
        )
        active_client = ClientProfile.objects.create(
            client_type="company", company_name="Needs reassignment", email="one@example.com",
            phone="1", country="UA", city="Kyiv", preferred_contact="email",
            requested_service="Web", project_request="Build", created_by=self.employee,
        )
        completed_client = ClientProfile.objects.create(
            client_type="company", company_name="Completed", email="two@example.com",
            phone="2", country="UA", city="Kyiv", preferred_contact="email",
            requested_service="Web", project_request="Build", created_by=self.employee, status="completed",
        )
        for client in (active_client, completed_client):
            DirectClientAccess.objects.create(client=client, employee=self.employee, granted_by=self.employee)

        self.authenticate(self.admin)
        self.assertEqual(self.client.delete(f"/api/auth/employees/{profile.id}/").status_code, 204)
        active_client.refresh_from_db()
        completed_client.refresh_from_db()
        self.assertEqual(active_client.pool_reason, "employee_deactivated")
        self.assertEqual(completed_client.status, "archived")
        self.assertTrue(
            DirectClientAccess.objects.filter(client=active_client, revoked_at__isnull=False).exists()
        )

    def test_login_is_blocked_after_five_failures(self):
        self.client.credentials()
        for index in range(5):
            response = self.client.post(
                "/api/auth/login/", {"username": "worker", "password": "wrong-password"}, format="json"
            )
        self.assertEqual(response.status_code, 429)
        self.assertEqual(LoginAttempt.objects.filter(username="worker", successful=False).count(), 5)
        response = self.client.post(
            "/api/auth/login/", {"username": "worker", "password": "test-pass-123"}, format="json"
        )
        self.assertEqual(response.status_code, 429)
