import uuid
from datetime import datetime
from app.extensions import db


STATUS_NEW = "new"
STATUS_ASSIGNED = "assigned"
STATUS_AWAITING_INFO = "awaiting_info"
STATUS_IN_PROGRESS = "in_progress"
STATUS_ESCALATED = "escalated"
STATUS_RESOLVED = "resolved"
STATUS_CLOSED = "closed"

PRIORITY_LOW = "low"
PRIORITY_MEDIUM = "medium"
PRIORITY_HIGH = "high"
PRIORITY_URGENT = "urgent"

ALL_STATUSES = [
    STATUS_NEW, STATUS_ASSIGNED, STATUS_AWAITING_INFO,
    STATUS_IN_PROGRESS, STATUS_ESCALATED, STATUS_RESOLVED, STATUS_CLOSED,
]
ALL_PRIORITIES = [PRIORITY_LOW, PRIORITY_MEDIUM, PRIORITY_HIGH, PRIORITY_URGENT]

STATUS_LABELS = {
    STATUS_NEW: "New",
    STATUS_ASSIGNED: "Assigned",
    STATUS_AWAITING_INFO: "Awaiting Info",
    STATUS_IN_PROGRESS: "In Progress",
    STATUS_ESCALATED: "Escalated",
    STATUS_RESOLVED: "Resolved",
    STATUS_CLOSED: "Closed",
}
PRIORITY_LABELS = {
    PRIORITY_LOW: "Low",
    PRIORITY_MEDIUM: "Medium",
    PRIORITY_HIGH: "High",
    PRIORITY_URGENT: "Urgent",
}


class Ticket(db.Model):
    __tablename__ = "tickets"

    id = db.Column(db.Integer, primary_key=True)
    ref = db.Column(db.String(20), unique=True, nullable=False, index=True)
    hospital_id = db.Column(db.Integer, db.ForeignKey("hospitals.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    assigned_to = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    subject = db.Column(db.String(500), nullable=False)
    status = db.Column(db.String(20), nullable=False, default=STATUS_NEW)
    priority = db.Column(db.String(20), nullable=False, default=PRIORITY_MEDIUM)
    source = db.Column(db.String(20), default="portal")  # portal | email
    email_thread_id = db.Column(db.String(500))  # Graph API conversationId
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    closed_at = db.Column(db.DateTime)
    rustdesk_peer_id = db.Column(db.String(100), nullable=True)
    escalation_url = db.Column(db.String(1000), nullable=True)
    escalation_number = db.Column(db.String(100), nullable=True)
    csat_sent = db.Column(db.Boolean, default=False)
    close_requested = db.Column(db.Boolean, default=False)
    first_response_at = db.Column(db.DateTime, nullable=True)
    sla_response_due = db.Column(db.DateTime, nullable=True)
    sla_resolve_due = db.Column(db.DateTime, nullable=True)
    sla_breached = db.Column(db.Boolean, default=False)
    phi_flagged = db.Column(db.Boolean, default=False, nullable=False, index=True)
    phi_flagged_at = db.Column(db.DateTime, nullable=True)
    phi_flagged_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    hospital = db.relationship("Hospital", back_populates="tickets")
    product = db.relationship("Product", back_populates="tickets")
    creator = db.relationship("User", foreign_keys=[created_by], back_populates="created_tickets")
    assignee = db.relationship("User", foreign_keys=[assigned_to], back_populates="assigned_tickets")
    phi_flagger = db.relationship("User", foreign_keys=[phi_flagged_by])
    messages = db.relationship("TicketMessage", back_populates="ticket", order_by="TicketMessage.created_at", lazy="dynamic")
    history = db.relationship("TicketHistory", back_populates="ticket", order_by="TicketHistory.created_at", lazy="dynamic")
    tasks = db.relationship("Task", back_populates="ticket", lazy="dynamic")
    attachments = db.relationship("TicketAttachment", back_populates="ticket", lazy="dynamic")
    csat = db.relationship("CSATFeedback", foreign_keys="CSATFeedback.ticket_id", uselist=False)
    collaborators = db.relationship("TicketCollaborator", back_populates="ticket",
                                    cascade="all, delete-orphan", lazy="dynamic")

    @property
    def status_label(self):
        return STATUS_LABELS.get(self.status, self.status)

    @property
    def priority_label(self):
        return PRIORITY_LABELS.get(self.priority, self.priority)

    @property
    def sla_status(self):
        """Returns 'ok', 'at_risk', 'breached', or None if no SLA set."""
        from datetime import datetime as _dt
        if self.status in ("closed", "resolved"):
            return None
        if self.sla_breached:
            return "breached"
        now = _dt.utcnow()
        due = self.sla_response_due if not self.first_response_at else self.sla_resolve_due
        if not due:
            return None
        remaining = (due - now).total_seconds() / 3600
        if remaining < 0:
            return "breached"
        if remaining < 1:
            return "at_risk"
        return "ok"

    def __repr__(self):
        return f"<Ticket {self.ref}>"


class TicketMessage(db.Model):
    __tablename__ = "ticket_messages"

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("tickets.id"), nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    sender_name = db.Column(db.String(200))
    sender_email = db.Column(db.String(200))
    body = db.Column(db.Text, nullable=False)
    is_internal = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    ticket = db.relationship("Ticket", back_populates="messages")
    sender = db.relationship("User", foreign_keys=[sender_id])
    attachments = db.relationship("TicketAttachment", back_populates="message", lazy="dynamic")


class TicketCollaborator(db.Model):
    __tablename__ = "ticket_collaborators"

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("tickets.id"), nullable=False)
    email = db.Column(db.String(200), nullable=False)
    name = db.Column(db.String(200))
    token = db.Column(db.String(64), unique=True, nullable=False,
                      default=lambda: uuid.uuid4().hex)
    collab_type = db.Column(db.String(20), nullable=False, default="customer")  # customer | vendor
    added_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    added_at = db.Column(db.DateTime, default=datetime.utcnow)

    ticket = db.relationship("Ticket", back_populates="collaborators")
    adder = db.relationship("User", foreign_keys=[added_by])

    __table_args__ = (
        db.UniqueConstraint("ticket_id", "email", name="uq_collab_ticket_email"),
    )


class TicketHistory(db.Model):
    __tablename__ = "ticket_history"

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("tickets.id"), nullable=False)
    changed_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    action = db.Column(db.String(50), nullable=False)
    old_value = db.Column(db.String(200))
    new_value = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    ticket = db.relationship("Ticket", back_populates="history")
    agent = db.relationship("User", foreign_keys=[changed_by])
