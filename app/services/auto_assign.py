"""Auto-assignment rule service: evaluates rules and assigns tickets."""
import logging
from app.models.assignment_rule import AssignmentRule

logger = logging.getLogger(__name__)


def apply_auto_assignment(ticket):
    """
    Find the first matching active rule and assign ticket.assigned_to if not already assigned.
    Returns True if a rule matched, False otherwise.
    Rules are evaluated in rule_order ASC (lower = higher priority).
    A rule matches if:
      - hospital_id is None OR matches ticket.hospital_id
      - product_id is None OR matches ticket.product_id
      - priority is None OR matches ticket.priority
    """
    if ticket.assigned_to:
        return False  # already assigned, skip

    rules = AssignmentRule.query.filter_by(is_active=True).order_by(AssignmentRule.rule_order).all()
    for rule in rules:
        if rule.hospital_id and rule.hospital_id != ticket.hospital_id:
            continue
        if rule.product_id and rule.product_id != ticket.product_id:
            continue
        if rule.priority and rule.priority != ticket.priority:
            continue
        # Rule matched
        ticket.assigned_to = rule.assigned_to
        logger.info("Auto-assigned ticket %s to user %d via rule %d", ticket.ref, rule.assigned_to, rule.id)
        return True
    return False
