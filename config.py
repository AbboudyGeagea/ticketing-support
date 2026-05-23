import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()


class Config:
    _secret = os.environ.get("SECRET_KEY")
    if not _secret:
        raise RuntimeError(
            "SECRET_KEY environment variable is not set. "
            "Generate one with: python scripts/generate-secret-key.py"
        )
    SECRET_KEY = _secret

    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "postgresql://ticketing_user:password@localhost/ticketing_db"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Microsoft Graph API (inbound + outbound email)
    AZURE_TENANT_ID = os.environ.get("AZURE_TENANT_ID")
    AZURE_CLIENT_ID = os.environ.get("AZURE_CLIENT_ID")
    AZURE_CLIENT_SECRET = os.environ.get("AZURE_CLIENT_SECRET")
    O365_MAILBOX = os.environ.get("O365_MAILBOX")

    # Celery / Redis
    CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://redis:6379/0")
    CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://redis:6379/0")
    RATELIMIT_STORAGE_URI = os.environ.get("CELERY_BROKER_URL", "redis://redis:6379/0")

    EMAIL_POLL_INTERVAL_SECONDS = int(os.environ.get("EMAIL_POLL_INTERVAL_SECONDS", 60))

    # File uploads
    UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", "/app/uploads")
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10 MB

    # App
    APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:5000")
    ITEMS_PER_PAGE = int(os.environ.get("ITEMS_PER_PAGE", 25))
    WTF_CSRF_ENABLED = True
    USE_BUNDLED_CSS = os.environ.get("USE_BUNDLED_CSS", "false").lower() == "true"

    # Session / cookie security
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    # Set SECURE_COOKIES=true in production (behind HTTPS/Nginx)
    SESSION_COOKIE_SECURE = os.environ.get("SECURE_COOKIES", "false").lower() == "true"
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SECURE = os.environ.get("SECURE_COOKIES", "false").lower() == "true"
    PERMANENT_SESSION_LIFETIME = timedelta(
        days=int(os.environ.get("SESSION_LIFETIME_DAYS", 30))
    )
    # Allow agents to leave forms open for up to 8 hours without CSRF expiry
    WTF_CSRF_TIME_LIMIT = int(os.environ.get("CSRF_TIME_LIMIT", 28800))
