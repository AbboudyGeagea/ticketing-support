"""add email_log table for outbound send tracking

Revision ID: a1b2c3d4e5f6
Revises: f5a6b7c8d9e0
Create Date: 2026-07-03
"""
from alembic import op
import sqlalchemy as sa

revision = 'a1b2c3d4e5f6'
down_revision = 'f5a6b7c8d9e0'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'email_log',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('ticket_ref', sa.String(20), nullable=True),
        sa.Column('recipients', sa.Text(), nullable=False),
        sa.Column('subject', sa.String(500), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('mailbox', sa.String(200), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_email_log_created_at', 'email_log', ['created_at'])
    op.create_index('ix_email_log_ticket_ref', 'email_log', ['ticket_ref'])


def downgrade():
    op.drop_index('ix_email_log_ticket_ref', 'email_log')
    op.drop_index('ix_email_log_created_at', 'email_log')
    op.drop_table('email_log')
