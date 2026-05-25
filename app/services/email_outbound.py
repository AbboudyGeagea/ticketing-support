"""Outbound email notifications via Microsoft Graph API."""
import logging
import requests
import msal
from flask import current_app, render_template

logger = logging.getLogger(__name__)

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_SCOPES = ["https://graph.microsoft.com/.default"]


def _get_token(eff: dict | None = None) -> str | None:
    from app.services.email_settings import get_effective_config
    eff = eff or get_effective_config()
    if not all([eff["tenant_id"], eff["client_id"], eff["client_secret"]]):
        logger.error("Graph API credentials missing — cannot acquire token")
        return None
    authority = f"https://login.microsoftonline.com/{eff['tenant_id']}"
    app = msal.ConfidentialClientApplication(
        eff["client_id"],
        authority=authority,
        client_credential=eff["client_secret"],
    )
    result = app.acquire_token_for_client(scopes=_SCOPES)
    if "access_token" not in result:
        logger.error("Graph API token error: %s", result.get("error_description"))
        return None
    return result["access_token"]


def _send(recipients: list[str], subject: str, html: str = None, text: str = None):
    if not recipients:
        return
    from app.services.email_settings import get_effective_config
    eff = get_effective_config()
    token = _get_token(eff)
    if not token:
        return
    mailbox = eff["mailbox"]
    content_type = "HTML" if html else "Text"
    content = html or text or ""
    payload = {
        "message": {
            "subject": subject,
            "body": {"contentType": content_type, "content": content},
            "toRecipients": [
                {"emailAddress": {"address": r}} for r in recipients
            ],
        },
        "saveToSentItems": True,
    }
    try:
        resp = requests.post(
            f"{_GRAPH_BASE}/users/{mailbox}/sendMail",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
            timeout=15,
        )
        if resp.status_code not in (200, 202):
            logger.error("Graph sendMail failed %s: %s", resp.status_code, resp.text)
    except Exception as exc:
        logger.error("Failed to send email to %s: %s", recipients, exc)


def notify_agents_new_ticket(ticket):
    from app.models.user import User
    agents = User.query.filter(
        User.role.in_(["agent", "admin"]),
        User.active == True,
    ).all()
    if not agents:
        return
    recipients = [a.email for a in agents]
    subject = f"[New Ticket] {ticket.ref} — {ticket.subject}"
    base_url = current_app.config.get("APP_BASE_URL", "")
    ticket_url = f"{base_url}/agent/tickets/{ticket.ref}"
    html = render_template("emails/new_ticket.html", ticket=ticket, ticket_url=ticket_url)
    _send(recipients, subject, html=html)


def notify_customer_reply(ticket, message):
    if not ticket.creator or not ticket.creator.email:
        return
    subject = f"[{ticket.ref}] Update on your ticket: {ticket.subject}"
    base_url = current_app.config.get("APP_BASE_URL", "")
    ticket_url = f"{base_url}/portal/tickets/{ticket.ref}"
    html = render_template(
        "emails/reply_notification.html",
        ticket=ticket,
        message=message,
        ticket_url=ticket_url,
    )
    _send([ticket.creator.email], subject, html=html)


def send_task_reminder(task):
    from app.models.user import User
    assignee = User.query.get(task.assigned_to)
    if not assignee:
        return
    subject = f"[Reminder] Task due: {task.title[:60]}"
    html = render_template("emails/task_reminder.html", task=task)
    _send([assignee.email], subject, html=html)


def notify_customer_status_change(ticket):
    if not ticket.creator or not ticket.creator.email:
        return
    subject = f"[{ticket.ref}] Your ticket status changed to: {ticket.status_label}"
    base_url = current_app.config.get("APP_BASE_URL", "")
    ticket_url = f"{base_url}/portal/tickets/{ticket.ref}"
    html = render_template("emails/status_change.html", ticket=ticket, ticket_url=ticket_url)
    _send([ticket.creator.email], subject, html=html)


def notify_customer_resolved_confirmation(ticket):
    if not ticket.creator or not ticket.creator.email:
        return
    from itsdangerous import URLSafeTimedSerializer
    s = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
    token = s.dumps(ticket.ref, salt="ticket-confirm")
    base_url = current_app.config.get("APP_BASE_URL", "")
    confirm_url = f"{base_url}/portal/tickets/{ticket.ref}/confirm?token={token}&action=close"
    reopen_url = f"{base_url}/portal/tickets/{ticket.ref}/confirm?token={token}&action=reopen"
    subject = f"[{ticket.ref}] Is your issue resolved?"
    html = render_template(
        "emails/resolved_confirmation.html",
        ticket=ticket,
        confirm_url=confirm_url,
        reopen_url=reopen_url,
    )
    _send([ticket.creator.email], subject, html=html)


def notify_sla_breach(ticket):
    from app.models.user import User
    if ticket.assignee:
        recipients = [ticket.assignee.email]
    else:
        agents = User.query.filter(User.role.in_(["agent", "admin"]), User.active == True).all()
        recipients = [a.email for a in agents]
    if not recipients:
        return
    base_url = current_app.config.get("APP_BASE_URL", "")
    ticket_url = f"{base_url}/agent/tickets/{ticket.ref}"
    subject = f"[SLA Breach] {ticket.ref} — {ticket.subject}"
    text = (
        f"Ticket {ticket.ref} has breached its SLA.\n\n"
        f"Subject: {ticket.subject}\n"
        f"Priority: {ticket.priority}\n"
        f"Hospital: {ticket.hospital.name if ticket.hospital else 'N/A'}\n\n"
        f"View ticket: {ticket_url}"
    )
    _send(recipients, subject, text=text)


def send_csat_survey(ticket):
    if not ticket.creator or not ticket.creator.email:
        return
    import uuid
    from app.models.csat_feedback import CSATFeedback
    from app.extensions import db
    if ticket.csat and ticket.csat.submitted_at:
        return
    token = uuid.uuid4().hex
    if not ticket.csat:
        csat = CSATFeedback(ticket_id=ticket.id, token=token)
        db.session.add(csat)
    else:
        ticket.csat.token = token
    ticket.csat_sent = True
    db.session.commit()
    base_url = current_app.config.get("APP_BASE_URL", "")
    feedback_url = f"{base_url}/feedback/{token}"
    subject = f"[{ticket.ref}] How did we do? Quick feedback"
    html = render_template("emails/csat_survey.html", ticket=ticket, feedback_url=feedback_url)
    _send([ticket.creator.email], subject, html=html)
