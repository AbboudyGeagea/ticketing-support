"""add email_log table for outbound send tracking

Revision ID: aa11bb22cc33
Revises: b8c9d0e1f2a3
Create Date: 2026-07-03
"""
from alembic import op
import sqlalchemy as sa

revision = 'aa11bb22cc33'
down_revision = 'b8c9d0e1f2a3'
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
