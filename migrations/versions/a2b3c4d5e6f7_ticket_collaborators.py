"""Add ticket_collaborators table

Revision ID: a2b3c4d5e6f7
Revises: f4a5b6c7d8e9
Create Date: 2026-06-17 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'a2b3c4d5e6f7'
down_revision = 'f4a5b6c7d8e9'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'ticket_collaborators',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ticket_id', sa.Integer(), nullable=False),
        sa.Column('email', sa.String(200), nullable=False),
        sa.Column('name', sa.String(200), nullable=True),
        sa.Column('token', sa.String(64), nullable=False),
        sa.Column('added_by', sa.Integer(), nullable=False),
        sa.Column('added_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['added_by'], ['users.id']),
        sa.ForeignKeyConstraint(['ticket_id'], ['tickets.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('ticket_id', 'email', name='uq_collab_ticket_email'),
        sa.UniqueConstraint('token'),
    )


def downgrade():
    op.drop_table('ticket_collaborators')
