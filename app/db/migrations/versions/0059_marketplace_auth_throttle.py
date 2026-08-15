"""Throttling state for marketplace authentication.

Adds a per-token attempt counter to password reset tokens and a short-lived
log of failed authentication attempts used to rate limit login and reset
confirmation by email and by client IP.

Revision ID: 0059_marketplace_auth_throttle
Revises: 0058_marketplace_listing_reports
Create Date: 2026-08-07
"""

from alembic import op


revision = "0059_marketplace_auth_throttle"
down_revision = "0058_marketplace_listing_reports"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        ALTER TABLE marketplace_password_reset_tokens
          ADD COLUMN IF NOT EXISTS attempts SMALLINT NOT NULL DEFAULT 0
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS marketplace_auth_attempts (
          id BIGSERIAL PRIMARY KEY,
          kind VARCHAR(20) NOT NULL CHECK (kind IN ('login', 'reset_confirm')),
          email TEXT NOT NULL,
          ip_address TEXT NOT NULL DEFAULT '',
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_marketplace_auth_attempts_email
          ON marketplace_auth_attempts(kind, LOWER(email), created_at DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_marketplace_auth_attempts_ip
          ON marketplace_auth_attempts(kind, ip_address, created_at DESC)
        """
    )
    # Housekeeping index for the purge of rows outside every throttling window.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_marketplace_auth_attempts_created
          ON marketplace_auth_attempts(created_at)
        """
    )


def downgrade():
    op.execute("DROP TABLE IF EXISTS marketplace_auth_attempts")
    op.execute(
        """
        ALTER TABLE marketplace_password_reset_tokens
          DROP COLUMN IF EXISTS attempts
        """
    )
