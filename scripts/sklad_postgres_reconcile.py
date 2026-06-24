#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any


try:
    import psycopg
    from psycopg.rows import dict_row
except ModuleNotFoundError:  # pragma: no cover - runtime script dependency
    psycopg = None  # type: ignore[assignment]
    dict_row = None  # type: ignore[assignment]


TABLES = (
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
    parser = argparse.ArgumentParser(
        description="Compare a SKLAD SQLite snapshot with a loaded PostgreSQL database."
    )
    parser.add_argument("sqlite_path", type=Path)
    parser.add_argument("postgres_url")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args()

    if psycopg is None or dict_row is None:
        raise SystemExit("psycopg is required. Install project dependencies first.")

    report = reconcile(args.sqlite_path, args.postgres_url)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print_human(report)
    return 0 if report["ok"] else 1


def reconcile(sqlite_path: Path, postgres_url: str) -> dict[str, Any]:
    if not sqlite_path.exists():
        return {"ok": False, "errors": [f"SQLite database not found: {sqlite_path}"], "warnings": []}

    sqlite_connection = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    sqlite_connection.row_factory = sqlite3.Row
    try:
        with psycopg.connect(postgres_url, row_factory=dict_row) as pg_connection:
            report: dict[str, Any] = {
                "ok": True,
                "sqlite_database": str(sqlite_path),
                "errors": [],
                "warnings": [],
                "counts": {},
                "id_ranges": {},
                "status_counts": {},
                "stock_balance_totals": {},
                "movement_totals": {},
            }
            _compare_counts(sqlite_connection, pg_connection, report)
            _compare_id_ranges(sqlite_connection, pg_connection, report)
            _compare_status_counts(sqlite_connection, pg_connection, report)
            _compare_named_metric(
                report,
                "stock_balance_totals",
                _stock_balance_totals(sqlite_connection),
                _stock_balance_totals(pg_connection),
            )
            _compare_named_metric(
                report,
                "movement_totals",
                _movement_totals(sqlite_connection),
                _movement_totals(pg_connection),
            )
            report["ok"] = not report["errors"]
            return report
    finally:
        sqlite_connection.close()


def _compare_counts(sqlite_connection: Any, pg_connection: Any, report: dict[str, Any]) -> None:
    for table in TABLES:
        sqlite_count = _count(sqlite_connection, table)
        pg_count = _count(pg_connection, table)
        report["counts"][table] = {"sqlite": sqlite_count, "postgres": pg_count}
        if sqlite_count != pg_count:
            report["errors"].append(
                f"Row count mismatch for {table}: sqlite={sqlite_count}, postgres={pg_count}"
            )


def _compare_id_ranges(sqlite_connection: Any, pg_connection: Any, report: dict[str, Any]) -> None:
    for table in TABLES:
        if table == "stock_balances" or not _column_exists(sqlite_connection, table, "id"):
            continue
        sqlite_range = _id_range(sqlite_connection, table)
        pg_range = _id_range(pg_connection, table)
        report["id_ranges"][table] = {"sqlite": sqlite_range, "postgres": pg_range}
        if sqlite_range != pg_range:
            report["errors"].append(
                f"ID range mismatch for {table}: sqlite={sqlite_range}, postgres={pg_range}"
            )


def _compare_status_counts(sqlite_connection: Any, pg_connection: Any, report: dict[str, Any]) -> None:
    for table, columns in STATUS_COLUMNS.items():
        for column in columns:
            metric_name = f"{table}.{column}"
            sqlite_counts = _status_counts(sqlite_connection, table, column)
            pg_counts = _status_counts(pg_connection, table, column)
            report["status_counts"][metric_name] = {
                "sqlite": sqlite_counts,
                "postgres": pg_counts,
            }
            if sqlite_counts != pg_counts:
                report["errors"].append(f"Status count mismatch for {metric_name}")


def _compare_named_metric(
    report: dict[str, Any],
    metric_name: str,
    sqlite_values: dict[str, dict[str, str | int]],
    pg_values: dict[str, dict[str, str | int]],
) -> None:
    report[metric_name] = {"sqlite": sqlite_values, "postgres": pg_values}
    if sqlite_values != pg_values:
        report["errors"].append(f"Aggregate mismatch for {metric_name}")


def _count(connection: Any, table: str) -> int:
    return int(connection.execute(f"SELECT COUNT(*) AS total FROM {table}").fetchone()["total"])


def _id_range(connection: Any, table: str) -> dict[str, int | None]:
    row = connection.execute(f"SELECT MIN(id) AS min_id, MAX(id) AS max_id FROM {table}").fetchone()
    return {
        "min_id": None if row["min_id"] is None else int(row["min_id"]),
        "max_id": None if row["max_id"] is None else int(row["max_id"]),
    }


def _status_counts(connection: Any, table: str, column: str) -> dict[str, int]:
    rows = connection.execute(
        f"SELECT {column} AS value, COUNT(*) AS total FROM {table} GROUP BY {column} ORDER BY {column}"
    ).fetchall()
    return {str(row["value"]): int(row["total"]) for row in rows}


def _stock_balance_totals(connection: Any) -> dict[str, dict[str, str | int]]:
    rows = connection.execute(
        """
        SELECT b.product_id, sb.warehouse_id, sb.quantity, sb.reserved_quantity
        FROM stock_balances sb
        JOIN batches b ON b.id = sb.batch_id
        """
    ).fetchall()
    totals: dict[tuple[int, int], dict[str, Decimal | int]] = defaultdict(
        lambda: {"rows": 0, "quantity": Decimal("0"), "reserved_quantity": Decimal("0")}
    )
    for row in rows:
        key = (int(row["warehouse_id"]), int(row["product_id"]))
        totals[key]["rows"] += 1  # type: ignore[operator]
        totals[key]["quantity"] += _decimal(row["quantity"])  # type: ignore[operator]
        totals[key]["reserved_quantity"] += _decimal(row["reserved_quantity"])  # type: ignore[operator]
    return {
        f"warehouse:{warehouse_id}|product:{product_id}": _stringify_decimal_values(values)
        for (warehouse_id, product_id), values in sorted(totals.items())
    }


def _movement_totals(connection: Any) -> dict[str, dict[str, str | int]]:
    rows = connection.execute(
        """
        SELECT movement_type, warehouse_id, quantity
        FROM stock_movements
        """
    ).fetchall()
    totals: dict[tuple[str, int], dict[str, Decimal | int]] = defaultdict(
        lambda: {"rows": 0, "quantity": Decimal("0")}
    )
    for row in rows:
        key = (str(row["movement_type"]), int(row["warehouse_id"]))
        totals[key]["rows"] += 1  # type: ignore[operator]
        totals[key]["quantity"] += _decimal(row["quantity"])  # type: ignore[operator]
    return {
        f"movement:{movement_type}|warehouse:{warehouse_id}": _stringify_decimal_values(values)
        for (movement_type, warehouse_id), values in sorted(totals.items())
    }


def _column_exists(connection: Any, table: str, column: str) -> bool:
    module = type(connection).__module__
    if module.startswith("sqlite3"):
        return column in {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
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


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value or "0"))


def _stringify_decimal_values(values: dict[str, Decimal | int]) -> dict[str, str | int]:
    result: dict[str, str | int] = {}
    for key, value in values.items():
        result[key] = _format_decimal(value) if isinstance(value, Decimal) else value
    return result


def _format_decimal(value: Decimal) -> str:
    normalized = value.normalize()
    return format(normalized, "f")


def print_human(report: dict[str, Any]) -> None:
    print(f"SQLite: {report.get('sqlite_database')}")
    print(f"OK: {report['ok']}")
    print("Counts:")
    for table, counts in report.get("counts", {}).items():
        marker = "OK" if counts["sqlite"] == counts["postgres"] else "DIFF"
        print(f"  {table}: sqlite={counts['sqlite']} postgres={counts['postgres']} [{marker}]")
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
