"""Add rustdesk_logs audit table

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-05-25 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'e3f4a5b6c7d8'
down_revision = 'd2e3f4a5b6c7'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'rustdesk_logs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('ticket_id', sa.Integer(), sa.ForeignKey('tickets.id', ondelete='CASCADE'), nullable=False),
        sa.Column('agent_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('peer_id', sa.String(50), nullable=True),
        sa.Column('connected_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_rustdesk_logs_ticket_id', 'rustdesk_logs', ['ticket_id'])


def downgrade():
    op.drop_index('ix_rustdesk_logs_ticket_id', 'rustdesk_logs')
    op.drop_table('rustdesk_logs')
