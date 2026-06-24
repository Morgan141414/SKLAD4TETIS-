"""add inventory metadata and supplier price history

Revision ID: 0011_inventory_metadata_price_history
Revises: 0010_sensor_warning_notifications
Create Date: 2026-06-15
"""

from __future__ import annotations

from alembic import op


revision = "0011_inventory_metadata_price_history"
down_revision = "0010_sensor_warning_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS inventory_responsibles (
          session_id BIGINT NOT NULL REFERENCES inventory_sessions(id) ON DELETE CASCADE,
          responsible_id TEXT NOT NULL,
          PRIMARY KEY(session_id, responsible_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS inventory_session_categories (
          session_id BIGINT NOT NULL REFERENCES inventory_sessions(id) ON DELETE CASCADE,
          category_id BIGINT NOT NULL REFERENCES categories(id),
          PRIMARY KEY(session_id, category_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS supplier_price_history (
          id BIGSERIAL PRIMARY KEY,
          supplier_id BIGINT NOT NULL REFERENCES suppliers(id),
          product_id BIGINT NOT NULL REFERENCES products(id),
          batch_id BIGINT REFERENCES batches(id),
          lot TEXT,
          unit_price NUMERIC(18, 4) NOT NULL,
          source TEXT NOT NULL,
          recorded_at TIMESTAMPTZ NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_supplier_price_history_supplier_product_recorded
          ON supplier_price_history(supplier_id, product_id, recorded_at DESC, id DESC)
        """
    )
    op.execute(
        """
        INSERT INTO supplier_price_history(
          supplier_id, product_id, batch_id, lot, unit_price, source, recorded_at
        )
        SELECT b.supplier_id, b.product_id, b.id, b.lot, b.unit_price, 'batch_backfill', b.received_at
        FROM batches b
        WHERE NOT EXISTS (
          SELECT 1 FROM supplier_price_history h WHERE h.batch_id = b.id
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_supplier_price_history_supplier_product_recorded")
    op.execute("DROP TABLE IF EXISTS supplier_price_history")
    op.execute("DROP TABLE IF EXISTS inventory_session_categories")
    op.execute("DROP TABLE IF EXISTS inventory_responsibles")
