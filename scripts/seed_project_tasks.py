"""One-shot script: insert project task list (CVIS/Pyxis/PACS/SMS per hospital)."""
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
# Task data
# parent title → hospital keyword, product keyword, list of (subtask title, done?)
# ---------------------------------------------------------------------------
TASK_TREE = [
    {
        "title": "CVIS — SJH",
        "hospital": "SJH",
        "product": "CVIS",
        "subtasks": [
            ("Worklist (modality + US configuration on IBE)", False),
            ("List of users",                                 True),   # ✓
            ("Template",                                      False),
            ("Measurements mapping (profile)",               False),
            ("ECGs / Holters",                               False),
            ("CD-Direct",                                    False),
            ("Cathlab — List of users",                      False),
            ("Cathlab — Template",                           False),
            ("Cathlab — Test right workflow",                False),
            ("Cathlab — Charting",                           False),
            ("Testing",                                      False),
        ],
    },
    {
        "title": "Pyxis — SJH",
        "hospital": "SJH",
        "product": "Pyxis",
        "subtasks": [
            ("Training",        False),
            ("Towers (HW team)", False),
            ("Go-Live",         False),
        ],
    },
    {
        "title": "SLH",
        "hospital": "SLH",
        "product": None,
        "subtasks": [
            ("Portal installation", False),
        ],
    },
    {
        "title": "NDDS",
        "hospital": "NDDS",
        "product": None,
        "subtasks": [
            ("ORM testing", False),
        ],
    },
    {
        "title": "CLV",
        "hospital": "CLV",
        "product": None,
        "subtasks": [
            ("Integration", True),   # ✓
        ],
    },
    {
        "title": "Makassed",
        "hospital": "Makassed",
        "product": None,
        "subtasks": [
            ("Modalities configuration", True),   # ✓
            ("WS installation",          True),   # ✓
            ("Logo / Master Template",   True),   # ✓
            ("Application testing",      True),   # ✓
            ("Training / Go-Live",       True),   # ✓
        ],
    },
    {
        "title": "Pyxis — LAU",
        "hospital": "LAU",
        "product": "Pyxis",
        "subtasks": [
            ("Inventory interface", False),
        ],
    },
]


def find_hospital(keyword):
    if not keyword:
        return None
    h = Hospital.query.filter(Hospital.name.ilike(f"%{keyword}%")).first()
    if not h:
        print(f"  WARNING: hospital not found for keyword '{keyword}'")
    return h


def find_product(keyword):
    if not keyword:
        return None
    p = Product.query.filter(Product.name.ilike(f"%{keyword}%")).first()
    if not p:
        print(f"  WARNING: product not found for keyword '{keyword}'")
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

    total_parents = 0
    total_subtasks = 0

    for entry in TASK_TREE:
        # Skip if parent already exists
        if Task.query.filter_by(title=entry["title"], parent_id=None).first():
            print(f"  SKIP (already exists): {entry['title']}")
            continue

        hospital = find_hospital(entry["hospital"])
        product  = find_product(entry["product"])

        parent = Task(
            title=entry["title"],
            status=TASK_TODO,
            priority="medium",
            hospital_id=hospital.id if hospital else None,
            product_id=product.id if product else None,
            created_by=admin.id,
            assigned_to=admin.id,
        )
        db.session.add(parent)
        db.session.flush()  # get parent.id before subtasks

        print(f"  ADD parent: {entry['title']} (hospital={hospital.name if hospital else '—'}, product={product.name if product else '—'})")
        total_parents += 1

        for (sub_title, is_done) in entry["subtasks"]:
            subtask = Task(
                title=sub_title,
                parent_id=parent.id,
                status=TASK_DONE if is_done else TASK_TODO,
                priority="medium",
                hospital_id=hospital.id if hospital else None,
                product_id=product.id if product else None,
                created_by=admin.id,
                assigned_to=admin.id,
            )
            db.session.add(subtask)
            mark = " ✓" if is_done else ""
            print(f"       subtask: {sub_title}{mark}")
            total_subtasks += 1

    db.session.commit()
    print(f"\nDone — {total_parents} parent tasks, {total_subtasks} subtasks created.")
