"""initial PostgreSQL schema

Revision ID: 0001_initial_postgresql
Revises:
Create Date: 2026-06-09
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0001_initial_postgresql"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql_path = Path(__file__).resolve().parents[2] / "sql" / "0001_initial_postgresql.sql"
    op.execute(sql_path.read_text())


def downgrade() -> None:
    for table_name in (
        "outbox_events",
        "idempotency_keys",
        "abc_xyz_run_items",
        "abc_xyz_runs",
        "notifications",
        "audit_log",
        "inventory_lines",
        "inventory_sessions",
        "reservations",
        "batch_transformations",
        "stock_document_lines",
        "stock_documents",
        "stock_movements",
        "stock_balances",
        "batch_recalls",
        "quarantine_reviews",
        "batches",
        "products",
        "sensor_readings",
        "sensor_devices",
        "warehouses",
        "suppliers",
        "categories",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE")
