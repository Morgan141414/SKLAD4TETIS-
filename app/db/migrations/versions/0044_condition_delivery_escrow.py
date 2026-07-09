"""Add condition, delivery, escrow, and gov-procurement fields.

Revision ID: 0044_condition_delivery_escrow
Revises: 0043_marketplace_cart
"""

from alembic import op
import sqlalchemy as sa

revision = "0044_condition_delivery_escrow"
down_revision = "0043_marketplace_cart"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── supplier_catalog_items: condition + delivery ──────────────────────────
    op.execute("""
        ALTER TABLE supplier_catalog_items
            ADD COLUMN IF NOT EXISTS condition TEXT NOT NULL DEFAULT 'new'
                CHECK (condition IN ('new', 'used', 'refurbished')),
            ADD COLUMN IF NOT EXISTS delivery_type TEXT NOT NULL DEFAULT 'buyer_arranges'
                CHECK (delivery_type IN ('pickup', 'courier', 'freight', 'postal', 'buyer_arranges')),
            ADD COLUMN IF NOT EXISTS delivery_price NUMERIC(18,2),
            ADD COLUMN IF NOT EXISTS delivery_included BOOLEAN NOT NULL DEFAULT false,
            ADD COLUMN IF NOT EXISTS delivery_regions TEXT
    """)

    # ── purchase_requests: condition accepted + gov-procurement ───────────────
    op.execute("""
        ALTER TABLE purchase_requests
            ADD COLUMN IF NOT EXISTS condition_accepted TEXT NOT NULL DEFAULT 'any'
                CHECK (condition_accepted IN ('new', 'used', 'any')),
            ADD COLUMN IF NOT EXISTS is_gov_procurement BOOLEAN NOT NULL DEFAULT false,
            ADD COLUMN IF NOT EXISTS gov_status TEXT DEFAULT 'demand'
                CHECK (gov_status IN ('demand', 'accepting', 'closed', 'feedback')),
            ADD COLUMN IF NOT EXISTS gov_feedback_text TEXT,
            ADD COLUMN IF NOT EXISTS gov_feedback_rating INTEGER
                CHECK (gov_feedback_rating BETWEEN 1 AND 5)
    """)

    # ── purchase_orders: escrow + delivery tracking ───────────────────────────
    op.execute("""
        ALTER TABLE purchase_orders
            ADD COLUMN IF NOT EXISTS escrow_amount NUMERIC(18,2),
            ADD COLUMN IF NOT EXISTS escrow_status TEXT NOT NULL DEFAULT 'none'
                CHECK (escrow_status IN ('none', 'reserved', 'held', 'released', 'refunded')),
            ADD COLUMN IF NOT EXISTS escrow_reserved_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS escrow_released_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS delivery_type TEXT
                CHECK (delivery_type IN ('pickup', 'courier', 'freight', 'postal', 'buyer_arranges')),
            ADD COLUMN IF NOT EXISTS delivery_price NUMERIC(18,2),
            ADD COLUMN IF NOT EXISTS delivery_included BOOLEAN NOT NULL DEFAULT false,
            ADD COLUMN IF NOT EXISTS delivery_status TEXT NOT NULL DEFAULT 'pending'
                CHECK (delivery_status IN ('pending', 'preparing', 'shipped', 'in_transit', 'delivered', 'returned')),
            ADD COLUMN IF NOT EXISTS delivery_tracking_number TEXT,
            ADD COLUMN IF NOT EXISTS delivery_shipped_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS delivery_delivered_at TIMESTAMPTZ
    """)

    # ── auctions: Dutch flag + escrow ─────────────────────────────────────────
    op.execute("""
        ALTER TABLE auctions
            ADD COLUMN IF NOT EXISTS is_dutch BOOLEAN NOT NULL DEFAULT true,
            ADD COLUMN IF NOT EXISTS escrow_status TEXT NOT NULL DEFAULT 'none'
                CHECK (escrow_status IN ('none', 'reserved', 'released', 'refunded')),
            ADD COLUMN IF NOT EXISTS escrow_reserved_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS escrow_released_at TIMESTAMPTZ
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE auctions
            DROP COLUMN IF EXISTS is_dutch,
            DROP COLUMN IF EXISTS escrow_status,
            DROP COLUMN IF EXISTS escrow_reserved_at,
            DROP COLUMN IF EXISTS escrow_released_at
    """)
    op.execute("""
        ALTER TABLE purchase_orders
            DROP COLUMN IF EXISTS escrow_amount,
            DROP COLUMN IF EXISTS escrow_status,
            DROP COLUMN IF EXISTS escrow_reserved_at,
            DROP COLUMN IF EXISTS escrow_released_at,
            DROP COLUMN IF EXISTS delivery_type,
            DROP COLUMN IF EXISTS delivery_price,
            DROP COLUMN IF EXISTS delivery_included,
            DROP COLUMN IF EXISTS delivery_status,
            DROP COLUMN IF EXISTS delivery_tracking_number,
            DROP COLUMN IF EXISTS delivery_shipped_at,
            DROP COLUMN IF EXISTS delivery_delivered_at
    """)
    op.execute("""
        ALTER TABLE purchase_requests
            DROP COLUMN IF EXISTS condition_accepted,
            DROP COLUMN IF EXISTS is_gov_procurement,
            DROP COLUMN IF EXISTS gov_status,
            DROP COLUMN IF EXISTS gov_feedback_text,
            DROP COLUMN IF EXISTS gov_feedback_rating
    """)
    op.execute("""
        ALTER TABLE supplier_catalog_items
            DROP COLUMN IF EXISTS condition,
            DROP COLUMN IF EXISTS delivery_type,
            DROP COLUMN IF EXISTS delivery_price,
            DROP COLUMN IF EXISTS delivery_included,
            DROP COLUMN IF EXISTS delivery_regions
    """)
