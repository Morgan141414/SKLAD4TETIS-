"""Add commission_members and resolution_type to quarantine_reviews

Revision ID: 0025_quarantine_commission
Revises: 0024_job_log
Create Date: 2026-06-17
"""
from alembic import op

revision = "0025_quarantine_commission"
down_revision = "0024_job_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE quarantine_reviews
            ADD COLUMN IF NOT EXISTS commission_members JSONB,
            ADD COLUMN IF NOT EXISTS resolution_type TEXT,
            ADD COLUMN IF NOT EXISTS disposal_quantity NUMERIC(18,4)
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE quarantine_reviews DROP COLUMN IF EXISTS disposal_quantity")
    op.execute("ALTER TABLE quarantine_reviews DROP COLUMN IF EXISTS resolution_type")
    op.execute("ALTER TABLE quarantine_reviews DROP COLUMN IF EXISTS commission_members")
