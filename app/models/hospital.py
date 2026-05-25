from datetime import datetime
from app.extensions import db
from app.models.product import hospital_products

CREDENTIAL_CATEGORIES = [
    ("remote_desktop", "Remote Desktop"),
    ("vpn", "VPN"),
    ("network", "Network / IP"),
    ("admin_account", "Admin Account"),
    ("os_account", "OS Account"),
    ("other", "Other"),
]


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
    rustdesk_id = db.Column(db.String(50), nullable=True)

    users = db.relationship("User", back_populates="hospital", lazy="dynamic")
    products = db.relationship("Product", secondary=hospital_products, back_populates="hospitals")
    tickets = db.relationship("Ticket", back_populates="hospital", lazy="dynamic")
    credentials = db.relationship(
        "HospitalCredential",
        back_populates="hospital",
        order_by="HospitalCredential.category, HospitalCredential.label",
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        return f"<Hospital {self.name}>"


class HospitalCredential(db.Model):
    __tablename__ = "hospital_credentials"

    id = db.Column(db.Integer, primary_key=True)
    hospital_id = db.Column(db.Integer, db.ForeignKey("hospitals.id"), nullable=False)
    category = db.Column(db.String(30), nullable=False, default="other")
    label = db.Column(db.String(200), nullable=False)
    username = db.Column(db.String(200))
    password_enc = db.Column(db.Text)
    host_enc = db.Column(db.Text)
    role_enc = db.Column(db.Text)
    url = db.Column(db.String(500))
    notes = db.Column(db.Text)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    hospital = db.relationship("Hospital", back_populates="credentials")
    creator = db.relationship("User", foreign_keys=[created_by])

    @property
    def category_label(self):
        return dict(CREDENTIAL_CATEGORIES).get(self.category, self.category)
