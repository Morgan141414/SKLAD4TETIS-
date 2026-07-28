"""listing expiry and promotion columns"""
from alembic import op

revision = "0047_listing_expiry_promotion"
down_revision = "0046_favorites_otp"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE supplier_catalog_items
            ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS listing_plan TEXT DEFAULT 'free',
            ADD COLUMN IF NOT EXISTS promoted_until TIMESTAMPTZ
    """)
    # Give existing posts 30 days grace (so nothing disappears immediately)
    op.execute("""
        UPDATE supplier_catalog_items
        SET expires_at = NOW() + INTERVAL '30 days'
        WHERE expires_at IS NULL
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_sci_expires_at ON supplier_catalog_items(expires_at)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_sci_promoted_until ON supplier_catalog_items(promoted_until)")


def downgrade():
    op.execute("""
        ALTER TABLE supplier_catalog_items
            DROP COLUMN IF EXISTS expires_at,
            DROP COLUMN IF EXISTS listing_plan,
            DROP COLUMN IF EXISTS promoted_until
    """)
