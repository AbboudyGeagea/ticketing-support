from datetime import datetime
from app.extensions import db
from app.models.kb_folder import KBFolder


class KBArticle(db.Model):
    __tablename__ = "kb_articles"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(500), nullable=False)
    slug = db.Column(db.String(500), unique=True, nullable=False, index=True)
    body = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(100))
    folder_id = db.Column(db.Integer, db.ForeignKey("kb_folders.id"), nullable=True, index=True)
    # "Published" (draft vs live). Agents see published articles; customers additionally
    # need a customer-facing folder (or, for unfiled articles, is_published_customer).
    is_published_agent = db.Column(db.Boolean, default=False, nullable=False)
    # Only used while the article is unfiled — inside a folder, the folder decides.
    is_published_customer = db.Column(db.Boolean, default=False, nullable=False)
    views = db.Column(db.Integer, default=0)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    author = db.relationship("User", foreign_keys=[created_by])
    folder = db.relationship("KBFolder", back_populates="articles")
    attachments = db.relationship(
        "KBArticleAttachment", back_populates="article",
        cascade="all, delete-orphan", order_by="KBArticleAttachment.created_at",
    )

    @property
    def is_customer_visible(self):
        if self.folder is not None:
            return bool(self.folder.is_customer_facing and self.is_published_agent)
        return bool(self.is_published_customer)

    @classmethod
    def customer_visible_clause(cls):
        """SQL filter matching `is_customer_visible` — use for every customer-facing query."""
        return db.or_(
            db.and_(cls.folder_id.is_(None), cls.is_published_customer.is_(True)),
            db.and_(
                cls.is_published_agent.is_(True),
                cls.folder.has(KBFolder.is_customer_facing.is_(True)),
            ),
        )

    def move_to(self, folder):
        """Put the article in `folder` (None = unfiled). Leaving a folder keeps whatever
        customers could see at that moment, so the stale unfiled flag never resurfaces."""
        if self.folder is not None and folder is None:
            self.is_published_customer = self.is_customer_visible
        self.folder = folder

    def __repr__(self):
        return f"<KBArticle {self.title[:50]}>"
