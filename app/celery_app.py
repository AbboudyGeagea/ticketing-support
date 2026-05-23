from celery import Celery

# Bare instance — tasks decorate against this. make_celery() configures it with the Flask app.
celery = Celery("ticketing")


def make_celery(app):
    celery.conf.update(
        broker_url=app.config.get("CELERY_BROKER_URL", "redis://127.0.0.1:6379/0"),
        result_backend=app.config.get("CELERY_RESULT_BACKEND", "redis://127.0.0.1:6379/0"),
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
        include=["app.tasks.email_tasks", "app.tasks.reminder_tasks"],
        beat_schedule={
            "poll-email": {
                "task": "app.tasks.email_tasks.poll_email",
                "schedule": app.config.get("EMAIL_POLL_INTERVAL_SECONDS", 60),
            },
            "task-reminders": {
                "task": "app.tasks.reminder_tasks.send_task_reminders",
                "schedule": 300,
            },
            "csat-surveys": {
                "task": "app.tasks.reminder_tasks.send_csat_surveys",
                "schedule": 3600,
            },
            "sla-escalations": {
                "task": "app.tasks.reminder_tasks.check_sla_escalations",
                "schedule": 900,  # every 15 minutes
            },
        },
    )

    class ContextTask(celery.Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = ContextTask
    return celery
