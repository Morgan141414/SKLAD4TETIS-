"""add ABC/XYZ analysis history

Revision ID: 0003_abc_xyz_history
Revises: 0002_warehouse_tetis_mapping
Create Date: 2026-06-13
"""

from __future__ import annotations

from alembic import op


revision = "0003_abc_xyz_history"
down_revision = "0002_warehouse_tetis_mapping"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS abc_xyz_runs (
          id BIGSERIAL PRIMARY KEY,
          warehouse_id BIGINT REFERENCES warehouses(id),
          analysis_days INTEGER NOT NULL,
          period_start TIMESTAMPTZ NOT NULL,
          period_end TIMESTAMPTZ NOT NULL,
          source TEXT NOT NULL,
          status TEXT NOT NULL,
          items_count INTEGER NOT NULL DEFAULT 0,
          error TEXT,
          generated_by TEXT NOT NULL,
          generated_at TIMESTAMPTZ NOT NULL,
          CONSTRAINT abc_xyz_runs_analysis_days_positive CHECK (analysis_days > 0),
          CONSTRAINT abc_xyz_runs_items_count_non_negative CHECK (items_count >= 0),
          CONSTRAINT abc_xyz_runs_source_check CHECK (source IN ('manual', 'background')),
          CONSTRAINT abc_xyz_runs_status_check CHECK (status IN ('succeeded', 'failed', 'skipped'))
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_abc_xyz_runs_warehouse_generated
          ON abc_xyz_runs(warehouse_id, generated_at DESC, id DESC)
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_abc_xyz_runs_period
          ON abc_xyz_runs(COALESCE(warehouse_id, 0), analysis_days, period_start, period_end, source)
          WHERE status = 'succeeded'
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS abc_xyz_run_items (
          id BIGSERIAL PRIMARY KEY,
          run_id BIGINT NOT NULL REFERENCES abc_xyz_runs(id) ON DELETE CASCADE,
          product_id BIGINT NOT NULL REFERENCES products(id),
          product_name TEXT NOT NULL,
          sku TEXT NOT NULL,
          abc_class TEXT NOT NULL,
          xyz_class TEXT NOT NULL,
          consumption_quantity NUMERIC(18, 3) NOT NULL,
          consumption_value NUMERIC(18, 3) NOT NULL,
          current_free_quantity NUMERIC(18, 3) NOT NULL,
          reorder_point NUMERIC(18, 3) NOT NULL,
          safety_stock NUMERIC(18, 3) NOT NULL,
          recommended_order_quantity NUMERIC(18, 3) NOT NULL,
          recommendation TEXT NOT NULL,
          movement_count INTEGER NOT NULL,
          CONSTRAINT abc_xyz_run_items_abc_check CHECK (abc_class IN ('A', 'B', 'C')),
          CONSTRAINT abc_xyz_run_items_xyz_check CHECK (xyz_class IN ('X', 'Y', 'Z')),
          CONSTRAINT abc_xyz_run_items_movement_count_non_negative CHECK (movement_count >= 0)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_abc_xyz_run_items_run
          ON abc_xyz_run_items(run_id, product_id)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS abc_xyz_run_items")
    op.execute("DROP INDEX IF EXISTS uq_abc_xyz_runs_period")
    op.execute("DROP INDEX IF EXISTS idx_abc_xyz_runs_warehouse_generated")
    op.execute("DROP TABLE IF EXISTS abc_xyz_runs")
