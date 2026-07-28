"""add supplier onboarding profiles

Revision ID: 0017_supplier_onboarding
Revises: 0016_batch_serial_numbers
Create Date: 2026-06-24
"""

from __future__ import annotations

from alembic import op


revision = "0017_supplier_onboarding"
down_revision = "0016_batch_serial_numbers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS supplier_applications (
          id BIGSERIAL PRIMARY KEY,
          actor_id TEXT NOT NULL UNIQUE,
          supplier_id BIGINT REFERENCES suppliers(id),
          status TEXT NOT NULL,
          name TEXT NOT NULL,
          bin TEXT,
          phone TEXT,
          email TEXT,
          contact_person TEXT,
          address TEXT,
          notes TEXT,
          review_reason TEXT,
          submitted_at TIMESTAMPTZ NOT NULL,
          reviewed_by TEXT,
          reviewed_at TIMESTAMPTZ,
          CONSTRAINT supplier_applications_status_check CHECK (
            status IN ('pending', 'approved', 'rejected', 'needs_changes', 'suspended')
          )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS supplier_members (
          supplier_id BIGINT NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
          actor_id TEXT NOT NULL,
          member_role TEXT NOT NULL DEFAULT 'owner',
          is_active BOOLEAN NOT NULL DEFAULT TRUE,
          created_at TIMESTAMPTZ NOT NULL,
          PRIMARY KEY(supplier_id, actor_id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_supplier_applications_status_submitted
        ON supplier_applications(status, submitted_at DESC, id DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_supplier_members_actor_active
        ON supplier_members(actor_id, is_active, supplier_id)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_supplier_members_actor_active")
    op.execute("DROP INDEX IF EXISTS idx_supplier_applications_status_submitted")
    op.execute("DROP TABLE IF EXISTS supplier_members")
    op.execute("DROP TABLE IF EXISTS supplier_applications")
