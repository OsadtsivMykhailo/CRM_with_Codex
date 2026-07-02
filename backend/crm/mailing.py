import html
import re

from bleach import clean
from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection
from django.db import transaction
from django.utils import timezone
from django.utils.html import strip_tags

from .email_security import decrypt_secret
from .models import (
    ClientProfile,
    EmailCampaign,
    EmailCampaignRecipient,
    EmailServerConfiguration,
)
from .services import accessible_clients, audit, notify


ALLOWED_HTML_TAGS = [
    "p", "br", "strong", "b", "em", "i", "u", "s", "h1", "h2", "h3",
    "ul", "ol", "li", "blockquote", "a", "hr",
]
ALLOWED_HTML_ATTRIBUTES = {"a": ["href", "title", "target", "rel"]}
SUPPORTED_MARKERS = {
    "{{FirstName}}",
    "{{CompanyName}}",
    "{{Company}}",
    "{{client_name}}",
    "{{company_name}}",
    "{{employee_name}}",
    "{{employee_email}}",
    "{{unsubscribe_url}}",
}
MARKER_PATTERN = re.compile(r"{{[A-Za-z_][A-Za-z0-9_]*}}")


def sanitize_email_html(value):
    return clean(
        value or "",
        tags=ALLOWED_HTML_TAGS,
        attributes=ALLOWED_HTML_ATTRIBUTES,
        protocols=["http", "https", "mailto"],
        strip=True,
    )


def content_markers(*values):
    markers = set()
    for value in values:
        markers.update(MARKER_PATTERN.findall(value or ""))
    return markers


def unknown_markers(*values):
    return sorted(content_markers(*values) - SUPPORTED_MARKERS)


def _client_first_name(client):
    if client.client_type == client.ClientType.COMPANY:
        return (client.contact_person or "").strip().split(maxsplit=1)[0] if client.contact_person.strip() else ""
    return client.first_name.strip()


def personalization_errors(campaign, recipients, sender_company_name):
    markers = content_markers(campaign.subject, campaign.html_body, campaign.text_body)
    errors = []
    unknown = sorted(markers - SUPPORTED_MARKERS)
    for marker in unknown:
        errors.append(f"Невідома змінна {marker}.")
    if "{{Company}}" in markers and not (sender_company_name or "").strip():
        errors.append("Для змінної {{Company}} не заповнено назву компанії-відправника в налаштуваннях пошти.")
    for recipient in recipients:
        client = recipient.client
        if (
            "{{client_name}}" in markers
            and client.client_type == client.ClientType.COMPANY
            and not client.contact_person.strip()
        ):
            errors.append(
                f"Анкета «{client.display_name or f'#{client.pk}'}»: поле «контактна особа» потрібне для "
                "{{client_name}}."
            )
        if "{{FirstName}}" in markers and not _client_first_name(client):
            field = "контактна особа" if client.client_type == client.ClientType.COMPANY else "ім’я"
            errors.append(
                f"Анкета «{client.display_name or f'#{client.pk}'}»: поле «{field}» потрібне для "
                "{{FirstName}}."
            )
        if ("{{CompanyName}}" in markers or "{{company_name}}" in markers) and not client.company_name.strip():
            errors.append(
                f"Анкета «{client.display_name or f'#{client.pk}'}»: поле «назва компанії» потрібне "
                "для " + ("{{CompanyName}}" if "{{CompanyName}}" in markers else "{{company_name}}") + "."
            )
    return errors


def merge_values(campaign, recipient, sender_company_name):
    client = recipient.client
    employee = campaign.created_by
    company_name = client.company_name if client.client_type == client.ClientType.COMPANY else ""
    unsubscribe_url = f"{settings.FRONTEND_URL.rstrip('/')}/unsubscribe/{client.unsubscribe_token}"
    client_name = client.contact_person.strip() if client.client_type == client.ClientType.COMPANY else recipient.display_name
    return {
        "{{FirstName}}": _client_first_name(client),
        "{{CompanyName}}": company_name,
        "{{Company}}": sender_company_name,
        "{{client_name}}": client_name,
        "{{company_name}}": company_name,
        "{{employee_name}}": employee.get_full_name() or employee.username,
        "{{employee_email}}": employee.email,
        "{{unsubscribe_url}}": unsubscribe_url,
    }


def render_content(value, values, escape_values=False):
    rendered = value or ""
    for marker, replacement in values.items():
        rendered = rendered.replace(marker, html.escape(str(replacement)) if escape_values else str(replacement))
    return rendered


def email_connection(configuration):
    return get_connection(
        backend="django.core.mail.backends.smtp.EmailBackend",
        host=configuration.host,
        port=configuration.port,
        username=configuration.username or None,
        password=decrypt_secret(configuration.encrypted_password) or None,
        use_tls=configuration.use_tls,
        use_ssl=configuration.use_ssl,
        timeout=20,
    )


def send_recipient(campaign, recipient, connection, sender_company_name):
    values = merge_values(campaign, recipient, sender_company_name)
    subject = render_content(campaign.subject, values)
    html_body = render_content(campaign.html_body, values, escape_values=True)
    text_body = render_content(campaign.text_body, values)
    unsubscribe_url = values["{{unsubscribe_url}}"]
    unsubscribe_api_url = (
        f"{settings.BACKEND_PUBLIC_URL.rstrip('/')}/api/email-unsubscribe/"
        f"{recipient.client.unsubscribe_token}/"
    )

    headers = {}
    if campaign.message_type == "marketing":
        footer = (
            '<hr><p style="font-size:12px;color:#666">'
            f'<a href="{html.escape(unsubscribe_url)}">Відмовитися від рекламних розсилок</a></p>'
        )
        html_body += footer
        text_body = (text_body or strip_tags(html_body)) + f"\n\nВідписатися: {unsubscribe_url}"
        headers = {
            "List-Unsubscribe": f"<{unsubscribe_api_url}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        }
    elif not text_body:
        text_body = strip_tags(html_body)

    message = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=f"{campaign.from_name} <{campaign.from_email}>",
        to=[recipient.email],
        reply_to=[campaign.from_email],
        headers=headers,
        connection=connection,
    )
    if html_body:
        message.attach_alternative(html_body, "text/html")
    for attachment in campaign.attachments.all():
        with attachment.file.open("rb") as file_handle:
            message.attach(attachment.original_name, file_handle.read(), attachment.content_type or None)
    message.send(fail_silently=False)


def process_campaign(campaign):
    sender_is_valid = campaign.created_by.is_active
    if campaign.sender_type == EmailCampaign.SenderType.SHARED:
        sender_is_valid = sender_is_valid and campaign.shared_sender.is_active and (
            campaign.shared_sender.allowed_employees.filter(pk=campaign.created_by_id).exists()
        )
    else:
        sender_is_valid = sender_is_valid and (
            campaign.from_email.casefold() == campaign.created_by.email.casefold()
        )
    if not sender_is_valid:
        campaign.recipients.filter(status=EmailCampaignRecipient.Status.PENDING).update(
            status=EmailCampaignRecipient.Status.FAILED,
            error_message="Відправник більше не має права використовувати цю адресу.",
        )
        campaign.status = EmailCampaign.Status.FAILED
        campaign.failed_count = campaign.recipients.count()
        campaign.completed_at = timezone.now()
        campaign.save(update_fields=["status", "failed_count", "completed_at", "updated_at"])
        notify(
            campaign.created_by,
            "email_campaign_failed",
            "Розсилку не виконано",
            f"Для «{campaign.subject}» відправник більше не має доступу до вибраної адреси.",
            campaign,
        )
        return campaign

    configuration, _ = EmailServerConfiguration.objects.get_or_create(pk=1)
    if not configuration.is_active:
        campaign.status = EmailCampaign.Status.FAILED
        campaign.completed_at = timezone.now()
        campaign.failed_count = campaign.recipients.count()
        campaign.recipients.filter(status=EmailCampaignRecipient.Status.PENDING).update(
            status=EmailCampaignRecipient.Status.FAILED,
            error_message="SMTP-сервер вимкнений.",
        )
        campaign.save(update_fields=["status", "completed_at", "failed_count", "updated_at"])
        notify(
            campaign.created_by,
            "email_campaign_failed",
            "Розсилку не виконано",
            f"Для «{campaign.subject}» не налаштовано активний SMTP-сервер.",
            campaign,
        )
        return campaign

    campaign.status = EmailCampaign.Status.PROCESSING
    campaign.save(update_fields=["status", "updated_at"])
    connection = None
    try:
        connection = email_connection(configuration)
        connection.open()
        recipients = campaign.recipients.select_related("client").all()
        allowed_client_ids = set(
            accessible_clients(campaign.created_by)
            .exclude(status=ClientProfile.Status.ARCHIVED)
            .values_list("id", flat=True)
        )
        for recipient in recipients:
            if recipient.status != EmailCampaignRecipient.Status.PENDING:
                continue
            if recipient.client_id not in allowed_client_ids:
                recipient.status = EmailCampaignRecipient.Status.SKIPPED
                recipient.error_message = "Доступ працівника до клієнта було відкликано."
                recipient.save(update_fields=["status", "error_message"])
                continue
            if campaign.message_type == "marketing" and not recipient.client.marketing_email_consent:
                recipient.status = EmailCampaignRecipient.Status.SKIPPED
                recipient.error_message = "Клієнт не надав згоди на рекламні розсилки."
                recipient.save(update_fields=["status", "error_message"])
                continue
            try:
                send_recipient(campaign, recipient, connection, configuration.company_name)
                recipient.status = EmailCampaignRecipient.Status.SENT
                recipient.sent_at = timezone.now()
                recipient.error_message = ""
                recipient.save(update_fields=["status", "sent_at", "error_message"])
            except Exception as exc:  # SMTP providers return different exception classes.
                recipient.status = EmailCampaignRecipient.Status.FAILED
                recipient.error_message = str(exc)[:1000]
                recipient.save(update_fields=["status", "error_message"])
    except Exception as exc:
        campaign.recipients.filter(status=EmailCampaignRecipient.Status.PENDING).update(
            status=EmailCampaignRecipient.Status.FAILED,
            error_message=str(exc)[:1000],
        )
    finally:
        if connection:
            connection.close()

    sent = campaign.recipients.filter(status=EmailCampaignRecipient.Status.SENT).count()
    failed = campaign.recipients.filter(status=EmailCampaignRecipient.Status.FAILED).count()
    skipped = campaign.recipients.filter(status=EmailCampaignRecipient.Status.SKIPPED).count()
    if sent == 0 and failed:
        final_status = EmailCampaign.Status.FAILED
    elif failed:
        final_status = EmailCampaign.Status.PARTIAL_FAILED
    else:
        final_status = EmailCampaign.Status.COMPLETED
    campaign.status = final_status
    campaign.sent_count = sent
    campaign.failed_count = failed
    campaign.skipped_count = skipped
    campaign.completed_at = timezone.now()
    campaign.save(update_fields=[
        "status", "sent_count", "failed_count", "skipped_count", "completed_at", "updated_at",
    ])
    audit(
        campaign.created_by,
        "email_campaign.completed",
        campaign,
        {"sent": sent, "failed": failed, "skipped": skipped},
    )
    notify(
        campaign.created_by,
        "email_campaign_completed",
        "Розсилку завершено",
        f"«{campaign.subject}»: надіслано — {sent}, помилок — {failed}, пропущено — {skipped}.",
        campaign,
    )
    return campaign


@transaction.atomic
def claim_next_campaign():
    campaign = (
        EmailCampaign.objects.select_for_update(skip_locked=True)
        .filter(status=EmailCampaign.Status.QUEUED)
        .order_by("queued_at", "id")
        .first()
    )
    if campaign:
        campaign.status = EmailCampaign.Status.PROCESSING
        campaign.save(update_fields=["status", "updated_at"])
    return campaign
