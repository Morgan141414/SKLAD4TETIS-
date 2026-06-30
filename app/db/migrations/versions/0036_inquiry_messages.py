"""inquiry_messages for multi-turn chat on marketplace inquiries

Revision ID: 0036_inquiry_messages
Revises: 0035_catalog_image_and_user_email
"""
from alembic import op

revision = "0036_inquiry_messages"
down_revision = "0035_catalog_image_and_user_email"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS inquiry_messages (
            id          SERIAL PRIMARY KEY,
            inquiry_id  INTEGER NOT NULL REFERENCES marketplace_inquiries(id) ON DELETE CASCADE,
            actor_id    TEXT NOT NULL,
            role        TEXT NOT NULL CHECK (role IN ('buyer', 'supplier', 'system')),
            body        TEXT NOT NULL,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_inquiry_messages_inquiry_id "
        "ON inquiry_messages(inquiry_id, created_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS inquiry_messages")
