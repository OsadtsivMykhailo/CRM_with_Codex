from django.core import mail
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone
from unittest.mock import patch
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from accounts.models import User
from .mailing import merge_values, process_campaign, render_content
from .models import (
    AuditLog,
    ClientGroup,
    ClientGroupAdditionRequest,
    ClientGroupCreationRequest,
    ClientProfile,
    DeletionRequest,
    DirectClientAccess,
    EmailCampaign,
    EmailCampaignRecipient,
    EmailServerConfiguration,
    Notification,
    SharedSender,
)


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
            f"/api/clients/{profile.id}/assign/",
            {"assignee_type": "employee", "assignee_id": self.employee.id},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            set(response.data),
            {"id", "display_name", "created_at", "pool_reason", "pool_reason_label"},
        )
        self.assertTrue(DirectClientAccess.objects.filter(client=profile, employee=self.employee).exists())
        self.assertEqual(self.client.get(f"/api/clients/{profile.id}/").status_code, 404)

    def test_admin_assigns_unassigned_client_to_one_client_group(self):
        profile = ClientProfile.objects.create(
            pool_reason=ClientProfile.PoolReason.SELF_REGISTERED,
            **client_payload(email="pool-group@example.com"),
        )
        group = ClientGroup.objects.create(name="Група призначення", created_by=self.admin)
        group.editors.add(self.employee, self.other_employee)
        self.authenticate(self.admin)
        response = self.client.post(
            f"/api/clients/{profile.id}/assign/",
            {"assignee_type": "group", "assignee_id": group.id},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        profile.refresh_from_db()
        self.assertEqual(profile.pool_reason, ClientProfile.PoolReason.NONE)
        self.assertTrue(group.clients.filter(pk=profile.pk).exists())
        self.assertFalse(profile.direct_accesses.exists())
        self.assertEqual(
            Notification.objects.filter(kind="client_assigned_via_group", entity_id=str(profile.id)).count(),
            2,
        )

        self.authenticate(self.employee)
        self.assertEqual(self.client.get(f"/api/clients/{profile.id}/").status_code, 200)

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

    def test_rejection_reason_is_sent_in_notification_and_email(self):
        profile = ClientProfile.objects.create(
            created_by=self.employee,
            **client_payload(email="rejected-delete@example.com"),
        )
        DirectClientAccess.objects.create(
            client=profile,
            employee=self.employee,
            granted_by=self.employee,
        )
        self.authenticate(self.employee)
        created = self.client.post(
            "/api/deletion-requests/",
            {"client_id": profile.id, "reason": "Анкету створено помилково"},
            format="json",
        )

        self.authenticate(self.admin)
        rejection_reason = "Анкета містить коректні дані клієнта."
        response = self.client.post(
            f"/api/deletion-requests/{created.data['id']}/decision/",
            {"decision": "rejected", "note": rejection_reason},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        notification = Notification.objects.get(
            user=self.employee,
            kind="deletion_request_rejected",
        )
        self.assertIn(rejection_reason, notification.message)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(rejection_reason, mail.outbox[0].body)

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

    def test_client_controls_marketing_consent_and_can_unsubscribe_by_link(self):
        response = self.client.post("/api/register/", {
            "username": "marketing-client",
            "password": "strong-pass-123",
            "marketing_email_consent": True,
            **client_payload(email="marketing@example.com"),
        }, format="json")
        profile = ClientProfile.objects.get(user__username="marketing-client")
        self.assertTrue(profile.marketing_email_consent)

        self.client.credentials(HTTP_AUTHORIZATION=f"Token {response.data['token']}")
        changed = self.client.patch(
            "/api/clients/email-preferences/",
            {"marketing_email_consent": False},
            format="json",
        )
        self.assertEqual(changed.status_code, 200)
        self.assertFalse(changed.data["marketing_email_consent"])

        profile.marketing_email_consent = True
        profile.save(update_fields=["marketing_email_consent"])
        self.client.credentials()
        unsubscribed = self.client.post(f"/api/email-unsubscribe/{profile.unsubscribe_token}/", {}, format="json")
        self.assertEqual(unsubscribed.status_code, 200)
        profile.refresh_from_db()
        self.assertFalse(profile.marketing_email_consent)

    def test_campaign_accepts_only_accessible_clients_and_deduplicates_email(self):
        first = ClientProfile.objects.create(created_by=self.employee, **client_payload(email="same@example.com"))
        second = ClientProfile.objects.create(
            created_by=self.employee,
            **client_payload(email="same@example.com", first_name="Петро"),
        )
        forbidden = ClientProfile.objects.create(
            created_by=self.other_employee,
            **client_payload(email="forbidden@example.com", first_name="Марія"),
        )
        for profile in (first, second):
            DirectClientAccess.objects.create(client=profile, employee=self.employee, granted_by=self.employee)
        DirectClientAccess.objects.create(
            client=forbidden,
            employee=self.other_employee,
            granted_by=self.other_employee,
        )
        self.authenticate(self.employee)
        response = self.client.post("/api/email-campaigns/", {
            "message_type": "service",
            "sender_type": "personal",
            "subject": "Оновлення для {{client_name}}",
            "html_body": "<p>Вітаємо, <strong>{{client_name}}</strong></p>",
            "text_body": "Вітаємо, {{client_name}}",
            "client_ids": [first.id, second.id],
        }, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["total_recipients"], 1)

        forbidden_response = self.client.post("/api/email-campaigns/", {
            "message_type": "service",
            "sender_type": "personal",
            "subject": "Недоступний клієнт",
            "html_body": "<p>Тест</p>",
            "client_ids": [forbidden.id],
        }, format="json")
        self.assertEqual(forbidden_response.status_code, 400)

    def test_marketing_campaign_skips_client_without_consent(self):
        consenting = ClientProfile.objects.create(
            created_by=self.employee,
            marketing_email_consent=True,
            **client_payload(email="yes@example.com"),
        )
        refusing = ClientProfile.objects.create(
            created_by=self.employee,
            marketing_email_consent=False,
            **client_payload(email="no@example.com", first_name="Олена"),
        )
        for profile in (consenting, refusing):
            DirectClientAccess.objects.create(client=profile, employee=self.employee, granted_by=self.employee)
        self.authenticate(self.employee)
        created = self.client.post("/api/email-campaigns/", {
            "message_type": "marketing",
            "sender_type": "personal",
            "subject": "Новини",
            "html_body": "<p>Привіт, {{client_name}}</p>",
            "client_ids": [consenting.id, refusing.id],
        }, format="json")
        campaign = EmailCampaign.objects.get(pk=created.data["id"])
        campaign.status = EmailCampaign.Status.QUEUED
        campaign.save(update_fields=["status"])
        EmailServerConfiguration.objects.create(pk=1)
        with patch("crm.mailing.email_connection") as connection, patch("crm.mailing.send_recipient") as send:
            process_campaign(campaign)
        campaign.refresh_from_db()
        self.assertEqual(send.call_count, 1)
        self.assertEqual(campaign.sent_count, 1)
        self.assertEqual(campaign.skipped_count, 1)

    def test_group_campaign_and_shared_sender_require_employee_access(self):
        profile = ClientProfile.objects.create(created_by=self.employee, **client_payload(email="group@example.com"))
        DirectClientAccess.objects.create(client=profile, employee=self.employee, granted_by=self.employee)
        group = ClientGroup.objects.create(name="Команда проєкту", created_by=self.employee)
        group.editors.add(self.employee)
        group.clients.add(profile)
        shared = SharedSender.objects.create(
            name="Multisoft Info",
            email="info@multisoft.example",
            created_by=self.admin,
        )
        shared.allowed_employees.add(self.employee)
        self.authenticate(self.employee)
        response = self.client.post("/api/email-campaigns/", {
            "message_type": "service",
            "sender_type": "shared",
            "shared_sender_id": shared.id,
            "subject": "Групове оновлення",
            "html_body": "<p>Оновлення</p>",
            "client_group_ids": [group.id],
        }, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["from_email"], shared.email)
        self.assertEqual(response.data["total_recipients"], 1)

        self.authenticate(self.other_employee)
        denied = self.client.post("/api/email-campaigns/", {
            "message_type": "service",
            "sender_type": "shared",
            "shared_sender_id": shared.id,
            "subject": "Недоступна адреса",
            "html_body": "<p>Оновлення</p>",
            "include_all_accessible": True,
        }, format="json")
        self.assertEqual(denied.status_code, 400)

    def test_only_admin_can_update_smtp_configuration_and_password_is_hidden(self):
        self.authenticate(self.admin)
        response = self.client.patch("/api/email-settings/", {
            "host": "smtp.example.com",
            "port": 587,
            "username": "crm",
            "password": "smtp-secret",
            "use_tls": True,
        }, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["has_password"])
        self.assertNotIn("password", response.data)
        self.assertNotEqual(EmailServerConfiguration.objects.get(pk=1).encrypted_password, "smtp-secret")

        self.authenticate(self.employee)
        self.assertEqual(self.client.get("/api/email-settings/").status_code, 403)

    def test_employee_cannot_turn_personal_template_into_company_template(self):
        self.authenticate(self.employee)
        created = self.client.post("/api/email-templates/", {
            "name": "Мій шаблон",
            "scope": "personal",
            "message_type": "service",
            "subject": "Привітання",
            "html_body": "<p>Вітаємо!</p>",
            "text_body": "Вітаємо!",
        }, format="json")
        self.assertEqual(created.status_code, 201)
        changed = self.client.patch(
            f"/api/email-templates/{created.data['id']}/",
            {"scope": "company"},
            format="json",
        )
        self.assertEqual(changed.status_code, 400)

    def test_campaign_cannot_be_queued_after_client_access_is_revoked(self):
        profile = ClientProfile.objects.create(
            created_by=self.employee,
            **client_payload(email="revoked@example.com"),
        )
        access = DirectClientAccess.objects.create(
            client=profile,
            employee=self.employee,
            granted_by=self.employee,
        )
        self.authenticate(self.employee)
        created = self.client.post("/api/email-campaigns/", {
            "message_type": "service",
            "sender_type": "personal",
            "subject": "Чернетка",
            "html_body": "<p>Оновлення</p>",
            "client_ids": [profile.id],
        }, format="json")
        access.revoked_at = timezone.now()
        access.revoked_by = self.admin
        access.save(update_fields=["revoked_at", "revoked_by"])
        response = self.client.post(
            f"/api/email-campaigns/{created.data['id']}/queue/",
            {},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_only_admin_manages_groups_and_group_editors_receive_client_access(self):
        profile = ClientProfile.objects.create(
            created_by=self.employee,
            **client_payload(email="group-access@example.com"),
        )
        self.authenticate(self.employee)
        denied = self.client.post("/api/client-groups/", {
            "name": "Недозволена група",
            "client_ids": [profile.id],
            "editor_ids": [self.employee.id],
        }, format="json")
        self.assertEqual(denied.status_code, 403)

        self.authenticate(self.admin)
        created = self.client.post("/api/client-groups/", {
            "name": "Команда клієнта",
            "client_ids": [profile.id],
            "editor_ids": [self.other_employee.id],
        }, format="json")
        self.assertEqual(created.status_code, 201)
        options = self.client.get("/api/client-groups/client-options/")
        self.assertEqual(set(options.data[0]), {"id", "display_name", "status"})

        self.authenticate(self.other_employee)
        accessible = self.client.get(f"/api/clients/{profile.id}/")
        self.assertEqual(accessible.status_code, 200)
        self.assertIn(self.other_employee.id, {
            employee["id"] for employee in accessible.data["responsible_employees"]
        })
        self.assertEqual(
            self.client.patch(f"/api/client-groups/{created.data['id']}/", {"name": "Зміна"}, format="json").status_code,
            403,
        )

    def test_employee_can_assign_new_client_only_to_own_group(self):
        own_group = ClientGroup.objects.create(name="Моя група", created_by=self.admin)
        own_group.editors.add(self.employee)
        foreign_group = ClientGroup.objects.create(name="Чужа група", created_by=self.admin)
        foreign_group.editors.add(self.other_employee)
        self.authenticate(self.employee)
        created = self.client.post("/api/clients/", client_payload(
            email="created-in-group@example.com",
            client_group_id=own_group.id,
        ), format="json")
        self.assertEqual(created.status_code, 201)
        self.assertTrue(own_group.clients.filter(pk=created.data["id"]).exists())
        denied = self.client.post("/api/clients/", client_payload(
            email="foreign-group@example.com",
            client_group_id=foreign_group.id,
        ), format="json")
        self.assertEqual(denied.status_code, 400)

    def test_direct_access_employee_requests_group_addition_and_admin_approves(self):
        profile = ClientProfile.objects.create(
            created_by=self.employee,
            **client_payload(email="addition@example.com"),
        )
        DirectClientAccess.objects.create(client=profile, employee=self.employee, granted_by=self.employee)
        group = ClientGroup.objects.create(name="Запитувана група", created_by=self.admin)
        group.editors.add(self.employee, self.other_employee)
        self.authenticate(self.employee)
        created = self.client.post("/api/client-group-addition-requests/", {
            "client_id": profile.id,
            "group_id": group.id,
            "reason": "Клієнт належить до цього сегмента",
        }, format="json")
        self.assertEqual(created.status_code, 201)
        self.assertFalse(group.clients.filter(pk=profile.pk).exists())

        self.authenticate(self.admin)
        pending = self.client.get("/api/client-group-addition-requests/")
        self.assertEqual(set(pending.data[0]["client"]), {"id", "display_name"})
        approved = self.client.post(
            f"/api/client-group-addition-requests/{created.data['id']}/decision/",
            {"decision": "approved", "note": "Підтверджено"},
            format="json",
        )
        self.assertEqual(approved.status_code, 200)
        self.assertTrue(group.clients.filter(pk=profile.pk).exists())

        self.authenticate(self.other_employee)
        self.assertEqual(self.client.get(f"/api/clients/{profile.id}/").status_code, 200)

    def test_group_creation_request_creates_group_and_adds_requester_as_editor(self):
        profile = ClientProfile.objects.create(
            created_by=self.employee,
            **client_payload(email="creation-request@example.com"),
        )
        DirectClientAccess.objects.create(client=profile, employee=self.employee, granted_by=self.employee)
        self.authenticate(self.employee)
        created = self.client.post("/api/client-group-creation-requests/", {
            "proposed_name": "Новий сегмент",
            "reason": "Потрібна окрема команда для проєкту",
            "proposed_client_ids": [profile.id],
            "proposed_employee_ids": [self.other_employee.id],
        }, format="json")
        self.assertEqual(created.status_code, 201)
        request_item = ClientGroupCreationRequest.objects.get(pk=created.data["id"])
        self.assertEqual(request_item.status, "pending")

        self.authenticate(self.admin)
        approved = self.client.post(
            f"/api/client-group-creation-requests/{request_item.id}/decision/",
            {"decision": "approved", "note": "Команду погоджено"},
            format="json",
        )
        self.assertEqual(approved.status_code, 200)
        group = ClientGroup.objects.get(name="Новий сегмент")
        self.assertEqual(set(group.editors.values_list("id", flat=True)), {
            self.employee.id, self.other_employee.id,
        })
        self.assertTrue(group.clients.filter(pk=profile.pk).exists())

    def test_group_request_manual_rejection_has_cooldown_and_reason(self):
        profile = ClientProfile.objects.create(
            created_by=self.employee,
            **client_payload(email="cooldown@example.com"),
        )
        DirectClientAccess.objects.create(client=profile, employee=self.employee, granted_by=self.employee)
        group = ClientGroup.objects.create(name="Cooldown", created_by=self.admin)
        group.editors.add(self.employee)
        self.authenticate(self.employee)
        created = self.client.post("/api/client-group-addition-requests/", {
            "client_id": profile.id, "group_id": group.id, "reason": "Перевірка правила відхилення",
        }, format="json")
        self.authenticate(self.admin)
        reason = "Поки що група не підходить"
        self.client.post(
            f"/api/client-group-addition-requests/{created.data['id']}/decision/",
            {"decision": "rejected", "note": reason},
            format="json",
        )
        self.assertIn(reason, Notification.objects.get(
            user=self.employee, kind="client_group_addition_request_rejected"
        ).message)
        self.authenticate(self.employee)
        repeated = self.client.post("/api/client-group-addition-requests/", {
            "client_id": profile.id, "group_id": group.id, "reason": "Повторна перевірка правила",
        }, format="json")
        self.assertEqual(repeated.status_code, 400)

    def test_personalization_blocks_missing_field_and_renders_each_recipient(self):
        company = ClientProfile.objects.create(
            created_by=self.employee,
            **client_payload(
                client_type="company", first_name="", last_name="", company_name="Acme",
                contact_person="", email="acme@example.com",
            ),
        )
        DirectClientAccess.objects.create(client=company, employee=self.employee, granted_by=self.employee)
        self.authenticate(self.employee)
        created = self.client.post("/api/email-campaigns/", {
            "message_type": "service",
            "sender_type": "personal",
            "subject": "Вітаємо, {{FirstName}} — {{Company}}",
            "html_body": "<p>Співпраця з {{CompanyName}}</p>",
            "client_ids": [company.id],
        }, format="json")
        self.assertEqual(created.status_code, 201)
        blocked = self.client.post(f"/api/email-campaigns/{created.data['id']}/queue/", {}, format="json")
        self.assertEqual(blocked.status_code, 400)
        self.assertIn("{{FirstName}}", str(blocked.data))
        self.assertIn("Acme", str(blocked.data))

        legacy = self.client.post("/api/email-campaigns/", {
            "message_type": "service",
            "sender_type": "personal",
            "subject": "Вітаємо, {{client_name}}",
            "html_body": "<p>Повідомлення для {{company_name}}</p>",
            "client_ids": [company.id],
        }, format="json")
        legacy_blocked = self.client.post(
            f"/api/email-campaigns/{legacy.data['id']}/queue/", {}, format="json"
        )
        self.assertEqual(legacy_blocked.status_code, 400)
        self.assertIn("{{client_name}}", str(legacy_blocked.data))

        company.contact_person = "Олена Коваль"
        company.save(update_fields=["contact_person"])
        queued = self.client.post(f"/api/email-campaigns/{created.data['id']}/queue/", {}, format="json")
        self.assertEqual(queued.status_code, 200)
        campaign = EmailCampaign.objects.get(pk=created.data["id"])
        recipient = EmailCampaignRecipient.objects.get(campaign=campaign)
        values = merge_values(campaign, recipient, "Multisoft Velari")
        self.assertEqual(values["{{FirstName}}"], "Олена")
        self.assertEqual(values["{{CompanyName}}"], "Acme")
        self.assertEqual(values["{{Company}}"], "Multisoft Velari")
        self.assertEqual(values["{{client_name}}"], "Олена Коваль")
        self.assertEqual(render_content(campaign.subject, values), "Вітаємо, Олена — Multisoft Velari")
