"""Add marketplace listing reports and moderation fields.

Revision ID: 0058_marketplace_listing_reports
Revises: 0057_marketplace_password_reset
Create Date: 2026-07-28
"""

from alembic import op


revision = "0058_marketplace_listing_reports"
down_revision = "0057_marketplace_password_reset"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        ALTER TABLE supplier_catalog_items
          ADD COLUMN IF NOT EXISTS moderation_status VARCHAR(20) NOT NULL DEFAULT 'approved',
          ADD COLUMN IF NOT EXISTS moderation_note TEXT,
          ADD COLUMN IF NOT EXISTS moderated_at TIMESTAMPTZ,
          ADD COLUMN IF NOT EXISTS moderated_by INTEGER REFERENCES sklad_users(id) ON DELETE SET NULL
        """
    )
    op.execute(
        """
        ALTER TABLE supplier_catalog_items
          DROP CONSTRAINT IF EXISTS chk_supplier_catalog_items_moderation_status
        """
    )
    op.execute(
        """
        ALTER TABLE supplier_catalog_items
          ADD CONSTRAINT chk_supplier_catalog_items_moderation_status
          CHECK (moderation_status IN ('approved', 'pending', 'rejected'))
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_sci_moderation_status
          ON supplier_catalog_items(moderation_status, is_active, updated_at DESC)
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS marketplace_listing_reports (
          id BIGSERIAL PRIMARY KEY,
          catalog_item_id INTEGER NOT NULL REFERENCES supplier_catalog_items(id) ON DELETE CASCADE,
          reporter_user_id INTEGER NOT NULL REFERENCES sklad_users(id) ON DELETE CASCADE,
          reason VARCHAR(30) NOT NULL CHECK (reason IN ('spam', 'fraud', 'prohibited', 'offensive', 'other')),
          details TEXT,
          status VARCHAR(20) NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'reviewed', 'dismissed')),
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          reviewed_at TIMESTAMPTZ,
          reviewed_by INTEGER REFERENCES sklad_users(id) ON DELETE SET NULL,
          UNIQUE(catalog_item_id, reporter_user_id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_listing_reports_status_created
          ON marketplace_listing_reports(status, created_at ASC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_listing_reports_item_status
          ON marketplace_listing_reports(catalog_item_id, status)
        """
    )


def downgrade():
    op.execute("DROP TABLE IF EXISTS marketplace_listing_reports")
    op.execute("DROP INDEX IF EXISTS idx_sci_moderation_status")
    op.execute(
        """
        ALTER TABLE supplier_catalog_items
          DROP CONSTRAINT IF EXISTS chk_supplier_catalog_items_moderation_status
        """
    )
    op.execute(
        """
        ALTER TABLE supplier_catalog_items
          DROP COLUMN IF EXISTS moderated_by,
          DROP COLUMN IF EXISTS moderated_at,
          DROP COLUMN IF EXISTS moderation_note,
          DROP COLUMN IF EXISTS moderation_status
        """
    )
