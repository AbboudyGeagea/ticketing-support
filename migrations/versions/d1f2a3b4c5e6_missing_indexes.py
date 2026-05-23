"""Add missing indexes on high-traffic columns

Revision ID: d1f2a3b4c5e6
Revises: c9d3e5f2b781
Create Date: 2026-05-22 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'd1f2a3b4c5e6'
down_revision = 'c9d3e5f2b781'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('tickets', schema=None) as batch_op:
        batch_op.create_index('ix_tickets_status', ['status'])
        batch_op.create_index('ix_tickets_assigned_to', ['assigned_to'])
        batch_op.create_index('ix_tickets_hospital_id', ['hospital_id'])
        batch_op.create_index('ix_tickets_updated_at', ['updated_at'])
        batch_op.create_index('ix_tickets_email_thread_id', ['email_thread_id'])

    with op.batch_alter_table('ticket_messages', schema=None) as batch_op:
        batch_op.create_index('ix_ticket_messages_ticket_id', ['ticket_id'])
        batch_op.create_index('ix_ticket_messages_sender_id', ['sender_id'])

    with op.batch_alter_table('ticket_history', schema=None) as batch_op:
        batch_op.create_index('ix_ticket_history_ticket_id', ['ticket_id'])

    with op.batch_alter_table('ticket_attachments', schema=None) as batch_op:
        batch_op.create_index('ix_ticket_attachments_ticket_id', ['ticket_id'])
        batch_op.create_index('ix_ticket_attachments_message_id', ['message_id'])

    with op.batch_alter_table('tasks', schema=None) as batch_op:
        batch_op.create_index('ix_tasks_assigned_to', ['assigned_to'])
        batch_op.create_index('ix_tasks_status', ['status'])
        batch_op.create_index('ix_tasks_deadline', ['deadline'])
        batch_op.create_index('ix_tasks_ticket_id', ['ticket_id'])


def downgrade():
    with op.batch_alter_table('tasks', schema=None) as batch_op:
        batch_op.drop_index('ix_tasks_ticket_id')
        batch_op.drop_index('ix_tasks_deadline')
        batch_op.drop_index('ix_tasks_status')
        batch_op.drop_index('ix_tasks_assigned_to')

    with op.batch_alter_table('ticket_attachments', schema=None) as batch_op:
        batch_op.drop_index('ix_ticket_attachments_message_id')
        batch_op.drop_index('ix_ticket_attachments_ticket_id')

    with op.batch_alter_table('ticket_history', schema=None) as batch_op:
        batch_op.drop_index('ix_ticket_history_ticket_id')

    with op.batch_alter_table('ticket_messages', schema=None) as batch_op:
        batch_op.drop_index('ix_ticket_messages_sender_id')
        batch_op.drop_index('ix_ticket_messages_ticket_id')

    with op.batch_alter_table('tickets', schema=None) as batch_op:
        batch_op.drop_index('ix_tickets_email_thread_id')
        batch_op.drop_index('ix_tickets_updated_at')
        batch_op.drop_index('ix_tickets_hospital_id')
        batch_op.drop_index('ix_tickets_assigned_to')
        batch_op.drop_index('ix_tickets_status')
