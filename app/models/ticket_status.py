from app.extensions import db


class TicketStatus(db.Model):
    __tablename__ = "ticket_statuses"

    slug = db.Column(db.String(50), primary_key=True)   # used in code: open, in_progress, …
    label = db.Column(db.String(100), nullable=False)   # shown to users
    color = db.Column(db.String(7), nullable=False)     # hex e.g. #3B82F6
    order = db.Column(db.Integer, default=0)
    is_system = db.Column(db.Boolean, default=True)     # system statuses cannot be deleted

    def __repr__(self):
        return f"<TicketStatus {self.slug}>"
