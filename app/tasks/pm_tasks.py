import logging
from app.celery_app import celery

logger = logging.getLogger(__name__)


@celery.task(name="app.tasks.pm_tasks.send_pm_reminders")
def send_pm_reminders():
    """Runs daily. PM is due PM_INTERVAL_DAYS after a hospital's last submitted
    checkup; every agent gets one email listing the hospitals that are due in
    PM_WARN_DAYS, due today or overdue — the ones they're responsible for first."""
    from app.models.user import User
    from app.services.pm_service import local_today, alert_rows
    from app.services.email_outbound import send_pm_alert

    rows = alert_rows(local_today())
    if not rows:
        return 0
    agents = User.query.filter(User.role.in_(["agent", "admin"]), User.active == True).all()  # noqa: E712
    sent = 0
    for agent in agents:
        if not agent.email or agent.is_viewer:
            continue
        try:
            send_pm_alert(agent, rows)
            sent += 1
        except Exception:
            logger.exception("PM alert failed for %s", agent.email)
    logger.info("PM alerts for %d hospital(s) sent to %d agent(s)", len(rows), sent)
    return sent
