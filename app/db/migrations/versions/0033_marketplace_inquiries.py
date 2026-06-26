"""marketplace inquiries — buyer-to-supplier contact requests

Revision ID: 0033_marketplace_inquiries
Revises: 0032_supplier_catalog
"""
from alembic import op

revision = "0033_marketplace_inquiries"
down_revision = "0032_supplier_catalog"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS marketplace_inquiries (
            id BIGSERIAL PRIMARY KEY,
            catalog_item_id BIGINT NOT NULL REFERENCES supplier_catalog_items(id) ON DELETE CASCADE,
            supplier_id BIGINT NOT NULL REFERENCES suppliers(id),
            warehouse_id BIGINT REFERENCES warehouses(id),
            actor_id TEXT NOT NULL,
            quantity NUMERIC(18,3) NOT NULL DEFAULT 1,
            unit_price NUMERIC(18,2),
            notes TEXT,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','responded','ordered','closed')),
            supplier_response TEXT,
            responded_at TIMESTAMPTZ,
            purchase_request_id BIGINT REFERENCES purchase_requests(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_marketplace_inquiries_supplier ON marketplace_inquiries(supplier_id, status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_marketplace_inquiries_actor ON marketplace_inquiries(actor_id, created_at DESC)")

def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS marketplace_inquiries")
