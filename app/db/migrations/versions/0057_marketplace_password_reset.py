"""Marketplace password reset tokens

Revision ID: 0057_marketplace_password_reset
Revises: 0056_marketplace_buy_request_lifecycle
"""

revision = "0057_marketplace_password_reset"
down_revision = "0056_marketplace_buy_request_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from alembic import op

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS marketplace_password_reset_tokens (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES sklad_users(id) ON DELETE CASCADE,
            token_hash TEXT NOT NULL UNIQUE,
            expires_at TIMESTAMPTZ NOT NULL,
            used_at TIMESTAMPTZ,
            request_ip TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_mprt_user_active
        ON marketplace_password_reset_tokens(user_id, expires_at)
        WHERE used_at IS NULL
        """
    )


def downgrade() -> None:
    from alembic import op

    op.execute("DROP INDEX IF EXISTS idx_mprt_user_active")
    op.execute("DROP TABLE IF EXISTS marketplace_password_reset_tokens")
