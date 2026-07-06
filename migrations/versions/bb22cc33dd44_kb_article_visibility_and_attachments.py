"""split KB article publish flag per role, add KB attachments

Revision ID: bb22cc33dd44
Revises: aa11bb22cc33
Create Date: 2026-07-06
"""
from alembic import op
import sqlalchemy as sa

revision = 'bb22cc33dd44'
down_revision = 'aa11bb22cc33'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('kb_articles', sa.Column(
        'is_published_agent', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('kb_articles', sa.Column(
        'is_published_customer', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.execute(
        "UPDATE kb_articles SET is_published_agent = is_published, "
        "is_published_customer = is_published"
    )
    op.drop_column('kb_articles', 'is_published')
    op.alter_column('kb_articles', 'is_published_agent', server_default=None)
    op.alter_column('kb_articles', 'is_published_customer', server_default=None)

    op.create_table(
        'kb_article_attachments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('kb_article_id', sa.Integer(), sa.ForeignKey('kb_articles.id'), nullable=False),
        sa.Column('filename', sa.String(200), nullable=False),
        sa.Column('original_name', sa.String(500), nullable=False),
        sa.Column('mimetype', sa.String(100), nullable=True),
        sa.Column('size', sa.Integer(), nullable=True),
        sa.Column('uploaded_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_kb_article_attachments_kb_article_id', 'kb_article_attachments', ['kb_article_id'])


def downgrade():
    op.drop_index('ix_kb_article_attachments_kb_article_id', 'kb_article_attachments')
    op.drop_table('kb_article_attachments')

    op.add_column('kb_articles', sa.Column(
        'is_published', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.execute("UPDATE kb_articles SET is_published = is_published_customer")
    op.drop_column('kb_articles', 'is_published_agent')
    op.drop_column('kb_articles', 'is_published_customer')
    op.alter_column('kb_articles', 'is_published', server_default=None)
