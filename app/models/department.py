from datetime import datetime
from app.extensions import db

hospital_departments = db.Table(
    "hospital_departments",
    db.Column("hospital_id", db.Integer, db.ForeignKey("hospitals.id"), primary_key=True),
    db.Column("department_id", db.Integer, db.ForeignKey("departments.id"), primary_key=True),
)


class Department(db.Model):
    __tablename__ = "departments"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    hospitals = db.relationship("Hospital", secondary=hospital_departments, back_populates="departments")
    users = db.relationship("User", back_populates="department", lazy="dynamic")

    def __repr__(self):
        return f"<Department {self.name}>"
