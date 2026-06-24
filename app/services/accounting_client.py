"""Accounting system integration (1C / generic webhook)."""
import logging
import json
import urllib.request
import hmac
import hashlib
from typing import Any
from datetime import datetime, UTC

logger = logging.getLogger(__name__)


class AccountingClient:
    """Sends warehouse events to accounting system via webhook."""

    def __init__(self, webhook_url: str, secret: str | None = None, timeout: int = 15) -> None:
        self.webhook_url = webhook_url
        self.secret = secret
        self.timeout = timeout

    def post_writeoff(self, movement: dict[str, Any]) -> bool:
        """Post a write-off to accounting."""
        payload = {
            "type": "writeoff",
            "date": datetime.now(UTC).strftime("%Y-%m-%d"),
            "document_no": f"WO-{movement.get('id', 0):06d}",
            "lines": [{
                "product_id": movement.get("product_id") or movement.get("batch_id"),
                "quantity": float(movement.get("quantity", 0)),
                "unit_price": float(movement.get("unit_price", 0)),
                "amount": float(movement.get("quantity", 0)) * float(movement.get("unit_price", 0)),
                "warehouse_id": movement.get("warehouse_id"),
                "reason": movement.get("reason", ""),
            }],
        }
        return self._send(payload)

    def post_receipt(self, batch: dict[str, Any]) -> bool:
        """Post a goods receipt to accounting."""
        qty = float(batch.get("quantity", 0))
        price = float(batch.get("unit_price", 0))
        payload = {
            "type": "receipt",
            "date": datetime.now(UTC).strftime("%Y-%m-%d"),
            "document_no": f"GR-{batch.get('id', 0):06d}",
            "lines": [{
                "product_id": batch.get("product_id"),
                "lot": batch.get("lot", ""),
                "quantity": qty,
                "unit_price": price,
                "amount": qty * price,
                "supplier_id": batch.get("supplier_id"),
                "warehouse_id": batch.get("warehouse_id"),
                "expires_on": batch.get("expires_on"),
            }],
        }
        return self._send(payload)

    def _send(self, payload: dict[str, Any]) -> bool:
        data = json.dumps(payload, ensure_ascii=False).encode()
        headers = {"Content-Type": "application/json; charset=utf-8"}
        if self.secret:
            sig = hmac.new(self.secret.encode(), data, hashlib.sha256).hexdigest()
            headers["X-Signature-SHA256"] = sig
        req = urllib.request.Request(self.webhook_url, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                ok = 200 <= resp.status < 300
                if not ok:
                    logger.warning("Accounting webhook HTTP %s", resp.status)
                return ok
        except Exception as e:
            logger.warning("Accounting webhook error: %s", e)
            return False
