"""add related_ticket_id to tickets (clickable link to the originating closed ticket)

Revision ID: ee55ff66aa77
Revises: dd44ee55ff66
Create Date: 2026-07-28
"""
from alembic import op
import sqlalchemy as sa

revision = 'ee55ff66aa77'
down_revision = 'dd44ee55ff66'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('tickets', sa.Column('related_ticket_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_tickets_related_ticket_id', 'tickets', 'tickets',
        ['related_ticket_id'], ['id'],
    )
    op.create_index('ix_tickets_related_ticket_id', 'tickets', ['related_ticket_id'])


def downgrade():
    op.drop_index('ix_tickets_related_ticket_id', 'tickets')
    op.drop_constraint('fk_tickets_related_ticket_id', 'tickets', type_='foreignkey')
    op.drop_column('tickets', 'related_ticket_id')
