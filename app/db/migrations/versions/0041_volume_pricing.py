"""Volume/tiered pricing for catalog items

Revision ID: 0041_volume_pricing
Revises: 0040_category_taxonomy
"""
from alembic import op

revision = "0041_volume_pricing"
down_revision = "0040_category_taxonomy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS catalog_item_price_tiers (
            id              SERIAL PRIMARY KEY,
            catalog_item_id INTEGER NOT NULL REFERENCES supplier_catalog_items(id) ON DELETE CASCADE,
            min_quantity    NUMERIC(18,3) NOT NULL,
            unit_price      NUMERIC(18,2) NOT NULL,
            label           TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_price_tiers_item "
        "ON catalog_item_price_tiers(catalog_item_id, min_quantity)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS catalog_item_price_tiers")
