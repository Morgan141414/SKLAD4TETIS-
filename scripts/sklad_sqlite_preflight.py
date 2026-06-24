#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


TABLES = (
    "categories",
    "suppliers",
    "warehouses",
    "products",
    "batches",
    "stock_balances",
    "stock_movements",
    "stock_documents",
    "stock_document_lines",
    "reservations",
    "inventory_sessions",
    "inventory_lines",
    "audit_log",
    "notifications",
    "purchase_requests",
    "idempotency_keys",
)

DECIMAL_COLUMNS = {
    "products": ("reorder_point", "safety_stock"),
    "batches": ("unit_price",),
    "stock_balances": ("quantity", "reserved_quantity"),
    "stock_movements": ("quantity",),
    "stock_document_lines": ("quantity", "unit_price"),
    "reservations": ("quantity",),
    "inventory_lines": ("expected_quantity", "actual_quantity", "difference_quantity"),
    "purchase_requests": (
        "current_free_quantity",
        "reorder_point",
        "safety_stock",
        "recommended_quantity",
    ),
}

STATUS_COLUMNS = {
    "batches": ("status",),
    "stock_movements": ("movement_type",),
    "stock_documents": ("document_type", "status"),
    "reservations": ("status",),
    "inventory_sessions": ("status",),
    "notifications": ("notification_type",),
    "purchase_requests": ("status",),
    "idempotency_keys": ("status",),
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit a SKLAD SQLite DB before PostgreSQL migration.")
    parser.add_argument("sqlite_path", type=Path)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args()

    report = audit(args.sqlite_path)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print_human(report)
    return 0 if report["ok"] else 1


def audit(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"ok": False, "errors": [f"SQLite database not found: {path}"], "warnings": []}

    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        report: dict[str, Any] = {
            "ok": True,
            "database": str(path),
            "errors": [],
            "warnings": [],
            "counts": {},
            "distinct_values": {},
            "constraint_checks": {},
        }
        _integrity_checks(connection, report)
        _counts(connection, report)
        _distinct_values(connection, report)
        _decimal_checks(connection, report)
        _json_checks(connection, report)
        _business_checks(connection, report)
        report["ok"] = not report["errors"]
        return report
    finally:
        connection.close()


def _integrity_checks(connection: sqlite3.Connection, report: dict[str, Any]) -> None:
    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    report["integrity_check"] = integrity
    if integrity != "ok":
        report["errors"].append(f"PRAGMA integrity_check failed: {integrity}")

    fk_rows = [dict(row) for row in connection.execute("PRAGMA foreign_key_check").fetchall()]
    report["foreign_key_check"] = fk_rows
    if fk_rows:
        report["errors"].append(f"Foreign key check returned {len(fk_rows)} rows")


def _counts(connection: sqlite3.Connection, report: dict[str, Any]) -> None:
    for table in TABLES:
        if not _table_exists(connection, table):
            report["warnings"].append(f"Missing table: {table}")
            continue
        report["counts"][table] = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _distinct_values(connection: sqlite3.Connection, report: dict[str, Any]) -> None:
    for table, columns in STATUS_COLUMNS.items():
        if not _table_exists(connection, table):
            continue
        for column in columns:
            values = [
                row[0]
                for row in connection.execute(
                    f"SELECT DISTINCT {column} FROM {table} ORDER BY {column}"
                ).fetchall()
            ]
            report["distinct_values"][f"{table}.{column}"] = values


def _decimal_checks(connection: sqlite3.Connection, report: dict[str, Any]) -> None:
    invalid: list[dict[str, Any]] = []
    negative: list[dict[str, Any]] = []
    for table, columns in DECIMAL_COLUMNS.items():
        if not _table_exists(connection, table):
            continue
        id_column = "id" if _column_exists(connection, table, "id") else "rowid"
        for column in columns:
            if not _column_exists(connection, table, column):
                continue
            rows = connection.execute(
                f"SELECT {id_column} AS row_id, {column} FROM {table} WHERE {column} IS NOT NULL"
            ).fetchall()
            for row in rows:
                try:
                    value = Decimal(str(row[column]))
                except (InvalidOperation, ValueError):
                    invalid.append({"table": table, "column": column, "row_id": row["row_id"]})
                    continue
                if column not in {"difference_quantity"} and value < 0:
                    negative.append({"table": table, "column": column, "row_id": row["row_id"]})
    if invalid:
        report["errors"].append(f"Invalid decimal values: {len(invalid)}")
    if negative:
        report["errors"].append(f"Negative decimal values: {len(negative)}")
    report["constraint_checks"]["invalid_decimals"] = invalid[:50]
    report["constraint_checks"]["negative_decimals"] = negative[:50]


def _json_checks(connection: sqlite3.Connection, report: dict[str, Any]) -> None:
    invalid: list[dict[str, Any]] = []
    for table, column in (("audit_log", "payload"), ("idempotency_keys", "response_body")):
        if not _table_exists(connection, table) or not _column_exists(connection, table, column):
            continue
        rows = connection.execute(
            f"SELECT id, {column} FROM {table} WHERE {column} IS NOT NULL"
        ).fetchall()
        for row in rows:
            try:
                json.loads(row[column])
            except (TypeError, json.JSONDecodeError):
                invalid.append({"table": table, "column": column, "id": row["id"]})
    if invalid:
        report["errors"].append(f"Invalid JSON values: {len(invalid)}")
    report["constraint_checks"]["invalid_json"] = invalid[:50]


def _business_checks(connection: sqlite3.Connection, report: dict[str, Any]) -> None:
    checks = {
        "reserved_gt_quantity": """
            SELECT COUNT(*) FROM stock_balances
            WHERE CAST(reserved_quantity AS REAL) > CAST(quantity AS REAL)
        """,
        "non_positive_movements": """
            SELECT COUNT(*) FROM stock_movements
            WHERE CAST(quantity AS REAL) <= 0
        """,
        "duplicate_unread_low_stock": """
            SELECT COUNT(*) FROM (
              SELECT warehouse_id, product_id
              FROM notifications
              WHERE notification_type = 'low_stock' AND is_read = 0
              GROUP BY warehouse_id, product_id
              HAVING COUNT(*) > 1
            )
        """,
        "duplicate_unread_expiry": """
            SELECT COUNT(*) FROM (
              SELECT warehouse_id, batch_id
              FROM notifications
              WHERE notification_type = 'expiry' AND is_read = 0
              GROUP BY warehouse_id, batch_id
              HAVING COUNT(*) > 1
            )
        """,
        "duplicate_draft_purchase_requests": """
            SELECT COUNT(*) FROM (
              SELECT warehouse_id, product_id
              FROM purchase_requests
              WHERE status = 'draft'
              GROUP BY warehouse_id, product_id
              HAVING COUNT(*) > 1
            )
        """,
    }
    for name, query in checks.items():
        try:
            count = connection.execute(query).fetchone()[0]
        except sqlite3.OperationalError as error:
            report["warnings"].append(f"Skipped {name}: {error}")
            continue
        report["constraint_checks"][name] = count
        if count:
            report["errors"].append(f"{name} returned {count}")


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()
        is not None
    )


def _column_exists(connection: sqlite3.Connection, table: str, column: str) -> bool:
    return column in {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}


def print_human(report: dict[str, Any]) -> None:
    print(f"Database: {report.get('database')}")
    print(f"OK: {report['ok']}")
    print(f"Integrity: {report.get('integrity_check')}")
    print("Counts:")
    for table, count in report.get("counts", {}).items():
        print(f"  {table}: {count}")
    if report["warnings"]:
        print("Warnings:")
        for warning in report["warnings"]:
            print(f"  - {warning}")
    if report["errors"]:
        print("Errors:")
        for error in report["errors"]:
            print(f"  - {error}")


if __name__ == "__main__":
    raise SystemExit(main())
