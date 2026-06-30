"""add phi flag columns to tickets

Revision ID: b8c9d0e1f2a3
Revises: f5a6b7c8d9e0
Create Date: 2026-06-25
"""
from alembic import op
import sqlalchemy as sa

revision = 'b8c9d0e1f2a3'
down_revision = 'f5a6b7c8d9e0'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('tickets', sa.Column('phi_flagged', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('tickets', sa.Column('phi_flagged_at', sa.DateTime(), nullable=True))
    op.add_column('tickets', sa.Column('phi_flagged_by', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_tickets_phi_flagged_by', 'tickets', 'users', ['phi_flagged_by'], ['id'])
    op.create_index('ix_tickets_phi_flagged', 'tickets', ['phi_flagged'])


def downgrade():
    op.drop_index('ix_tickets_phi_flagged', table_name='tickets')
    op.drop_constraint('fk_tickets_phi_flagged_by', 'tickets', type_='foreignkey')
    op.drop_column('tickets', 'phi_flagged_by')
    op.drop_column('tickets', 'phi_flagged_at')
    op.drop_column('tickets', 'phi_flagged')
