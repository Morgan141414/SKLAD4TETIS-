"""auctions table

Revision ID: 0019_auctions
Revises: 0018_supplier_geo
"""
from alembic import op

revision = "0019_auctions"
down_revision = "0018_supplier_geo"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS auctions (
          id BIGSERIAL PRIMARY KEY,
          title TEXT NOT NULL,
          description TEXT,
          product_id BIGINT NOT NULL REFERENCES products(id),
          warehouse_id BIGINT NOT NULL,
          quantity NUMERIC(18,3) NOT NULL,
          unit TEXT NOT NULL DEFAULT 'шт',
          start_price NUMERIC(18,2) NOT NULL,
          current_price NUMERIC(18,2) NOT NULL,
          min_price NUMERIC(18,2) NOT NULL,
          step_amount NUMERIC(18,2) NOT NULL DEFAULT 100,
          step_interval_seconds INTEGER NOT NULL DEFAULT 300,
          status TEXT NOT NULL DEFAULT 'draft',
          winner_supplier_id BIGINT REFERENCES suppliers(id),
          winner_bid NUMERIC(18,2),
          starts_at TIMESTAMPTZ,
          ends_at TIMESTAMPTZ,
          next_step_at TIMESTAMPTZ,
          created_by TEXT NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS auction_bids (
          id BIGSERIAL PRIMARY KEY,
          auction_id BIGINT NOT NULL REFERENCES auctions(id),
          supplier_id BIGINT NOT NULL REFERENCES suppliers(id),
          bid_amount NUMERIC(18,2) NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_auction_bids_auction ON auction_bids(auction_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS auction_bids")
    op.execute("DROP TABLE IF EXISTS auctions")
