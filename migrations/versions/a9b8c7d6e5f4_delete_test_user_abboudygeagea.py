"""Delete test user abboudygeagea@gmail.com

Revision ID: a9b8c7d6e5f4
Revises: f1a2b3c4d5e6
Create Date: 2026-06-19 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'a9b8c7d6e5f4'
down_revision = 'f1a2b3c4d5e6'
branch_labels = None
depends_on = None

TARGET_EMAIL = 'abboudygeagea@gmail.com'


def upgrade():
    conn = op.get_bind()

    row = conn.execute(
        sa.text("SELECT id FROM users WHERE email = :email"),
        {"email": TARGET_EMAIL}
    ).fetchone()

    if not row:
        print(f"[skip] User {TARGET_EMAIL} not found — nothing to delete.")
        return

    uid = row[0]

    conn.execute(sa.text("UPDATE tickets SET created_by = NULL WHERE created_by = :uid"), {"uid": uid})
    conn.execute(sa.text("UPDATE tickets SET assigned_to = NULL WHERE assigned_to = :uid"), {"uid": uid})
    conn.execute(sa.text("UPDATE tasks SET assigned_to = NULL WHERE assigned_to = :uid"), {"uid": uid})
    conn.execute(sa.text("UPDATE tasks SET created_by = NULL WHERE created_by = :uid"), {"uid": uid})
    conn.execute(sa.text("UPDATE ticket_attachments SET uploaded_by = NULL WHERE uploaded_by = :uid"), {"uid": uid})
    conn.execute(sa.text("DELETE FROM saved_filters WHERE user_id = :uid"), {"uid": uid})
    conn.execute(sa.text("DELETE FROM user_products WHERE user_id = :uid"), {"uid": uid})
    conn.execute(sa.text("DELETE FROM users WHERE id = :uid"), {"uid": uid})

    print(f"[done] Deleted user {TARGET_EMAIL} (id={uid}).")


def downgrade():
    # Data deletion is irreversible
    pass
