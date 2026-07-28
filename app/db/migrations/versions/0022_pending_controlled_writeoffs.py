"""
0022 — Pending controlled write-offs (ПКУ двойная подпись)
"""

from alembic import op
import sqlalchemy as sa

revision = "0022_pending_controlled_writeoffs"
down_revision = "0021_controlled_limits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS pending_controlled_writeoffs (
            id SERIAL PRIMARY KEY,
            batch_id INTEGER NOT NULL REFERENCES batches(id),
            warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
            quantity NUMERIC NOT NULL,
            reason TEXT,
            patient_id TEXT NOT NULL,
            doctor_id TEXT NOT NULL,
            medical_record_no TEXT NOT NULL,
            requested_by TEXT NOT NULL,
            requested_at TEXT NOT NULL,
            second_approver_id TEXT,
            second_approval_note TEXT,
            second_approved_at TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            rejected_reason TEXT,
            writeoff_movement_id INTEGER REFERENCES stock_movements(id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_pcwo_batch ON pending_controlled_writeoffs(batch_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_pcwo_warehouse ON pending_controlled_writeoffs(warehouse_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_pcwo_status ON pending_controlled_writeoffs(status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_pcwo_doctor ON pending_controlled_writeoffs(doctor_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS pending_controlled_writeoffs")
