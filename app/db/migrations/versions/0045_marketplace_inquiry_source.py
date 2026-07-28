"""Track marketplace inquiry source channel.

Revision ID: 0045_marketplace_inquiry_source
Revises: 0044_condition_delivery_escrow
"""

from alembic import op

revision = "0045_marketplace_inquiry_source"
down_revision = "0044_condition_delivery_escrow"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE marketplace_inquiries
            ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'marqet'
                CHECK (source IN ('marqet', 'qpartner', 'api'))
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_marketplace_inquiries_source "
        "ON marketplace_inquiries(source, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_marketplace_inquiries_source")
    op.execute("ALTER TABLE marketplace_inquiries DROP COLUMN IF EXISTS source")
