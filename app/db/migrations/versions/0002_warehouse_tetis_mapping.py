"""add Tetis warehouse mapping fields

Revision ID: 0002_warehouse_tetis_mapping
Revises: 0001_initial_postgresql
Create Date: 2026-06-12
"""

from __future__ import annotations

from alembic import op


revision = "0002_warehouse_tetis_mapping"
down_revision = "0001_initial_postgresql"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE warehouses ADD COLUMN IF NOT EXISTS tetis_org_id TEXT")
    op.execute("ALTER TABLE warehouses ADD COLUMN IF NOT EXISTS external_tetis_id TEXT")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_warehouses_tetis_org_id "
        "ON warehouses(tetis_org_id, id)"
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_warehouses_tetis_org_external
          ON warehouses(tetis_org_id, external_tetis_id)
          WHERE tetis_org_id IS NOT NULL AND external_tetis_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_warehouses_tetis_org_external")
    op.execute("DROP INDEX IF EXISTS idx_warehouses_tetis_org_id")
    op.execute("ALTER TABLE warehouses DROP COLUMN IF EXISTS external_tetis_id")
    op.execute("ALTER TABLE warehouses DROP COLUMN IF EXISTS tetis_org_id")
