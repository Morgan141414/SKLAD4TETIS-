"""supplier self onboarding applications

Revision ID: 0030_supplier_applications
Revises: 0029_mis_procedure_consumption
"""

from alembic import op


revision = "0030_supplier_applications"
down_revision = "0029_mis_procedure_consumption"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS supplier_applications (
          id BIGSERIAL PRIMARY KEY,
          actor_id TEXT NOT NULL,
          supplier_id BIGINT REFERENCES suppliers(id),
          status TEXT NOT NULL,
          name TEXT NOT NULL,
          bin TEXT,
          phone TEXT,
          email TEXT NOT NULL,
          contact_person TEXT,
          address TEXT,
          city TEXT,
          delivery_days INTEGER,
          notes TEXT,
          review_reason TEXT,
          submitted_at TIMESTAMPTZ NOT NULL,
          reviewed_by TEXT,
          reviewed_at TIMESTAMPTZ,
          CONSTRAINT supplier_applications_status_check CHECK (
            status IN ('pending', 'approved', 'rejected', 'needs_changes', 'suspended')
          ),
          CONSTRAINT supplier_applications_delivery_days_check CHECK (
            delivery_days IS NULL OR delivery_days > 0
          )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_supplier_applications_status_submitted
        ON supplier_applications(status, submitted_at DESC, id DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_supplier_applications_status_submitted")
    op.execute("DROP TABLE IF EXISTS supplier_applications")
