"""add quarantine review workflow

Revision ID: 0004_quarantine_reviews
Revises: 0003_abc_xyz_history
Create Date: 2026-06-13
"""

from __future__ import annotations

from alembic import op


revision = "0004_quarantine_reviews"
down_revision = "0003_abc_xyz_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS quarantine_reviews (
          id BIGSERIAL PRIMARY KEY,
          batch_id BIGINT NOT NULL REFERENCES batches(id),
          warehouse_id BIGINT NOT NULL REFERENCES warehouses(id),
          status TEXT NOT NULL,
          responsible_id TEXT,
          due_at TIMESTAMPTZ,
          decision_reason TEXT,
          created_by TEXT NOT NULL,
          decided_by TEXT,
          created_at TIMESTAMPTZ NOT NULL,
          updated_at TIMESTAMPTZ NOT NULL,
          decided_at TIMESTAMPTZ,
          CONSTRAINT quarantine_reviews_status_check CHECK (
            status IN ('pending', 'in_review', 'approved', 'rejected')
          ),
          UNIQUE(batch_id, warehouse_id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_quarantine_reviews_warehouse_status_due
          ON quarantine_reviews(warehouse_id, status, due_at, id)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_quarantine_reviews_warehouse_status_due")
    op.execute("DROP TABLE IF EXISTS quarantine_reviews")
