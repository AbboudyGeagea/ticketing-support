"""departments table + hospital M2M + user department/job_title

Revision ID: a5b6c7d8e9f0
Revises: ff66aa77bb88
Create Date: 2026-08-25
"""
from alembic import op
import sqlalchemy as sa

revision = 'a5b6c7d8e9f0'
down_revision = 'ff66aa77bb88'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('departments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table('hospital_departments',
        sa.Column('hospital_id', sa.Integer(), nullable=False),
        sa.Column('department_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['hospital_id'], ['hospitals.id'], ),
        sa.ForeignKeyConstraint(['department_id'], ['departments.id'], ),
        sa.PrimaryKeyConstraint('hospital_id', 'department_id'),
    )
    op.add_column('users', sa.Column('department_id', sa.Integer(), nullable=True))
    op.add_column('users', sa.Column('job_title', sa.String(length=150), nullable=True))
    op.create_foreign_key(
        'fk_users_department_id', 'users', 'departments',
        ['department_id'], ['id'],
    )
    op.create_index('ix_users_department_id', 'users', ['department_id'])


def downgrade():
    op.drop_index('ix_users_department_id', 'users')
    op.drop_constraint('fk_users_department_id', 'users', type_='foreignkey')
    op.drop_column('users', 'job_title')
    op.drop_column('users', 'department_id')
    op.drop_table('hospital_departments')
    op.drop_table('departments')
