from datetime import datetime
from app.extensions import db

class CannedResponse(db.Model):
    __tablename__ = "canned_responses"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(300), nullable=False)
    body = db.Column(db.Text, nullable=False)
    is_shared = db.Column(db.Boolean, default=True)   # shared = visible to all agents
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    creator = db.relationship("User", foreign_keys=[created_by])
