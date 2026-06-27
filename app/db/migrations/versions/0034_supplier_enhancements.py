"""supplier portal enhancements — review replies, catalog valid_until, supplier bank_details
Revision ID: 0034_supplier_enhancements
Revises: 0033_marketplace_inquiries
"""
from alembic import op

revision = "0034_supplier_enhancements"
down_revision = "0033_marketplace_inquiries"


def upgrade() -> None:
    # Supplier can reply to approved reviews
    op.execute("""
        ALTER TABLE supplier_reviews
            ADD COLUMN IF NOT EXISTS supplier_reply TEXT,
            ADD COLUMN IF NOT EXISTS replied_at TIMESTAMPTZ
    """)
    # Catalog item price expiry
    op.execute("""
        ALTER TABLE supplier_catalog_items
            ADD COLUMN IF NOT EXISTS valid_until DATE
    """)
    # Supplier bank/payment details (free-text for flexibility)
    op.execute("""
        ALTER TABLE suppliers
            ADD COLUMN IF NOT EXISTS bank_details TEXT,
            ADD COLUMN IF NOT EXISTS website TEXT,
            ADD COLUMN IF NOT EXISTS inn TEXT
    """)
    # Index for valid_until lookups (auto-hide expired items)
    op.execute("CREATE INDEX IF NOT EXISTS idx_supplier_catalog_valid_until ON supplier_catalog_items(valid_until) WHERE valid_until IS NOT NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE supplier_reviews DROP COLUMN IF EXISTS supplier_reply, DROP COLUMN IF EXISTS replied_at")
    op.execute("ALTER TABLE supplier_catalog_items DROP COLUMN IF EXISTS valid_until")
    op.execute("ALTER TABLE suppliers DROP COLUMN IF EXISTS bank_details, DROP COLUMN IF EXISTS website, DROP COLUMN IF EXISTS inn")
