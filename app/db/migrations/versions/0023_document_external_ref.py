"""Add external_ref and notes fields to stock_documents (ЭСФ / накладная)

Revision ID: 0023_document_external_ref
Revises: 0022_pending_controlled_writeoffs
Create Date: 2026-06-16
"""
from alembic import op

revision = "0023_document_external_ref"
down_revision = "0022_pending_controlled_writeoffs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE stock_documents
            ADD COLUMN IF NOT EXISTS external_ref TEXT,
            ADD COLUMN IF NOT EXISTS notes TEXT
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_stock_documents_external_ref
        ON stock_documents(external_ref)
        WHERE external_ref IS NOT NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_stock_documents_external_ref")
    op.execute("ALTER TABLE stock_documents DROP COLUMN IF EXISTS external_ref")
    op.execute("ALTER TABLE stock_documents DROP COLUMN IF EXISTS notes")
