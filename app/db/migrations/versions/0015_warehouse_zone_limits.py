"""add warehouse zone and limit fields

Revision ID: 0015_warehouse_zone_limits
Revises: 0014_supplier_card_fields
Create Date: 2026-06-15
"""

from __future__ import annotations

from alembic import op


revision = "0015_warehouse_zone_limits"
down_revision = "0014_supplier_card_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE warehouses ADD COLUMN IF NOT EXISTS storage_zone TEXT")
    op.execute("ALTER TABLE warehouses ADD COLUMN IF NOT EXISTS capacity_limit NUMERIC")
    op.execute("ALTER TABLE warehouses ADD COLUMN IF NOT EXISTS storage_conditions TEXT")
    op.execute("ALTER TABLE warehouses ADD COLUMN IF NOT EXISTS responsible_person TEXT")
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_warehouses_storage_zone
        ON warehouses(storage_zone, id)
        WHERE storage_zone IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_warehouses_storage_zone")
    op.execute("ALTER TABLE warehouses DROP COLUMN IF EXISTS responsible_person")
    op.execute("ALTER TABLE warehouses DROP COLUMN IF EXISTS storage_conditions")
    op.execute("ALTER TABLE warehouses DROP COLUMN IF EXISTS capacity_limit")
    op.execute("ALTER TABLE warehouses DROP COLUMN IF EXISTS storage_zone")
