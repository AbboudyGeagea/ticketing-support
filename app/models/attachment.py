from datetime import datetime
from app.extensions import db


class TicketAttachment(db.Model):
    __tablename__ = "ticket_attachments"

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("tickets.id"), nullable=False)
    message_id = db.Column(db.Integer, db.ForeignKey("ticket_messages.id"), nullable=True)
    uploaded_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    filename = db.Column(db.String(200), nullable=False)        # UUID-based stored filename
    original_name = db.Column(db.String(500), nullable=False)   # original user filename
    mimetype = db.Column(db.String(100))
    size = db.Column(db.Integer)                                 # bytes
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    ticket = db.relationship("Ticket", back_populates="attachments")
    message = db.relationship("TicketMessage", back_populates="attachments")
    uploader = db.relationship("User", foreign_keys=[uploaded_by])
