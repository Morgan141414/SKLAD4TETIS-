"""supplier portal access (password_hash, is_active)

Revision ID: 0028_supplier_portal_access
Revises: 0027_product_image
"""
from alembic import op

revision = "0028_supplier_portal_access"
down_revision = "0027_product_image"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS password_hash TEXT")
    op.execute("ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS portal_access_enabled BOOLEAN NOT NULL DEFAULT false")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_suppliers_email_portal "
        "ON suppliers (email) WHERE password_hash IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_suppliers_email_portal")
    op.execute("ALTER TABLE suppliers DROP COLUMN IF EXISTS portal_access_enabled")
    op.execute("ALTER TABLE suppliers DROP COLUMN IF EXISTS password_hash")
