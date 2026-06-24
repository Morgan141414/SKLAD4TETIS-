"""add catalog soft delete flags

Revision ID: 0013_catalog_soft_delete
Revises: 0012_supplier_profile_fields
Create Date: 2026-06-15
"""

from __future__ import annotations

from alembic import op


revision = "0013_catalog_soft_delete"
down_revision = "0012_supplier_profile_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE categories ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE")
    op.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE")
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_categories_active_name
        ON categories(is_active, name, id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_products_active_name
        ON products(is_active, name, id)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_products_active_name")
    op.execute("DROP INDEX IF EXISTS idx_categories_active_name")
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS is_active")
    op.execute("ALTER TABLE categories DROP COLUMN IF EXISTS is_active")
