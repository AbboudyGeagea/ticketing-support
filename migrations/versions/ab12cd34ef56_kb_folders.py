"""KB folders with folder-level customer visibility

Revision ID: ab12cd34ef56
Revises: d9e0f1a2b3c4
Create Date: 2026-11-10

Existing articles stay unfiled (folder_id NULL) and keep their current customer
visibility; nothing changes for customers until an admin moves articles into folders.
"""
from alembic import op
import sqlalchemy as sa

revision = 'ab12cd34ef56'
down_revision = 'd9e0f1a2b3c4'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'kb_folders',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('is_customer_facing', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name', name='uq_kb_folders_name'),
    )
    op.add_column('kb_articles', sa.Column('folder_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_kb_articles_folder_id', 'kb_articles', 'kb_folders', ['folder_id'], ['id'])
    op.create_index('ix_kb_articles_folder_id', 'kb_articles', ['folder_id'])


def downgrade():
    # Articles leaving their folders keep what customers could see at that moment.
    op.execute(
        "UPDATE kb_articles SET is_published_customer = (kb_articles.is_published_agent AND f.is_customer_facing) "
        "FROM kb_folders f WHERE kb_articles.folder_id = f.id"
    )
    op.drop_index('ix_kb_articles_folder_id', 'kb_articles')
    op.drop_constraint('fk_kb_articles_folder_id', 'kb_articles', type_='foreignkey')
    op.drop_column('kb_articles', 'folder_id')
    op.drop_table('kb_folders')
