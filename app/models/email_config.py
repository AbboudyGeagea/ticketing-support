from datetime import datetime
from app.extensions import db


class EmailConfig(db.Model):
    """Singleton row holding Azure/Graph credentials for inbound + outbound email.

    Values stored here override the env-var defaults (AZURE_TENANT_ID etc).
    The client secret is encrypted with CREDENTIAL_ENCRYPTION_KEY (Fernet).
    """
    __tablename__ = "email_config"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.String(100))
    client_id = db.Column(db.String(100))
    client_secret_enc = db.Column(db.Text)
    mailbox = db.Column(db.String(200))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    @classmethod
    def get_singleton(cls):
        row = cls.query.first()
        if row is None:
            row = cls()
            db.session.add(row)
            db.session.flush()
        return row
