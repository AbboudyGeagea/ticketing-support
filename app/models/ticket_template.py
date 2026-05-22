from datetime import datetime
from app.extensions import db


class TicketTemplate(db.Model):
    __tablename__ = "ticket_templates"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.String(500))
    category = db.Column(db.String(100))
    subject = db.Column(db.String(500), nullable=False)
    body = db.Column(db.Text, nullable=False)
    default_priority = db.Column(db.String(20), nullable=False, default="medium")
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    product = db.relationship("Product", foreign_keys=[product_id])
    author = db.relationship("User", foreign_keys=[created_by])

    def __repr__(self):
        return f"<TicketTemplate {self.name}>"
