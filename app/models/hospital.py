from datetime import datetime
from app.extensions import db
from app.models.product import hospital_products


class Hospital(db.Model):
    __tablename__ = "hospitals"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    email_domain = db.Column(db.String(100))
    address = db.Column(db.String(500))
    phone = db.Column(db.String(50))
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    rustdesk_server_url = db.Column(db.String(500), nullable=True)
    rustdesk_server_key = db.Column(db.String(200), nullable=True)

    users = db.relationship("User", back_populates="hospital", lazy="dynamic")
    products = db.relationship("Product", secondary=hospital_products, back_populates="hospitals")
    tickets = db.relationship("Ticket", back_populates="hospital", lazy="dynamic")

    def __repr__(self):
        return f"<Hospital {self.name}>"
