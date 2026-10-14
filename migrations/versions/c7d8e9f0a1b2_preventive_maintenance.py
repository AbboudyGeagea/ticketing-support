"""preventive maintenance (PM): check catalog, checkups, results, readings, attachments

Revision ID: c7d8e9f0a1b2
Revises: b6c7d8e9f0a1
Create Date: 2026-10-14
"""
from alembic import op
import sqlalchemy as sa

revision = 'c7d8e9f0a1b2'
down_revision = 'b6c7d8e9f0a1'
branch_labels = None
depends_on = None

SERVER_PRODUCTS = ["VUE PACS", "VUE RIS", "CVIS"]
PACS_ONLY = ["VUE PACS"]

# (name, description, products, [(label, type, unit, direction, attention, alert)])
SEED_CHECKS = [
    (
        "Free storage",
        "Free disk space on the product's servers. Record the lowest volume; "
        "note the server and drive in the comment.",
        SERVER_PRODUCTS,
        [("Lowest free space", "percent", None, "below", 20, 10)],
    ),
    (
        "Services",
        "All application services are running.",
        SERVER_PRODUCTS,
        [],
    ),
    (
        "DB backup",
        "Last database backup completed successfully.",
        SERVER_PRODUCTS,
        [],
    ),
    (
        "Images backup",
        "Image archive backup / replication is up to date.",
        SERVER_PRODUCTS,
        [],
    ),
    (
        "Inforouter",
        "Failed commands, and commands IR has put back in the Scheduled state after failing.",
        PACS_ONLY,
        [
            ("Failed commands", "number", None, "above", None, None),
            ("Failed command types", "text", None, "above", None, None),
            ("Scheduled commands", "number", None, "above", None, None),
            ("Scheduled command types", "text", None, "above", None, None),
        ],
    ),
    (
        "R2I queues",
        "R2I queues are draining normally.",
        PACS_ONLY,
        [("Items in queue", "number", None, "above", None, None)],
    ),
    (
        "Immediate feedback queues",
        "Immediate feedback queues are draining normally.",
        PACS_ONLY,
        [("Items in queue", "number", None, "above", None, None)],
    ),
]


def upgrade():
    op.create_table(
        'pm_hospital_settings',
        sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), primary_key=True),
        sa.Column('owner_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
    )

    op.create_table(
        'pm_checks',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('description', sa.Text()),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime()),
    )

    op.create_table(
        'pm_check_products',
        sa.Column('check_id', sa.Integer(), sa.ForeignKey('pm_checks.id'), primary_key=True),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id'), primary_key=True),
    )

    op.create_table(
        'pm_check_fields',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('check_id', sa.Integer(), sa.ForeignKey('pm_checks.id'), nullable=False),
        sa.Column('label', sa.String(100), nullable=False),
        sa.Column('field_type', sa.String(20), nullable=False, server_default='number'),
        sa.Column('unit', sa.String(20)),
        sa.Column('direction', sa.String(10), nullable=False, server_default='above'),
        sa.Column('attention_threshold', sa.Float(), nullable=True),
        sa.Column('alert_threshold', sa.Float(), nullable=True),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
    )
    op.create_index('ix_pm_check_fields_check_id', 'pm_check_fields', ['check_id'])

    op.create_table(
        'pm_checkups',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=False),
        sa.Column('check_date', sa.Date(), nullable=False),
        sa.Column('performed_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='draft'),
        sa.Column('notes', sa.Text()),
        sa.Column('created_at', sa.DateTime()),
        sa.Column('updated_at', sa.DateTime()),
        sa.Column('submitted_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_pm_checkups_hospital_id', 'pm_checkups', ['hospital_id'])
    op.create_index('ix_pm_checkups_check_date', 'pm_checkups', ['check_date'])
    op.create_index('ix_pm_checkups_status', 'pm_checkups', ['status'])

    op.create_table(
        'pm_results',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('checkup_id', sa.Integer(), sa.ForeignKey('pm_checkups.id'), nullable=False),
        sa.Column('check_id', sa.Integer(), sa.ForeignKey('pm_checks.id'), nullable=False),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id'), nullable=False),
        sa.Column('check_name', sa.String(200), nullable=False),
        sa.Column('check_description', sa.Text()),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('status', sa.String(20), nullable=True),
        sa.Column('comment', sa.Text()),
        sa.Column('resolved_at', sa.DateTime(), nullable=True),
        sa.Column('resolved_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('resolution_note', sa.Text()),
        sa.Column('task_id', sa.Integer(), sa.ForeignKey('tasks.id'), nullable=True),
        sa.UniqueConstraint('checkup_id', 'check_id', 'product_id', name='uq_pm_result_check_product'),
    )
    op.create_index('ix_pm_results_checkup_id', 'pm_results', ['checkup_id'])
    op.create_index('ix_pm_results_check_id', 'pm_results', ['check_id'])
    op.create_index('ix_pm_results_product_id', 'pm_results', ['product_id'])
    op.create_index('ix_pm_results_status', 'pm_results', ['status'])
    op.create_index('ix_pm_results_task_id', 'pm_results', ['task_id'])

    op.create_table(
        'pm_readings',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('result_id', sa.Integer(), sa.ForeignKey('pm_results.id'), nullable=False),
        sa.Column('field_id', sa.Integer(), sa.ForeignKey('pm_check_fields.id'), nullable=True),
        sa.Column('label', sa.String(100), nullable=False),
        sa.Column('field_type', sa.String(20), nullable=False, server_default='number'),
        sa.Column('unit', sa.String(20)),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('value', sa.String(500)),
    )
    op.create_index('ix_pm_readings_result_id', 'pm_readings', ['result_id'])

    op.create_table(
        'pm_attachments',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('result_id', sa.Integer(), sa.ForeignKey('pm_results.id'), nullable=False),
        sa.Column('uploaded_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('filename', sa.String(200), nullable=False),
        sa.Column('original_name', sa.String(500), nullable=False),
        sa.Column('mimetype', sa.String(100)),
        sa.Column('size', sa.Integer()),
        sa.Column('created_at', sa.DateTime()),
    )
    op.create_index('ix_pm_attachments_result_id', 'pm_attachments', ['result_id'])

    _seed_checks()


def _seed_checks():
    conn = op.get_bind()
    for order, (name, description, product_names, fields) in enumerate(SEED_CHECKS, start=1):
        check_id = conn.execute(
            sa.text(
                "INSERT INTO pm_checks (name, description, sort_order, active, created_at) "
                "VALUES (:name, :description, :sort_order, TRUE, NOW()) RETURNING id"
            ),
            {"name": name, "description": description, "sort_order": order * 10},
        ).scalar()
        # Products are linked by name; a product renamed or missing on this
        # install is simply skipped and can be ticked later in Admin -> PM Checks.
        for pname in product_names:
            conn.execute(
                sa.text(
                    "INSERT INTO pm_check_products (check_id, product_id) "
                    "SELECT :check_id, id FROM products WHERE name = :pname"
                ),
                {"check_id": check_id, "pname": pname},
            )
        for forder, (label, ftype, unit, direction, attention, alert) in enumerate(fields, start=1):
            conn.execute(
                sa.text(
                    "INSERT INTO pm_check_fields (check_id, label, field_type, unit, direction, "
                    "attention_threshold, alert_threshold, sort_order) "
                    "VALUES (:check_id, :label, :ftype, :unit, :direction, :attention, :alert, :sort_order)"
                ),
                {
                    "check_id": check_id, "label": label, "ftype": ftype, "unit": unit,
                    "direction": direction, "attention": attention, "alert": alert,
                    "sort_order": forder,
                },
            )


def downgrade():
    op.drop_index('ix_pm_attachments_result_id', 'pm_attachments')
    op.drop_table('pm_attachments')
    op.drop_index('ix_pm_readings_result_id', 'pm_readings')
    op.drop_table('pm_readings')
    for ix in ('task_id', 'status', 'product_id', 'check_id', 'checkup_id'):
        op.drop_index(f'ix_pm_results_{ix}', 'pm_results')
    op.drop_table('pm_results')
    for ix in ('status', 'check_date', 'hospital_id'):
        op.drop_index(f'ix_pm_checkups_{ix}', 'pm_checkups')
    op.drop_table('pm_checkups')
    op.drop_index('ix_pm_check_fields_check_id', 'pm_check_fields')
    op.drop_table('pm_check_fields')
    op.drop_table('pm_check_products')
    op.drop_table('pm_checks')
    op.drop_table('pm_hospital_settings')
