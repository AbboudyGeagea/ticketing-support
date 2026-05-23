"""Add hospital_credentials table

Revision ID: a1b2c3d4e5f6
Revises: f1a2b3c4d5e6
Create Date: 2026-05-23 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'a1b2c3d4e5f6'
down_revision = 'f1a2b3c4d5e6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'hospital_credentials',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=False),
        sa.Column('category', sa.String(30), nullable=False, server_default='other'),
        sa.Column('label', sa.String(200), nullable=False),
        sa.Column('username', sa.String(200), nullable=True),
        sa.Column('password_enc', sa.Text(), nullable=True),
        sa.Column('host_enc', sa.Text(), nullable=True),
        sa.Column('role_enc', sa.Text(), nullable=True),
        sa.Column('url', sa.String(500), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_hospital_credentials_hospital_id', 'hospital_credentials', ['hospital_id'])


def downgrade():
    op.drop_index('ix_hospital_credentials_hospital_id', 'hospital_credentials')
    op.drop_table('hospital_credentials')
