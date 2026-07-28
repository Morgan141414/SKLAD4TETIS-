"""add supplier offers

Revision ID: 0018_supplier_offers
Revises: 0017_supplier_onboarding
Create Date: 2026-06-24
"""

from __future__ import annotations

from alembic import op


revision = "0018_supplier_offers"
down_revision = "0017_supplier_onboarding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS supplier_offers (
          id BIGSERIAL PRIMARY KEY,
          purchase_request_id BIGINT NOT NULL REFERENCES purchase_requests(id) ON DELETE CASCADE,
          supplier_id BIGINT NOT NULL REFERENCES suppliers(id),
          actor_id TEXT NOT NULL,
          status TEXT NOT NULL,
          unit_price NUMERIC(18, 4) NOT NULL,
          quantity NUMERIC(18, 3) NOT NULL,
          delivery_date DATE,
          expires_at DATE,
          comment TEXT,
          reviewed_by TEXT,
          reviewed_at TIMESTAMPTZ,
          review_reason TEXT,
          created_at TIMESTAMPTZ NOT NULL,
          updated_at TIMESTAMPTZ NOT NULL,
          CONSTRAINT supplier_offers_status_check CHECK (
            status IN ('submitted', 'accepted', 'rejected', 'withdrawn')
          ),
          CONSTRAINT supplier_offers_unit_price_non_negative CHECK (unit_price >= 0),
          CONSTRAINT supplier_offers_quantity_positive CHECK (quantity > 0)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_supplier_offers_request_status
        ON supplier_offers(purchase_request_id, status, id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_supplier_offers_supplier_status
        ON supplier_offers(supplier_id, status, updated_at DESC, id DESC)
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_supplier_offers_active_supplier_request
        ON supplier_offers(purchase_request_id, supplier_id)
        WHERE status IN ('submitted', 'accepted')
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_supplier_offers_one_accepted_request
        ON supplier_offers(purchase_request_id)
        WHERE status = 'accepted'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_supplier_offers_one_accepted_request")
    op.execute("DROP INDEX IF EXISTS uq_supplier_offers_active_supplier_request")
    op.execute("DROP INDEX IF EXISTS idx_supplier_offers_supplier_status")
    op.execute("DROP INDEX IF EXISTS idx_supplier_offers_request_status")
    op.execute("DROP TABLE IF EXISTS supplier_offers")
