"""Expand RIS PACS Installation template with requirements from RIS_PACS_Requirements.docx

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-05-25 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'f4a5b6c7d8e9'
down_revision = 'e3f4a5b6c7d8'
branch_labels = None
depends_on = None

TEMPLATE_NAME = "RIS PACS Installation"

# Requirements derived from RIS_PACS_Requirements.docx.
# Appended to the 9 generic requirements already in the seed migration.
# Format: (title, req_type, description)
NEW_REQUIREMENTS = [
    # ── System / Infrastructure ────────────────────────────────────────────────
    (
        "Provide FQDN and SSL certificate",
        "provide",
        "Fully Qualified Domain Name (FQDN) for the PACS/RIS portal and a valid SSL "
        "certificate (or CSR for Intermedic to sign). Required for secure HTTPS access.",
    ),
    (
        "Provide public IP and NAT details",
        "provide",
        "One dedicated public IP for external PACS/RIS access. Specify whether NAT "
        "translation is in place and the internal target IP/port for each service.",
    ),
    (
        "Provide SMTP configuration",
        "provide",
        "SMTP server address, port (25/465/587), authentication credentials, sender "
        "address, and TLS/SSL mode for system email notifications and report delivery.",
    ),
    (
        "Confirm PACS licensing availability",
        "provide",
        "Confirm all required PACS module licenses (concurrent readers, modality "
        "connections, web viewer, speech, patient portal) are procured before install begins.",
    ),
    (
        "Provide storage volume estimate",
        "provide",
        "Estimated annual study volume per modality (number of studies and average "
        "DICOM study size in GB) used to size the storage system correctly.",
    ),
    # ── Configuration & Setup ─────────────────────────────────────────────────
    (
        "Provide hospital branding logo",
        "provide",
        "Hospital logo in high-resolution PNG or SVG format for PACS viewer, RIS portal, "
        "MyVue patient portal, and printed report header branding.",
    ),
    (
        "Provide user list with roles (Excel)",
        "provide",
        "Excel file with one row per user: full name, username, user code, and role "
        "(radiologist, technologist, registrar, scheduling, IT admin). "
        "Used to create all RIS/PACS accounts before go-live.",
    ),
    (
        "Provide radiology procedure codes (Excel)",
        "provide",
        "Excel file listing SPS codes, PPS codes, RP codes, procedure descriptions, "
        "exam durations (minutes), and the modality each procedure maps to. "
        "Used to configure the RIS procedure dictionary.",
    ),
    (
        "Provide SPS-to-modality mapping",
        "provide",
        "Mapping of each Scheduled Procedure Step (SPS) code to its target modality "
        "AE title. Needed to route worklist items to the correct modality automatically.",
    ),
    (
        "Provide referring physician list (Excel)",
        "provide",
        "Excel file with first name, last name, and referring physician code for every "
        "physician who will place radiology orders. Used for HIS-RIS order routing and reporting.",
    ),
    (
        "Provide list of ordering departments",
        "provide",
        "All hospital departments or units authorised to place radiology orders, "
        "including department names and codes as they appear in the HIS.",
    ),
    (
        "Provide modality AE Title, IP, and port list (Excel)",
        "provide",
        "Excel file with DICOM AE Title, IP address, and DICOM port for each modality "
        "(CT, MRI, US, CR, DR, mammography, etc.). Distinct from the general modality list "
        "— must include exact DICOM parameters for AE registration and MWL configuration.",
    ),
    (
        "Provide availability and opening hours template (Excel)",
        "provide",
        "Excel schedule of each modality's operating hours per day of the week. "
        "Used to configure worklist availability slots and scheduling rules in RIS.",
    ),
    (
        "Provide HIS-RIS integration workflow documentation",
        "provide",
        "Detailed description of how patient orders flow from HIS to RIS (ORM messages) "
        "and how results/reports flow back (ORU messages), including trigger events and "
        "responsible teams on both sides.",
    ),
    (
        "Provide patient preparation letters and questionnaires",
        "provide",
        "Exam preparation instruction documents and intake questionnaire forms (e.g., "
        "MRI safety, contrast allergy) to be loaded into the patient portal and printed "
        "at scheduling.",
    ),
    (
        "Provide radiology organisation structure",
        "provide",
        "Main radiology department name and all subdepartments or reading rooms "
        "(e.g., General Radiology, Interventional, Neuroradiology) to be created in RIS.",
    ),
    # ── Clarification questions ────────────────────────────────────────────────
    (
        "Confirm Speech / voice recognition requirement",
        "question",
        "Is the Speech VM and voice recognition integration required? If yes, specify "
        "the software (e.g., Nuance PowerScribe, Dragon Medical) and whether it will "
        "be cloud-based or on-premise.",
    ),
    (
        "Confirm Patient Portal (MyVue) requirement",
        "question",
        "Will patients access the MyVue patient portal to view their reports and images? "
        "If yes, confirm patient authentication method (email OTP / password / national ID) "
        "and whether a custom domain/subdomain is required.",
    ),
    (
        "Confirm EIS integration requirement",
        "question",
        "Is Enterprise Imaging System (EIS) integration required? If yes, provide the "
        "EIS vendor, version, and connection/API specifications.",
    ),
    # ── Approvals ─────────────────────────────────────────────────────────────
    (
        "Approve report templates",
        "approve",
        "Radiologist lead reviews and signs off on all three report templates — "
        "Master Template (structured report), Radiologist Template (free-text layout), "
        "and MyVue Template (patient-facing summary) — before go-live.",
    ),
    (
        "Approve SPS-to-modality mapping",
        "approve",
        "Radiology IT and department head confirm that each SPS procedure code is "
        "routed to the correct modality AE title before MWL goes live.",
    ),
    (
        "Approve analytics and management reports configuration",
        "approve",
        "Radiology department head confirms the KPIs and management report definitions "
        "(turnaround time, volume by modality, radiologist productivity) before go-live.",
    ),
    (
        "Approve SRSA security configuration",
        "approve",
        "IT security team confirms device-to-site or site-to-site SRSA (Secure Remote "
        "Support Access) setup is correctly configured and tested before system handover.",
    ),
]


def upgrade():
    conn = op.get_bind()

    row = conn.execute(
        sa.text("SELECT id FROM project_templates WHERE name = :n"),
        {"n": TEMPLATE_NAME}
    ).fetchone()
    if not row:
        return  # template not yet seeded — nothing to expand

    tmpl_id = row[0]

    max_order_row = conn.execute(
        sa.text(
            'SELECT COALESCE(MAX("order"), 0) FROM project_template_requirements '
            "WHERE template_id = :tid"
        ),
        {"tid": tmpl_id}
    ).fetchone()
    next_order = (max_order_row[0] if max_order_row else 0) + 1

    reqs_t = sa.table(
        "project_template_requirements",
        sa.column("template_id", sa.Integer),
        sa.column("title", sa.String),
        sa.column("description", sa.Text),
        sa.column("req_type", sa.String),
        sa.column("order", sa.Integer),
    )

    for title, req_type, description in NEW_REQUIREMENTS:
        existing = conn.execute(
            sa.text(
                "SELECT id FROM project_template_requirements "
                "WHERE template_id = :tid AND title = :t"
            ),
            {"tid": tmpl_id, "t": title}
        ).fetchone()
        if existing:
            next_order += 1
            continue
        conn.execute(reqs_t.insert().values(
            template_id=tmpl_id,
            title=title,
            description=description,
            req_type=req_type,
            order=next_order,
        ))
        next_order += 1


def downgrade():
    conn = op.get_bind()

    row = conn.execute(
        sa.text("SELECT id FROM project_templates WHERE name = :n"),
        {"n": TEMPLATE_NAME}
    ).fetchone()
    if not row:
        return

    tmpl_id = row[0]
    for title, _, _ in NEW_REQUIREMENTS:
        conn.execute(
            sa.text(
                "DELETE FROM project_template_requirements "
                "WHERE template_id = :tid AND title = :t"
            ),
            {"tid": tmpl_id, "t": title}
        )
