"""add approval lifecycle to stock documents

Revision ID: 0007_stock_document_approvals
Revises: 0006_batch_transformations
Create Date: 2026-06-13
"""

from __future__ import annotations

from alembic import op


revision = "0007_stock_document_approvals"
down_revision = "0006_batch_transformations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE stock_documents ADD COLUMN IF NOT EXISTS approved_by TEXT")
    op.execute("ALTER TABLE stock_documents ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ")
    op.execute(
        """
        ALTER TABLE stock_documents
        DROP CONSTRAINT IF EXISTS stock_documents_status_check
        """
    )
    op.execute(
        """
        ALTER TABLE stock_documents
        ADD CONSTRAINT stock_documents_status_check CHECK (
          status IN ('draft', 'approved', 'posted', 'cancelled')
        )
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE stock_documents
        DROP CONSTRAINT IF EXISTS stock_documents_status_check
        """
    )
    op.execute(
        """
        ALTER TABLE stock_documents
        ADD CONSTRAINT stock_documents_status_check CHECK (
          status IN ('draft', 'posted', 'cancelled')
        )
        """
    )
    op.execute("ALTER TABLE stock_documents DROP COLUMN IF EXISTS approved_at")
    op.execute("ALTER TABLE stock_documents DROP COLUMN IF EXISTS approved_by")
