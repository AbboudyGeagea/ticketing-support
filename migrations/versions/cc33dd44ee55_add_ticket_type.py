"""add ticket type (report a problem / ask a question / request a change)

Revision ID: cc33dd44ee55
Revises: bb22cc33dd44
Create Date: 2026-07-20
"""
from alembic import op
import sqlalchemy as sa

revision = 'cc33dd44ee55'
down_revision = 'bb22cc33dd44'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('tickets', sa.Column(
        'type', sa.String(20), nullable=False, server_default='problem'))
    op.alter_column('tickets', 'type', server_default=None)


def downgrade():
    op.drop_column('tickets', 'type')
