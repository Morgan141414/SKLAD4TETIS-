"""job_log table for background job history and lock tracking

Revision ID: 0024_job_log
Revises: 0023_document_external_ref
Create Date: 2026-06-16
"""
from alembic import op

revision = "0024_job_log"
down_revision = "0023_document_external_ref"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS job_log (
            id          BIGSERIAL PRIMARY KEY,
            job_name    TEXT NOT NULL,
            status      TEXT NOT NULL DEFAULT 'running',
            started_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            finished_at TIMESTAMPTZ,
            duration_ms INTEGER,
            result_json JSONB,
            error_text  TEXT
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_job_log_name_started
        ON job_log (job_name, started_at DESC)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_job_log_name_started")
    op.execute("DROP TABLE IF EXISTS job_log")
