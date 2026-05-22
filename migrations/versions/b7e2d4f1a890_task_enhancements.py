"""task enhancements: sprints, subtasks, checklists, time tracking, dependencies

Revision ID: b7e2d4f1a890
Revises: a3f1c8d2e045
Create Date: 2026-05-22 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'b7e2d4f1a890'
down_revision = 'a3f1c8d2e045'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('sprints',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('goal', sa.Text(), nullable=True),
        sa.Column('start_date', sa.DateTime(), nullable=False),
        sa.Column('end_date', sa.DateTime(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='planned'),
        sa.Column('created_by', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id')
    )

    op.add_column('tasks', sa.Column('sprint_id', sa.Integer(), sa.ForeignKey('sprints.id'), nullable=True))
    op.add_column('tasks', sa.Column('parent_id', sa.Integer(), sa.ForeignKey('tasks.id'), nullable=True))
    op.add_column('tasks', sa.Column('progress', sa.Integer(), nullable=True, server_default='0'))
    op.add_column('tasks', sa.Column('estimated_minutes', sa.Integer(), nullable=True))
    op.add_column('tasks', sa.Column('recurrence', sa.String(length=20), nullable=True, server_default='none'))
    op.add_column('tasks', sa.Column('recurrence_end', sa.DateTime(), nullable=True))

    op.create_table('task_checklists',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('task_id', sa.Integer(), nullable=False),
        sa.Column('text', sa.String(length=500), nullable=False),
        sa.Column('is_done', sa.Boolean(), nullable=True, server_default='false'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['task_id'], ['tasks.id']),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_table('time_entries',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('task_id', sa.Integer(), nullable=False),
        sa.Column('logged_by', sa.Integer(), nullable=False),
        sa.Column('minutes', sa.Integer(), nullable=False),
        sa.Column('note', sa.String(length=500), nullable=True),
        sa.Column('logged_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['task_id'], ['tasks.id']),
        sa.ForeignKeyConstraint(['logged_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_table('task_dependencies',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('task_id', sa.Integer(), nullable=False),
        sa.Column('depends_on_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['task_id'], ['tasks.id']),
        sa.ForeignKeyConstraint(['depends_on_id'], ['tasks.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('task_id', 'depends_on_id')
    )


def downgrade():
    op.drop_table('task_dependencies')
    op.drop_table('time_entries')
    op.drop_table('task_checklists')
    op.drop_column('tasks', 'recurrence_end')
    op.drop_column('tasks', 'recurrence')
    op.drop_column('tasks', 'estimated_minutes')
    op.drop_column('tasks', 'progress')
    op.drop_column('tasks', 'parent_id')
    op.drop_column('tasks', 'sprint_id')
    op.drop_table('sprints')
