"""product image_path column

Revision ID: 0027_product_image
Revises: 0026_repack_templates
"""
from alembic import op

revision = "0027_product_image"
down_revision = "0026_repack_templates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS image_path TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS image_path")
