"""Outbound email notifications via Flask-Mail (SMTP/O365)."""
import logging
from flask import current_app, render_template
from flask_mail import Message
from app.extensions import mail

logger = logging.getLogger(__name__)


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

    html = render_template(
        "emails/new_ticket.html",
        ticket=ticket,
        ticket_url=ticket_url,
    )

    msg = Message(subject=subject, recipients=recipients, html=html)
    _send(msg)


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

    msg = Message(
        subject=subject,
        recipients=[ticket.creator.email],
        reply_to=current_app.config.get("MAIL_DEFAULT_SENDER"),
        html=html,
    )
    _send(msg)


def send_task_reminder(task):
    from app.models.user import User
    assignee = db_get_user(task.assigned_to)
    if not assignee:
        return

    subject = f"[Reminder] Task due: {task.title[:60]}"
    html = render_template("emails/task_reminder.html", task=task)
    msg = Message(subject=subject, recipients=[assignee.email], html=html)
    _send(msg)


def db_get_user(user_id):
    from app.models.user import User
    return User.query.get(user_id)


def _send(msg: Message):
    try:
        mail.send(msg)
    except Exception as exc:
        logger.error("Failed to send email to %s: %s", msg.recipients, exc)


def notify_customer_status_change(ticket):
    """Email customer when their ticket status changes (excluding reply-triggered changes)."""
    if not ticket.creator or not ticket.creator.email:
        return
    subject = f"[{ticket.ref}] Your ticket status changed to: {ticket.status_label}"
    base_url = current_app.config.get("APP_BASE_URL", "")
    ticket_url = f"{base_url}/portal/tickets/{ticket.ref}"
    html = render_template("emails/status_change.html", ticket=ticket, ticket_url=ticket_url)
    msg = Message(subject=subject, recipients=[ticket.creator.email], html=html)
    _send(msg)


def notify_customer_resolved_confirmation(ticket):
    """Email customer asking them to confirm resolution or reopen. Generates a signed token."""
    if not ticket.creator or not ticket.creator.email:
        return
    from itsdangerous import URLSafeTimedSerializer
    s = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
    token = s.dumps(ticket.ref, salt="ticket-confirm")
    base_url = current_app.config.get("APP_BASE_URL", "")
    confirm_url = f"{base_url}/portal/tickets/{ticket.ref}/confirm?token={token}&action=close"
    reopen_url = f"{base_url}/portal/tickets/{ticket.ref}/confirm?token={token}&action=reopen"
    subject = f"[{ticket.ref}] Is your issue resolved?"
    html = render_template("emails/resolved_confirmation.html", ticket=ticket,
                           confirm_url=confirm_url, reopen_url=reopen_url)
    msg = Message(subject=subject, recipients=[ticket.creator.email], html=html)
    _send(msg)


def notify_sla_breach(ticket):
    """Notify the ticket assignee (or all agents) that an SLA has been breached."""
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
    body = (
        f"Ticket {ticket.ref} has breached its SLA.\n\n"
        f"Subject: {ticket.subject}\n"
        f"Priority: {ticket.priority}\n"
        f"Hospital: {ticket.hospital.name if ticket.hospital else 'N/A'}\n\n"
        f"View ticket: {ticket_url}"
    )
    msg = Message(subject=subject, recipients=recipients, body=body)
    _send(msg)


def send_csat_survey(ticket):
    """Send CSAT survey after ticket closes. Creates CSATFeedback record with token."""
    if not ticket.creator or not ticket.creator.email:
        return
    import uuid
    from app.models.csat_feedback import CSATFeedback
    from app.extensions import db
    # Don't re-send
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
    msg = Message(subject=subject, recipients=[ticket.creator.email], html=html)
    _send(msg)
