"""supplier verification: is_verified flag + document uploads

Revision ID: 0037_supplier_verification
Revises: 0036_inquiry_messages
"""
from alembic import op

revision = "0037_supplier_verification"
down_revision = "0036_inquiry_messages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Verification status on supplier profile
    op.execute("ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS is_verified BOOLEAN NOT NULL DEFAULT FALSE")
    op.execute("ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ")
    op.execute("ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS legal_name TEXT")
    op.execute("ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS verification_comment TEXT")

    # Uploaded verification documents
    op.execute("""
        CREATE TABLE IF NOT EXISTS supplier_verification_docs (
            id          SERIAL PRIMARY KEY,
            supplier_id INTEGER NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
            doc_type    TEXT NOT NULL,
            file_url    TEXT NOT NULL,
            original_name TEXT,
            uploaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            uploaded_by TEXT NOT NULL
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_sup_ver_docs_supplier "
        "ON supplier_verification_docs(supplier_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS supplier_verification_docs")
    op.execute("ALTER TABLE suppliers DROP COLUMN IF EXISTS verification_comment")
    op.execute("ALTER TABLE suppliers DROP COLUMN IF EXISTS legal_name")
    op.execute("ALTER TABLE suppliers DROP COLUMN IF EXISTS verified_at")
    op.execute("ALTER TABLE suppliers DROP COLUMN IF EXISTS is_verified")
