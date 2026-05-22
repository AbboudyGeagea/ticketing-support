"""Apply SLA deadlines to a ticket based on its priority."""
from datetime import datetime, timedelta


def apply_sla(ticket):
    """Set sla_response_due and sla_resolve_due on ticket based on active SLAPolicy."""
    try:
        from app.models.sla_policy import SLAPolicy
        policy = SLAPolicy.query.filter_by(priority=ticket.priority, is_active=True).first()
        if not policy:
            return
        now = datetime.utcnow()
        ticket.sla_response_due = now + timedelta(hours=policy.response_hours)
        ticket.sla_resolve_due = now + timedelta(hours=policy.resolve_hours)
    except Exception:
        pass
