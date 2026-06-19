from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app.extensions import db, login_manager
from app.models.product import user_products


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    hospital_id = db.Column(db.Integer, db.ForeignKey("hospitals.id"), nullable=True)
    email = db.Column(db.String(200), unique=True, nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    password_hash = db.Column(db.String(256))
    role = db.Column(db.String(20), nullable=False)  # customer | agent | admin
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    is_available = db.Column(db.Boolean, default=True)   # agent availability toggle

    hospital = db.relationship("Hospital", back_populates="users")
    products = db.relationship("Product", secondary=user_products, lazy="subquery")
    created_tickets = db.relationship(
        "Ticket", foreign_keys="Ticket.created_by", back_populates="creator", lazy="dynamic"
    )
    assigned_tickets = db.relationship(
        "Ticket", foreign_keys="Ticket.assigned_to", back_populates="assignee", lazy="dynamic"
    )
    assigned_tasks = db.relationship(
        "Task", foreign_keys="Task.assigned_to", back_populates="assignee", lazy="dynamic"
    )
    created_tasks = db.relationship(
        "Task", foreign_keys="Task.created_by", back_populates="creator", lazy="dynamic"
    )
    uploaded_attachments = db.relationship(
        "TicketAttachment", foreign_keys="TicketAttachment.uploaded_by", back_populates="uploader", lazy="dynamic"
    )
    saved_filters = db.relationship("SavedFilter", foreign_keys="SavedFilter.user_id", lazy="dynamic")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    @property
    def is_agent(self):
        return self.role in ("agent", "admin")

    @property
    def is_admin(self):
        return self.role == "admin"

    @property
    def is_customer(self):
        return self.role == "customer"

    def __repr__(self):
        return f"<User {self.email} ({self.role})>"


@login_manager.user_loader
def load_user(user_id):
    user = db.session.get(User, int(user_id))
    if user and not user.active:
        return None
    return user
