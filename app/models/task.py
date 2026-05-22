from datetime import datetime
from app.extensions import db

TASK_TODO = "todo"
TASK_IN_PROGRESS = "in_progress"
TASK_DONE = "done"

ALL_TASK_STATUSES = [TASK_TODO, TASK_IN_PROGRESS, TASK_DONE]
TASK_STATUS_LABELS = {TASK_TODO: "To Do", TASK_IN_PROGRESS: "In Progress", TASK_DONE: "Done"}


class Task(db.Model):
    __tablename__ = "tasks"

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("tickets.id"), nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    assigned_to = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    title = db.Column(db.String(500), nullable=False)
    description = db.Column(db.Text)
    status = db.Column(db.String(20), nullable=False, default=TASK_TODO)
    priority = db.Column(db.String(20), nullable=False, default="medium")
    deadline = db.Column(db.DateTime, nullable=True)
    reminder_at = db.Column(db.DateTime, nullable=True)
    reminder_sent = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    ticket = db.relationship("Ticket", back_populates="tasks")
    creator = db.relationship("User", foreign_keys=[created_by], back_populates="created_tasks")
    assignee = db.relationship("User", foreign_keys=[assigned_to], back_populates="assigned_tasks")

    @property
    def is_overdue(self):
        return self.deadline and self.deadline < datetime.utcnow() and self.status != TASK_DONE

    @property
    def status_label(self):
        return TASK_STATUS_LABELS.get(self.status, self.status)

    def __repr__(self):
        return f"<Task {self.id}: {self.title[:40]}>"
