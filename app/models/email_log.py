from datetime import datetime
from app.extensions import db


class EmailLog(db.Model):
    """Records every outbound email send attempt for admin visibility."""
    __tablename__ = "email_log"

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    ticket_ref = db.Column(db.String(20), nullable=True, index=True)
    recipients = db.Column(db.Text, nullable=False)   # comma-joined list
    subject = db.Column(db.String(500), nullable=False)
    status = db.Column(db.String(20), nullable=False)  # "sent" | "failed" | "skipped"
    error = db.Column(db.Text, nullable=True)          # error detail on failure/skip
    mailbox = db.Column(db.String(200), nullable=True) # which mailbox was used
