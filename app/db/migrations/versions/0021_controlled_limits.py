"""controlled substance limits per warehouse

Revision ID: 0021_controlled_limits
Revises: 0020_label_reprint_supplier_rating
Create Date: 2026-06-16
"""

from __future__ import annotations

from alembic import op


revision = "0021_controlled_limits"
down_revision = "0020_label_reprint_supplier_rating"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Per-warehouse controlled substance storage limit
    op.execute(
        "ALTER TABLE warehouses ADD COLUMN IF NOT EXISTS controlled_substance_limit NUMERIC"
    )
    # Track per-product controlled substance limits per warehouse
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS controlled_substance_limits (
            id          SERIAL PRIMARY KEY,
            warehouse_id INTEGER NOT NULL REFERENCES warehouses(id) ON DELETE CASCADE,
            product_id   INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            max_quantity NUMERIC(18,3) NOT NULL DEFAULT 0,
            unit         TEXT,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE(warehouse_id, product_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ctrl_limits_warehouse ON controlled_substance_limits(warehouse_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ctrl_limits_product ON controlled_substance_limits(product_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS controlled_substance_limits")
    op.execute(
        "ALTER TABLE warehouses DROP COLUMN IF EXISTS controlled_substance_limit"
    )
