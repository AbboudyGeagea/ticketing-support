"""Add missing indexes on high-traffic columns

Revision ID: d1f2a3b4c5e6
Revises: c9d3e5f2b781
Create Date: 2026-05-22 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'd1f2a3b4c5e6'
down_revision = 'c9d3e5f2b781'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE INDEX IF NOT EXISTS ix_tickets_status ON tickets(status)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tickets_assigned_to ON tickets(assigned_to)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tickets_hospital_id ON tickets(hospital_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tickets_updated_at ON tickets(updated_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tickets_email_thread_id ON tickets(email_thread_id)")

    op.execute("CREATE INDEX IF NOT EXISTS ix_ticket_messages_ticket_id ON ticket_messages(ticket_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ticket_messages_sender_id ON ticket_messages(sender_id)")

    op.execute("CREATE INDEX IF NOT EXISTS ix_ticket_history_ticket_id ON ticket_history(ticket_id)")

    op.execute("CREATE INDEX IF NOT EXISTS ix_ticket_attachments_ticket_id ON ticket_attachments(ticket_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ticket_attachments_message_id ON ticket_attachments(message_id)")

    op.execute("CREATE INDEX IF NOT EXISTS ix_tasks_assigned_to ON tasks(assigned_to)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tasks_status ON tasks(status)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tasks_deadline ON tasks(deadline)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tasks_ticket_id ON tasks(ticket_id)")


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_tickets_status")
    op.execute("DROP INDEX IF EXISTS ix_tickets_assigned_to")
    op.execute("DROP INDEX IF EXISTS ix_tickets_hospital_id")
    op.execute("DROP INDEX IF EXISTS ix_tickets_updated_at")
    op.execute("DROP INDEX IF EXISTS ix_tickets_email_thread_id")

    op.execute("DROP INDEX IF EXISTS ix_ticket_messages_ticket_id")
    op.execute("DROP INDEX IF EXISTS ix_ticket_messages_sender_id")

    op.execute("DROP INDEX IF EXISTS ix_ticket_history_ticket_id")

    op.execute("DROP INDEX IF EXISTS ix_ticket_attachments_ticket_id")
    op.execute("DROP INDEX IF EXISTS ix_ticket_attachments_message_id")

    op.execute("DROP INDEX IF EXISTS ix_tasks_assigned_to")
    op.execute("DROP INDEX IF EXISTS ix_tasks_status")
    op.execute("DROP INDEX IF EXISTS ix_tasks_deadline")
    op.execute("DROP INDEX IF EXISTS ix_tasks_ticket_id")
