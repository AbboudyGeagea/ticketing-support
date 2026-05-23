"""task progress check constraint (0–100)

Revision ID: c9d3e5f2b781
Revises: b7e2d4f1a890
Create Date: 2026-05-22 13:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'c9d3e5f2b781'
down_revision = 'b7e2d4f1a890'
branch_labels = None
depends_on = None


def upgrade():
    op.create_check_constraint(
        "ck_task_progress_range",
        "tasks",
        "progress BETWEEN 0 AND 100",
    )


def downgrade():
    op.drop_constraint("ck_task_progress_range", "tasks", type_="check")
