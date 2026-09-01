"""ticket department_id (routing snapshot, backfilled from creator)

Revision ID: b6c7d8e9f0a1
Revises: a5b6c7d8e9f0
Create Date: 2026-09-01
"""
from alembic import op
import sqlalchemy as sa

revision = 'b6c7d8e9f0a1'
down_revision = 'a5b6c7d8e9f0'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('tickets', sa.Column('department_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_tickets_department_id', 'tickets', 'departments',
        ['department_id'], ['id'],
    )
    op.create_index('ix_tickets_department_id', 'tickets', ['department_id'])

    op.execute("""
        UPDATE tickets
        SET department_id = u.department_id
        FROM users u
        WHERE tickets.created_by = u.id
          AND u.department_id IS NOT NULL
    """)


def downgrade():
    op.drop_index('ix_tickets_department_id', 'tickets')
    op.drop_constraint('fk_tickets_department_id', 'tickets', type_='foreignkey')
    op.drop_column('tickets', 'department_id')
