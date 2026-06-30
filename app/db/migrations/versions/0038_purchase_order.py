"""Purchase Order number and print form support

Revision ID: 0038_purchase_order
Revises: 0037_supplier_verification
"""
from alembic import op

revision = "0038_purchase_order"
down_revision = "0037_supplier_verification"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS purchase_orders (
            id           SERIAL PRIMARY KEY,
            po_number    TEXT NOT NULL UNIQUE,
            inquiry_id   INTEGER NOT NULL REFERENCES marketplace_inquiries(id) ON DELETE CASCADE,
            buyer_name   TEXT,
            buyer_bin    TEXT,
            buyer_address TEXT,
            buyer_contact TEXT,
            delivery_address TEXT,
            payment_terms TEXT,
            notes        TEXT,
            status       TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','sent','accepted','completed','cancelled')),
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            sent_at      TIMESTAMPTZ,
            accepted_at  TIMESTAMPTZ
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_purchase_orders_inquiry "
        "ON purchase_orders(inquiry_id)"
    )
    # Sequence for PO number
    op.execute("CREATE SEQUENCE IF NOT EXISTS purchase_order_seq START 1000")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS purchase_orders")
    op.execute("DROP SEQUENCE IF EXISTS purchase_order_seq")
