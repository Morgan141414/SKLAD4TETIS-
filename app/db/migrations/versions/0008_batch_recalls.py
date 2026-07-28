"""add batch recall workflow

Revision ID: 0008_batch_recalls
Revises: 0007_stock_document_approvals
Create Date: 2026-06-13
"""

from __future__ import annotations

from alembic import op


revision = "0008_batch_recalls"
down_revision = "0007_stock_document_approvals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS batch_recalls (
          id BIGSERIAL PRIMARY KEY,
          batch_id BIGINT NOT NULL REFERENCES batches(id),
          product_id BIGINT NOT NULL REFERENCES products(id),
          reason TEXT NOT NULL,
          source TEXT NOT NULL DEFAULT 'manual',
          reference TEXT,
          created_by TEXT NOT NULL,
          created_at TIMESTAMPTZ NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_batch_recalls_batch_created
          ON batch_recalls(batch_id, created_at DESC, id DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_batch_recalls_created
          ON batch_recalls(created_at DESC, id DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_batch_recalls_created")
    op.execute("DROP INDEX IF EXISTS idx_batch_recalls_batch_created")
    op.execute("DROP TABLE IF EXISTS batch_recalls")
