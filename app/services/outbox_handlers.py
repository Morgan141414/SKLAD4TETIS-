"""Concrete outbox event handlers.

Each handler receives the event payload (a dict) and raises on failure so the
relay can retry the delivery.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)


def _settings() -> Any:
    from app.core.config import get_settings

    return get_settings()


def handle_marketplace_inquiry_created(payload: dict[str, Any]) -> None:
    settings = _settings()
    if not settings.smtp_host:
        return
    from app.services.email_notifier import notify_new_inquiry

    notify_new_inquiry(
        settings,
        payload["supplier_email"],
        payload.get("supplier_name", ""),
        payload.get("product_name", ""),
        payload.get("quantity", 0),
        payload.get("unit", ""),
        payload.get("notes"),
        payload.get("inquiry_id"),
    )


def handle_marketplace_inquiry_responded(payload: dict[str, Any]) -> None:
    settings = _settings()
    if not settings.smtp_host:
        return
    from app.services.email_notifier import notify_inquiry_response

    notify_inquiry_response(
        settings,
        payload["buyer_email"],
        payload.get("supplier_name", ""),
        payload.get("product_name", ""),
        payload.get("response_text", ""),
        payload.get("inquiry_id"),
    )


def handle_purchase_request_ordered(payload: dict[str, Any]) -> None:
    settings = _settings()
    url = settings.accounting_webhook_url
    if not url:
        return
    body = json.dumps(
        {
            "event": "purchase_request.ordered",
            "id": payload.get("id"),
            "warehouse_id": payload.get("warehouse_id"),
            "product_id": payload.get("product_id"),
            "recommended_quantity": str(payload.get("recommended_quantity") or 0),
            "reason": payload.get("reason"),
            "created_at": payload.get("created_at"),
        }
    ).encode()
    headers = {"Content-Type": "application/json"}
    secret = settings.accounting_webhook_secret
    if secret:
        sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        headers["X-Sklad-Signature"] = sig
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    urllib.request.urlopen(request, timeout=10).close()


HANDLERS: dict[str, Any] = {
    "marketplace.inquiry.created": handle_marketplace_inquiry_created,
    "marketplace.inquiry.responded": handle_marketplace_inquiry_responded,
    "accounting.purchase_request.ordered": handle_purchase_request_ordered,
}