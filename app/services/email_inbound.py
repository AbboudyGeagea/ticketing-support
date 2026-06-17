"""
Inbound email processing via Microsoft Graph API.
Polls the O365 mailbox for unread messages and converts them to tickets.
"""
import re
import uuid
import logging
from datetime import datetime
from bs4 import BeautifulSoup

import msal
import requests

logger = logging.getLogger(__name__)

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_SCOPES = ["https://graph.microsoft.com/.default"]
_CONV_CACHE_TTL = 60 * 60 * 24 * 30  # 30 days


def _redis_client():
    import redis
    from flask import current_app
    url = current_app.config.get("CELERY_BROKER_URL", "redis://redis:6379/0")
    return redis.from_url(url, decode_responses=True)


def _cache_set(conversation_id: str, ticket_ref: str) -> None:
    try:
        _redis_client().setex(f"conv:{conversation_id}", _CONV_CACHE_TTL, ticket_ref)
    except Exception:
        logger.debug("Redis conv cache write failed for %s", conversation_id)


def _cache_get(conversation_id: str) -> str | None:
    try:
        return _redis_client().get(f"conv:{conversation_id}")
    except Exception:
        logger.debug("Redis conv cache read failed for %s — falling back to DB", conversation_id)
        return None


def _get_token(tenant_id: str, client_id: str, client_secret: str) -> str | None:
    authority = f"https://login.microsoftonline.com/{tenant_id}"
    app = msal.ConfidentialClientApplication(
        client_id, authority=authority, client_credential=client_secret
    )
    result = app.acquire_token_for_client(scopes=_SCOPES)
    if "access_token" not in result:
        logger.error("Graph API token error: %s", result.get("error_description"))
        return None
    return result["access_token"]


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    return soup.get_text(separator="\n").strip()


def fetch_and_process(app):
    """Called by APScheduler every N seconds."""
    from app.services.email_settings import get_effective_config
    eff = get_effective_config(app)
    tenant_id = eff["tenant_id"]
    client_id = eff["client_id"]
    client_secret = eff["client_secret"]
    mailbox = eff["mailbox"]

    if not all([tenant_id, client_id, client_secret, mailbox]):
        logger.debug("Email inbound not configured, skipping poll.")
        return

    token = _get_token(tenant_id, client_id, client_secret)
    if not token:
        return

    headers = _headers(token)
    url = (
        f"{_GRAPH_BASE}/users/{mailbox}/messages"
        f"?$filter=isRead eq false"
        f"&$orderby=receivedDateTime asc"
        f"&$top=50"
        f"&$select=id,subject,from,body,receivedDateTime,conversationId"
    )

    resp = requests.get(url, headers=headers, timeout=30)
    if not resp.ok:
        logger.error("Graph API fetch error %s: %s", resp.status_code, resp.text[:300])
        return

    messages = resp.json().get("value", [])
    logger.info("Fetched %d unread message(s) from %s", len(messages), mailbox)

    with app.app_context():
        for msg in messages:
            try:
                _process_message(msg, headers, mailbox, token)
            except Exception:
                logger.exception("Failed to process message %s", msg.get("id"))


def _process_message(msg: dict, headers: dict, mailbox: str, token: str):
    from app.models.ticket import Ticket, TicketMessage, TicketHistory
    from app.models.user import User
    from app.models.hospital import Hospital
    from app.extensions import db

    graph_msg_id = msg["id"]
    conversation_id = msg.get("conversationId", "")
    sender_email = msg.get("from", {}).get("emailAddress", {}).get("address", "").lower().strip()
    sender_name = msg.get("from", {}).get("emailAddress", {}).get("name", sender_email)
    subject = (msg.get("subject") or "(no subject)").strip()
    body_content = msg.get("body", {}).get("content", "")
    body_type = msg.get("body", {}).get("contentType", "text")

    body_text = _html_to_text(body_content) if body_type == "html" else body_content

    # Strip auto-reply noise: if subject starts with common auto-reply prefixes, skip
    auto_reply_prefixes = ("automatic reply:", "out of office:", "autoreply:")
    if any(subject.lower().startswith(p) for p in auto_reply_prefixes):
        _mark_read(mailbox, graph_msg_id, headers)
        return

    # Check if this is a reply to an existing ticket (by conversationId or Re: ref in subject)
    existing_ticket = _find_existing_ticket(conversation_id, subject)

    if existing_ticket:
        _append_reply(existing_ticket, sender_email, sender_name, body_text, db)
        logger.info("Appended reply to %s from %s", existing_ticket.ref, sender_email)
    else:
        _create_ticket(sender_email, sender_name, subject, body_text, conversation_id, db)

    # Commit first, then mark read — so a Graph API failure never causes
    # us to reprocess a message that was already written to the DB.
    db.session.commit()
    try:
        _mark_read(mailbox, graph_msg_id, headers)
    except Exception:
        logger.warning("Failed to mark message %s as read in Graph API", graph_msg_id)


def _find_existing_ticket(conversation_id: str, subject: str):
    from app.models.ticket import Ticket

    if conversation_id:
        # Check Redis cache first (fast path)
        cached_ref = _cache_get(conversation_id)
        if cached_ref:
            t = Ticket.query.filter_by(ref=cached_ref).first()
            if t:
                return t
        # Fall back to DB lookup
        t = Ticket.query.filter_by(email_thread_id=conversation_id).first()
        if t:
            return t

    # Fall back: look for ticket ref in subject like [0042]
    match = re.search(r"\[(\d{4,})\]", subject)
    if match:
        return Ticket.query.filter_by(ref=match.group(1)).first()

    return None


def _create_ticket(sender_email, sender_name, subject, body, conversation_id, db):
    from app.models.ticket import Ticket, TicketMessage
    from app.models.user import User
    from app.models.hospital import Hospital
    from app.models.product import Product
    from app.services.email_outbound import notify_agents_new_ticket

    sender_user = User.query.filter_by(email=sender_email).first()
    hospital_id = sender_user.hospital_id if sender_user else None

    # Try matching hospital by email domain
    if not hospital_id:
        domain = sender_email.split("@")[-1] if "@" in sender_email else None
        if domain:
            h = Hospital.query.filter_by(email_domain=domain, active=True).first()
            hospital_id = h.id if h else None

    if not hospital_id:
        logger.warning("No hospital match for email %s — ticket not created.", sender_email)
        return

    # Resolve the default product for this hospital (first active product via association)
    default_product = (
        Product.query
        .join(Product.hospitals)
        .filter(Hospital.id == hospital_id, Product.active == True)
        .first()
    )
    product_id = default_product.id if default_product else None

    ticket = Ticket(
        ref=uuid.uuid4().hex[:20],  # temp unique value; sliced to fit VARCHAR(20)
        hospital_id=hospital_id,
        product_id=product_id,
        created_by=sender_user.id if sender_user else None,
        subject=subject,
        status="open",
        priority="medium",
        source="email",
        email_thread_id=conversation_id,
    )
    db.session.add(ticket)
    db.session.flush()

    ticket.ref = f"{ticket.id:04d}"
    if conversation_id:
        _cache_set(conversation_id, ticket.ref)

    msg = TicketMessage(
        ticket_id=ticket.id,
        sender_id=sender_user.id if sender_user else None,
        sender_name=sender_name,
        sender_email=sender_email,
        body=body,
    )
    db.session.add(msg)

    try:
        from app.services.auto_assign import apply_auto_assignment
        apply_auto_assignment(ticket)
    except Exception:
        logger.exception("Auto-assignment failed for %s", ticket.ref)

    try:
        from app.services.sla_service import apply_sla
        apply_sla(ticket)
    except Exception:
        logger.exception("SLA apply failed for %s", ticket.ref)

    logger.info("Created ticket %s from email %s", ticket.ref, sender_email)

    try:
        notify_agents_new_ticket(ticket)
    except Exception:
        logger.exception("Failed to send new-ticket agent notification for %s", ticket.ref)


def _append_reply(ticket, sender_email, sender_name, body, db):
    from app.models.ticket import Ticket, TicketMessage
    from app.models.user import User

    sender_user = User.query.filter_by(email=sender_email).first()
    msg = TicketMessage(
        ticket_id=ticket.id,
        sender_id=sender_user.id if sender_user else None,
        sender_name=sender_name,
        sender_email=sender_email,
        body=body,
        is_internal=False,
    )
    db.session.add(msg)

    if ticket.status in ("resolved", "pending", "closed"):
        ticket.status = "open"
        ticket.closed_at = None

    ticket.updated_at = datetime.utcnow()


def _mark_read(mailbox: str, message_id: str, headers: dict):
    url = f"{_GRAPH_BASE}/users/{mailbox}/messages/{message_id}"
    requests.patch(url, headers=headers, json={"isRead": True}, timeout=15)
