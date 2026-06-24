"""add supplier card fields

Revision ID: 0014_supplier_card_fields
Revises: 0013_catalog_soft_delete
Create Date: 2026-06-15
"""

from __future__ import annotations

from alembic import op


revision = "0014_supplier_card_fields"
down_revision = "0013_catalog_soft_delete"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS contact_person TEXT")
    op.execute("ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS email TEXT")
    op.execute("ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS contract_number TEXT")
    op.execute("ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS contract_expires_on DATE")
    op.execute("ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS payment_terms TEXT")
    op.execute("ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS notes TEXT")
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_suppliers_contract_expires
        ON suppliers(contract_expires_on, id)
        WHERE contract_expires_on IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_suppliers_contract_expires")
    op.execute("ALTER TABLE suppliers DROP COLUMN IF EXISTS notes")
    op.execute("ALTER TABLE suppliers DROP COLUMN IF EXISTS payment_terms")
    op.execute("ALTER TABLE suppliers DROP COLUMN IF EXISTS contract_expires_on")
    op.execute("ALTER TABLE suppliers DROP COLUMN IF EXISTS contract_number")
    op.execute("ALTER TABLE suppliers DROP COLUMN IF EXISTS email")
    op.execute("ALTER TABLE suppliers DROP COLUMN IF EXISTS contact_person")
