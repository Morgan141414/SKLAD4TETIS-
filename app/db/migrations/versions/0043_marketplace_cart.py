"""Persistent marketplace cart, like Kaspi/Amazon checkout flow

Revision ID: 0043_marketplace_cart
Revises: 0042_catalog_item_reviews
"""
from alembic import op

revision = "0043_marketplace_cart"
down_revision = "0042_catalog_item_reviews"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS marketplace_cart_items (
            id              BIGSERIAL PRIMARY KEY,
            actor_id        TEXT NOT NULL,
            catalog_item_id BIGINT NOT NULL REFERENCES supplier_catalog_items(id) ON DELETE CASCADE,
            quantity        NUMERIC(18,3) NOT NULL DEFAULT 1,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (actor_id, catalog_item_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_cart_items_actor ON marketplace_cart_items(actor_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS marketplace_cart_items")
