from datetime import datetime
from app.extensions import db

TASK_TODO = "todo"
TASK_IN_PROGRESS = "in_progress"
TASK_DONE = "done"

ALL_TASK_STATUSES = [TASK_TODO, TASK_IN_PROGRESS, TASK_DONE]
TASK_STATUS_LABELS = {TASK_TODO: "To Do", TASK_IN_PROGRESS: "In Progress", TASK_DONE: "Done"}

RECURRENCE_NONE = "none"
RECURRENCE_DAILY = "daily"
RECURRENCE_WEEKLY = "weekly"
RECURRENCE_MONTHLY = "monthly"


class Sprint(db.Model):
    __tablename__ = "sprints"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    goal = db.Column(db.Text)
    start_date = db.Column(db.DateTime, nullable=False)
    end_date = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="planned")  # planned|active|completed
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    tasks = db.relationship("Task", back_populates="sprint", lazy="dynamic")
    creator = db.relationship("User", foreign_keys=[created_by])

    def __repr__(self):
        return f"<Sprint {self.name}>"


class Task(db.Model):
    __tablename__ = "tasks"

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("tickets.id"), nullable=True)
    sprint_id = db.Column(db.Integer, db.ForeignKey("sprints.id"), nullable=True)
    parent_id = db.Column(db.Integer, db.ForeignKey("tasks.id"), nullable=True)
    hospital_id = db.Column(db.Integer, db.ForeignKey("hospitals.id"), nullable=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    assigned_to = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    title = db.Column(db.String(500), nullable=False)
    description = db.Column(db.Text)
    status = db.Column(db.String(20), nullable=False, default=TASK_TODO)
    priority = db.Column(db.String(20), nullable=False, default="medium")
    progress = db.Column(db.Integer, default=0)
    estimated_minutes = db.Column(db.Integer, nullable=True)
    deadline = db.Column(db.DateTime, nullable=True)
    reminder_at = db.Column(db.DateTime, nullable=True)
    reminder_sent = db.Column(db.Boolean, default=False)
    recurrence = db.Column(db.String(20), default=RECURRENCE_NONE)
    recurrence_end = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    ticket = db.relationship("Ticket", back_populates="tasks")
    sprint = db.relationship("Sprint", back_populates="tasks")
    hospital = db.relationship("Hospital", foreign_keys=[hospital_id])
    product = db.relationship("Product", foreign_keys=[product_id])
    creator = db.relationship("User", foreign_keys=[created_by], back_populates="created_tasks")
    assignee = db.relationship("User", foreign_keys=[assigned_to], back_populates="assigned_tasks")
    subtasks = db.relationship("Task", foreign_keys="Task.parent_id", backref=db.backref("parent", remote_side="Task.id"), lazy="dynamic")
    checklists = db.relationship("TaskChecklist", back_populates="task", order_by="TaskChecklist.created_at", lazy="dynamic", cascade="all, delete-orphan")
    time_entries = db.relationship("TimeEntry", back_populates="task", lazy="dynamic", cascade="all, delete-orphan")
    dependencies = db.relationship("TaskDependency", foreign_keys="TaskDependency.task_id", back_populates="task", lazy="dynamic", cascade="all, delete-orphan")
    dependents = db.relationship("TaskDependency", foreign_keys="TaskDependency.depends_on_id", back_populates="depends_on", lazy="dynamic")

    @property
    def is_overdue(self):
        return self.deadline and self.deadline < datetime.utcnow() and self.status != TASK_DONE

    @property
    def status_label(self):
        return TASK_STATUS_LABELS.get(self.status, self.status)

    @property
    def total_logged_minutes(self):
        return sum(e.minutes for e in self.time_entries)

    @property
    def checklist_progress(self):
        items = self.checklists.all()
        if not items:
            return None
        done = sum(1 for i in items if i.is_done)
        return {"done": done, "total": len(items)}

    def __repr__(self):
        return f"<Task {self.id}: {self.title[:40]}>"


class TaskChecklist(db.Model):
    __tablename__ = "task_checklists"

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey("tasks.id"), nullable=False)
    text = db.Column(db.String(500), nullable=False)
    is_done = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    task = db.relationship("Task", back_populates="checklists")


class TimeEntry(db.Model):
    __tablename__ = "time_entries"

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey("tasks.id"), nullable=False)
    logged_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    minutes = db.Column(db.Integer, nullable=False)
    note = db.Column(db.String(500))
    logged_at = db.Column(db.DateTime, default=datetime.utcnow)

    task = db.relationship("Task", back_populates="time_entries")
    user = db.relationship("User", foreign_keys=[logged_by])


class TaskDependency(db.Model):
    __tablename__ = "task_dependencies"

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey("tasks.id"), nullable=False)
    depends_on_id = db.Column(db.Integer, db.ForeignKey("tasks.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    task = db.relationship("Task", foreign_keys=[task_id], back_populates="dependencies")
    depends_on = db.relationship("Task", foreign_keys=[depends_on_id], back_populates="dependents")
