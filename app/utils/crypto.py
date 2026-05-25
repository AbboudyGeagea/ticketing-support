import os
import base64
import hashlib
from cryptography.fernet import Fernet, InvalidToken


def _derive_key_from_secret(secret: str) -> bytes:
    """Deterministically derive a Fernet-compatible key from any string."""
    digest = hashlib.sha256(secret.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def _get_key() -> bytes:
    """Return a Fernet key.

    Order of precedence:
      1. CREDENTIAL_ENCRYPTION_KEY env var, if present and non-empty
      2. Flask SECRET_KEY (from current_app.config), derived via SHA-256

    SECRET_KEY is mandatory in config.py, so this never fails inside an
    active app context. Falling back to it lets the app work even when
    CREDENTIAL_ENCRYPTION_KEY isn't propagated into the process env.
    """
    explicit = os.environ.get("CREDENTIAL_ENCRYPTION_KEY", "").strip()
    if explicit:
        return explicit.encode() if isinstance(explicit, str) else explicit

    secret = ""
    try:
        from flask import current_app
        secret = (current_app.config.get("SECRET_KEY") or "").strip()
    except Exception:
        secret = os.environ.get("SECRET_KEY", "").strip()

    if not secret:
        raise RuntimeError(
            "No encryption key available — SECRET_KEY must be set "
            "(CREDENTIAL_ENCRYPTION_KEY is optional and was not found)."
        )
    return _derive_key_from_secret(secret)


def _fernet():
    return Fernet(_get_key())


def encrypt(plaintext: str) -> str:
    if not plaintext:
        return ""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    if not ciphertext:
        return ""
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except (InvalidToken, Exception):
        return ""
