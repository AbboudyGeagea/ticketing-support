"""Add rustdesk_id to hospitals

Revision ID: d2e3f4a5b6c7
Revises: b2c3d4e5f6a1
Create Date: 2026-05-25 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'd2e3f4a5b6c7'
down_revision = 'b2c3d4e5f6a1'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('hospitals',
        sa.Column('rustdesk_id', sa.String(50), nullable=True))


def downgrade():
    op.drop_column('hospitals', 'rustdesk_id')
