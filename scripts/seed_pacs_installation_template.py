"""One-shot script: add tasks + requirements to the 'PACS Installation' project template.

Source: PACS Project Tracker -V4.xlsx (Intermedic sheet, WBS rows 9-68).
T/R classification per row provided by the user; a few rows split into
separate Requirement (customer-side) and Task (Intermedic-side) items.
Idempotent — safe to re-run, skips any title that already exists on
the template.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import create_app
from app.extensions import db
from app.models.project import ProjectTemplate, ProjectTemplateTask, ProjectTemplateRequirement
from app.models.user import User

TEMPLATE_NAME = "PACS Installation"

# (title, description) — description carries the original WBS reference for traceability
TASKS = [
    ("1.1 Receiving Hardware", None),
    ("3.5 PACS Installation", "Technical installation of Vue PACS (counterpart to requirement 2.4)"),
    ("3.6 Vue Motion Installation", "Technical installation of Vue Motion (counterpart to requirement 6.1)"),
    ("3.7 Vue Explorer Installation", "Technical installation of Vue Explorer (counterpart to requirement 6.1)"),
    ("4.1 Check Accessibility (Old/New Server)", None),
    ("4.2 3 Years Data Migration - PACS", None),
    ("4.3 5 Years Data Migration - PACS", None),
    ("4.4 All Remaining Data Migration - PACS", None),
    ("4.5 Backup Studies - Post Go-Live", None),
    ("5.2 Radiologist Template (Implementation)", "Counterpart to requirement 5.2 (Design)"),
    ("8.1 EIS Installation", None),
    ("8.2 EIS Modality Configuration", None),
    ("8.3 EIS Connectivity Test", None),
    ("9.1 Radiologist Training on PACS", None),
    ("9.2 Secretaries and Technicians Training", None),
    ("9.3 System Administrator Training - PACS", None),
]

# (title, description) — all default to req_type="provide"
REQUIREMENTS = [
    ("1.2 Hardware Assembly", None),
    ("1.2.1 Raid Configuration", None),
    ("1.2.2 Network Configuration", None),
    ("1.3 VPN Access", None),
    ("1.4 VM Preparation", None),
    ("1.4.1 VM Installation", None),
    ("1.4.2 Vdisks Configuration", None),
    ("1.4.3 Vnetwork Configuration", None),
    ("1.4.4 VMs Creation", None),
    ("1.5 Windows Server 2019", None),
    ("2.1 Transcription Licenses", None),
    ("2.2 Prerequisites", None),
    ("2.3 SSL", None),
    ("2.4 Vue PACS Installation", "Approval/scheduling checkpoint (see task 3.5 for the technical install)"),
    ("2.5 Admin Tools Testing", None),
    ("3.1 Users Permission/Creation", None),
    ("3.2 Modalities", None),
    ("3.3 Workflow Configuration", None),
    ("3.4 Testing", None),
    ("5.1 Master Template", None),
    ("5.2 Radiologist Template (Design)", "Counterpart to task 5.2 (Implementation)"),
    ("5.3 User Accessibility", None),
    ("5.5 CD-Direct Reinstallation", None),
    ("6.1 Vue Motion/Vue Explorer Installation", "Approval/scheduling checkpoint (see tasks 3.6/3.7 for the technical install)"),
    ("6.2 SSL", None),
    ("6.3 Configuration (Logo)", None),
    ("6.4 Testing", None),
    ("7.1 MyVue Installation", None),
    ("7.2 SSL", None),
    ("7.3 Configuration", None),
    ("7.4 Testing", None),
    ("10.1 CD-Direct Prerequisites", None),
    ("10.2 CD-Direct Installation", None),
    ("10.3 CD-Direct Configuration", None),
    ("10.4 CD-Direct Testing", None),
    ("10.5 CD-Direct Go Live", None),
    ("0.1 Customer Acceptance", None),
]


app = create_app()

with app.app_context():
    tmpl = ProjectTemplate.query.filter_by(name=TEMPLATE_NAME).first()
    if not tmpl:
        print(f"ERROR: No project template named '{TEMPLATE_NAME}' found. Aborting — not creating a new one.")
        sys.exit(1)

    print(f"Using template: {tmpl.name} (id={tmpl.id})\n")

    existing_task_titles = {t.title for t in tmpl.tasks}
    existing_req_titles = {r.title for r in tmpl.requirements}
    next_task_order = max([t.order for t in tmpl.tasks], default=-1) + 1
    next_req_order = max([r.order for r in tmpl.requirements], default=-1) + 1

    created_tasks = 0
    skipped_tasks = 0
    for title, desc in TASKS:
        if title in existing_task_titles:
            print(f"  SKIP (task exists): {title}")
            skipped_tasks += 1
            continue
        t = ProjectTemplateTask(
            template_id=tmpl.id,
            title=title,
            description=desc,
            default_priority="medium",
            order=next_task_order,
        )
        db.session.add(t)
        next_task_order += 1
        print(f"  ADD TASK: {title}")
        created_tasks += 1

    created_reqs = 0
    skipped_reqs = 0
    for title, desc in REQUIREMENTS:
        if title in existing_req_titles:
            print(f"  SKIP (requirement exists): {title}")
            skipped_reqs += 1
            continue
        r = ProjectTemplateRequirement(
            template_id=tmpl.id,
            title=title,
            description=desc,
            req_type="provide",
            order=next_req_order,
        )
        db.session.add(r)
        next_req_order += 1
        print(f"  ADD REQUIREMENT: {title}")
        created_reqs += 1

    db.session.commit()
    print(f"\nDone — tasks: {created_tasks} created, {skipped_tasks} skipped. "
          f"requirements: {created_reqs} created, {skipped_reqs} skipped.")
