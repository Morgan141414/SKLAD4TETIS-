#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_ACTOR_ID = "pg-runtime-smoke"
DEFAULT_ROLE = "warehouse_manager"


class SmokeFailure(RuntimeError):
    pass


@dataclass
class SmokeClient:
    base_url: str
    actor_id: str = DEFAULT_ACTOR_ID
    role: str = DEFAULT_ROLE
    timeout: int = 20
    steps: list[dict[str, Any]] = field(default_factory=list)

    def get(self, path: str, query: dict[str, Any] | None = None) -> Any:
        return self._request("GET", path, query=query)

    def post(self, path: str, payload: dict[str, Any] | None = None, query: dict[str, Any] | None = None) -> Any:
        return self._request("POST", path, payload=payload or {}, query=query)

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
    ) -> Any:
        started = time.monotonic()
        url = self._url(path, query)
        headers = {
            "Accept": "application/json",
            "X-Actor-Id": self.actor_id,
            "X-Actor-Roles": self.role,
        }
        body = None
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = Request(url, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                response_body = response.read().decode("utf-8")
                parsed = json.loads(response_body) if response_body else None
                self.steps.append(
                    {
                        "method": method,
                        "path": path,
                        "status": response.status,
                        "duration_ms": _duration_ms(started),
                    }
                )
                return parsed
        except HTTPError as error:
            details = error.read().decode("utf-8", errors="replace")
            self.steps.append(
                {
                    "method": method,
                    "path": path,
                    "status": error.code,
                    "duration_ms": _duration_ms(started),
                    "error": details,
                }
            )
            raise SmokeFailure(f"{method} {path} returned HTTP {error.code}: {details}") from error
        except URLError as error:
            self.steps.append(
                {
                    "method": method,
                    "path": path,
                    "status": "network_error",
                    "duration_ms": _duration_ms(started),
                    "error": str(error.reason),
                }
            )
            raise SmokeFailure(f"{method} {path} failed: {error.reason}") from error

    def _url(self, path: str, query: dict[str, Any] | None) -> str:
        url = f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"
        if query:
            filtered = {key: value for key, value in query.items() if value is not None}
            if filtered:
                url = f"{url}?{urlencode(filtered)}"
        return url


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a mutating PostgreSQL runtime smoke test against a SKLAD API."
    )
    parser.add_argument("base_url", help="API base URL, for example http://127.0.0.1:8121/api/v1")
    parser.add_argument("--actor-id", default=DEFAULT_ACTOR_ID)
    parser.add_argument("--role", default=DEFAULT_ROLE)
    parser.add_argument("--prefix", default="PG Smoke")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args()

    client = SmokeClient(args.base_url, actor_id=args.actor_id, role=args.role)
    report = run_smoke(client, args.prefix)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print_human(report)
    return 0 if report["ok"] else 1


def run_smoke(client: SmokeClient, prefix: str) -> dict[str, Any]:
    report: dict[str, Any] = {
        "ok": False,
        "base_url": client.base_url,
        "errors": [],
        "warnings": [],
        "ids": {},
        "balances": {},
        "movement_total": 0,
        "audit_total": 0,
        "notification_total": 0,
        "purchase_request_total": 0,
        "steps": client.steps,
    }
    suffix = str(int(time.time() * 1000))

    try:
        readiness = client.get("/health/ready")
        report["readiness"] = readiness
        if readiness.get("backend") != "postgresql":
            raise SmokeFailure(f"API is not running with PostgreSQL backend: {readiness}")

        category = client.post("/categories", {"name": f"{prefix} Category {suffix}"})
        supplier = client.post("/suppliers", {"name": f"{prefix} Supplier {suffix}"})
        source = client.post("/warehouses", {"name": f"{prefix} Source {suffix}"})
        target = client.post("/warehouses", {"name": f"{prefix} Target {suffix}"})
        product = client.post(
            "/products",
            {
                "name": f"{prefix} Product {suffix}",
                "sku": f"PG-SMOKE-{suffix}",
                "unit": "pcs",
                "category_id": category["id"],
                "reorder_point": "20",
                "safety_stock": "2",
            },
        )
        batch = client.post(
            "/receipts",
            {
                "product_id": product["id"],
                "supplier_id": supplier["id"],
                "warehouse_id": source["id"],
                "quantity": "18",
                "unit_price": "100",
                "lot": f"PG-SMOKE-LOT-{suffix}",
                "expires_on": "2027-12-31",
                "quarantine": False,
            },
        )
        reservation = client.post(
            "/reservations",
            {
                "batch_id": batch["id"],
                "warehouse_id": source["id"],
                "quantity": "4",
                "reserved_for": f"{prefix} Reservation {suffix}",
            },
        )
        used_reservation = client.post(
            f"/reservations/{reservation['id']}/use",
            {"reason": "Runtime smoke reserved issue"},
        )
        transfer_document = client.post(
            "/stock-documents/transfers",
            {
                "source_warehouse_id": source["id"],
                "lines": [
                    {
                        "batch_id": batch["id"],
                        "target_warehouse_id": target["id"],
                        "quantity": "3",
                        "reason": "Runtime smoke transfer",
                    }
                ],
            },
        )
        posted_transfer = client.post(f"/stock-documents/{transfer_document['id']}/post")
        writeoff = client.post(
            "/write-offs",
            {
                "batch_id": batch["id"],
                "warehouse_id": target["id"],
                "quantity": "1",
                "reason": "Runtime smoke direct writeoff",
            },
        )
        notifications = client.post(
            "/notifications/generate-low-stock",
            query={"warehouse_id": source["id"]},
        )
        purchase_requests = client.post(
            "/purchase-requests/generate",
            query={"warehouse_id": source["id"]},
        )
        balances_page = client.get("/balances", query={"product_id": product["id"]})
        movements_page = client.get("/stock-movements", query={"product_id": product["id"]})
        audit_page = client.get("/audit-log", query={"warehouse_id": source["id"]})

        ids = {
            "category_id": category["id"],
            "supplier_id": supplier["id"],
            "source_warehouse_id": source["id"],
            "target_warehouse_id": target["id"],
            "product_id": product["id"],
            "batch_id": batch["id"],
            "reservation_id": reservation["id"],
            "transfer_document_id": transfer_document["id"],
            "writeoff_id": writeoff["id"],
        }
        report["ids"] = ids
        report["balances"] = _balances_by_warehouse(balances_page["items"])
        report["movement_total"] = int(movements_page["total"])
        report["audit_total"] = int(audit_page["total"])
        report["notification_total"] = len(notifications)
        report["purchase_request_total"] = len(purchase_requests)

        _assert_equal(used_reservation["status"], "used", "reservation should be used")
        _assert_equal(posted_transfer["status"], "posted", "transfer document should be posted")
        _assert_balance(report["balances"], source["id"], "11")
        _assert_balance(report["balances"], target["id"], "2")
        if report["movement_total"] < 5:
            raise SmokeFailure(f"Expected at least 5 stock movements, got {report['movement_total']}")
        if not notifications:
            raise SmokeFailure("Expected at least one low-stock notification")
        if not purchase_requests:
            raise SmokeFailure("Expected at least one purchase request")

        report["ok"] = True
    except Exception as error:
        report["errors"].append(str(error))

    return report


def _balances_by_warehouse(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(item["warehouse_id"]): item for item in items}


def _assert_equal(actual: Any, expected: Any, message: str) -> None:
    if actual != expected:
        raise SmokeFailure(f"{message}: expected {expected!r}, got {actual!r}")


def _assert_balance(balances: dict[str, dict[str, Any]], warehouse_id: int, free_quantity: str) -> None:
    key = str(warehouse_id)
    if key not in balances:
        raise SmokeFailure(f"Balance row for warehouse {warehouse_id} is missing")
    actual = Decimal(str(balances[key]["free_quantity"]))
    expected = Decimal(free_quantity)
    if actual != expected:
        raise SmokeFailure(
            f"Unexpected free balance for warehouse {warehouse_id}: expected {expected}, got {actual}"
        )


def _duration_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def print_human(report: dict[str, Any]) -> None:
    print(f"Base URL: {report['base_url']}")
    print(f"OK: {report['ok']}")
    if report.get("readiness"):
        print(f"Backend: {report['readiness'].get('backend')}")
    print(f"Movements: {report['movement_total']}")
    print(f"Audit rows: {report['audit_total']}")
    print(f"Notifications: {report['notification_total']}")
    print(f"Purchase requests: {report['purchase_request_total']}")
    if report["errors"]:
        print("Errors:")
        for error in report["errors"]:
            print(f"- {error}")


if __name__ == "__main__":
    sys.exit(main())
