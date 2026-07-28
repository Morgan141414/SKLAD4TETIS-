"""marketplace buy requests v2: moderation, matching and private notifications

Revision ID: 0055_marketplace_buy_requests_v2
Revises: 0054_normalize_legacy_admin_role
"""
from alembic import op

revision = "0055_marketplace_buy_requests_v2"
down_revision = "0054_normalize_legacy_admin_role"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE marketplace_buy_requests
          ADD COLUMN IF NOT EXISTS moderation_status VARCHAR(20) NOT NULL DEFAULT 'approved',
          ADD COLUMN IF NOT EXISTS view_count BIGINT NOT NULL DEFAULT 0,
          ADD COLUMN IF NOT EXISTS matched_catalog_item_id BIGINT REFERENCES supplier_catalog_items(id) ON DELETE SET NULL,
          ADD COLUMN IF NOT EXISTS matched_at TIMESTAMPTZ,
          ADD COLUMN IF NOT EXISTS moderation_note TEXT,
          ADD CONSTRAINT chk_buy_request_moderation_status
            CHECK (moderation_status IN ('approved', 'pending', 'rejected')),
          ADD CONSTRAINT chk_buy_request_view_count CHECK (view_count >= 0)
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_buy_requests_moderation ON marketplace_buy_requests(moderation_status, status, created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_buy_requests_match ON marketplace_buy_requests(matched_catalog_item_id) WHERE matched_catalog_item_id IS NOT NULL")

    op.execute("""
        CREATE TABLE IF NOT EXISTS marketplace_buy_request_views (
            request_id BIGINT NOT NULL REFERENCES marketplace_buy_requests(id) ON DELETE CASCADE,
            viewer_key CHAR(64) NOT NULL,
            viewed_on DATE NOT NULL DEFAULT CURRENT_DATE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (request_id, viewer_key, viewed_on)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_buy_request_views_cleanup ON marketplace_buy_request_views(viewed_on)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS marketplace_buy_request_reports (
            id BIGSERIAL PRIMARY KEY,
            request_id BIGINT NOT NULL REFERENCES marketplace_buy_requests(id) ON DELETE CASCADE,
            reporter_user_id BIGINT NOT NULL REFERENCES sklad_users(id) ON DELETE CASCADE,
            reason VARCHAR(30) NOT NULL CHECK (reason IN ('spam', 'fraud', 'prohibited', 'offensive', 'other')),
            details VARCHAR(500),
            status VARCHAR(20) NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'reviewed', 'dismissed')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            reviewed_at TIMESTAMPTZ,
            reviewed_by BIGINT REFERENCES sklad_users(id) ON DELETE SET NULL,
            UNIQUE (request_id, reporter_user_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_buy_request_reports_queue ON marketplace_buy_request_reports(status, created_at)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS marketplace_buy_request_matches (
            id BIGSERIAL PRIMARY KEY,
            request_id BIGINT NOT NULL REFERENCES marketplace_buy_requests(id) ON DELETE CASCADE,
            catalog_item_id BIGINT NOT NULL REFERENCES supplier_catalog_items(id) ON DELETE CASCADE,
            matched_by_user_id BIGINT REFERENCES sklad_users(id) ON DELETE SET NULL,
            source VARCHAR(20) NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'automatic')),
            status VARCHAR(20) NOT NULL DEFAULT 'suggested' CHECK (status IN ('suggested', 'accepted', 'dismissed')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (request_id, catalog_item_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_buy_request_matches_request ON marketplace_buy_request_matches(request_id, status, created_at DESC)")

    # Marketplace notifications are intentionally isolated from warehouse alerts.
    op.execute("""
        CREATE TABLE IF NOT EXISTS marketplace_user_notifications (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES sklad_users(id) ON DELETE CASCADE,
            notification_type VARCHAR(40) NOT NULL,
            title VARCHAR(180) NOT NULL,
            body VARCHAR(500),
            entity_type VARCHAR(40),
            entity_id BIGINT,
            is_read BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_marketplace_user_notifications ON marketplace_user_notifications(user_id, is_read, created_at DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS marketplace_user_notifications")
    op.execute("DROP TABLE IF EXISTS marketplace_buy_request_matches")
    op.execute("DROP TABLE IF EXISTS marketplace_buy_request_reports")
    op.execute("DROP TABLE IF EXISTS marketplace_buy_request_views")
    op.execute("DROP INDEX IF EXISTS idx_buy_requests_match")
    op.execute("DROP INDEX IF EXISTS idx_buy_requests_moderation")
    op.execute("ALTER TABLE marketplace_buy_requests DROP CONSTRAINT IF EXISTS chk_buy_request_view_count")
    op.execute("ALTER TABLE marketplace_buy_requests DROP CONSTRAINT IF EXISTS chk_buy_request_moderation_status")
    op.execute("ALTER TABLE marketplace_buy_requests DROP COLUMN IF EXISTS moderation_note")
    op.execute("ALTER TABLE marketplace_buy_requests DROP COLUMN IF EXISTS matched_at")
    op.execute("ALTER TABLE marketplace_buy_requests DROP COLUMN IF EXISTS matched_catalog_item_id")
    op.execute("ALTER TABLE marketplace_buy_requests DROP COLUMN IF EXISTS view_count")
    op.execute("ALTER TABLE marketplace_buy_requests DROP COLUMN IF EXISTS moderation_status")
