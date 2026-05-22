from datetime import datetime
from app.extensions import db

PROJECT_STATUSES = ["planning", "active", "on_hold", "completed"]
PROJECT_STATUS_LABELS = {"planning": "Planning", "active": "Active", "on_hold": "On Hold", "completed": "Completed"}
PTASK_STATUSES = ["todo", "in_progress", "done"]
PTASK_PRIORITIES = ["low", "medium", "high", "urgent"]


class Project(db.Model):
    __tablename__ = "projects"

    id = db.Column(db.Integer, primary_key=True)
    hospital_id = db.Column(db.Integer, db.ForeignKey("hospitals.id"), nullable=False)
    name = db.Column(db.String(300), nullable=False)
    description = db.Column(db.Text)
    status = db.Column(db.String(20), nullable=False, default="planning")
    start_date = db.Column(db.Date, nullable=True)
    end_date = db.Column(db.Date, nullable=True)
    is_customer_visible = db.Column(db.Boolean, default=False)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    hospital = db.relationship("Hospital", backref=db.backref("projects", lazy="dynamic"))
    creator = db.relationship("User", foreign_keys=[created_by])
    milestones = db.relationship(
        "ProjectMilestone",
        back_populates="project",
        order_by="ProjectMilestone.due_date",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    tasks = db.relationship(
        "ProjectTask",
        back_populates="project",
        order_by="ProjectTask.due_date",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    comments = db.relationship(
        "ProjectComment",
        back_populates="project",
        order_by="ProjectComment.created_at",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )

    @property
    def status_label(self):
        return PROJECT_STATUS_LABELS.get(self.status, self.status)


class ProjectMilestone(db.Model):
    __tablename__ = "project_milestones"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False)
    name = db.Column(db.String(300), nullable=False)
    description = db.Column(db.Text)
    due_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(20), nullable=False, default="pending")  # pending | completed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    project = db.relationship("Project", back_populates="milestones")


class ProjectTask(db.Model):
    __tablename__ = "project_tasks"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False)
    assigned_to = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    title = db.Column(db.String(500), nullable=False)
    description = db.Column(db.Text)
    status = db.Column(db.String(20), nullable=False, default="todo")
    priority = db.Column(db.String(20), nullable=False, default="medium")
    due_date = db.Column(db.Date, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    project = db.relationship("Project", back_populates="tasks")
    assignee = db.relationship("User", foreign_keys=[assigned_to])


class ProjectComment(db.Model):
    __tablename__ = "project_comments"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    project = db.relationship("Project", back_populates="comments")
    author = db.relationship("User", foreign_keys=[author_id])


class ProjectTemplate(db.Model):
    __tablename__ = "project_templates"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(300), nullable=False)
    description = db.Column(db.Text)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    creator = db.relationship("User", foreign_keys=[created_by])
    tasks = db.relationship(
        "ProjectTemplateTask",
        back_populates="template",
        order_by="ProjectTemplateTask.order",
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        return f"<ProjectTemplate {self.name}>"


class ProjectTemplateTask(db.Model):
    __tablename__ = "project_template_tasks"

    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.Integer, db.ForeignKey("project_templates.id"), nullable=False)
    title = db.Column(db.String(500), nullable=False)
    description = db.Column(db.Text)
    default_priority = db.Column(db.String(20), nullable=False, default="medium")
    order = db.Column(db.Integer, default=0)

    template = db.relationship("ProjectTemplate", back_populates="tasks")
