"""Add project subtasks, requirements, and template linkage

Revision ID: a1b2c3d4e5f6
Revises: f1a2b3c4d5e6
Create Date: 2026-05-25 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'a1b2c3d4e5f6'
down_revision = 'f1a2b3c4d5e6'
branch_labels = None
depends_on = None


def upgrade():
    # ── project_tasks: add parent_id for subtasks ──────────────────────────────
    op.add_column('project_tasks',
        sa.Column('parent_id', sa.Integer(), sa.ForeignKey('project_tasks.id'), nullable=True))

    # ── project_template_tasks: add parent_id for subtask hierarchy ───────────
    op.add_column('project_template_tasks',
        sa.Column('parent_id', sa.Integer(), sa.ForeignKey('project_template_tasks.id'), nullable=True))

    # ── projects: add template_id to track origin template ────────────────────
    op.add_column('projects',
        sa.Column('template_id', sa.Integer(), sa.ForeignKey('project_templates.id'), nullable=True))

    # ── project_template_requirements ─────────────────────────────────────────
    op.create_table(
        'project_template_requirements',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('template_id', sa.Integer(), sa.ForeignKey('project_templates.id', ondelete='CASCADE'), nullable=False),
        sa.Column('title', sa.String(500), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('req_type', sa.String(20), nullable=False, server_default='provide'),
        sa.Column('order', sa.Integer(), nullable=False, server_default='0'),
    )

    # ── project_requirements ───────────────────────────────────────────────────
    op.create_table(
        'project_requirements',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('title', sa.String(500), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('req_type', sa.String(20), nullable=False, server_default='provide'),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('assigned_to_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('assigned_to_email', sa.String(254), nullable=True),
        sa.Column('assigned_agent_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('response_text', sa.Text(), nullable=True),
        sa.Column('due_date', sa.Date(), nullable=True),
        sa.Column('email_sent', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table('project_requirements')
    op.drop_table('project_template_requirements')
    op.drop_column('projects', 'template_id')
    op.drop_column('project_template_tasks', 'parent_id')
    op.drop_column('project_tasks', 'parent_id')
