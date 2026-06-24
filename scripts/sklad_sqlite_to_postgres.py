#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any


try:
    import psycopg
    from psycopg.rows import dict_row
    from psycopg.types.json import Jsonb
except ModuleNotFoundError:  # pragma: no cover - runtime script dependency
    psycopg = None  # type: ignore[assignment]
    dict_row = None  # type: ignore[assignment]
    Jsonb = None  # type: ignore[assignment]


TABLE_ORDER = (
    "categories",
    "suppliers",
    "warehouses",
    "products",
    "batches",
    "stock_balances",
    "stock_documents",
    "stock_document_lines",
    "stock_movements",
    "reservations",
    "inventory_sessions",
    "inventory_lines",
    "audit_log",
    "notifications",
    "purchase_requests",
    "idempotency_keys",
)

BOOLEAN_COLUMNS = {
    ("warehouses", "inventory_lock"),
    ("products", "is_controlled"),
    ("stock_document_lines", "quarantine"),
    ("notifications", "is_read"),
}

JSON_COLUMNS = {
    ("audit_log", "payload"),
    ("idempotency_keys", "response_body"),
}

DECIMAL_COLUMNS = {
    ("products", "reorder_point"),
    ("products", "safety_stock"),
    ("batches", "unit_price"),
    ("stock_balances", "quantity"),
    ("stock_balances", "reserved_quantity"),
    ("stock_movements", "quantity"),
    ("stock_document_lines", "quantity"),
    ("stock_document_lines", "unit_price"),
    ("reservations", "quantity"),
    ("inventory_lines", "expected_quantity"),
    ("inventory_lines", "actual_quantity"),
    ("inventory_lines", "difference_quantity"),
    ("purchase_requests", "current_free_quantity"),
    ("purchase_requests", "reorder_point"),
    ("purchase_requests", "safety_stock"),
    ("purchase_requests", "recommended_quantity"),
}

DATE_COLUMNS = {
    ("batches", "expires_on"),
    ("stock_document_lines", "expires_on"),
}

TIMESTAMPTZ_COLUMNS = {
    ("batches", "received_at"),
    ("stock_movements", "created_at"),
    ("stock_documents", "created_at"),
    ("stock_documents", "posted_at"),
    ("reservations", "expires_at"),
    ("reservations", "created_at"),
    ("inventory_sessions", "started_at"),
    ("inventory_sessions", "posted_at"),
    ("inventory_sessions", "cancelled_at"),
    ("audit_log", "created_at"),
    ("notifications", "created_at"),
    ("notifications", "read_at"),
    ("purchase_requests", "created_at"),
    ("idempotency_keys", "created_at"),
    ("idempotency_keys", "locked_at"),
    ("idempotency_keys", "expires_at"),
}

SERIAL_TABLES = tuple(table for table in TABLE_ORDER if table != "stock_balances")


def main() -> int:
    parser = argparse.ArgumentParser(description="Load a SKLAD SQLite snapshot into PostgreSQL.")
    parser.add_argument("sqlite_path", type=Path)
    parser.add_argument("postgres_url")
    parser.add_argument("--truncate", action="store_true", help="Truncate target SKLAD tables first.")
    args = parser.parse_args()

    if psycopg is None or dict_row is None or Jsonb is None:
        raise SystemExit("psycopg is required. Install project dependencies first.")

    sqlite_connection = sqlite3.connect(args.sqlite_path)
    sqlite_connection.row_factory = sqlite3.Row
    try:
        with psycopg.connect(args.postgres_url, row_factory=dict_row) as pg_connection:
            with pg_connection.transaction():
                if args.truncate:
                    truncate_tables(pg_connection)
                copied = copy_tables(sqlite_connection, pg_connection)
                reset_sequences(pg_connection)
            print(json.dumps({"copied": copied}, ensure_ascii=False, indent=2, sort_keys=True))
    finally:
        sqlite_connection.close()
    return 0


def truncate_tables(connection: Any) -> None:
    table_list = ", ".join(reversed(TABLE_ORDER + ("outbox_events",)))
    connection.execute(f"TRUNCATE TABLE {table_list} RESTART IDENTITY CASCADE")


def copy_tables(sqlite_connection: sqlite3.Connection, pg_connection: Any) -> dict[str, int]:
    copied: dict[str, int] = {}
    for table in TABLE_ORDER:
        rows = sqlite_connection.execute(f"SELECT * FROM {table}").fetchall()
        if not rows:
            copied[table] = 0
            continue
        columns = rows[0].keys()
        placeholders = ", ".join(["%s"] * len(columns))
        column_list = ", ".join(columns)
        query = f"INSERT INTO {table} ({column_list}) VALUES ({placeholders})"
        for row in rows:
            pg_connection.execute(
                query,
                tuple(convert_value(table, column, row[column]) for column in columns),
            )
        copied[table] = len(rows)
    return copied


def convert_value(table: str, column: str, value: Any) -> Any:
    if value is None:
        return None
    key = (table, column)
    if key in BOOLEAN_COLUMNS:
        return bool(value)
    if key in JSON_COLUMNS:
        return Jsonb(json.loads(value)) if value else None
    if key in DECIMAL_COLUMNS:
        return Decimal(str(value))
    if key in DATE_COLUMNS:
        return date.fromisoformat(str(value)) if value else None
    if key in TIMESTAMPTZ_COLUMNS:
        return datetime.fromisoformat(str(value)) if value else None
    return value


def reset_sequences(connection: Any) -> None:
    for table in SERIAL_TABLES:
        if not column_exists(connection, table, "id"):
            continue
        connection.execute(
            """
            SELECT setval(
              pg_get_serial_sequence(%s, 'id'),
              COALESCE((SELECT MAX(id) FROM """ + table + """), 1),
              (SELECT COUNT(*) > 0 FROM """ + table + """)
            )
            """,
            (table,),
        )


def column_exists(connection: Any, table: str, column: str) -> bool:
    row = connection.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = %s
          AND column_name = %s
        """,
        (table, column),
    ).fetchone()
    return row is not None


if __name__ == "__main__":
    raise SystemExit(main())
