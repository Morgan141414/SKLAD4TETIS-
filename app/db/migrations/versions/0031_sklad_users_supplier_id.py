"""link sklad_users to a supplier row, for tetis-routed supplier mode

Revision ID: 0031_sklad_users_supplier_id
Revises: 0030_supplier_applications
"""
from alembic import op

revision = "0031_sklad_users_supplier_id"
down_revision = "0030_supplier_applications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE sklad_users ADD COLUMN IF NOT EXISTS supplier_id BIGINT REFERENCES suppliers(id)")


def downgrade() -> None:
    op.execute("ALTER TABLE sklad_users DROP COLUMN IF EXISTS supplier_id")
