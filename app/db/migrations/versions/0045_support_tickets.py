"""Support tickets table for marqet.kz feedback/support form

Revision ID: 0045_support_tickets
Revises: 0044_condition_delivery_escrow
"""
from alembic import op

revision = "0045_support_tickets"
down_revision = "0044_condition_delivery_escrow"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS support_tickets (
            id          BIGSERIAL PRIMARY KEY,
            name        TEXT NOT NULL,
            email       TEXT,
            phone       TEXT,
            subject     TEXT NOT NULL,
            message     TEXT NOT NULL,
            status      TEXT NOT NULL DEFAULT 'new',
            actor_id    TEXT,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT support_status_check CHECK (status IN ('new', 'in_progress', 'resolved', 'closed'))
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_support_tickets_status ON support_tickets(status, created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_support_tickets_email ON support_tickets(email) WHERE email IS NOT NULL")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS support_tickets")
