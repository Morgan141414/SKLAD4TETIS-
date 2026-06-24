"""add repack documents and batch transformations

Revision ID: 0006_batch_transformations
Revises: 0005_sensor_conditions
Create Date: 2026-06-13
"""

from __future__ import annotations

from alembic import op


revision = "0006_batch_transformations"
down_revision = "0005_sensor_conditions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in (
        "ALTER TABLE stock_document_lines ADD COLUMN IF NOT EXISTS target_product_id BIGINT REFERENCES products(id)",
        "ALTER TABLE stock_document_lines ADD COLUMN IF NOT EXISTS target_quantity NUMERIC(18, 3)",
        "ALTER TABLE stock_document_lines ADD COLUMN IF NOT EXISTS conversion_factor NUMERIC(18, 6)",
        "ALTER TABLE stock_document_lines ADD COLUMN IF NOT EXISTS loss_quantity NUMERIC(18, 3)",
        "ALTER TABLE stock_document_lines ADD COLUMN IF NOT EXISTS target_unit_price NUMERIC(18, 4)",
        "ALTER TABLE stock_document_lines ADD COLUMN IF NOT EXISTS target_lot TEXT",
        "ALTER TABLE stock_document_lines ADD COLUMN IF NOT EXISTS target_expires_on DATE",
    ):
        op.execute(statement)
    op.execute(
        """
        ALTER TABLE stock_movements
        DROP CONSTRAINT IF EXISTS stock_movements_type_check
        """
    )
    op.execute(
        """
        ALTER TABLE stock_movements
        ADD CONSTRAINT stock_movements_type_check CHECK (
          movement_type IN (
            'receipt',
            'write_off',
            'reserve',
            'release_reserve',
            'transfer_out',
            'transfer_in',
            'return_to_supplier',
            'repack_out',
            'repack_in'
          )
        )
        """
    )
    op.execute(
        """
        ALTER TABLE stock_documents
        DROP CONSTRAINT IF EXISTS stock_documents_type_check
        """
    )
    op.execute(
        """
        ALTER TABLE stock_documents
        ADD CONSTRAINT stock_documents_type_check CHECK (
          document_type IN (
            'receipt',
            'write_off',
            'transfer',
            'department_return',
            'supplier_return',
            'repack'
          )
        )
        """
    )
    op.execute(
        """
        ALTER TABLE stock_documents
        DROP CONSTRAINT IF EXISTS stock_documents_supplier_matches_type
        """
    )
    op.execute(
        """
        ALTER TABLE stock_documents
        ADD CONSTRAINT stock_documents_supplier_matches_type CHECK (
          (document_type IN ('receipt', 'supplier_return') AND supplier_id IS NOT NULL)
          OR (document_type IN ('write_off', 'transfer', 'department_return', 'repack') AND supplier_id IS NULL)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS batch_transformations (
          id BIGSERIAL PRIMARY KEY,
          document_id BIGINT REFERENCES stock_documents(id),
          source_batch_id BIGINT NOT NULL REFERENCES batches(id),
          target_batch_id BIGINT NOT NULL REFERENCES batches(id),
          warehouse_id BIGINT NOT NULL REFERENCES warehouses(id),
          source_product_id BIGINT NOT NULL REFERENCES products(id),
          target_product_id BIGINT NOT NULL REFERENCES products(id),
          source_quantity NUMERIC(18, 3) NOT NULL,
          target_quantity NUMERIC(18, 3) NOT NULL,
          conversion_factor NUMERIC(18, 6) NOT NULL,
          loss_quantity NUMERIC(18, 3) NOT NULL DEFAULT 0,
          reason TEXT,
          created_by TEXT NOT NULL,
          created_at TIMESTAMPTZ NOT NULL,
          CONSTRAINT batch_transformations_source_quantity_positive CHECK (source_quantity > 0),
          CONSTRAINT batch_transformations_target_quantity_positive CHECK (target_quantity > 0),
          CONSTRAINT batch_transformations_conversion_positive CHECK (conversion_factor > 0),
          CONSTRAINT batch_transformations_loss_non_negative CHECK (loss_quantity >= 0)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_batch_transformations_source_batch
          ON batch_transformations(source_batch_id, created_at DESC, id DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_batch_transformations_target_batch
          ON batch_transformations(target_batch_id, created_at DESC, id DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_batch_transformations_document
          ON batch_transformations(document_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_batch_transformations_warehouse_created
          ON batch_transformations(warehouse_id, created_at DESC, id DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_batch_transformations_warehouse_created")
    op.execute("DROP INDEX IF EXISTS idx_batch_transformations_document")
    op.execute("DROP INDEX IF EXISTS idx_batch_transformations_target_batch")
    op.execute("DROP INDEX IF EXISTS idx_batch_transformations_source_batch")
    op.execute("DROP TABLE IF EXISTS batch_transformations")
