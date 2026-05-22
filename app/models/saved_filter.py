from datetime import datetime
from app.extensions import db

class SavedFilter(db.Model):
    __tablename__ = "saved_filters"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    filter_params = db.Column(db.Text, nullable=False)   # JSON: {"status":"open","priority":"high",...}
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", foreign_keys=[user_id], overlaps="saved_filters")
