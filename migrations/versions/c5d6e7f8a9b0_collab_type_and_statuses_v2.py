"""Add collab_type, close_requested; replace ticket statuses with new workflow

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
Create Date: 2026-06-18

"""
from alembic import op
import sqlalchemy as sa

revision = 'c5d6e7f8a9b0'
down_revision = 'b4c5d6e7f8a9'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Add collab_type to ticket_collaborators
    op.add_column('ticket_collaborators',
        sa.Column('collab_type', sa.String(20), nullable=False, server_default='customer'))

    # 2. Add close_requested to tickets
    op.add_column('tickets',
        sa.Column('close_requested', sa.Boolean(), nullable=False, server_default=sa.text('false')))

    # 3. Migrate existing ticket statuses: open → new, pending → awaiting_info
    op.execute("UPDATE tickets SET status = 'new' WHERE status = 'open'")
    op.execute("UPDATE tickets SET status = 'awaiting_info' WHERE status = 'pending'")

    # 4. Replace old ticket_statuses rows with new workflow statuses
    op.execute("DELETE FROM ticket_statuses WHERE slug IN ('open', 'pending')")

    op.execute("""
        INSERT INTO ticket_statuses (slug, label, color, "order", is_system)
        VALUES
            ('new',           'New',           '#3B82F6', 1, true),
            ('assigned',      'Assigned',      '#8B5CF6', 2, true),
            ('awaiting_info', 'Awaiting Info', '#F97316', 3, true),
            ('in_progress',   'In Progress',   '#EAB308', 4, true),
            ('escalated',     'Escalated',     '#EF4444', 5, true),
            ('resolved',      'Resolved',      '#22C55E', 6, true),
            ('closed',        'Closed',        '#64748B', 7, true)
        ON CONFLICT (slug) DO UPDATE
            SET label = EXCLUDED.label,
                color = EXCLUDED.color,
                "order" = EXCLUDED."order",
                is_system = EXCLUDED.is_system
    """)


def downgrade():
    # Reverse data migration
    op.execute("UPDATE tickets SET status = 'open' WHERE status = 'new'")
    op.execute("UPDATE tickets SET status = 'pending' WHERE status = 'awaiting_info'")

    op.execute("DELETE FROM ticket_statuses WHERE slug IN ('new', 'assigned', 'awaiting_info', 'escalated')")

    op.execute("""
        INSERT INTO ticket_statuses (slug, label, color, "order", is_system)
        VALUES
            ('open',       'Open',       '#3B82F6', 1, true),
            ('in_progress','In Progress','#EAB308', 2, true),
            ('pending',    'Pending',    '#F97316', 3, true),
            ('resolved',   'Resolved',  '#22C55E', 4, true),
            ('closed',     'Closed',    '#64748B', 5, true)
        ON CONFLICT (slug) DO NOTHING
    """)

    op.drop_column('tickets', 'close_requested')
    op.drop_column('ticket_collaborators', 'collab_type')
