"""add product_id + rustdesk_id to hospital_credentials

Revision ID: ff66aa77bb88
Revises: ee55ff66aa77
Create Date: 2026-07-30
"""
from alembic import op
import sqlalchemy as sa

revision = 'ff66aa77bb88'
down_revision = 'ee55ff66aa77'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('hospital_credentials', sa.Column('product_id', sa.Integer(), nullable=True))
    op.add_column('hospital_credentials', sa.Column('rustdesk_id', sa.String(50), nullable=True))
    op.create_foreign_key(
        'fk_hospital_credentials_product_id', 'hospital_credentials', 'products',
        ['product_id'], ['id'],
    )
    op.create_index('ix_hospital_credentials_product_id', 'hospital_credentials', ['product_id'])


def downgrade():
    op.drop_index('ix_hospital_credentials_product_id', 'hospital_credentials')
    op.drop_constraint('fk_hospital_credentials_product_id', 'hospital_credentials', type_='foreignkey')
    op.drop_column('hospital_credentials', 'rustdesk_id')
    op.drop_column('hospital_credentials', 'product_id')
