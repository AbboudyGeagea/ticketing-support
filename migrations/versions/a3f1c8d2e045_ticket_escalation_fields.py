"""ticket escalation fields

Revision ID: a3f1c8d2e045
Revises: 689aed09d9c0
Create Date: 2026-05-22 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'a3f1c8d2e045'
down_revision = '689aed09d9c0'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('tickets', sa.Column('escalation_url', sa.String(length=1000), nullable=True))
    op.add_column('tickets', sa.Column('escalation_number', sa.String(length=100), nullable=True))


def downgrade():
    op.drop_column('tickets', 'escalation_number')
    op.drop_column('tickets', 'escalation_url')
