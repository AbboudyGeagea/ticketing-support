"""Apply SLA deadlines to a ticket based on its priority."""
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def apply_sla(ticket):
    """Set sla_response_due and sla_resolve_due on ticket based on active SLAPolicy."""
    try:
        from app.models.sla_policy import SLAPolicy
        policy = SLAPolicy.query.filter_by(priority=ticket.priority, is_active=True).first()
        if not policy:
            logger.warning(
                "No active SLA policy for priority '%s' — ticket %s will have no SLA deadline",
                ticket.priority, getattr(ticket, "ref", "<unflushed>"),
            )
            return
        now = datetime.utcnow()
        ticket.sla_response_due = now + timedelta(hours=policy.response_hours)
        ticket.sla_resolve_due = now + timedelta(hours=policy.resolve_hours)
    except Exception:
        logger.exception("apply_sla failed for ticket %s", getattr(ticket, "ref", "<unflushed>"))
