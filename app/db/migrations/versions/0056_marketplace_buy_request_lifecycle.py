"""marketplace buy request lifecycle and expiry

Revision ID: 0056_marketplace_buy_request_lifecycle
Revises: 0055_marketplace_buy_requests_v2
"""
from alembic import op

revision = "0056_marketplace_buy_request_lifecycle"
down_revision = "0055_marketplace_buy_requests_v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE marketplace_buy_requests
          DROP CONSTRAINT IF EXISTS marketplace_buy_requests_status_check,
          ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ,
          ADD COLUMN IF NOT EXISTS fulfilled_at TIMESTAMPTZ,
          ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ
    """)
    op.execute("""
        UPDATE marketplace_buy_requests
        SET expires_at = COALESCE(expires_at, created_at + INTERVAL '30 days')
        WHERE expires_at IS NULL
    """)
    op.execute("""
        ALTER TABLE marketplace_buy_requests
          ALTER COLUMN expires_at SET DEFAULT (NOW() + INTERVAL '30 days'),
          ALTER COLUMN expires_at SET NOT NULL,
          ADD CONSTRAINT marketplace_buy_requests_status_check
            CHECK (status IN ('open', 'closed', 'fulfilled', 'expired', 'deleted')),
          ADD CONSTRAINT marketplace_buy_requests_fulfilled_at_check
            CHECK (status <> 'fulfilled' OR fulfilled_at IS NOT NULL),
          ADD CONSTRAINT marketplace_buy_requests_deleted_at_check
            CHECK (status <> 'deleted' OR deleted_at IS NOT NULL)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_buy_requests_expiry
        ON marketplace_buy_requests(expires_at)
        WHERE status = 'open'
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_buy_requests_expiry")
    op.execute("""
        ALTER TABLE marketplace_buy_requests
          DROP CONSTRAINT IF EXISTS marketplace_buy_requests_deleted_at_check,
          DROP CONSTRAINT IF EXISTS marketplace_buy_requests_fulfilled_at_check,
          DROP CONSTRAINT IF EXISTS marketplace_buy_requests_status_check
    """)
    op.execute("""
        UPDATE marketplace_buy_requests
        SET status = 'closed'
        WHERE status IN ('fulfilled', 'expired', 'deleted')
    """)
    op.execute("""
        ALTER TABLE marketplace_buy_requests
          ADD CONSTRAINT marketplace_buy_requests_status_check
            CHECK (status IN ('open', 'closed')),
          DROP COLUMN IF EXISTS deleted_at,
          DROP COLUMN IF EXISTS fulfilled_at,
          DROP COLUMN IF EXISTS expires_at
    """)
