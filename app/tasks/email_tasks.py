import logging
from app.celery_app import celery

logger = logging.getLogger(__name__)


@celery.task(name="app.tasks.email_tasks.poll_email", bind=True, max_retries=3)
def poll_email(self):
    try:
        from flask import current_app
        from app.services.email_inbound import fetch_and_process
        fetch_and_process(current_app._get_current_object())
    except Exception as exc:
        logger.exception("poll_email failed")
        raise self.retry(exc=exc, countdown=30)
