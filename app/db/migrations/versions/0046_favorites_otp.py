"""Add marketplace_favorites and marketplace_phone_otps tables

Revision ID: 0046_favorites_otp
Revises: 0045_support_tickets
"""
from alembic import op

revision = "0046_favorites_otp"
down_revision = "0045_support_tickets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS marketplace_favorites (
            id              BIGSERIAL PRIMARY KEY,
            actor_id        TEXT NOT NULL,
            catalog_item_id BIGINT NOT NULL REFERENCES supplier_catalog_items(id) ON DELETE CASCADE,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (actor_id, catalog_item_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_mf_actor ON marketplace_favorites(actor_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_mf_item ON marketplace_favorites(catalog_item_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS marketplace_phone_otps (
            id          BIGSERIAL PRIMARY KEY,
            phone       TEXT NOT NULL,
            otp         TEXT NOT NULL,
            actor_id    TEXT,
            expires_at  TIMESTAMPTZ NOT NULL,
            used        BOOLEAN NOT NULL DEFAULT FALSE,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_otp_phone ON marketplace_phone_otps(phone, expires_at)")

    # Add view_count to supplier_catalog_items if missing (defensive)
    op.execute("""
        ALTER TABLE supplier_catalog_items
        ADD COLUMN IF NOT EXISTS impression_count BIGINT NOT NULL DEFAULT 0
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS marketplace_favorites")
    op.execute("DROP TABLE IF EXISTS marketplace_phone_otps")
    op.execute("ALTER TABLE supplier_catalog_items DROP COLUMN IF EXISTS impression_count")
