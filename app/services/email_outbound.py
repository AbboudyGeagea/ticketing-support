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


def _send(
    recipients: list[str],
    subject: str,
    html: str = None,
    text: str = None,
    ticket_ref: str = None,
    is_thread_root: bool = False,
):
    valid_recipients = [r for r in recipients if r and r.strip()]
    if not valid_recipients:
        return
    from app.services.email_settings import get_effective_config
    eff = get_effective_config()
    token = _get_token(eff)
    if not token:
        return
    mailbox = eff["mailbox"]
    content_type = "HTML" if html else "Text"
    content = html or text or ""
    # Build RFC 2822 threading headers for ticket-related emails.
    # The thread root gets a deterministic Message-ID; subsequent emails
    # add In-Reply-To / References pointing to it so mail clients group them.
    internet_headers = []
    if ticket_ref:
        domain = mailbox.split("@")[-1] if "@" in mailbox else "intermedic.com"
        thread_msg_id = f"<ticket-{ticket_ref}@{domain}>"
        if is_thread_root:
            internet_headers.append({"name": "Message-ID", "value": thread_msg_id})
        else:
            internet_headers.append({"name": "In-Reply-To", "value": thread_msg_id})
            internet_headers.append({"name": "References",  "value": thread_msg_id})

    message_body: dict = {
        "subject": subject,
        "body": {"contentType": content_type, "content": content},
        "toRecipients": [{"emailAddress": {"address": r}} for r in valid_recipients],
    }
    if internet_headers:
        message_body["internetMessageHeaders"] = internet_headers

    payload = {
        "message": message_body,
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
            logger.error("Graph sendMail failed %s: %s", resp.status_code, resp.text[:500])
    except Exception as exc:
        logger.error("Failed to send email to %s: %s", valid_recipients, exc)


def _render_db_template(slug, **context):
    """Return (subject, html) from a DB-stored template, or (None, None) to fall back to file."""
    try:
        from app.models.email_template import EmailTemplate
        tpl = EmailTemplate.query.filter_by(slug=slug).first()
        if not tpl:
            return None, None
        from datetime import datetime
        from jinja2.sandbox import SandboxedEnvironment
        env = SandboxedEnvironment(autoescape=True)
        context.setdefault("now", datetime.utcnow())
        html = env.from_string(tpl.body).render(**context)
        subject = env.from_string(tpl.subject).render(**context)
        return subject, html
    except Exception as exc:
        logger.error("DB email template render failed [%s]: %s", slug, exc)
        return None, None


def send_invite_email(user):
    """Send a set-password invitation to a newly created user or agent."""
    from itsdangerous import URLSafeTimedSerializer
    s = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
    token = s.dumps(user.id, salt="user-invite")
    base_url = current_app.config.get("APP_BASE_URL", "")
    set_password_url = f"{base_url}/auth/set-password/{token}"
    subject = "Welcome to Intermedic Support — Set your password"
    html = render_template("emails/invite.html", user=user, set_password_url=set_password_url)
    _send([user.email], subject, html=html)


def notify_customer_ticket_created(ticket):
    """Confirmation email to the customer (creator) when a ticket is opened via the portal."""
    if not ticket.creator or not ticket.creator.email:
        return
    base_url = current_app.config.get("APP_BASE_URL", "")
    ticket_url = f"{base_url}/portal/tickets/{ticket.ref}"
    ctx = dict(ticket=ticket, ticket_url=ticket_url)
    subject, html = _render_db_template("ticket_created_customer", **ctx)
    if not html:
        subject = f"[{ticket.ref}] {ticket.subject}"
        html = render_template("emails/ticket_created_customer.html", **ctx)
    _send([ticket.creator.email], subject, html=html, ticket_ref=ticket.ref, is_thread_root=True)


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

    # Notify assigned agent (skip if they assigned themselves, or if viewer)
    if assignee and ticket.assigned_to != assigned_by_id and not assignee.is_viewer:
        agent_ctx = dict(ticket=ticket, assignee=assignee, assigned_by=assigner, ticket_url=agent_ticket_url)
        subject, html = _render_db_template("ticket_assigned_agent", **agent_ctx)
        if not html:
            subject = f"[{ticket.ref}] {ticket.subject}"
            html = render_template("emails/ticket_assigned_agent.html", **agent_ctx)
        _send([assignee.email], subject, html=html, ticket_ref=ticket.ref)

    # Broadcast to all other active agents so the team knows who owns the ticket
    if assignee:
        other_agents = User.query.filter(
            User.role.in_(["agent", "admin"]),
            User.active == True,
            User.id != assignee.id,
        ).all()
        recipients = [a.email for a in other_agents if not a.is_viewer]
        if recipients:
            team_ctx = dict(ticket=ticket, assignee=assignee, assigned_by=assigner, ticket_url=agent_ticket_url)
            team_html = render_template("emails/ticket_assigned_team.html", **team_ctx)
            _send(recipients, f"[{ticket.ref}] {ticket.subject}", html=team_html, ticket_ref=ticket.ref)

    # Always notify the customer when an agent is assigned — do NOT expose agent name
    if ticket.creator and ticket.creator.email and assignee:
        cust_ctx = dict(ticket=ticket, ticket_url=portal_ticket_url)
        subject, html = _render_db_template("ticket_assigned_customer", **cust_ctx)
        if not html:
            subject = f"[{ticket.ref}] {ticket.subject}"
            html = render_template("emails/ticket_assigned_customer.html", **cust_ctx)
        _send([ticket.creator.email], subject, html=html, ticket_ref=ticket.ref)


def notify_assigned_agent_new_message(ticket, message):
    """Notify all active agents when a customer or collaborator posts a message."""
    from app.models.user import User
    base_url = current_app.config.get("APP_BASE_URL", "")
    ticket_url = f"{base_url}/agent/tickets/{ticket.ref}"

    agents = User.query.filter(
        User.role.in_(["agent", "admin"]),
        User.active == True,
    ).all()
    recipients = [a.email for a in agents if a.email]

    if not recipients:
        return

    ctx = dict(ticket=ticket, message=message, ticket_url=ticket_url)
    subject, html = _render_db_template("agent_new_message", **ctx)
    if not html:
        subject = f"[{ticket.ref}] {ticket.subject}"
        html = render_template("emails/agent_new_message.html", **ctx)
    _send(recipients, subject, html=html, ticket_ref=ticket.ref)


def notify_agents_new_ticket(ticket):
    from app.models.user import User
    agents = User.query.filter(
        User.role.in_(["agent", "admin"]),
        User.active == True,
    ).all()
    if not agents:
        return
    recipients = [a.email for a in agents]
    base_url = current_app.config.get("APP_BASE_URL", "")
    ticket_url = f"{base_url}/agent/tickets/{ticket.ref}"
    first_message = ticket.messages.first()
    ctx = dict(ticket=ticket, ticket_url=ticket_url, first_message=first_message)
    subject, html = _render_db_template("new_ticket", **ctx)
    if not html:
        subject = f"[{ticket.ref}] {ticket.subject}"
        html = render_template("emails/new_ticket.html", **ctx)
    _send(recipients, subject, html=html, ticket_ref=ticket.ref, is_thread_root=True)


def notify_customer_reply(ticket, message):
    if not ticket.creator or not ticket.creator.email:
        return
    base_url = current_app.config.get("APP_BASE_URL", "")
    ticket_url = f"{base_url}/portal/tickets/{ticket.ref}"
    ctx = dict(ticket=ticket, message=message, ticket_url=ticket_url)
    subject, html = _render_db_template("reply_notification", **ctx)
    if not html:
        subject = f"[{ticket.ref}] {ticket.subject}"
        html = render_template("emails/reply_notification.html", **ctx)
    _send([ticket.creator.email], subject, html=html, ticket_ref=ticket.ref)


def send_task_reminder(task):
    from app.models.user import User
    assignee = User.query.get(task.assigned_to)
    if not assignee or assignee.is_viewer:
        return
    subject = f"[Reminder] Task due: {task.title[:60]}"
    html = render_template("emails/task_reminder.html", task=task)
    _send([assignee.email], subject, html=html)


def notify_secondary_assignee(task):
    if not task.secondary_assignee or not task.secondary_assignee.email or task.secondary_assignee.is_viewer:
        return
    subject = f"[{task.ref}] You were assigned as a secondary resource"
    html = render_template("emails/task_secondary_assigned.html", task=task)
    _send([task.secondary_assignee.email], subject, html=html)


def notify_customer_status_change(ticket):
    if not ticket.creator or not ticket.creator.email:
        return
    base_url = current_app.config.get("APP_BASE_URL", "")
    ticket_url = f"{base_url}/portal/tickets/{ticket.ref}"
    ctx = dict(ticket=ticket, ticket_url=ticket_url)
    subject, html = _render_db_template("status_change", **ctx)
    if not html:
        subject = f"[{ticket.ref}] {ticket.subject}"
        html = render_template("emails/status_change.html", **ctx)
    _send([ticket.creator.email], subject, html=html, ticket_ref=ticket.ref)


def notify_customer_resolved_confirmation(ticket):
    if not ticket.creator or not ticket.creator.email:
        return
    from itsdangerous import URLSafeTimedSerializer
    s = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
    token = s.dumps(ticket.ref, salt="ticket-confirm")
    base_url = current_app.config.get("APP_BASE_URL", "")
    confirm_url = f"{base_url}/portal/tickets/{ticket.ref}/confirm?token={token}&action=close"
    reopen_url = f"{base_url}/portal/tickets/{ticket.ref}/confirm?token={token}&action=reopen"
    subject = f"[{ticket.ref}] {ticket.subject}"
    html = render_template(
        "emails/resolved_confirmation.html",
        ticket=ticket,
        confirm_url=confirm_url,
        reopen_url=reopen_url,
    )
    _send([ticket.creator.email], subject, html=html, ticket_ref=ticket.ref)


def notify_sla_breach(ticket):
    from app.models.user import User
    if ticket.assignee and not ticket.assignee.is_viewer:
        recipients = [ticket.assignee.email]
    else:
        # assignee is a viewer (no email) or unassigned — broadcast to all active non-viewer agents
        agents = User.query.filter(User.role.in_(["agent", "admin"]), User.active == True).all()
        recipients = [a.email for a in agents]
    if not recipients:
        return
    base_url = current_app.config.get("APP_BASE_URL", "")
    ticket_url = f"{base_url}/agent/tickets/{ticket.ref}"
    subject = f"[{ticket.ref}] {ticket.subject}"
    text = (
        f"Ticket {ticket.ref} has breached its SLA.\n\n"
        f"Subject: {ticket.subject}\n"
        f"Priority: {ticket.priority}\n"
        f"Hospital: {ticket.hospital.name if ticket.hospital else 'N/A'}\n\n"
        f"View ticket: {ticket_url}"
    )
    _send(recipients, subject, text=text, ticket_ref=ticket.ref, is_thread_root=False)


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
    subject = f"[{ticket.ref}] {ticket.subject}"
    html = render_template("emails/csat_survey.html", ticket=ticket, feedback_url=feedback_url)
    _send([ticket.creator.email], subject, html=html, ticket_ref=ticket.ref)


def notify_collaborator_added(ticket, collaborator):
    base_url = current_app.config.get("APP_BASE_URL", "")
    collab_url = f"{base_url}/portal/collab/{collaborator.token}"
    ctx = dict(ticket=ticket, collaborator=collaborator, collab_url=collab_url)
    subject, html = _render_db_template("collaborator_invite", **ctx)
    if not html:
        subject = f"[{ticket.ref}] {ticket.subject}"
        html = render_template("emails/collaborator_invite.html", **ctx)
    _send([collaborator.email], subject, html=html, ticket_ref=ticket.ref)


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
        ctx = dict(ticket=ticket, collaborator=collab, message=message, collab_url=collab_url)
        subject, html = _render_db_template("collaborator_update", **ctx)
        if not html:
            subject = f"[{ticket.ref}] {ticket.subject}"
            html = render_template("emails/collaborator_update.html", **ctx)
        _send([collab.email], subject, html=html, ticket_ref=ticket.ref)


def notify_agent_ticket_reopened(ticket):
    """Notify all active agents when a customer reopens a ticket via email link."""
    from app.models.user import User
    agents = User.query.filter(
        User.role.in_(["agent", "admin"]),
        User.active == True,
    ).all()
    recipients = [a.email for a in agents if a.email]
    if not recipients:
        return
    base_url = current_app.config.get("APP_BASE_URL", "")
    ticket_url = f"{base_url}/agent/tickets/{ticket.ref}"
    ctx = dict(ticket=ticket, ticket_url=ticket_url)
    subject, html = _render_db_template("agent_ticket_reopened", **ctx)
    if not html:
        subject = f"[{ticket.ref}] {ticket.subject}"
        html = render_template("emails/agent_ticket_reopened.html", **ctx)
    _send(recipients, subject, html=html, ticket_ref=ticket.ref)


def notify_agent_close_request(ticket):
    """Notify all active agents that a customer requested closure."""
    from app.models.user import User
    agents = User.query.filter(
        User.role.in_(["agent", "admin"]),
        User.active == True,
    ).all()
    recipients = [a.email for a in agents if a.email]
    if not recipients:
        return
    base_url = current_app.config.get("APP_BASE_URL", "")
    ticket_url = f"{base_url}/agent/tickets/{ticket.ref}"
    ctx = dict(ticket=ticket, ticket_url=ticket_url)
    subject, html = _render_db_template("agent_close_request", **ctx)
    if not html:
        subject = f"[{ticket.ref}] {ticket.subject}"
        html = render_template("emails/agent_close_request.html", **ctx)
    _send(recipients, subject, html=html, ticket_ref=ticket.ref)


def notify_customer_phi_flagged(ticket):
    """Notify the ticket creator that their ticket was removed for containing PHI."""
    if not ticket.creator or not ticket.creator.email:
        logger.warning("phi_flagged ticket %s has no creator email — cannot notify", ticket.ref)
        return
    recipient = ticket.creator.email
    recipient_name = ticket.creator.name or "Customer"
    base_url = current_app.config.get("APP_BASE_URL", "")
    portal_url = f"{base_url}/portal/tickets/new"
    support_email = current_app.config.get("SUPPORT_EMAIL", "informatics@intermedic.com")
    subject = f"[{ticket.ref}] {ticket.subject}"
    html = render_template(
        "emails/phi_violation_customer.html",
        ticket=ticket,
        recipient_name=recipient_name,
        portal_url=portal_url,
        support_email=support_email,
    )
    _send([recipient], subject, html=html, ticket_ref=ticket.ref)


def notify_all_agents_activity(ticket, event, actor_name=None):
    """Notify all active agents about any ticket activity (reply, status change, close, etc.)."""
    from app.models.user import User
    agents = User.query.filter(
        User.role.in_(["agent", "admin"]),
        User.active == True,
    ).all()
    recipients = [a.email for a in agents if a.email]
    if not recipients:
        return
    base_url = current_app.config.get("APP_BASE_URL", "")
    ticket_url = f"{base_url}/agent/tickets/{ticket.ref}"
    subject = f"[{ticket.ref}] {ticket.subject}"
    html = render_template("emails/agent_activity.html",
                           ticket=ticket, event=event,
                           actor_name=actor_name, ticket_url=ticket_url)
    _send(recipients, subject, html=html, ticket_ref=ticket.ref)
