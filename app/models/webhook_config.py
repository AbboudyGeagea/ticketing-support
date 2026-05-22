from datetime import datetime
from app.extensions import db

WEBHOOK_EVENTS = ["ticket_created", "ticket_status_changed", "ticket_closed", "ticket_resolved"]

class WebhookConfig(db.Model):
    __tablename__ = "webhook_configs"
    id = db.Column(db.Integer, primary_key=True)
    url = db.Column(db.String(500), nullable=False)
    secret = db.Column(db.String(200), nullable=True)   # HMAC secret for payload signing
    events = db.Column(db.String(500), nullable=False, default="ticket_created,ticket_status_changed")  # comma-separated
    is_active = db.Column(db.Boolean, default=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    creator = db.relationship("User", foreign_keys=[created_by])

    @property
    def event_list(self):
        return [e.strip() for e in self.events.split(",") if e.strip()]
