"""repack_templates table

Revision ID: 0026_repack_templates
Revises: 0025_quarantine_commission
"""
from alembic import op

revision = "0026_repack_templates"
down_revision = "0025_quarantine_commission"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS repack_templates (
          id BIGSERIAL PRIMARY KEY,
          name TEXT NOT NULL,
          source_product_id BIGINT REFERENCES products(id) ON DELETE SET NULL,
          target_product_id BIGINT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
          quantity_factor NUMERIC(18,6) NOT NULL DEFAULT 1,
          loss_factor NUMERIC(18,6) NOT NULL DEFAULT 0,
          target_unit_price NUMERIC(18,4),
          reason TEXT,
          created_by TEXT NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_repack_templates_source ON repack_templates(source_product_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_repack_templates_target ON repack_templates(target_product_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS repack_templates")
