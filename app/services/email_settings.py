"""Effective email/Graph configuration — DB row wins, env vars are the fallback.

Used by email_inbound, email_outbound, and the admin diagnostics page.
"""
import logging

logger = logging.getLogger(__name__)


def get_effective_config(app_or_cfg=None) -> dict:
    """Return {tenant_id, client_id, client_secret, mailbox} using DB if set, else env.

    Accepts either a Flask app, a config mapping, or None (uses current_app).
    Safe to call outside an app context only if app_or_cfg is provided.
    """
    if app_or_cfg is None:
        from flask import current_app
        cfg = current_app.config
    elif hasattr(app_or_cfg, "config"):
        cfg = app_or_cfg.config
    else:
        cfg = app_or_cfg

    result = {
        "tenant_id":     cfg.get("AZURE_TENANT_ID") or "",
        "client_id":     cfg.get("AZURE_CLIENT_ID") or "",
        "client_secret": cfg.get("AZURE_CLIENT_SECRET") or "",
        "mailbox":       cfg.get("O365_MAILBOX") or "",
        "source":        "env",
    }

    try:
        from app.models.email_config import EmailConfig
        from app.utils.crypto import decrypt
        row = EmailConfig.query.first()
        if row:
            if row.tenant_id:
                result["tenant_id"] = row.tenant_id
            if row.client_id:
                result["client_id"] = row.client_id
            if row.client_secret_enc:
                secret = decrypt(row.client_secret_enc)
                if secret:
                    result["client_secret"] = secret
            if row.mailbox:
                result["mailbox"] = row.mailbox
            if any([row.tenant_id, row.client_id, row.client_secret_enc, row.mailbox]):
                result["source"] = "db"
    except Exception:
        logger.debug("email_config DB lookup failed, falling back to env", exc_info=True)

    return result
