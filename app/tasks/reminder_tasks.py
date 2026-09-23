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
    """Auto-close tickets resolved for 48+ hours, or until Monday if resolved on Friday."""
    from datetime import timedelta
    from app.models.ticket import Ticket, TicketHistory
    from app.extensions import db

    resolved_tickets = Ticket.query.filter(Ticket.status == "resolved").all()
    now = datetime.utcnow()
    closed_count = 0

    for ticket in resolved_tickets:
        time_since_resolved = now - ticket.updated_at
        should_close = False

        if time_since_resolved >= timedelta(hours=48):
            resolved_day = ticket.updated_at.weekday()
            if resolved_day == 4:
                next_monday = ticket.updated_at + timedelta(days=3)
                next_monday = next_monday.replace(hour=0, minute=0, second=0, microsecond=0)
                if now >= next_monday:
                    should_close = True
            else:
                should_close = True

        if should_close:
            try:
                ticket.status = "closed"
                ticket.closed_at = now
                ticket.updated_at = now
                db.session.add(TicketHistory(
                    ticket_id=ticket.id,
                    changed_by=None,
                    action="status_change",
                    old_value="resolved",
                    new_value="closed",
                ))
                db.session.commit()
                closed_count += 1
                logger.info("Auto-closed ticket %s (resolved >48h)", ticket.ref)

                try:
                    from app.services.webhook_service import fire_ticket_status_changed
                    fire_ticket_status_changed(ticket, "resolved", "closed")
                except Exception:
                    logger.exception("fire_ticket_status_changed webhook failed for %s", ticket.ref)
            except Exception:
                logger.exception("Failed to auto-close ticket %s", ticket.ref)
                db.session.rollback()

    if closed_count > 0:
        logger.info("Auto-closed %d resolved ticket(s)", closed_count)
    return closed_count
