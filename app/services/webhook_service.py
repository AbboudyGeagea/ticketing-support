import hmac
import hashlib
import json
import logging
import requests
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def fire_webhook(event: str, payload: dict):
    from app.models.webhook_config import WebhookConfig
    hooks = WebhookConfig.query.filter_by(is_active=True).all()
    for hook in hooks:
        if event not in hook.event_list:
            continue
        _dispatch(hook, event, payload)


def _dispatch(hook, event: str, payload: dict):
    body = json.dumps({"event": event, "timestamp": datetime.now(timezone.utc).isoformat(), "data": payload})
    headers = {"Content-Type": "application/json", "X-Intermedic-Event": event}
    if hook.secret:
        sig = hmac.new(hook.secret.encode(), body.encode(), hashlib.sha256).hexdigest()  # type: ignore[attr-defined]
        headers["X-Intermedic-Signature"] = f"sha256={sig}"
    try:
        resp = requests.post(hook.url, data=body, headers=headers, timeout=10)
        resp.raise_for_status()
        logger.info("Webhook %s → %s OK (%d)", event, hook.url, resp.status_code)
    except Exception:
        logger.exception("Webhook %s → %s failed", event, hook.url)
