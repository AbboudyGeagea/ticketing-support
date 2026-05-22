from datetime import datetime
from app.extensions import db

class AssignmentRule(db.Model):
    __tablename__ = "assignment_rules"
    id = db.Column(db.Integer, primary_key=True)
    hospital_id = db.Column(db.Integer, db.ForeignKey("hospitals.id"), nullable=True)   # None = match any hospital
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=True)     # None = match any product
    priority = db.Column(db.String(20), nullable=True)   # None = match any priority; values: low/medium/high/urgent
    assigned_to = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    rule_order = db.Column(db.Integer, default=0)   # lower = higher priority, evaluated first
    is_active = db.Column(db.Boolean, default=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    hospital = db.relationship("Hospital", foreign_keys=[hospital_id])
    product = db.relationship("Product", foreign_keys=[product_id])
    assignee = db.relationship("User", foreign_keys=[assigned_to])
    creator = db.relationship("User", foreign_keys=[created_by])
