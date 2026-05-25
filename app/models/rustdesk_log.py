from datetime import datetime
from app.extensions import db


class RustDeskLog(db.Model):
    __tablename__ = "rustdesk_logs"

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("tickets.id"), nullable=False)
    agent_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    peer_id = db.Column(db.String(50))
    connected_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    ticket = db.relationship("Ticket", backref=db.backref(
        "rustdesk_logs", order_by="RustDeskLog.connected_at.desc()", lazy="dynamic"
    ))
    agent = db.relationship("User")
