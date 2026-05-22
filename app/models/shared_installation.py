from datetime import datetime
from app.extensions import db

shared_installation_hospitals = db.Table(
    "shared_installation_hospitals",
    db.Column("installation_id", db.Integer, db.ForeignKey("shared_installations.id"), primary_key=True),
    db.Column("hospital_id", db.Integer, db.ForeignKey("hospitals.id"), primary_key=True),
)


class SharedInstallation(db.Model):
    __tablename__ = "shared_installations"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    product = db.relationship("Product", lazy="joined")
    hospitals = db.relationship("Hospital", secondary=shared_installation_hospitals, lazy="subquery")

    def __repr__(self):
        return f"<SharedInstallation {self.name}>"
