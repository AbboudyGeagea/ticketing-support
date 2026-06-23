"""One-shot script: insert project tasks (flat, one row per item)."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import create_app
from app.extensions import db
from app.models.task import Task, TASK_TODO, TASK_DONE
from app.models.hospital import Hospital
from app.models.product import Product
from app.models.user import User

# ---------------------------------------------------------------------------
# (title, hospital_keyword, product_keyword, is_done)
# hospital_keyword: matched with ILIKE %keyword% against hospitals.name
# product_keyword:  matched with ILIKE %keyword% against products.name
# ---------------------------------------------------------------------------
TASKS = [
    # CVIS — SJH
    ("Worklist (modality + US configuration on IBE)",   "SJH",      "CVIS",  False),
    ("List of users",                                   "SJH",      "CVIS",  True),
    ("Template",                                        "SJH",      "CVIS",  False),
    ("Measurements mapping (profile)",                  "SJH",      "CVIS",  False),
    ("ECGs / Holters",                                  "SJH",      "CVIS",  False),
    ("CD-Direct",                                       "SJH",      "CVIS",  False),
    ("Cathlab (+ License)",                             "SJH",      "CVIS",  False),
    ("Cathlab — List of users",                         "SJH",      "CVIS",  False),
    ("Cathlab — Template",                              "SJH",      "CVIS",  False),
    ("Cathlab — Test right workflow",                   "SJH",      "CVIS",  False),
    ("Cathlab — Charting",                              "SJH",      "CVIS",  False),
    ("Testing",                                         "SJH",      "CVIS",  False),

    # Pyxis — SJH
    ("Training",                                        "SJH",      "Pyxis", False),
    ("Towers (HW team)",                                "SJH",      "Pyxis", False),
    ("Go-Live",                                         "SJH",      "Pyxis", False),

    # SLH (Saint Louis Hospital)
    ("Portal installation",                             "Saint Louis", None, False),

    # NDDS
    ("ORM testing",                                     "NDDS",     None,    False),

    # CLV
    ("Integration",                                     "CLV",      None,    True),

    # Makassed — PACS
    ("Modalities configuration",                        "Makassed", "PACS",  True),
    ("WS installation",                                 "Makassed", "PACS",  True),
    ("Logo / Master Template",                          "Makassed", "PACS",  True),
    ("Application testing",                             "Makassed", "PACS",  True),
    ("Training / Go-Live",                              "Makassed", "PACS",  True),

    # Pyxis — LAU
    ("Inventory interface",                             "LAU",      "Pyxis", False),
]


_hospital_cache = {}
_product_cache  = {}


def find_hospital(keyword):
    if not keyword:
        return None
    if keyword in _hospital_cache:
        return _hospital_cache[keyword]
    h = Hospital.query.filter(Hospital.name.ilike(f"%{keyword}%")).first()
    if not h:
        print(f"  WARNING: hospital not found for '{keyword}'")
    _hospital_cache[keyword] = h
    return h


def find_product(keyword):
    if not keyword:
        return None
    if keyword in _product_cache:
        return _product_cache[keyword]
    p = Product.query.filter(Product.name.ilike(f"%{keyword}%")).first()
    if not p:
        print(f"  WARNING: product not found for '{keyword}'")
    _product_cache[keyword] = p
    return p


app = create_app()

with app.app_context():
    admin = User.query.filter(
        User.role.in_(["admin", "agent"]),
        User.active == True,
    ).order_by(User.id).first()

    if not admin:
        print("ERROR: No active agent/admin user found. Aborting.")
        sys.exit(1)

    print(f"Using creator/assignee: {admin.name} (id={admin.id})\n")

    created = 0
    skipped = 0

    for (title, hosp_kw, prod_kw, is_done) in TASKS:
        hospital = find_hospital(hosp_kw)
        product  = find_product(prod_kw)

        existing = Task.query.filter_by(
            title=title,
            hospital_id=hospital.id if hospital else None,
            product_id=product.id if product else None,
        ).first()

        if existing:
            print(f"  SKIP: {title}")
            skipped += 1
            continue

        task = Task(
            title=title,
            status=TASK_DONE if is_done else TASK_TODO,
            priority="medium",
            hospital_id=hospital.id if hospital else None,
            product_id=product.id if product else None,
            created_by=admin.id,
            assigned_to=admin.id,
        )
        db.session.add(task)
        mark = " ✓" if is_done else ""
        h_name = hospital.name if hospital else "—"
        p_name = product.name if product else "—"
        print(f"  ADD: [{h_name} / {p_name}] {title}{mark}")
        created += 1

    db.session.commit()
    print(f"\nDone — {created} created, {skipped} skipped.")
