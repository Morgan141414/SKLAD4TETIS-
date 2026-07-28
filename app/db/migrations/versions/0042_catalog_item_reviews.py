"""Per-product reviews/ratings for marketplace catalog items

Revision ID: 0042_catalog_item_reviews
Revises: 0041_volume_pricing
"""
from alembic import op

revision = "0042_catalog_item_reviews"
down_revision = "0041_volume_pricing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS catalog_item_reviews (
            id              BIGSERIAL PRIMARY KEY,
            catalog_item_id BIGINT NOT NULL REFERENCES supplier_catalog_items(id) ON DELETE CASCADE,
            rating          INTEGER NOT NULL,
            comment         TEXT,
            reviewer_id     TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'approved',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_catalog_item_reviews_item ON catalog_item_reviews(catalog_item_id)")
    op.execute(
        "ALTER TABLE catalog_item_reviews ADD CONSTRAINT catalog_item_reviews_rating_range "
        "CHECK (rating >= 1 AND rating <= 5)"
    )
    op.execute(
        "ALTER TABLE catalog_item_reviews ADD CONSTRAINT catalog_item_reviews_status_check "
        "CHECK (status IN ('pending','approved','rejected'))"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS catalog_item_reviews")
