"""One-shot script: insert AUBMC customer users."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.hospital import Hospital

USERS = [
    ("Mayssam Ayoub",    "ma745@aub.edu.lb"),
    ("Aline Avedissian", "aa75@aub.edu.lb"),
    ("Haidar Al-Khansa", "ha137@aub.edu.lb"),
    ("Therese Saad",     "ts14@aub.edu.lb"),
    ("Mohamad AL Rifai", "ma633@aub.edu.lb"),
]

TEMP_PASSWORD = "12345678"

app = create_app()

with app.app_context():
    hospital = Hospital.query.filter(
        Hospital.name.ilike("%AUBMC%")
    ).first()

    if not hospital:
        print("ERROR: No hospital matching 'AUBMC' found. Aborting.")
        sys.exit(1)

    print(f"Hospital found: {hospital.name} (id={hospital.id})")

    created = 0
    skipped = 0
    for name, email in USERS:
        if User.query.filter_by(email=email).first():
            print(f"  SKIP (already exists): {email}")
            skipped += 1
            continue
        u = User(
            hospital_id=hospital.id,
            email=email,
            name=name,
            role="customer",
            active=True,
        )
        u.set_password(TEMP_PASSWORD)
        db.session.add(u)
        print(f"  ADD: {name} <{email}>")
        created += 1

    db.session.commit()
    print(f"\nDone — {created} created, {skipped} skipped.")
