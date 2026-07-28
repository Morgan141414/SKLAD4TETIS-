"""add public marketplace buy requests and seller responses

Revision ID: 0053_marketplace_buy_requests
Revises: 0052_merge_marketplace_prod_and_refunds
"""
from alembic import op

revision = "0053_marketplace_buy_requests"
down_revision = "0052_merge_marketplace_prod_and_refunds"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS marketplace_buy_requests (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES sklad_users(id) ON DELETE CASCADE,
            title VARCHAR(180) NOT NULL,
            description TEXT,
            category VARCHAR(120),
            city VARCHAR(120),
            budget_min NUMERIC(14,2),
            budget_max NUMERIC(14,2),
            quantity INTEGER NOT NULL DEFAULT 1,
            unit VARCHAR(20) NOT NULL DEFAULT 'шт',
            contact_phone VARCHAR(32),
            status VARCHAR(20) NOT NULL DEFAULT 'open'
                CHECK (status IN ('open', 'closed')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (quantity > 0),
            CHECK (budget_min IS NULL OR budget_min >= 0),
            CHECK (budget_max IS NULL OR budget_max >= 0),
            CHECK (budget_min IS NULL OR budget_max IS NULL OR budget_max >= budget_min)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_buy_requests_feed ON marketplace_buy_requests(status, created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_buy_requests_user ON marketplace_buy_requests(user_id, created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_buy_requests_category ON marketplace_buy_requests(category) WHERE status = 'open'")
    op.execute("""
        CREATE TABLE IF NOT EXISTS marketplace_buy_responses (
            id BIGSERIAL PRIMARY KEY,
            request_id BIGINT NOT NULL REFERENCES marketplace_buy_requests(id) ON DELETE CASCADE,
            responder_user_id BIGINT NOT NULL REFERENCES sklad_users(id) ON DELETE CASCADE,
            message TEXT NOT NULL,
            offered_price NUMERIC(14,2),
            contact_phone VARCHAR(32),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (request_id, responder_user_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_buy_responses_request ON marketplace_buy_responses(request_id, created_at DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS marketplace_buy_responses")
    op.execute("DROP TABLE IF EXISTS marketplace_buy_requests")
