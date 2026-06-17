"""One-shot script: insert CHN customer users."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.hospital import Hospital

USERS = [
    ("Anthony Bassim",      "anthony.bassim@chn.com.lb"),
    ("Khalil Bouabdallah",  "khalil.bouabdallah@chn.com.lb"),
    ("Rita Doueihy",        "rita.doueihy@chn.com.lb"),
    ("Georges Alam",        "georges.alam@chn.com.lb"),
    ("Johnny Chaanine",     "johnny.chaanine@chn.com.lb"),
    ("Eddy Chaghoury",      "eddy.chaghoury@chn.com.lb"),
    ("Radiology",           "radiology@chn.com.lb"),
]

TEMP_PASSWORD = "12345678"

app = create_app()

with app.app_context():
    hospital = Hospital.query.filter(
        Hospital.name.ilike("%CHN%")
    ).first()

    if not hospital:
        print("ERROR: No hospital matching 'CHN' found. Aborting.")
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
