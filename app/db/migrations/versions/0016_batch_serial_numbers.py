"""add batch serial numbers

Revision ID: 0016_batch_serial_numbers
Revises: 0015_warehouse_zone_limits
Create Date: 2026-06-15
"""

from __future__ import annotations

from alembic import op


revision = "0016_batch_serial_numbers"
down_revision = "0015_warehouse_zone_limits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE batches ADD COLUMN IF NOT EXISTS serial_number TEXT")
    op.execute("ALTER TABLE stock_document_lines ADD COLUMN IF NOT EXISTS serial_number TEXT")
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_batches_serial_number
        ON batches(serial_number, id)
        WHERE serial_number IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_batches_serial_number")
    op.execute("ALTER TABLE stock_document_lines DROP COLUMN IF EXISTS serial_number")
    op.execute("ALTER TABLE batches DROP COLUMN IF EXISTS serial_number")
