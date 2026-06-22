"""add assigned_to_2 (secondary assignee) to tasks

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-06-22
"""
from alembic import op
import sqlalchemy as sa

revision = 'f5a6b7c8d9e0'
down_revision = 'e4f5a6b7c8d9'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('tasks', sa.Column('assigned_to_2', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_tasks_assigned_to_2', 'tasks', 'users', ['assigned_to_2'], ['id'])


def downgrade():
    op.drop_constraint('fk_tasks_assigned_to_2', 'tasks', type_='foreignkey')
    op.drop_column('tasks', 'assigned_to_2')
