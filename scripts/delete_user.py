"""One-off script: hard-delete a user by email.

Usage (run from the project root on the server):
    python scripts/delete_user.py abboudygeagea@gmail.com
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import create_app
from app.extensions import db
from app.models.user import User

def delete_user(email):
    app = create_app()
    with app.app_context():
        user = User.query.filter_by(email=email.lower().strip()).first()
        if not user:
            print(f"No user found with email: {email}")
            sys.exit(1)

        print(f"Found: {user.name} ({user.email}) — role={user.role}, active={user.active}")
        confirm = input("Delete this user? [y/N] ").strip().lower()
        if confirm != "y":
            print("Aborted.")
            sys.exit(0)

        # Nullify FK references so the row can be deleted cleanly
        from sqlalchemy import text
        db.session.execute(text("UPDATE tickets SET created_by = NULL WHERE created_by = :uid"), {"uid": user.id})
        db.session.execute(text("UPDATE tickets SET assigned_to = NULL WHERE assigned_to = :uid"), {"uid": user.id})
        db.session.execute(text("UPDATE tasks SET assigned_to = NULL WHERE assigned_to = :uid"), {"uid": user.id})
        db.session.execute(text("UPDATE tasks SET created_by = NULL WHERE created_by = :uid"), {"uid": user.id})
        db.session.execute(text("UPDATE ticket_attachments SET uploaded_by = NULL WHERE uploaded_by = :uid"), {"uid": user.id})
        db.session.execute(text("DELETE FROM saved_filters WHERE user_id = :uid"), {"uid": user.id})
        db.session.execute(text("DELETE FROM user_products WHERE user_id = :uid"), {"uid": user.id})

        db.session.delete(user)
        db.session.commit()
        print(f"Deleted user: {email}")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/delete_user.py <email>")
        sys.exit(1)
    delete_user(sys.argv[1])
