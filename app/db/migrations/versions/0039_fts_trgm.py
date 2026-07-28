"""Full-text search: pg_trgm GIN index on catalog + product names

Revision ID: 0039_fts_trgm
Revises: 0038_purchase_order
"""
from alembic import op

revision = "0039_fts_trgm"
down_revision = "0038_purchase_order"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    # GIN trigram index for fast ILIKE / similarity search on catalog items
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_catalog_items_search_gin
        ON supplier_catalog_items
        USING GIN ((product_name || ' ' || COALESCE(sku,'') || ' ' || COALESCE(description,'') || ' ' || COALESCE(category,'')) gin_trgm_ops)
    """)
    # GIN trigram index on products table (warehouse products)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_products_search_gin
        ON products
        USING GIN ((name || ' ' || COALESCE(sku,'') || ' ' || COALESCE(description,'')) gin_trgm_ops)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_catalog_items_search_gin")
    op.execute("DROP INDEX IF EXISTS idx_products_search_gin")
