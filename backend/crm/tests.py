from django.core.exceptions import ValidationError
from django.urls import reverse
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from accounts.models import User
from .models import AuditLog, ClientProfile, DeletionRequest, DirectClientAccess, Notification


def client_payload(**overrides):
    data = {
        "client_type": "person",
        "first_name": "Іван",
        "last_name": "Клієнт",
        "email": "client@example.com",
        "phone": "+380000000000",
        "country": "Україна",
        "city": "Київ",
        "preferred_contact": "email",
        "requested_service": "Web development",
        "project_request": "Створення корпоративного сайту",
    }
    data.update(overrides)
    return data


class ClientAccessTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user("admin", "admin@example.com", "test-pass-123", role="admin")
        self.employee = User.objects.create_user("worker", "worker@example.com", "test-pass-123", role="employee")
        self.other_employee = User.objects.create_user("other", "other@example.com", "test-pass-123", role="employee")

    def authenticate(self, user):
        token, _ = Token.objects.get_or_create(user=user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    def test_creator_receives_access_and_other_employee_does_not(self):
        self.authenticate(self.employee)
        response = self.client.post("/api/clients/", client_payload(), format="json")
        self.assertEqual(response.status_code, 201)
        client_id = response.data["id"]
        self.assertTrue(DirectClientAccess.objects.filter(client_id=client_id, employee=self.employee).exists())
        self.assertTrue(AuditLog.objects.filter(action="client.created", entity_id=str(client_id)).exists())

        self.authenticate(self.other_employee)
        response = self.client.get("/api/clients/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [])

    def test_admin_cannot_list_assigned_client_profiles(self):
        profile = ClientProfile.objects.create(created_by=self.employee, **client_payload())
        DirectClientAccess.objects.create(client=profile, employee=self.employee, granted_by=self.employee)
        self.authenticate(self.admin)
        response = self.client.get("/api/clients/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [])

    def test_self_registration_creates_unassigned_client(self):
        response = self.client.post("/api/register/", {
            "username": "self-client",
            "password": "strong-pass-123",
            **client_payload(email="self@example.com"),
        }, format="json")
        self.assertEqual(response.status_code, 201)
        profile = ClientProfile.objects.get(user__username="self-client")
        self.assertIsNone(profile.created_by)
        self.assertFalse(profile.direct_accesses.exists())

        self.authenticate(self.admin)
        response = self.client.get("/api/clients/unassigned/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data[0]["id"], profile.id)

    def test_audit_log_cannot_be_changed_or_deleted(self):
        event = AuditLog.objects.create(actor=self.employee, action="test", entity_type="test", entity_id="1")
        event.action = "changed"
        with self.assertRaises(ValidationError):
            event.save()
        with self.assertRaises(ValidationError):
            event.delete()

    def test_employee_can_open_and_update_only_accessible_client(self):
        self.authenticate(self.employee)
        created = self.client.post("/api/clients/", client_payload(), format="json")
        client_id = created.data["id"]
        response = self.client.patch(
            f"/api/clients/{client_id}/",
            {"status": "active", "project_progress": 35, "project_status_note": "Discovery completed"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["project_progress"], 35)

        self.authenticate(self.other_employee)
        self.assertEqual(self.client.get(f"/api/clients/{client_id}/").status_code, 404)

    def test_client_has_only_own_cabinet_and_cannot_change_internal_fields(self):
        response = self.client.post("/api/register/", {
            "username": "cabinet-client", "password": "strong-pass-123", **client_payload(email="cabinet@example.com")
        }, format="json")
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {response.data['token']}")
        self.assertEqual(self.client.get("/api/clients/").status_code, 403)
        mine = self.client.get("/api/clients/mine/")
        self.assertEqual(mine.status_code, 200)
        self.assertNotIn("internal_notes", mine.data)
        client_id = mine.data["id"]
        self.assertEqual(
            self.client.patch(f"/api/clients/{client_id}/", {"city": "Львів"}, format="json").status_code,
            200,
        )
        self.assertEqual(
            self.client.patch(f"/api/clients/{client_id}/", {"status": "completed"}, format="json").status_code,
            400,
        )

    def test_admin_assigns_unassigned_client_without_general_client_access(self):
        profile = ClientProfile.objects.create(
            pool_reason=ClientProfile.PoolReason.SELF_REGISTERED,
            **client_payload(email="pool@example.com"),
        )
        self.authenticate(self.admin)
        response = self.client.post(
            f"/api/clients/{profile.id}/assign/", {"employee_id": self.employee.id}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            set(response.data),
            {"id", "display_name", "created_at", "pool_reason", "pool_reason_label"},
        )
        self.assertTrue(DirectClientAccess.objects.filter(client=profile, employee=self.employee).exists())
        self.assertEqual(self.client.get(f"/api/clients/{profile.id}/").status_code, 404)

    def test_deletion_request_requires_admin_decision_and_hides_client_after_approval(self):
        profile = ClientProfile.objects.create(created_by=self.employee, **client_payload(email="delete@example.com"))
        DirectClientAccess.objects.create(client=profile, employee=self.employee, granted_by=self.employee)
        self.authenticate(self.employee)
        response = self.client.post(
            "/api/deletion-requests/",
            {"client_id": profile.id, "reason": "Анкету створено помилково"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        request_id = response.data["id"]
        self.assertTrue(Notification.objects.filter(kind="deletion_request_created").exists())

        self.authenticate(self.admin)
        pending = self.client.get("/api/deletion-requests/")
        self.assertEqual(pending.data[0]["client"]["email"], "delete@example.com")
        decision = self.client.post(
            f"/api/deletion-requests/{request_id}/decision/",
            {"decision": "approved", "note": "Підтверджено"},
            format="json",
        )
        self.assertEqual(decision.status_code, 200)
        self.assertEqual(set(decision.data["client"]), {"id", "display_name"})
        profile.refresh_from_db()
        self.assertTrue(profile.is_deleted)
        self.assertEqual(DeletionRequest.objects.get(pk=request_id).status, "approved")

    def test_admin_can_reject_only_self_registered_pool_client(self):
        client_user = User.objects.create_user(
            "spam-client", "spam@example.com", "test-pass-123", role="client"
        )
        profile = ClientProfile.objects.create(
            user=client_user,
            pool_reason=ClientProfile.PoolReason.SELF_REGISTERED,
            **client_payload(email="spam@example.com"),
        )
        Token.objects.create(user=client_user)
        self.authenticate(self.admin)
        response = self.client.post(
            f"/api/clients/{profile.id}/reject-registration/",
            {"reason": "Очевидно некоректні дані"},
            format="json",
        )
        self.assertEqual(response.status_code, 204)
        profile.refresh_from_db()
        client_user.refresh_from_db()
        self.assertTrue(profile.is_deleted)
        self.assertFalse(client_user.is_active)
        self.assertFalse(Token.objects.filter(user=client_user).exists())
        event = AuditLog.objects.get(action="client.registration_rejected")
        self.assertEqual(event.changes["reason"], "Очевидно некоректні дані")

    def test_audit_log_is_paginated_and_filterable(self):
        for index in range(35):
            AuditLog.objects.create(
                actor=self.employee,
                action="client.updated" if index % 2 else "client.created",
                entity_type="crm.ClientProfile",
                entity_id=str(index),
                entity_label=f"Client {index}",
            )
        self.authenticate(self.admin)
        response = self.client.get("/api/audit/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 35)
        self.assertEqual(len(response.data["results"]), 30)
        filtered = self.client.get(
            "/api/audit/", {"actor": self.employee.id, "action": "client.updated"}
        )
        self.assertEqual(filtered.data["count"], 17)
