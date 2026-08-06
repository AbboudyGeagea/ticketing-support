"""add email_notifications_enabled to users (customer opt-out)

Revision ID: dd44ee55ff66
Revises: cc33dd44ee55
Create Date: 2026-07-25
"""
from alembic import op
import sqlalchemy as sa

revision = 'dd44ee55ff66'
down_revision = 'cc33dd44ee55'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column(
        'email_notifications_enabled', sa.Boolean(), nullable=False, server_default=sa.text('true')))
    op.alter_column('users', 'email_notifications_enabled', server_default=None)


def downgrade():
    op.drop_column('users', 'email_notifications_enabled')
