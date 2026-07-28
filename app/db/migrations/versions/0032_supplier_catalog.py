"""supplier catalog — per-supplier price list items for marketplace

Revision ID: 0032_supplier_catalog
Revises: 0031_sklad_users_supplier_id
"""
from alembic import op

revision = "0032_supplier_catalog"
down_revision = "0031_sklad_users_supplier_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS supplier_catalog_items (
            id          BIGSERIAL PRIMARY KEY,
            supplier_id BIGINT NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
            product_id  BIGINT REFERENCES products(id) ON DELETE SET NULL,
            product_name TEXT NOT NULL,
            sku         TEXT,
            unit        TEXT NOT NULL DEFAULT 'шт',
            unit_price  NUMERIC(18,2) NOT NULL,
            min_order_qty NUMERIC(18,3) NOT NULL DEFAULT 1,
            stock_qty   NUMERIC(18,3),
            delivery_days INT,
            category    TEXT,
            description TEXT,
            is_active   BOOLEAN NOT NULL DEFAULT TRUE,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_supplier_catalog_supplier ON supplier_catalog_items(supplier_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_supplier_catalog_active ON supplier_catalog_items(is_active, supplier_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_supplier_catalog_product ON supplier_catalog_items(product_id) WHERE product_id IS NOT NULL")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS supplier_catalog_items")
