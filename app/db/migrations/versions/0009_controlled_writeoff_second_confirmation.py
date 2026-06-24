"""add second confirmation fields for controlled write-offs

Revision ID: 0009_controlled_writeoff_second_confirmation
Revises: 0008_batch_recalls
Create Date: 2026-06-13
"""

from __future__ import annotations

from alembic import op


revision = "0009_controlled_writeoff_second_confirmation"
down_revision = "0008_batch_recalls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table_name in ("stock_movements", "stock_document_lines"):
        op.execute(f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS second_approver_id TEXT")
        op.execute(f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS second_approval_note TEXT")


def downgrade() -> None:
    for table_name in ("stock_document_lines", "stock_movements"):
        op.execute(f"ALTER TABLE {table_name} DROP COLUMN IF EXISTS second_approval_note")
        op.execute(f"ALTER TABLE {table_name} DROP COLUMN IF EXISTS second_approver_id")
