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


def fire_ticket_status_changed(ticket, old_status: str, new_status: str, changed_by_id=None):
    """Call after ticket.status changes and the change is committed.

    Fires "ticket_status_changed" always, plus "ticket_closed"/"ticket_resolved"
    when new_status is one of those specific values.
    """
    payload = {
        "ticket_ref": ticket.ref,
        "ticket_id": ticket.id,
        "subject": ticket.subject,
        "old_status": old_status,
        "new_status": new_status,
        "changed_by": changed_by_id,
    }
    fire_webhook("ticket_status_changed", payload)
    if new_status == "closed":
        fire_webhook("ticket_closed", payload)
    elif new_status == "resolved":
        fire_webhook("ticket_resolved", payload)


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
