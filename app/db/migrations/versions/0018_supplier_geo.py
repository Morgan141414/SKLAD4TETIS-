"""supplier geo fields and shipments table

Revision ID: 0018_supplier_geo
Revises: 0017_users
Create Date: 2026-06-16
"""
from alembic import op

revision = "0018_supplier_geo"
down_revision = "0017_users"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.execute("""
        ALTER TABLE suppliers
          ADD COLUMN IF NOT EXISTS lat NUMERIC(9,6),
          ADD COLUMN IF NOT EXISTS lng NUMERIC(9,6),
          ADD COLUMN IF NOT EXISTS city TEXT,
          ADD COLUMN IF NOT EXISTS delivery_days INTEGER
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS shipments (
          id BIGSERIAL PRIMARY KEY,
          supplier_id BIGINT NOT NULL REFERENCES suppliers(id),
          reference TEXT,
          status TEXT NOT NULL DEFAULT 'in_transit',
          origin_city TEXT,
          origin_lat NUMERIC(9,6),
          origin_lng NUMERIC(9,6),
          destination_warehouse_id BIGINT,
          current_city TEXT,
          current_lat NUMERIC(9,6),
          current_lng NUMERIC(9,6),
          estimated_arrival DATE,
          notes TEXT,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_shipments_supplier ON shipments(supplier_id)")

def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS shipments")
    op.execute("""
        ALTER TABLE suppliers
          DROP COLUMN IF EXISTS lat,
          DROP COLUMN IF EXISTS lng,
          DROP COLUMN IF EXISTS city,
          DROP COLUMN IF EXISTS delivery_days
    """)
