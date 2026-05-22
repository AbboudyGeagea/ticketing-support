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
