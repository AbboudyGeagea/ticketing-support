"""Seed 6 project templates with tasks, subtasks, and requirements

Revision ID: b2c3d4e5f6a1
Revises: a1b2c3d4e5f6
Create Date: 2026-05-25 00:01:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import table, column

revision = 'b2c3d4e5f6a1'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None

templates_t = table('project_templates',
    column('id', sa.Integer),
    column('name', sa.String),
    column('description', sa.Text),
    column('created_by', sa.Integer),
    column('created_at', sa.DateTime),
)
tasks_t = table('project_template_tasks',
    column('id', sa.Integer),
    column('template_id', sa.Integer),
    column('parent_id', sa.Integer),
    column('title', sa.String),
    column('description', sa.Text),
    column('default_priority', sa.String),
    column('order', sa.Integer),
)
reqs_t = table('project_template_requirements',
    column('id', sa.Integer),
    column('template_id', sa.Integer),
    column('title', sa.String),
    column('description', sa.Text),
    column('req_type', sa.String),
    column('order', sa.Integer),
)


def _first_admin_id(conn):
    row = conn.execute(
        sa.text("SELECT id FROM users WHERE role IN ('admin','agent') ORDER BY id LIMIT 1")
    ).fetchone()
    return row[0] if row else 1


def upgrade():
    conn = op.get_bind()
    admin_id = _first_admin_id(conn)

    # ── Template definitions ───────────────────────────────────────────────────
    # Each entry: (name, description, [(task_title, priority, [(subtask, priority)])], [(req_title, req_type, description)])

    TEMPLATES = [
        (
            "PACS Installation",
            "Full deployment of a VUE PACS system at a new site.",
            [
                ("Site Assessment", "medium", [
                    ("Network infrastructure review", "medium"),
                    ("Server room inspection", "medium"),
                    ("Existing imaging systems inventory", "low"),
                ]),
                ("Infrastructure & Network Setup", "high", [
                    ("Server hardware installation", "high"),
                    ("Network switch / VLAN configuration", "high"),
                    ("Storage system setup", "medium"),
                    ("Firewall rules and port openings", "high"),
                ]),
                ("PACS Software Installation", "high", [
                    ("Database server setup", "high"),
                    ("Application server installation", "high"),
                    ("Web viewer deployment", "medium"),
                ]),
                ("DICOM Configuration", "high", [
                    ("Modality worklist (MWL) setup", "high"),
                    ("DICOM router / gateway configuration", "high"),
                    ("Modality AE titles registration", "medium"),
                ]),
                ("User Account Setup", "medium", [
                    ("Create radiologist accounts", "medium"),
                    ("Create technologist accounts", "medium"),
                    ("Configure role-based permissions", "medium"),
                ]),
                ("Testing & Validation", "urgent", [
                    ("DICOM send / receive testing", "urgent"),
                    ("Viewer functionality testing", "high"),
                    ("Worklist end-to-end testing", "high"),
                    ("Performance / load testing", "medium"),
                ]),
                ("User Training", "medium", [
                    ("Radiologist training session", "medium"),
                    ("Technologist training session", "medium"),
                ]),
                ("Go-Live & Handover", "urgent", [
                    ("Day-1 on-site support", "urgent"),
                    ("Issue log review and closure", "high"),
                    ("Handover documentation delivery", "medium"),
                ]),
            ],
            [
                ("Provide network diagram", "provide", "Current network topology including VLANs, switches, and IP ranges."),
                ("Provide IP address allocation", "provide", "Dedicated IP block for PACS servers, workstations, and modalities."),
                ("Provide server room access", "provide", "Physical access credentials and escort arrangements."),
                ("List of modalities to connect", "provide", "Make, model, AE title, and IP for each modality (CT, MRI, US, etc.)."),
                ("Provide existing DICOM node list", "provide", "Any existing DICOM nodes that need to interoperate with the new PACS."),
                ("Approve server placement", "approve", "Sign off on server rack location and cable routing before installation."),
                ("Approve network configuration", "approve", "Review and approve final IP assignments and VLAN setup."),
                ("Sign off on user acceptance testing", "approve", "Confirm all test cases passed before go-live."),
                ("Approve go-live readiness", "approve", "Final customer sign-off authorising go-live."),
            ],
        ),
        (
            "RIS PACS Installation",
            "Integrated RIS + VUE PACS deployment including HL7 worklist bridge.",
            [
                ("Site Assessment", "medium", [
                    ("Network infrastructure review", "medium"),
                    ("Server room inspection", "medium"),
                    ("HIS / RIS interface requirements review", "high"),
                ]),
                ("Infrastructure & Network Setup", "high", [
                    ("Server hardware installation", "high"),
                    ("Network and VLAN configuration", "high"),
                    ("Storage setup", "medium"),
                    ("Firewall rules and port openings", "high"),
                ]),
                ("PACS Software Installation", "high", [
                    ("Database server setup", "high"),
                    ("Application server installation", "high"),
                    ("Web viewer deployment", "medium"),
                ]),
                ("RIS Module Configuration", "high", [
                    ("Patient scheduling module setup", "high"),
                    ("Reporting module configuration", "high"),
                    ("Billing codes and procedure mapping", "medium"),
                ]),
                ("HL7 Interface Setup", "urgent", [
                    ("HL7 ADT feed configuration", "urgent"),
                    ("Order (ORM) and result (ORU) message mapping", "urgent"),
                    ("HL7 interface engine testing", "high"),
                ]),
                ("DICOM Configuration", "high", [
                    ("MWL bridge to RIS", "urgent"),
                    ("Modality AE title registration", "medium"),
                    ("DICOM router setup", "high"),
                ]),
                ("User Account Setup", "medium", [
                    ("Radiologist and reporting accounts", "medium"),
                    ("Scheduling and front-desk accounts", "medium"),
                    ("Role-based permissions", "medium"),
                ]),
                ("Testing & Validation", "urgent", [
                    ("End-to-end order-to-report workflow test", "urgent"),
                    ("DICOM send / receive testing", "high"),
                    ("HL7 message integrity testing", "urgent"),
                ]),
                ("User Training", "medium", [
                    ("Radiologist training", "medium"),
                    ("Scheduling staff training", "medium"),
                    ("IT admin training", "medium"),
                ]),
                ("Go-Live & Handover", "urgent", [
                    ("Day-1 on-site support", "urgent"),
                    ("Issue log closure", "high"),
                    ("Handover documentation", "medium"),
                ]),
            ],
            [
                ("Provide network diagram", "provide", "Full network topology including all relevant servers and workstations."),
                ("Provide IP address allocation", "provide", "IP block for PACS/RIS servers, workstations, and modalities."),
                ("Provide HIS / HL7 interface specifications", "provide", "HL7 version, message types, and field mapping from the HIS team."),
                ("Provide patient demographic data sample", "provide", "De-identified sample HL7 ADT messages for interface testing."),
                ("List of modalities to connect", "provide", "Make, model, AE title, and IP for each modality."),
                ("Approve HL7 message mapping", "approve", "Confirm field mappings between HIS and RIS/PACS before go-live."),
                ("Approve network configuration", "approve", "Review and approve final IP assignments and VLAN configuration."),
                ("Sign off on end-to-end workflow test", "approve", "Confirm order → worklist → image → report workflow passes."),
                ("Approve go-live readiness", "approve", "Final customer sign-off authorising go-live."),
            ],
        ),
        (
            "Pyxis Installation",
            "Pyxis automated dispensing cabinet installation and configuration.",
            [
                ("Site Preparation", "high", [
                    ("Cabinet location walkthrough and approval", "high"),
                    ("Power outlet and UPS verification", "medium"),
                    ("Network point installation / patch", "high"),
                ]),
                ("Hardware Installation", "high", [
                    ("Cabinet delivery and physical assembly", "high"),
                    ("Touchscreen and biometric reader setup", "medium"),
                    ("Pocket and drawer hardware configuration", "medium"),
                ]),
                ("Server & Software Setup", "high", [
                    ("Pyxis ES server installation", "high"),
                    ("Client workstation configuration", "medium"),
                    ("Database setup and backup policy", "high"),
                ]),
                ("Formulary Configuration", "urgent", [
                    ("Drug database import", "urgent"),
                    ("Par level and reorder point setup", "high"),
                    ("Pocket / drawer assignment per drug", "high"),
                    ("Controlled substance configuration", "urgent"),
                ]),
                ("Interface Setup", "urgent", [
                    ("Pharmacy information system (PIS) interface", "urgent"),
                    ("ADT / patient census feed", "urgent"),
                    ("Charge capture interface", "high"),
                ]),
                ("User Training", "medium", [
                    ("Nurse training — dispensing and returns", "medium"),
                    ("Pharmacist training — loading and override", "medium"),
                    ("IT admin training", "medium"),
                ]),
                ("Go-Live & Handover", "urgent", [
                    ("Day-1 floor support", "urgent"),
                    ("Exception report review", "high"),
                    ("Handover documentation", "medium"),
                ]),
            ],
            [
                ("Provide floor plan with cabinet locations", "provide", "Annotated floor plan showing proposed cabinet placement in each unit."),
                ("Provide formulary / drug list", "provide", "Complete drug formulary with quantities, units, and controlled-substance flags."),
                ("Provide network specifications", "provide", "IP allocation and network access for cabinets and server."),
                ("Provide pharmacy system interface specs", "provide", "PIS vendor documentation for the HL7 / proprietary interface."),
                ("Provide ADT feed details", "provide", "ADT source system and message format for patient census integration."),
                ("Approve cabinet placement", "approve", "Physical sign-off on cabinet positions before delivery."),
                ("Approve formulary configuration", "approve", "Pharmacist review and sign-off on loaded formulary and par levels."),
                ("Sign off on interface testing", "approve", "Confirm PIS and ADT integrations pass end-to-end testing."),
                ("Approve go-live readiness", "approve", "Director of Pharmacy sign-off authorising go-live."),
            ],
        ),
        (
            "CVIS Installation",
            "Cardiovascular information system installation and cardiology device integration.",
            [
                ("Site Assessment", "medium", [
                    ("Cardiology workflow and department review", "medium"),
                    ("Existing ECG / cath lab system inventory", "high"),
                    ("HIS / RIS integration requirements", "high"),
                ]),
                ("Infrastructure Setup", "high", [
                    ("CVIS server installation", "high"),
                    ("Network and VLAN configuration", "high"),
                    ("Storage and archive setup", "medium"),
                ]),
                ("CVIS Application Configuration", "high", [
                    ("Department and unit setup", "high"),
                    ("Cardiology reporting templates", "high"),
                    ("User roles and permissions", "medium"),
                ]),
                ("Device Integration", "urgent", [
                    ("ECG device integration and testing", "urgent"),
                    ("Cath lab hemodynamic system integration", "urgent"),
                    ("Echo / stress system integration", "high"),
                    ("DICOM modality registration", "high"),
                ]),
                ("HIS / RIS Integration", "high", [
                    ("HL7 ADT and order feed", "high"),
                    ("Result / report export to HIS", "high"),
                ]),
                ("User Training", "medium", [
                    ("Cardiologist training — reporting and review", "medium"),
                    ("Cath lab technician training", "medium"),
                    ("IT admin training", "medium"),
                ]),
                ("Go-Live & Handover", "urgent", [
                    ("Day-1 on-site support", "urgent"),
                    ("Issue log closure", "high"),
                    ("Handover documentation", "medium"),
                ]),
            ],
            [
                ("Provide cardiology department workflow", "provide", "Current workflow documentation for ECG, cath lab, echo, and stress testing."),
                ("List of cardiology devices to integrate", "provide", "Make, model, and connectivity specs for each device (ECG, cath, echo)."),
                ("Provide HIS integration specifications", "provide", "HL7 specs from HIS vendor for ADT and order/result messages."),
                ("Provide network diagram", "provide", "Network topology including cardiology department and server room."),
                ("Approve CVIS configuration", "approve", "Cardiology department head sign-off on system configuration and templates."),
                ("Approve reporting templates", "approve", "Review and approve all cardiology report templates before go-live."),
                ("Sign off on device integration testing", "approve", "Confirm all cardiology devices pass integration testing."),
                ("Approve go-live readiness", "approve", "Chief of Cardiology sign-off authorising go-live."),
            ],
        ),
        (
            "EMR Installation",
            "Electronic medical records system installation, configuration, and data migration.",
            [
                ("Requirements Analysis", "high", [
                    ("Clinical workflow review by department", "high"),
                    ("User role and permission mapping", "medium"),
                    ("Custom form and template requirements", "medium"),
                ]),
                ("Infrastructure Setup", "high", [
                    ("Application server installation", "high"),
                    ("Database server setup", "high"),
                    ("Backup and disaster recovery setup", "high"),
                ]),
                ("EMR Application Configuration", "high", [
                    ("Department and ward setup", "high"),
                    ("Clinical forms and order sets", "high"),
                    ("User account creation and role assignment", "medium"),
                    ("ICD / CPT code library setup", "medium"),
                ]),
                ("Data Migration", "urgent", [
                    ("Patient demographic import", "urgent"),
                    ("Historical clinical data migration", "urgent"),
                    ("Data validation and reconciliation", "urgent"),
                ]),
                ("System Integrations", "high", [
                    ("Laboratory system interface (LIS)", "high"),
                    ("Pharmacy system interface", "high"),
                    ("Imaging / PACS integration", "high"),
                    ("Billing system integration", "medium"),
                ]),
                ("User Training", "medium", [
                    ("Physician training", "medium"),
                    ("Nursing staff training", "medium"),
                    ("Administrative staff training", "medium"),
                    ("IT super-user training", "high"),
                ]),
                ("Go-Live & Hypercare", "urgent", [
                    ("Parallel run with legacy system", "urgent"),
                    ("Day-1 to Day-3 on-site hypercare", "urgent"),
                    ("Issue triage and resolution", "urgent"),
                    ("Handover documentation", "medium"),
                ]),
            ],
            [
                ("Provide clinical workflow documentation", "provide", "Department-by-department workflow narratives and approval forms."),
                ("Provide patient data for migration", "provide", "Approved patient demographic export from current system in agreed format."),
                ("Provide laboratory interface specifications", "provide", "LIS vendor HL7 specs for order and result messages."),
                ("Provide pharmacy interface specifications", "provide", "Pharmacy system vendor specs for medication orders and dispense messages."),
                ("Provide billing system specifications", "provide", "Billing system integration requirements and charge capture workflow."),
                ("Approve clinical forms design", "approve", "Clinical leads sign-off on all custom forms and order sets before go-live."),
                ("Approve user role configuration", "approve", "IT and clinical heads confirm user roles and access permissions."),
                ("Sign off on data migration", "approve", "Formal sign-off confirming migrated data is complete and accurate."),
                ("Approve go-live readiness", "approve", "CMO / CIO sign-off authorising go-live cutover."),
            ],
        ),
        (
            "EMR-HIS Installation",
            "Combined EMR and Hospital Information System deployment with full billing and ADT integration.",
            [
                ("Requirements Analysis", "high", [
                    ("Clinical and administrative workflow review", "high"),
                    ("Billing and insurance workflow mapping", "high"),
                    ("User role and department mapping", "medium"),
                ]),
                ("Infrastructure Setup", "high", [
                    ("Application and database server installation", "high"),
                    ("HA / failover configuration", "high"),
                    ("Backup and DR setup", "high"),
                ]),
                ("EMR Configuration", "high", [
                    ("Department, ward, and bed setup", "high"),
                    ("Clinical forms and order sets", "high"),
                    ("ICD / CPT code library", "medium"),
                ]),
                ("HIS Configuration", "high", [
                    ("ADT (admission, discharge, transfer) setup", "urgent"),
                    ("Billing engine and fee schedule", "urgent"),
                    ("Insurance payer and plan setup", "high"),
                    ("Charge capture and revenue cycle setup", "high"),
                ]),
                ("Data Migration", "urgent", [
                    ("Patient demographic import", "urgent"),
                    ("Historical clinical record migration", "urgent"),
                    ("Financial / billing history migration", "urgent"),
                    ("Data validation and sign-off", "urgent"),
                ]),
                ("System Integrations", "high", [
                    ("LIS interface", "high"),
                    ("Pharmacy interface", "high"),
                    ("PACS / imaging integration", "high"),
                    ("Insurance eligibility verification", "high"),
                    ("National health authority reporting", "medium"),
                ]),
                ("User Training", "medium", [
                    ("Physician and clinical staff training", "medium"),
                    ("Nursing staff training", "medium"),
                    ("Billing and finance staff training", "high"),
                    ("Admissions and front-desk training", "medium"),
                    ("IT super-user training", "high"),
                ]),
                ("Go-Live & Hypercare", "urgent", [
                    ("Parallel run with legacy systems", "urgent"),
                    ("Day-1 to Day-5 on-site hypercare", "urgent"),
                    ("Billing cycle validation", "urgent"),
                    ("Issue triage and resolution", "urgent"),
                    ("Handover and project closure", "medium"),
                ]),
            ],
            [
                ("Provide clinical workflow documentation", "provide", "All department workflow narratives including clinical and administrative flows."),
                ("Provide patient data for migration", "provide", "Patient demographic and clinical history export from legacy system."),
                ("Provide billing and coding requirements", "provide", "Fee schedule, billing codes, and payer contract details."),
                ("Provide insurance payer list", "provide", "Complete list of insurance companies with contract details and eligibility rules."),
                ("Provide LIS interface specifications", "provide", "LIS HL7 specs for lab orders and results."),
                ("Provide pharmacy interface specifications", "provide", "Pharmacy system specs for medication management integration."),
                ("Provide national reporting requirements", "provide", "Ministry of Health reporting format and submission specs."),
                ("Approve clinical forms and order sets", "approve", "Clinical department heads sign-off on all forms before go-live."),
                ("Approve billing configuration", "approve", "Finance director and billing manager sign-off on fee schedule and payer setup."),
                ("Approve HIS–EMR data flow", "approve", "IT and clinical heads confirm ADT and clinical data flow between modules."),
                ("Sign off on data migration", "approve", "Formal sign-off on completeness and accuracy of all migrated data."),
                ("Approve go-live readiness", "approve", "CEO / CMO / CIO joint sign-off authorising go-live cutover."),
            ],
        ),
    ]

    # ── Insert templates ───────────────────────────────────────────────────────
    # Track IDs by querying last inserted id after each batch

    for tmpl_name, tmpl_desc, task_defs, req_defs in TEMPLATES:
        # Check if already seeded
        existing = conn.execute(
            sa.text("SELECT id FROM project_templates WHERE name = :n"),
            {"n": tmpl_name}
        ).fetchone()
        if existing:
            continue

        # Insert template
        conn.execute(templates_t.insert().values(
            name=tmpl_name,
            description=tmpl_desc,
            created_by=admin_id,
        ))
        tmpl_row = conn.execute(
            sa.text("SELECT id FROM project_templates WHERE name = :n ORDER BY id DESC LIMIT 1"),
            {"n": tmpl_name}
        ).fetchone()
        tmpl_id = tmpl_row[0]

        # Insert tasks and subtasks
        task_order = 0
        for task_title, task_priority, subtask_defs in task_defs:
            task_order += 1
            conn.execute(tasks_t.insert().values(
                template_id=tmpl_id,
                parent_id=None,
                title=task_title,
                description=None,
                default_priority=task_priority,
                order=task_order,
            ))
            parent_row = conn.execute(
                sa.text(
                    "SELECT id FROM project_template_tasks "
                    "WHERE template_id = :t AND title = :ti AND parent_id IS NULL "
                    "ORDER BY id DESC LIMIT 1"
                ),
                {"t": tmpl_id, "ti": task_title}
            ).fetchone()
            parent_id = parent_row[0]

            sub_order = 0
            for sub_title, sub_priority in subtask_defs:
                sub_order += 1
                conn.execute(tasks_t.insert().values(
                    template_id=tmpl_id,
                    parent_id=parent_id,
                    title=sub_title,
                    description=None,
                    default_priority=sub_priority,
                    order=sub_order,
                ))

        # Insert requirements
        req_order = 0
        for req_title, req_type, req_desc in req_defs:
            req_order += 1
            conn.execute(reqs_t.insert().values(
                template_id=tmpl_id,
                title=req_title,
                description=req_desc,
                req_type=req_type,
                order=req_order,
            ))


def downgrade():
    conn = op.get_bind()
    names = [
        "PACS Installation", "RIS PACS Installation", "Pyxis Installation",
        "CVIS Installation", "EMR Installation", "EMR-HIS Installation",
    ]
    for name in names:
        row = conn.execute(
            sa.text("SELECT id FROM project_templates WHERE name = :n"), {"n": name}
        ).fetchone()
        if row:
            conn.execute(
                sa.text("DELETE FROM project_template_requirements WHERE template_id = :id"),
                {"id": row[0]}
            )
            conn.execute(
                sa.text("DELETE FROM project_template_tasks WHERE template_id = :id"),
                {"id": row[0]}
            )
            conn.execute(
                sa.text("DELETE FROM project_templates WHERE id = :id"),
                {"id": row[0]}
            )
