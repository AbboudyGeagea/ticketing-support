from datetime import datetime
from app.extensions import db

TEMPLATE_REGISTRY = [
    {
        "slug": "ticket_created_customer",
        "name": "New Ticket — Customer Confirmation",
        "description": "Sent to the customer when they open a ticket via the portal.",
        "recipient": "Customer",
        "variables": [
            ("ticket.ref", "Ticket Number"),
            ("ticket.subject", "Subject"),
            ("ticket.priority_label", "Priority"),
            ("ticket.product.name", "Product"),
            ("ticket.creator.name", "Customer Name"),
            ("ticket.hospital.name", "Hospital"),
            ("ticket_url", "Ticket Link"),
        ],
    },
    {
        "slug": "new_ticket",
        "name": "New Ticket — Agent Notification",
        "description": "Sent to all agents when a new ticket is submitted.",
        "recipient": "All Agents",
        "variables": [
            ("ticket.ref", "Ticket Number"),
            ("ticket.subject", "Subject"),
            ("ticket.priority_label", "Priority"),
            ("ticket.product.name", "Product"),
            ("ticket.hospital.name", "Hospital"),
            ("ticket.source", "Source"),
            ("ticket_url", "Ticket Link"),
        ],
    },
    {
        "slug": "ticket_assigned_agent",
        "name": "Ticket Assigned — Agent",
        "description": "Sent to the assigned agent (skipped when self-assigned).",
        "recipient": "Assigned Agent",
        "variables": [
            ("ticket.ref", "Ticket Number"),
            ("ticket.subject", "Subject"),
            ("ticket.priority_label", "Priority"),
            ("ticket.product.name", "Product"),
            ("ticket.hospital.name", "Hospital"),
            ("assignee.name", "Agent Name"),
            ("assigned_by.name", "Assigned By"),
            ("ticket_url", "Ticket Link"),
        ],
    },
    {
        "slug": "ticket_assigned_customer",
        "name": "Ticket Assigned — Customer",
        "description": "Sent to the customer when an agent is assigned to their ticket.",
        "recipient": "Customer",
        "variables": [
            ("ticket.ref", "Ticket Number"),
            ("ticket.subject", "Subject"),
            ("ticket.product.name", "Product"),
            ("ticket.creator.name", "Customer Name"),
            ("assignee.name", "Agent Name"),
            ("ticket_url", "Ticket Link"),
        ],
    },
    {
        "slug": "reply_notification",
        "name": "Agent Replied — Customer Notification",
        "description": "Sent to the customer when an agent posts a reply.",
        "recipient": "Customer",
        "variables": [
            ("ticket.ref", "Ticket Number"),
            ("ticket.subject", "Subject"),
            ("ticket.product.name", "Product"),
            ("ticket.creator.name", "Customer Name"),
            ("message.body", "Message Body"),
            ("ticket_url", "Ticket Link"),
        ],
    },
    {
        "slug": "agent_new_message",
        "name": "New Message — Agent Notification",
        "description": "Sent to the assigned agent when a customer or collaborator posts a message.",
        "recipient": "Assigned Agent",
        "variables": [
            ("ticket.ref", "Ticket Number"),
            ("ticket.subject", "Subject"),
            ("ticket.product.name", "Product"),
            ("ticket.hospital.name", "Hospital"),
            ("message.sender_name", "Sender Name"),
            ("message.body", "Message Body"),
            ("ticket_url", "Ticket Link"),
        ],
    },
    {
        "slug": "status_change",
        "name": "Status Changed — Customer Notification",
        "description": "Sent to the customer whenever the ticket status is updated or the ticket is closed.",
        "recipient": "Customer",
        "variables": [
            ("ticket.ref", "Ticket Number"),
            ("ticket.subject", "Subject"),
            ("ticket.product.name", "Product"),
            ("ticket.status_label", "New Status"),
            ("ticket.creator.name", "Customer Name"),
            ("ticket_url", "Ticket Link"),
        ],
    },
    {
        "slug": "agent_close_request",
        "name": "Close Request — Agent Notification",
        "description": "Sent to the assigned agent when a customer requests ticket closure.",
        "recipient": "Assigned Agent",
        "variables": [
            ("ticket.ref", "Ticket Number"),
            ("ticket.subject", "Subject"),
            ("ticket.product.name", "Product"),
            ("ticket.creator.name", "Customer Name"),
            ("ticket.hospital.name", "Hospital"),
            ("ticket.assignee.name", "Assigned Agent"),
            ("ticket_url", "Ticket Link"),
        ],
    },
    {
        "slug": "agent_ticket_reopened",
        "name": "Ticket Reopened — Agent Notification",
        "description": "Sent to the assigned agent when a customer reopens a resolved ticket via email link.",
        "recipient": "Assigned Agent",
        "variables": [
            ("ticket.ref", "Ticket Number"),
            ("ticket.subject", "Subject"),
            ("ticket.product.name", "Product"),
            ("ticket.creator.name", "Customer Name"),
            ("ticket.hospital.name", "Hospital"),
            ("ticket.assignee.name", "Assigned Agent"),
            ("ticket_url", "Ticket Link"),
        ],
    },
    {
        "slug": "collaborator_invite",
        "name": "Collaborator Invite",
        "description": "Sent when someone is added as a collaborator on a ticket.",
        "recipient": "Collaborator",
        "variables": [
            ("ticket.ref", "Ticket Number"),
            ("ticket.subject", "Subject"),
            ("ticket.product.name", "Product"),
            ("ticket.hospital.name", "Hospital"),
            ("collaborator.name", "Collaborator Name"),
            ("collab_url", "Collaborator Link"),
        ],
    },
    {
        "slug": "collaborator_update",
        "name": "Collaborator Update",
        "description": "Sent to collaborators when a new message is posted on their ticket.",
        "recipient": "Collaborator",
        "variables": [
            ("ticket.ref", "Ticket Number"),
            ("ticket.subject", "Subject"),
            ("ticket.product.name", "Product"),
            ("ticket.hospital.name", "Hospital"),
            ("collaborator.name", "Collaborator Name"),
            ("message.sender_name", "Sender Name"),
            ("message.body", "Message Body"),
            ("collab_url", "Collaborator Link"),
        ],
    },
]

# Default Jinja2 subject strings (mirror the hardcoded Python subjects)
DEFAULT_SUBJECTS = {
    "ticket_created_customer": "[{{ ticket.ref }}] Your ticket has been received — {{ ticket.subject }}",
    "new_ticket": "[New Ticket] {{ ticket.ref }} — {{ ticket.subject }}",
    "ticket_assigned_agent": "[{{ ticket.ref }}] Ticket assigned to you — {{ ticket.subject }}",
    "ticket_assigned_customer": "[{{ ticket.ref }}] An agent has been assigned to your ticket",
    "reply_notification": "[{{ ticket.ref }}] Update on your ticket: {{ ticket.subject }}",
    "agent_new_message": "[{{ ticket.ref }}] New message — {{ ticket.subject }}",
    "status_change": "[{{ ticket.ref }}] Your ticket status changed to: {{ ticket.status_label }}",
    "agent_close_request": "[{{ ticket.ref }}] Customer requested closure — {{ ticket.subject }}",
    "agent_ticket_reopened": "[{{ ticket.ref }}] Customer reopened ticket — {{ ticket.subject }}",
    "collaborator_invite": "[{{ ticket.ref }}] You've been added as a collaborator",
    "collaborator_update": "[{{ ticket.ref }}] New update: {{ ticket.subject }}",
}

TEMPLATE_MAP = {t["slug"]: t for t in TEMPLATE_REGISTRY}


class EmailTemplate(db.Model):
    __tablename__ = "email_templates"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(100), unique=True, nullable=False, index=True)
    subject = db.Column(db.String(500), nullable=False)
    body = db.Column(db.Text, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    @property
    def meta(self):
        return TEMPLATE_MAP.get(self.slug, {})
