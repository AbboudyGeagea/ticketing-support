"""Outbound email notifications via Microsoft Graph API."""
import logging
import requests
import msal
from flask import current_app, render_template

logger = logging.getLogger(__name__)

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_SCOPES = ["https://graph.microsoft.com/.default"]


def send_diagnostic(recipient: str, subject: str, text: str) -> tuple[bool, str]:
    """Verbose send used by the admin diagnostics page.

    Returns (ok, message). On failure, message contains the Graph API
    HTTP status + body (or the MSAL error). Unlike _send(), nothing is
    swallowed — every failure mode surfaces a specific error string.
    """
    from app.services.email_settings import get_effective_config
    eff = get_effective_config()

    missing = [k for k in ("tenant_id", "client_id", "client_secret", "mailbox") if not eff.get(k)]
    if missing:
        return False, f"Missing credentials: {', '.join(missing)}"

    try:
        authority = f"https://login.microsoftonline.com/{eff['tenant_id']}"
        msal_app = msal.ConfidentialClientApplication(
            eff["client_id"], authority=authority, client_credential=eff["client_secret"],
        )
        result = msal_app.acquire_token_for_client(scopes=_SCOPES)
    except Exception as exc:
        return False, f"MSAL exception: {exc}"

    if "access_token" not in result:
        err = result.get("error", "unknown")
        desc = result.get("error_description", "")
        return False, f"Token acquisition failed [{err}]: {desc}"

    token = result["access_token"]
    mailbox = eff["mailbox"]
    payload = {
        "message": {
            "subject": subject,
            "body": {"contentType": "Text", "content": text},
            "toRecipients": [{"emailAddress": {"address": recipient}}],
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
    except Exception as exc:
        return False, f"HTTP request failed: {exc}"

    if resp.status_code in (200, 202):
        return True, f"Graph API accepted the message (HTTP {resp.status_code})."

    body = (resp.text or "")[:800]
    return False, f"Graph sendMail returned HTTP {resp.status_code}: {body}"


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


def notify_customer_ticket_created(ticket):
    """Confirmation email to the customer (creator) when a ticket is opened via the portal."""
    if not ticket.creator or not ticket.creator.email:
        return
    base_url = current_app.config.get("APP_BASE_URL", "")
    ticket_url = f"{base_url}/portal/tickets/{ticket.ref}"
    subject = f"[{ticket.ref}] Your ticket has been received — {ticket.subject}"
    html = render_template(
        "emails/ticket_created_customer.html",
        ticket=ticket,
        ticket_url=ticket_url,
    )
    _send([ticket.creator.email], subject, html=html)


def notify_agent_ticket_assigned(ticket, assigned_by_id):
    """
    Notify the newly assigned agent (unless they assigned themselves) and the customer.
    assigned_by_id: the user id of the person who performed the assignment action.
    """
    from app.models.user import User
    assignee = User.query.get(ticket.assigned_to) if ticket.assigned_to else None
    assigner = User.query.get(assigned_by_id) if assigned_by_id else None
    base_url = current_app.config.get("APP_BASE_URL", "")
    agent_ticket_url = f"{base_url}/agent/tickets/{ticket.ref}"
    portal_ticket_url = f"{base_url}/portal/tickets/{ticket.ref}"

    # Notify assigned agent (skip if they assigned themselves)
    if assignee and ticket.assigned_to != assigned_by_id:
        subject = f"[{ticket.ref}] Ticket assigned to you — {ticket.subject}"
        html = render_template(
            "emails/ticket_assigned_agent.html",
            ticket=ticket,
            assignee=assignee,
            assigned_by=assigner,
            ticket_url=agent_ticket_url,
        )
        _send([assignee.email], subject, html=html)

    # Always notify the customer when an agent is assigned
    if ticket.creator and ticket.creator.email and assignee:
        subject = f"[{ticket.ref}] An agent has been assigned to your ticket"
        html = render_template(
            "emails/ticket_assigned_customer.html",
            ticket=ticket,
            assignee=assignee,
            ticket_url=portal_ticket_url,
        )
        _send([ticket.creator.email], subject, html=html)


def notify_assigned_agent_new_message(ticket, message):
    """
    Notify the assigned agent when a customer or collaborator posts a message.
    Falls back to all active agents if the ticket is unassigned.
    """
    from app.models.user import User
    base_url = current_app.config.get("APP_BASE_URL", "")
    ticket_url = f"{base_url}/agent/tickets/{ticket.ref}"

    if ticket.assigned_to and ticket.assignee:
        recipients = [ticket.assignee.email]
    else:
        agents = User.query.filter(
            User.role.in_(["agent", "admin"]),
            User.active == True,
        ).all()
        recipients = [a.email for a in agents]

    if not recipients:
        return

    subject = f"[{ticket.ref}] New message — {ticket.subject}"
    html = render_template(
        "emails/agent_new_message.html",
        ticket=ticket,
        message=message,
        ticket_url=ticket_url,
    )
    _send(recipients, subject, html=html)


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


def notify_requirement_assigned(requirement):
    """Email the assignee when a project requirement is assigned to them."""
    recipient = requirement.assignee_email
    if not recipient:
        return
    agent = requirement.assigned_agent
    project = requirement.project
    base_url = current_app.config.get("APP_BASE_URL", "")
    portal_url = f"{base_url}/projects/portal/{project.id}"
    subject = f"[{project.name}] Action required: {requirement.title}"
    html = render_template(
        "emails/requirement_assigned.html",
        requirement=requirement,
        project=project,
        agent=agent,
        portal_url=portal_url,
    )
    _send([recipient], subject, html=html)


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


def notify_collaborator_added(ticket, collaborator):
    base_url = current_app.config.get("APP_BASE_URL", "")
    collab_url = f"{base_url}/portal/collab/{collaborator.token}"
    subject = f"[{ticket.ref}] You've been added as a collaborator"
    html = render_template(
        "emails/collaborator_invite.html",
        ticket=ticket,
        collaborator=collaborator,
        collab_url=collab_url,
    )
    _send([collaborator.email], subject, html=html)


def notify_collaborators_new_message(ticket, message):
    from app.models.ticket import TicketCollaborator
    collabs = TicketCollaborator.query.filter_by(ticket_id=ticket.id).all()
    if not collabs:
        return
    base_url = current_app.config.get("APP_BASE_URL", "")
    for collab in collabs:
        if collab.email == (message.sender_email or ""):
            continue
        # Vendor collab messages (internal) are not forwarded to customer collaborators
        if message.is_internal and collab.collab_type == "customer":
            continue
        collab_url = f"{base_url}/portal/collab/{collab.token}"
        subject = f"[{ticket.ref}] New update: {ticket.subject}"
        html = render_template(
            "emails/collaborator_update.html",
            ticket=ticket,
            collaborator=collab,
            message=message,
            collab_url=collab_url,
        )
        _send([collab.email], subject, html=html)


def notify_agent_ticket_reopened(ticket):
    """Notify the assigned agent (or all agents) when a customer reopens a ticket via email link."""
    from app.models.user import User
    if ticket.assigned_to and ticket.assignee:
        recipients = [ticket.assignee.email]
    else:
        agents = User.query.filter(
            User.role.in_(["agent", "admin"]),
            User.active == True,
        ).all()
        recipients = [a.email for a in agents]
    if not recipients:
        return
    base_url = current_app.config.get("APP_BASE_URL", "")
    ticket_url = f"{base_url}/agent/tickets/{ticket.ref}"
    subject = f"[{ticket.ref}] Customer reopened ticket — {ticket.subject}"
    text = (
        f"The customer has reopened ticket {ticket.ref}.\n\n"
        f"Subject: {ticket.subject}\n"
        f"Hospital: {ticket.hospital.name if ticket.hospital else 'N/A'}\n\n"
        f"View ticket: {ticket_url}"
    )
    _send(recipients, subject, text=text)


def notify_agent_close_request(ticket):
    """Notify the assigned agent (or all agents) that a customer requested closure."""
    from app.models.user import User
    if ticket.assigned_to and ticket.assignee:
        recipients = [ticket.assignee.email]
    else:
        agents = User.query.filter(
            User.role.in_(["agent", "admin"]),
            User.active == True,
        ).all()
        recipients = [a.email for a in agents]
    if not recipients:
        return
    base_url = current_app.config.get("APP_BASE_URL", "")
    ticket_url = f"{base_url}/agent/tickets/{ticket.ref}"
    subject = f"[{ticket.ref}] Customer requested closure — {ticket.subject}"
    text = (
        f"The customer has requested to close ticket {ticket.ref}.\n\n"
        f"Subject: {ticket.subject}\n"
        f"Hospital: {ticket.hospital.name if ticket.hospital else 'N/A'}\n\n"
        f"Approve or deny the request: {ticket_url}"
    )
    _send(recipients, subject, text=text)
