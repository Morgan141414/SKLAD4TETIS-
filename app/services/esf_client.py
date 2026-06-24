"""IS-ESF integration client for Kazakhstan electronic invoicing."""
import logging
import json
import urllib.request
import urllib.parse
from typing import Any
from datetime import datetime, UTC

logger = logging.getLogger(__name__)

ESF_SANDBOX_URL = "https://esf.gov.kz:8443/esf-web/rest/api"
ESF_PROD_URL = "https://esf.gov.kz:8443/esf-web/rest/api"


class ESFClient:
    """Client for Kazakhstan IS-ESF API."""

    def __init__(self, base_url: str, session_id: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.session_id = session_id

    def authenticate(self, username: str, password: str) -> str:
        """Authenticate and return session ID."""
        url = f"{self.base_url}/sessions"
        payload = json.dumps({"username": username, "password": password}).encode()
        req = urllib.request.Request(url, data=payload,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
                self.session_id = data.get("sessionId") or data.get("session_id", "")
                return self.session_id
        except Exception as e:
            raise RuntimeError(f"ESF authentication failed: {e}") from e

    def get_invoice(self, invoice_id: str) -> dict[str, Any]:
        """Get invoice by ID."""
        url = f"{self.base_url}/invoices/{urllib.parse.quote(invoice_id)}"
        return self._get(url)

    def create_invoice(self, invoice_data: dict[str, Any]) -> dict[str, Any]:
        """Create a new electronic invoice."""
        url = f"{self.base_url}/invoices"
        return self._post(url, invoice_data)

    def get_invoices(self, date_from: str, date_to: str, page: int = 0, size: int = 20) -> dict[str, Any]:
        """List invoices in date range."""
        params = urllib.parse.urlencode({"dateFrom": date_from, "dateTo": date_to,
                                         "page": page, "size": size})
        url = f"{self.base_url}/invoices?{params}"
        return self._get(url)

    def _get(self, url: str) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if self.session_id:
            headers["Cookie"] = f"JSESSIONID={self.session_id}"
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except Exception as e:
            raise RuntimeError(f"ESF GET failed: {e}") from e

    def _post(self, url: str, data: dict[str, Any]) -> dict[str, Any]:
        payload = json.dumps(data).encode()
        headers = {"Content-Type": "application/json"}
        if self.session_id:
            headers["Cookie"] = f"JSESSIONID={self.session_id}"
        req = urllib.request.Request(url, data=payload, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except Exception as e:
            raise RuntimeError(f"ESF POST failed: {e}") from e


def receipt_to_esf_invoice(receipt_data: dict[str, Any], seller_bin: str) -> dict[str, Any]:
    """Convert a warehouse receipt to ESF invoice format (stub for customization)."""
    now = datetime.now(UTC)
    return {
        "invoiceType": "ORDINARY_INVOICE",
        "invoiceDate": now.strftime("%Y-%m-%d"),
        "seller": {"tin": seller_bin},
        "buyer": {"tin": receipt_data.get("buyer_bin", "")},
        "invoiceLines": [
            {
                "lineNumber": 1,
                "productName": receipt_data.get("product_name", ""),
                "unitCode": "796",
                "unitName": "шт",
                "quantity": float(receipt_data.get("quantity", 1)),
                "unitPrice": float(receipt_data.get("unit_price", 0)),
                "lineTotal": float(receipt_data.get("quantity", 1)) * float(receipt_data.get("unit_price", 0)),
            }
        ],
    }
