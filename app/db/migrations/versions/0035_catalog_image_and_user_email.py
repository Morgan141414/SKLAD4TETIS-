"""catalog item images + sklad_users email field

Revision ID: 0035_catalog_image_and_user_email
Revises: 0034_supplier_enhancements
"""
from alembic import op

revision = "0035_catalog_image_and_user_email"
down_revision = "0034_supplier_enhancements"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Supplier catalog item photo
    op.execute("ALTER TABLE supplier_catalog_items ADD COLUMN IF NOT EXISTS image_url TEXT")
    # Store buyer email so we can notify them when supplier responds
    op.execute("ALTER TABLE sklad_users ADD COLUMN IF NOT EXISTS email TEXT")
    op.execute("CREATE INDEX IF NOT EXISTS idx_sklad_users_email ON sklad_users(email) WHERE email IS NOT NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE supplier_catalog_items DROP COLUMN IF EXISTS image_url")
    op.execute("ALTER TABLE sklad_users DROP COLUMN IF EXISTS email")
