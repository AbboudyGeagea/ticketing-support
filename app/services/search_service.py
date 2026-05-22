"""PostgreSQL full-text search over tickets (subject + ref)."""
from app.extensions import db
from app.models.ticket import Ticket


def search_tickets(query_str: str, limit: int = 50):
    """Return tickets matching the FTS query against subject and ref."""
    if not query_str or not query_str.strip():
        return []
    tsquery = db.func.plainto_tsquery("english", query_str)
    tsvector = db.func.to_tsvector(
        "english",
        db.func.coalesce(Ticket.subject, "") + " " + db.func.coalesce(Ticket.ref, ""),
    )
    return (
        Ticket.query
        .filter(tsvector.op("@@")(tsquery))
        .order_by(Ticket.updated_at.desc())
        .limit(limit)
        .all()
    )
