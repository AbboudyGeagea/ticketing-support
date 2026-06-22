"""add hospital_id and product_id to tasks

Revision ID: e4f5a6b7c8d9
Revises: d7e8f9a0b1c2
Create Date: 2026-06-22
"""
from alembic import op
import sqlalchemy as sa

revision = 'e4f5a6b7c8d9'
down_revision = 'd7e8f9a0b1c2'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('tasks', sa.Column('hospital_id', sa.Integer(), nullable=True))
    op.add_column('tasks', sa.Column('product_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_tasks_hospital_id', 'tasks', 'hospitals', ['hospital_id'], ['id'])
    op.create_foreign_key('fk_tasks_product_id', 'tasks', 'products', ['product_id'], ['id'])


def downgrade():
    op.drop_constraint('fk_tasks_product_id', 'tasks', type_='foreignkey')
    op.drop_constraint('fk_tasks_hospital_id', 'tasks', type_='foreignkey')
    op.drop_column('tasks', 'product_id')
    op.drop_column('tasks', 'hospital_id')
