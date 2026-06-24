"""MIS clinic/room mapping on warehouses + procedure consumption templates

Revision ID: 0029_mis_procedure_consumption
Revises: 0028_supplier_portal_access
"""
from alembic import op

revision = "0029_mis_procedure_consumption"
down_revision = "0028_supplier_portal_access"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE warehouses ADD COLUMN IF NOT EXISTS mis_clinic_id TEXT")
    op.execute("ALTER TABLE warehouses ADD COLUMN IF NOT EXISTS mis_room_id TEXT")
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_warehouses_mis_clinic_room
        ON warehouses(mis_clinic_id, mis_room_id)
        WHERE mis_clinic_id IS NOT NULL AND mis_room_id IS NOT NULL
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS procedure_consumption_templates (
          id BIGSERIAL PRIMARY KEY,
          mis_clinic_id TEXT NOT NULL,
          service_code TEXT NOT NULL,
          name TEXT NOT NULL,
          created_by TEXT NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (mis_clinic_id, service_code)
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS procedure_consumption_items (
          id BIGSERIAL PRIMARY KEY,
          template_id BIGINT NOT NULL REFERENCES procedure_consumption_templates(id) ON DELETE CASCADE,
          product_id BIGINT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
          quantity NUMERIC(18,3) NOT NULL
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_procedure_consumption_items_template "
        "ON procedure_consumption_items(template_id)"
    )

    op.execute("""
        CREATE TABLE IF NOT EXISTS mis_processed_events (
          id BIGSERIAL PRIMARY KEY,
          mis_event_id TEXT NOT NULL UNIQUE,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS mis_processed_events")
    op.execute("DROP TABLE IF EXISTS procedure_consumption_items")
    op.execute("DROP TABLE IF EXISTS procedure_consumption_templates")
    op.execute("DROP INDEX IF EXISTS uq_warehouses_mis_clinic_room")
    op.execute("ALTER TABLE warehouses DROP COLUMN IF EXISTS mis_room_id")
    op.execute("ALTER TABLE warehouses DROP COLUMN IF EXISTS mis_clinic_id")
