"""Outbound email via Microsoft Graph API.

Rebuilt from scratch 2026-07-03. Design rules:
- The core sender (_send) is mechanically identical to send_diagnostic,
  which is the verified-working path (admin test email + invite email).
- File templates ONLY (app/templates/emails/*.html). No DB-stored
  templates — their content lives outside git and broke silently.
- No custom internet message headers of any kind.
- Every send attempt is written to email_log (sent / failed / skipped).
"""
import logging
import requests
import msal
from flask import current_app, render_template

logger = logging.getLogger(__name__)

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_SCOPES = ["https://graph.microsoft.com/.default"]


# ---------------------------------------------------------------------------
# Core plumbing
# ---------------------------------------------------------------------------

def _get_token(eff: dict) -> tuple[str | None, str | None]:
    """Return (token, error). Exactly one of the two is None."""
    missing = [k for k in ("tenant_id", "client_id", "client_secret") if not eff.get(k)]
    if missing:
        return None, f"Missing credentials: {', '.join(missing)}"
    try:
        authority = f"https://login.microsoftonline.com/{eff['tenant_id']}"
        msal_app = msal.ConfidentialClientApplication(
            eff["client_id"], authority=authority, client_credential=eff["client_secret"],
        )
        result = msal_app.acquire_token_for_client(scopes=_SCOPES)
    except Exception as exc:
        return None, f"MSAL exception: {exc}"
    if "access_token" not in result:
        err = result.get("error", "unknown")
        desc = result.get("error_description", "")
        return None, f"Token acquisition failed [{err}]: {desc}"
    return result["access_token"], None


def _log_email(recipients, subject, status, error=None, mailbox=None):
    """Write one row to email_log. Never raises — diagnostic only."""
    try:
        from app.models.email_log import EmailLog
        from app.extensions import db
        entry = EmailLog(
            recipients=", ".join(recipients),
            subject=subject,
            status=status,
            error=error,
            mailbox=mailbox,
        )
        db.session.add(entry)
        db.session.commit()
    except Exception:
        logger.exception("email_log write failed")


def _report(status: str, recipients: list[str], subject: str, error: str = None, mailbox: str = None):
    """Single choke point: every send outcome is logged to email_log for /admin/email/test."""
    _log_email(recipients, subject, status, error=error, mailbox=mailbox)


def _clean_subject(subject: str) -> str:
    """Collapse whitespace/newlines (Graph rejects control chars in subjects)."""
    return " ".join((subject or "(no subject)").split())[:250]


def _send(recipients: list[str], subject: str, html: str = None, text: str = None):
    """Send one message via Graph sendMail. Never raises."""
    seen = set()
    valid = []
    for r in recipients or []:
        addr = (r or "").strip()
        if addr and "@" in addr and addr.lower() not in seen:
            seen.add(addr.lower())
            valid.append(addr)
    subject = _clean_subject(subject)
    if not valid:
        logger.warning("email skipped — no valid recipients for '%s'", subject)
        _report("skipped", ["(none)"], subject, error="No valid recipients")
        return

    try:
        from app.services.email_settings import get_effective_config
        eff = get_effective_config()
    except Exception as exc:
        _report("failed", valid, subject, error=f"Config lookup failed: {exc}")
        return

    mailbox = eff.get("mailbox")
    if not mailbox:
        _report("skipped", valid, subject, error="O365_MAILBOX not configured")
        return

    token, token_err = _get_token(eff)
    if not token:
        _report("skipped", valid, subject, error=token_err, mailbox=mailbox)
        logger.error("email skipped — %s", token_err)
        return

    payload = {
        "message": {
            "subject": subject,
            "body": {
                "contentType": "HTML" if html else "Text",
                "content": html or text or "",
            },
            "toRecipients": [{"emailAddress": {"address": r}} for r in valid],
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
        _report("failed", valid, subject, error=f"HTTP request failed: {exc}", mailbox=mailbox)
        logger.error("email send failed to %s: %s", valid, exc)
        return

    if resp.status_code in (200, 202):
        _report("sent", valid, subject, mailbox=mailbox)
        logger.info("email sent to %s: %s", valid, subject)
    else:
        err = f"Graph HTTP {resp.status_code}: {(resp.text or '')[:600]}"
        _report("failed", valid, subject, error=err, mailbox=mailbox)
        logger.error("email send failed to %s: %s", valid, err)


def _render(template_name: str, **ctx) -> str | None:
    """Render a file template; on failure log + return None (send is skipped)."""
    try:
        return render_template(f"emails/{template_name}", **ctx)
    except Exception as exc:
        logger.exception("email template render failed: %s", template_name)
        _report("failed", ["(render error)"], template_name, error=f"Template {template_name} failed to render: {exc}")
        return None


def send_diagnostic(recipient: str, subject: str, text: str) -> tuple[bool, str]:
    """Verbose send used by the admin diagnostics page. Returns (ok, message)."""
    from app.services.email_settings import get_effective_config
    eff = get_effective_config()
    if not eff.get("mailbox"):
        return False, "Missing credentials: mailbox"
    token, token_err = _get_token(eff)
    if not token:
        return False, token_err
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
            f"{_GRAPH_BASE}/users/{eff['mailbox']}/sendMail",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
            timeout=15,
        )
    except Exception as exc:
        return False, f"HTTP request failed: {exc}"
    if resp.status_code in (200, 202):
        return True, f"Graph API accepted the message (HTTP {resp.status_code})."
    return False, f"Graph sendMail returned HTTP {resp.status_code}: {(resp.text or '')[:800]}"


# ---------------------------------------------------------------------------
# Recipient helpers
# ---------------------------------------------------------------------------

def _all_agent_emails(exclude_id=None):
    from app.models.user import User
    q = User.query.filter(User.role.in_(["agent", "admin"]), User.active == True)  # noqa: E712
    return [u.email for u in q.all()
            if u.email and not u.is_viewer and u.id != exclude_id]


def _get_hospital_product_users(ticket):
    """All active, notification-subscribed customers in the ticket's hospital with access to its product.

    A ticket without a resolvable product (rare — some email-intake tickets)
    must never fall back to notifying the whole hospital: that would leak
    updates across departments. It falls back to the creator's own
    department, or just the creator if even that is unknown.
    """
    from app.models.user import User
    users = User.query.filter(
        User.hospital_id == ticket.hospital_id,
        User.role == "customer",
        User.active == True,  # noqa: E712
        User.email_notifications_enabled == True,  # noqa: E712
    ).all()
    if ticket.product_id:
        users = [u for u in users if any(p.id == ticket.product_id for p in u.products)]
    else:
        creator_dept_id = ticket.creator.department_id if ticket.creator else None
        if creator_dept_id:
            users = [u for u in users if u.department_id == creator_dept_id]
        else:
            users = [u for u in users if u.id == ticket.created_by]
    return [u for u in users if u.email]


def _base_url() -> str:
    return current_app.config.get("APP_BASE_URL", "")


# ---------------------------------------------------------------------------
# Auth / account emails
# ---------------------------------------------------------------------------

def send_invite_email(user):
    """Send a set-password invitation to a newly created user or agent."""
    from itsdangerous import URLSafeTimedSerializer
    s = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
    token = s.dumps(user.id, salt="user-invite")
    set_password_url = f"{_base_url()}/auth/set-password/{token}"
    html = _render("invite.html", user=user, set_password_url=set_password_url)
    if html:
        _send([user.email], "Welcome to Intermedic Support — Set your password", html=html)


# ---------------------------------------------------------------------------
# Ticket lifecycle — customer-facing
# ---------------------------------------------------------------------------

def notify_customer_ticket_created(ticket):
    """Notify all hospital/product users when a ticket is opened.

    Creator gets "your ticket was submitted"; everyone else who shares
    hospital + product gets "your colleague opened a ticket".
    """
    users = _get_hospital_product_users(ticket)
    if not users:
        logger.info("notify_customer_ticket_created skipped — no matching recipients for ticket %s", ticket.ref)
        return
    ticket_url = f"{_base_url()}/portal/tickets/{ticket.ref}"
    subject = f"[{ticket.ref}] {ticket.subject}"
    for user in users:
        if user.id == ticket.created_by:
            html = _render("ticket_created_customer.html", ticket=ticket, ticket_url=ticket_url, recipient=user)
        else:
            html = _render("ticket_created_colleague.html", ticket=ticket, ticket_url=ticket_url, recipient=user)
        if html:
            _send([user.email], subject, html=html)


def notify_customer_reply(ticket, message):
    """Notify all hospital/product users that an agent replied."""
    recipients = [u.email for u in _get_hospital_product_users(ticket)]
    if not recipients:
        return
    ticket_url = f"{_base_url()}/portal/tickets/{ticket.ref}"
    html = _render("reply_notification.html", ticket=ticket, message=message, ticket_url=ticket_url)
    if html:
        _send(recipients, f"[{ticket.ref}] {ticket.subject}", html=html)


def notify_customer_status_change(ticket):
    """Notify all hospital/product users of a status change, each addressed by name."""
    users = _get_hospital_product_users(ticket)
    if not users:
        logger.info("notify_customer_status_change skipped — no matching recipients for ticket %s", ticket.ref)
        return
    ticket_url = f"{_base_url()}/portal/tickets/{ticket.ref}"
    subject = f"[{ticket.ref}] {ticket.subject}"
    for user in users:
        html = _render("status_change.html", ticket=ticket, ticket_url=ticket_url, recipient=user)
        if html:
            _send([user.email], subject, html=html)


def notify_customer_resolved_confirmation(ticket):
    if not ticket.creator or not ticket.creator.email or not ticket.creator.email_notifications_enabled:
        return
    from itsdangerous import URLSafeTimedSerializer
    s = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
    token = s.dumps(ticket.ref, salt="ticket-confirm")
    confirm_url = f"{_base_url()}/portal/tickets/{ticket.ref}/confirm?token={token}&action=close"
    reopen_url = f"{_base_url()}/portal/tickets/{ticket.ref}/confirm?token={token}&action=reopen"
    html = _render("resolved_confirmation.html", ticket=ticket,
                   confirm_url=confirm_url, reopen_url=reopen_url)
    if html:
        _send([ticket.creator.email], f"[{ticket.ref}] {ticket.subject}", html=html)


def notify_customer_phi_flagged(ticket):
    """Notify the creator that their ticket was removed for containing PHI."""
    if not ticket.creator or not ticket.creator.email:
        logger.warning("phi_flagged ticket %s has no creator email", ticket.ref)
        return
    if not ticket.creator.email_notifications_enabled:
        return
    html = _render(
        "phi_violation_customer.html",
        ticket=ticket,
        recipient_name=ticket.creator.name or "Customer",
        portal_url=f"{_base_url()}/portal/tickets/new",
        support_email=current_app.config.get("SUPPORT_EMAIL", "informatics@intermedic.com"),
    )
    if html:
        _send([ticket.creator.email], f"[{ticket.ref}] {ticket.subject}", html=html)


def send_csat_survey(ticket):
    if not ticket.creator or not ticket.creator.email or not ticket.creator.email_notifications_enabled:
        return
    import uuid
    from app.models.csat_feedback import CSATFeedback
    from app.extensions import db
    if ticket.csat and ticket.csat.submitted_at:
        return
    token = uuid.uuid4().hex
    if not ticket.csat:
        db.session.add(CSATFeedback(ticket_id=ticket.id, token=token))
    else:
        ticket.csat.token = token
    ticket.csat_sent = True
    db.session.commit()
    feedback_url = f"{_base_url()}/feedback/{token}"
    html = _render("csat_survey.html", ticket=ticket, feedback_url=feedback_url)
    if html:
        _send([ticket.creator.email], f"[{ticket.ref}] {ticket.subject}", html=html)


# ---------------------------------------------------------------------------
# Ticket lifecycle — agent-facing
# ---------------------------------------------------------------------------

def notify_agents_new_ticket(ticket):
    recipients = _all_agent_emails()
    if not recipients:
        return
    ticket_url = f"{_base_url()}/agent/tickets/{ticket.ref}"
    first_message = ticket.messages.first()
    html = _render("new_ticket.html", ticket=ticket, ticket_url=ticket_url,
                   first_message=first_message)
    if html:
        tag = {"urgent": "[URGENT] ", "high": "[HIGH] "}.get(ticket.priority, "")
        _send(recipients, f"{tag}[{ticket.ref}] {ticket.subject}", html=html)


def notify_assigned_agent_new_message(ticket, message):
    """Notify all active agents when a customer or collaborator posts a message."""
    recipients = _all_agent_emails()
    if not recipients:
        return
    ticket_url = f"{_base_url()}/agent/tickets/{ticket.ref}"
    html = _render("agent_new_message.html", ticket=ticket, message=message,
                   ticket_url=ticket_url)
    if html:
        _send(recipients, f"[{ticket.ref}] {ticket.subject}", html=html)


def notify_agent_ticket_reopened(ticket):
    recipients = _all_agent_emails()
    if not recipients:
        return
    ticket_url = f"{_base_url()}/agent/tickets/{ticket.ref}"
    html = _render("agent_ticket_reopened.html", ticket=ticket, ticket_url=ticket_url)
    if html:
        _send(recipients, f"[{ticket.ref}] {ticket.subject}", html=html)


def notify_agent_close_request(ticket):
    recipients = _all_agent_emails()
    if not recipients:
        return
    ticket_url = f"{_base_url()}/agent/tickets/{ticket.ref}"
    html = _render("agent_close_request.html", ticket=ticket, ticket_url=ticket_url)
    if html:
        _send(recipients, f"[{ticket.ref}] {ticket.subject}", html=html)


def notify_all_agents_activity(ticket, event, actor_name=None, message=None):
    """Broadcast any ticket activity (reply, status change, close, …) to all agents."""
    recipients = _all_agent_emails()
    if not recipients:
        return
    ticket_url = f"{_base_url()}/agent/tickets/{ticket.ref}"
    html = _render("agent_activity.html", ticket=ticket, event=event,
                   actor_name=actor_name, message=message, ticket_url=ticket_url)
    if html:
        _send(recipients, f"[{ticket.ref}] {ticket.subject}", html=html)


def notify_agent_ticket_assigned(ticket, assigned_by_id):
    """Notify the new assignee, the rest of the team, and the customer."""
    from app.models.user import User
    assignee = User.query.get(ticket.assigned_to) if ticket.assigned_to else None
    assigner = User.query.get(assigned_by_id) if assigned_by_id else None
    if not assignee:
        return
    agent_url = f"{_base_url()}/agent/tickets/{ticket.ref}"
    portal_url = f"{_base_url()}/portal/tickets/{ticket.ref}"
    subject = f"[{ticket.ref}] {ticket.subject}"

    # The assignee themselves (unless self-assigned or a viewer)
    if assignee.email and ticket.assigned_to != assigned_by_id and not assignee.is_viewer:
        html = _render("ticket_assigned_agent.html", ticket=ticket, assignee=assignee,
                       assigned_by=assigner, ticket_url=agent_url)
        if html:
            _send([assignee.email], subject, html=html)

    # The rest of the team
    team = _all_agent_emails(exclude_id=assignee.id)
    if team:
        html = _render("ticket_assigned_team.html", ticket=ticket, assignee=assignee,
                       assigned_by=assigner, ticket_url=agent_url)
        if html:
            _send(team, subject, html=html)

    # All hospital/product customers (never expose the agent's name), each addressed by name
    for user in _get_hospital_product_users(ticket):
        html = _render("ticket_assigned_customer.html", ticket=ticket, ticket_url=portal_url, recipient=user)
        if html:
            _send([user.email], subject, html=html)


def notify_sla_breach(ticket):
    if ticket.assignee and not ticket.assignee.is_viewer and ticket.assignee.email:
        recipients = [ticket.assignee.email]
    else:
        recipients = _all_agent_emails()
    if not recipients:
        return
    ticket_url = f"{_base_url()}/agent/tickets/{ticket.ref}"
    text = (
        f"Ticket {ticket.ref} has breached its SLA.\n\n"
        f"Subject: {ticket.subject}\n"
        f"Priority: {ticket.priority}\n"
        f"Hospital: {ticket.hospital.name if ticket.hospital else 'N/A'}\n\n"
        f"View ticket: {ticket_url}"
    )
    _send(recipients, f"[{ticket.ref}] {ticket.subject}", text=text)


# ---------------------------------------------------------------------------
# Collaborators
# ---------------------------------------------------------------------------

def notify_collaborator_added(ticket, collaborator):
    if not collaborator.email:
        return
    collab_url = f"{_base_url()}/portal/collab/{collaborator.token}"
    html = _render("collaborator_invite.html", ticket=ticket, collaborator=collaborator,
                   collab_url=collab_url)
    if html:
        _send([collaborator.email], f"[{ticket.ref}] {ticket.subject}", html=html)


def notify_collaborators_new_message(ticket, message):
    from app.models.ticket import TicketCollaborator
    collabs = TicketCollaborator.query.filter_by(ticket_id=ticket.id).all()
    for collab in collabs:
        if not collab.email or collab.email == (message.sender_email or ""):
            continue
        # Vendor collab messages (internal) are not forwarded to customer collaborators
        if message.is_internal and collab.collab_type == "customer":
            continue
        collab_url = f"{_base_url()}/portal/collab/{collab.token}"
        html = _render("collaborator_update.html", ticket=ticket, collaborator=collab,
                       message=message, collab_url=collab_url)
        if html:
            _send([collab.email], f"[{ticket.ref}] {ticket.subject}", html=html)


# ---------------------------------------------------------------------------
# Tasks / projects
# ---------------------------------------------------------------------------

def send_task_reminder(task):
    from app.models.user import User
    assignee = User.query.get(task.assigned_to)
    if not assignee or assignee.is_viewer or not assignee.email:
        return
    html = _render("task_reminder.html", task=task)
    if html:
        _send([assignee.email], f"[Reminder] Task due: {task.title[:60]}", html=html)


def notify_secondary_assignee(task):
    sec = task.secondary_assignee
    if not sec or not sec.email or sec.is_viewer:
        return
    html = _render("task_secondary_assigned.html", task=task)
    if html:
        _send([sec.email], f"[{task.ref}] You were assigned as a secondary resource", html=html)


def notify_requirement_assigned(requirement):
    """Email the assignee when a project requirement is assigned to them."""
    recipient = requirement.assignee_email
    if not recipient:
        return
    project = requirement.project
    portal_url = f"{_base_url()}/projects/portal/{project.id}"
    html = _render("requirement_assigned.html", requirement=requirement, project=project,
                   agent=requirement.assigned_agent, portal_url=portal_url)
    if html:
        _send([recipient], f"[{project.name}] Action required: {requirement.title}", html=html)
