"""MIS (Medical Information System) integration via webhook."""
import logging
import json
import urllib.request
from typing import Any
from datetime import datetime, UTC

logger = logging.getLogger(__name__)


class MISClient:
    """Sends stock events to MIS via HTTP webhook."""

    def __init__(self, webhook_url: str, api_key: str | None = None, timeout: int = 15) -> None:
        self.webhook_url = webhook_url
        self.api_key = api_key
        self.timeout = timeout

    def notify_writeoff(self, writeoff: dict[str, Any]) -> bool:
        """Notify MIS about a write-off operation."""
        payload = {
            "event": "stock.writeoff",
            "timestamp": datetime.now(UTC).isoformat(),
            "data": {
                "batch_id": writeoff.get("batch_id"),
                "product_name": writeoff.get("product_name", ""),
                "lot": writeoff.get("lot", ""),
                "quantity": float(writeoff.get("quantity", 0)),
                "unit": writeoff.get("unit", "шт"),
                "warehouse_id": writeoff.get("warehouse_id"),
                "warehouse_name": writeoff.get("warehouse_name", ""),
                "patient_id": writeoff.get("patient_id"),
                "doctor_id": writeoff.get("doctor_id"),
                "medical_record_no": writeoff.get("medical_record_no"),
                "reason": writeoff.get("reason", ""),
                "actor_id": writeoff.get("actor_id", ""),
                "movement_id": writeoff.get("id"),
            },
        }
        return self._send(payload)

    def notify_receipt(self, receipt: dict[str, Any]) -> bool:
        """Notify MIS about a new stock receipt."""
        payload = {
            "event": "stock.receipt",
            "timestamp": datetime.now(UTC).isoformat(),
            "data": {
                "batch_id": receipt.get("id"),
                "product_id": receipt.get("product_id"),
                "lot": receipt.get("lot", ""),
                "quantity": float(receipt.get("quantity", 0)),
                "unit_price": float(receipt.get("unit_price", 0)),
                "expires_on": receipt.get("expires_on"),
                "warehouse_id": receipt.get("warehouse_id"),
                "supplier_id": receipt.get("supplier_id"),
            },
        }
        return self._send(payload)

    def notify_transfer(self, transfer: dict[str, Any]) -> bool:
        """Notify MIS about a stock transfer."""
        payload = {
            "event": "stock.transfer",
            "timestamp": datetime.now(UTC).isoformat(),
            "data": {
                "batch_id": transfer.get("batch_id"),
                "quantity": float(transfer.get("quantity", 0)),
                "source_warehouse_id": transfer.get("source_warehouse_id"),
                "target_warehouse_id": transfer.get("target_warehouse_id"),
                "reason": transfer.get("reason", ""),
            },
        }
        return self._send(payload)

    def _send(self, payload: dict[str, Any]) -> bool:
        data = json.dumps(payload).encode()
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        req = urllib.request.Request(self.webhook_url, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                ok = 200 <= resp.status < 300
                if not ok:
                    logger.warning("MIS webhook returned HTTP %s", resp.status)
                return ok
        except Exception as e:
            logger.warning("MIS webhook failed: %s", e)
            return False
