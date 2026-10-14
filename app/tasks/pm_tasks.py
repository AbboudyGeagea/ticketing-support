import logging
from flask import current_app
from app.celery_app import celery

logger = logging.getLogger(__name__)


@celery.task(name="app.tasks.pm_tasks.send_pm_reminders")
def send_pm_reminders():
    """Runs daily; on PM_REMINDER_DAY of the month, emails each hospital's
    responsible agent the PM checkups they still haven't submitted."""
    from app.services.pm_service import local_today, due_by_owner
    from app.services.email_outbound import send_pm_reminder

    today = local_today()
    if today.day != current_app.config.get("PM_REMINDER_DAY", 20):
        return 0
    month_label = today.strftime("%B %Y")
    sent = 0
    for owner, rows in due_by_owner(today).items():
        try:
            send_pm_reminder(owner, rows, month_label)
            sent += 1
        except Exception:
            logger.exception("PM reminder failed for %s", owner.email)
    logger.info("PM reminders sent to %d agent(s)", sent)
    return sent
