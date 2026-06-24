import logging
from datetime import datetime
from app.celery_app import celery

logger = logging.getLogger(__name__)


@celery.task(name="app.tasks.reminder_tasks.send_task_reminders")
def send_task_reminders():
    from app.models.task import Task, TASK_DONE
    from app.extensions import db
    from app.services.email_outbound import send_task_reminder

    now = datetime.utcnow()
    due_tasks = Task.query.filter(
        Task.reminder_at <= now,
        Task.reminder_sent == False,
        Task.status != TASK_DONE,
    ).all()

    for task in due_tasks:
        try:
            send_task_reminder(task)
            task.reminder_sent = True
            db.session.commit()
            logger.info("Reminder sent for task %d", task.id)
        except Exception:
            logger.exception("Failed to send reminder for task %d", task.id)


@celery.task(name="app.tasks.reminder_tasks.send_csat_surveys")
def send_csat_surveys():
    from datetime import timedelta
    from app.models.ticket import Ticket
    from app.services.email_outbound import send_csat_survey

    cutoff = datetime.utcnow() - timedelta(hours=24)
    tickets = Ticket.query.filter(
        Ticket.status == "closed",
        Ticket.csat_sent == False,
        Ticket.closed_at <= cutoff,
        Ticket.created_by.isnot(None),
    ).all()

    for ticket in tickets:
        try:
            send_csat_survey(ticket)
            logger.info("CSAT survey sent for ticket %s", ticket.ref)
        except Exception:
            logger.exception("Failed to send CSAT for ticket %s", ticket.ref)


@celery.task(name="app.tasks.reminder_tasks.check_sla_escalations")
def check_sla_escalations():
    """Mark tickets as SLA breached and notify assignees."""
    from app.models.ticket import Ticket
    from app.extensions import db

    now = datetime.utcnow()
    breached = Ticket.query.filter(
        Ticket.status.notin_(["closed", "resolved"]),
        Ticket.sla_breached == False,
        db.or_(
            db.and_(
                Ticket.sla_response_due.isnot(None),
                Ticket.sla_response_due < now,
                Ticket.first_response_at.is_(None),
            ),
            db.and_(
                Ticket.sla_resolve_due.isnot(None),
                Ticket.sla_resolve_due < now,
            ),
        ),
    ).all()

    for ticket in breached:
        ticket.sla_breached = True
        logger.info("SLA breached on ticket %s", ticket.ref)
        try:
            from app.services.email_outbound import notify_sla_breach
            notify_sla_breach(ticket)
        except Exception:
            pass

    if breached:
        db.session.commit()
        logger.info("Marked %d ticket(s) as SLA breached", len(breached))


@celery.task(name="app.tasks.reminder_tasks.auto_close_resolved_tickets")
def auto_close_resolved_tickets():
    """Auto-close tickets that have been resolved for more than 2 days without customer response."""
    from datetime import timedelta
    from app.models.ticket import Ticket, TicketHistory
    from app.extensions import db

    cutoff = datetime.utcnow() - timedelta(days=2)
    tickets = Ticket.query.filter(
        Ticket.status == "resolved",
        Ticket.updated_at < cutoff,
    ).all()

    now = datetime.utcnow()
    for ticket in tickets:
        ticket.status = "closed"
        ticket.closed_at = now
        ticket.updated_at = now
        db.session.add(TicketHistory(
            ticket_id=ticket.id,
            agent_id=None,
            action="status_change",
            old_value="resolved",
            new_value="closed",
        ))
        logger.info("Auto-closed ticket %s (resolved for >2 days)", ticket.ref)

    if tickets:
        db.session.commit()
        logger.info("Auto-closed %d resolved ticket(s)", len(tickets))
    return len(tickets)
