from datetime import datetime
from app.extensions import db

class CSATFeedback(db.Model):
    __tablename__ = "csat_feedback"
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("tickets.id"), nullable=False, unique=True)
    token = db.Column(db.String(64), unique=True, nullable=False)   # random UUID token
    rating = db.Column(db.Integer, nullable=True)   # 1-5; null until submitted
    comment = db.Column(db.Text, nullable=True)
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)
    submitted_at = db.Column(db.DateTime, nullable=True)

    ticket = db.relationship("Ticket", foreign_keys=[ticket_id], overlaps="csat")
