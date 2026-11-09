"""delete all tasks: every Tasks-tab task and every project task

Removes all rows from `tasks` (with their checklists, dependencies, subtasks and
logged time entries) and from `project_tasks` (with their subtasks). PM findings
keep their data but lose the link to a follow-up task. Projects, milestones,
requirements, project templates and sprints are kept.

This cannot be undone: downgrade does not bring the rows back.

Revision ID: d9e0f1a2b3c4
Revises: c7d8e9f0a1b2
Create Date: 2026-11-09
"""
from alembic import op

revision = 'd9e0f1a2b3c4'
down_revision = 'c7d8e9f0a1b2'
branch_labels = None
depends_on = None


def upgrade():
    # Children and references first, so no foreign key blocks the deletes.
    op.execute("UPDATE pm_results SET task_id = NULL WHERE task_id IS NOT NULL")
    op.execute("DELETE FROM task_dependencies")
    op.execute("DELETE FROM task_checklists")
    op.execute("DELETE FROM time_entries")
    op.execute("UPDATE tasks SET parent_id = NULL WHERE parent_id IS NOT NULL")
    op.execute("DELETE FROM tasks")

    op.execute("UPDATE project_tasks SET parent_id = NULL WHERE parent_id IS NOT NULL")
    op.execute("DELETE FROM project_tasks")


def downgrade():
    # Deleted data can't be restored; nothing to undo schema-wise.
    pass
