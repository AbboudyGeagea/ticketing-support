"""One-shot script: rename CLV hospital and insert customer users."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.hospital import Hospital

USERS = [
    ("PACS",             "pacs@cliniquedulevantsm.com"),
    ("Liliane Rouphael", "liliane.rouphael@cliniquedulevantsm.com"),
    ("Ziad Maalouf",     "ziad.maalouf@cliniquedulevantsm.com"),
    ("Elias Baddour",    "biomedical@cliniquedulevantsm.com"),
]

TEMP_PASSWORD = "12345678"

app = create_app()

with app.app_context():
    hospital = Hospital.query.filter(
        Hospital.name.ilike("%CLV%") | Hospital.name.ilike("%Levant%")
    ).first()

    if not hospital:
        print("ERROR: No hospital matching 'CLV' or 'Levant' found. Aborting.")
        sys.exit(1)

    print(f"Hospital found: {hospital.name} (id={hospital.id})")

    if hospital.name != "Clinique Du Levant":
        hospital.name = "Clinique Du Levant"
        print("  UPDATED: hospital name → Clinique Du Levant")

    if hospital.email_domain != "cliniquedulevantsm.com":
        hospital.email_domain = "cliniquedulevantsm.com"
        print("  UPDATED: email domain → cliniquedulevantsm.com")

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
