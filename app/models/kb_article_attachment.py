from datetime import datetime
from app.extensions import db


class KBArticleAttachment(db.Model):
    __tablename__ = "kb_article_attachments"

    id = db.Column(db.Integer, primary_key=True)
    kb_article_id = db.Column(db.Integer, db.ForeignKey("kb_articles.id"), nullable=False, index=True)
    filename = db.Column(db.String(200), nullable=False)        # UUID-based stored filename
    original_name = db.Column(db.String(500), nullable=False)   # original user filename
    mimetype = db.Column(db.String(100))
    size = db.Column(db.Integer)                                 # bytes
    uploaded_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    article = db.relationship("KBArticle", back_populates="attachments")
    uploader = db.relationship("User", foreign_keys=[uploaded_by])
