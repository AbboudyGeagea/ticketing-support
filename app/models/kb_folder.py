from datetime import datetime
from app.extensions import db


class KBFolder(db.Model):
    """Shared KB folder. No owner and no per-agent permissions: every agent sees every
    folder. `is_customer_facing` decides whether the published articles inside it are
    visible on the customer portal."""
    __tablename__ = "kb_folders"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), unique=True, nullable=False)
    is_customer_facing = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    articles = db.relationship("KBArticle", back_populates="folder")

    def __repr__(self):
        return f"<KBFolder {self.name}>"
