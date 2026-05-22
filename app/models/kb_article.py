from datetime import datetime
from app.extensions import db


class KBArticle(db.Model):
    __tablename__ = "kb_articles"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(500), nullable=False)
    slug = db.Column(db.String(500), unique=True, nullable=False, index=True)
    body = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(100))
    is_published = db.Column(db.Boolean, default=False)
    views = db.Column(db.Integer, default=0)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    author = db.relationship("User", foreign_keys=[created_by])

    def __repr__(self):
        return f"<KBArticle {self.title[:50]}>"
