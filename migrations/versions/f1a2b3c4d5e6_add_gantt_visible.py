"""Add is_gantt_visible to projects

Revision ID: f1a2b3c4d5e6
Revises: e5f6a7b8c9d0
Create Date: 2026-05-23 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'f1a2b3c4d5e6'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('projects', sa.Column('is_gantt_visible', sa.Boolean(), nullable=False, server_default='false'))


def downgrade():
    op.drop_column('projects', 'is_gantt_visible')
