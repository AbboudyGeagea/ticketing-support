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
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'ck_task_progress_range'
            ) THEN
                ALTER TABLE tasks ADD CONSTRAINT ck_task_progress_range
                    CHECK (progress BETWEEN 0 AND 100);
            END IF;
        END $$;
    """)


def downgrade():
    op.execute("""
        ALTER TABLE tasks DROP CONSTRAINT IF EXISTS ck_task_progress_range;
    """)
