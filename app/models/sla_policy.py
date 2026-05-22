from datetime import datetime
from app.extensions import db


class SLAPolicy(db.Model):
    __tablename__ = "sla_policies"

    id = db.Column(db.Integer, primary_key=True)
    priority = db.Column(db.String(20), nullable=False, unique=True)  # low|medium|high|urgent
    response_hours = db.Column(db.Float, nullable=False)   # hours until first response due
    resolve_hours = db.Column(db.Float, nullable=False)    # hours until resolution due
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<SLAPolicy {self.priority} r={self.response_hours}h res={self.resolve_hours}h>"
