"""notification_outbox_events table for reliable outbound notifications (email, webhook)

Revision ID: 0061_outbox_events
Revises: 0060_marketplace_moderator_role
Create Date: 2026-08-14
"""
from alembic import op

revision = "0061_outbox_events"
down_revision = "0060_marketplace_moderator_role"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS notification_outbox_events (
            id             BIGSERIAL PRIMARY KEY,
            event_type     TEXT NOT NULL,
            payload        TEXT NOT NULL,
            status         TEXT NOT NULL DEFAULT 'pending',
            attempts       INTEGER NOT NULL DEFAULT 0,
            last_error     TEXT,
            next_attempt_at TIMESTAMPTZ,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            delivered_at   TIMESTAMPTZ
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_notification_outbox_events_pending
        ON notification_outbox_events (status, next_attempt_at, id)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_notification_outbox_events_pending")
    op.execute("DROP TABLE IF EXISTS notification_outbox_events")