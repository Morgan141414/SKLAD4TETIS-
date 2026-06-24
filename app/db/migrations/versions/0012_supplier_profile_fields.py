"""add supplier profile fields

Revision ID: 0012_supplier_profile_fields
Revises: 0011_inventory_metadata_price_history
Create Date: 2026-06-15
"""

from __future__ import annotations

from alembic import op


revision = "0012_supplier_profile_fields"
down_revision = "0011_inventory_metadata_price_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS address TEXT")
    op.execute("ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS rating INTEGER")
    op.execute("ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS is_preferred BOOLEAN NOT NULL DEFAULT FALSE")
    op.execute(
        """
        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conname = 'suppliers_rating_range'
          ) THEN
            ALTER TABLE suppliers
            ADD CONSTRAINT suppliers_rating_range
            CHECK (rating IS NULL OR (rating >= 1 AND rating <= 5));
          END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE suppliers DROP CONSTRAINT IF EXISTS suppliers_rating_range")
    op.execute("ALTER TABLE suppliers DROP COLUMN IF EXISTS is_preferred")
    op.execute("ALTER TABLE suppliers DROP COLUMN IF EXISTS rating")
    op.execute("ALTER TABLE suppliers DROP COLUMN IF EXISTS address")
