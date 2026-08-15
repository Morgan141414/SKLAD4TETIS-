from __future__ import annotations

import uuid
from datetime import (
    UTC,
    date,
    datetime,
    timedelta,
)
from decimal import Decimal
from typing import Any

from app.domain.enums import AuditAction
from app.domain.errors import (
    ConflictError,
    NotFoundError,
    ValidationError,
)
from app.domain.schemas import SupplierApplicationReview
from app.services.warehouse.base import WarehouseServiceBase
from app.storage.sqlite import (
    decimal_to_db,
    insert_and_get_id,
    now_iso,
)


class MarketplaceMixin(WarehouseServiceBase):
    def get_cart(self, actor_id: str) -> dict[str, Any]:
        connection = self.database.connect()
        try:
            rows = connection.execute(
                """SELECT cc.id, cc.catalog_item_id, cc.quantity, cc.created_at,
                          ci.product_name, ci.sku, ci.unit, ci.unit_price, ci.min_order_qty,
                          ci.image_url, ci.is_active, ci.supplier_id,
                          s.name AS supplier_name, s.city AS supplier_city
                   FROM marketplace_cart_items cc
                   JOIN supplier_catalog_items ci ON ci.id = cc.catalog_item_id
                   JOIN suppliers s ON s.id = ci.supplier_id
                   WHERE cc.actor_id = ?
                   ORDER BY cc.created_at DESC""",
                (actor_id,),
            ).fetchall()
            items = [dict(r) for r in rows]
            total_amount = sum(float(i["unit_price"]) * float(i["quantity"]) for i in items if i["unit_price"] is not None)
            return {"items": items, "total_items": len(items), "total_amount": total_amount}
        finally:
            self._close_connection(connection)

    def add_to_cart(self, actor_id: str, catalog_item_id: int, quantity: float) -> dict[str, Any]:
        if quantity <= 0:
            raise ValidationError("quantity must be > 0")
        with self.database.transaction() as conn:
            self._require_active(conn, "supplier_catalog_items", catalog_item_id)
            existing = conn.execute(
                "SELECT id, quantity FROM marketplace_cart_items WHERE actor_id = ? AND catalog_item_id = ?",
                (actor_id, catalog_item_id),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE marketplace_cart_items SET quantity = ?, updated_at = NOW() WHERE id = ?",
                    (float(existing["quantity"]) + quantity, existing["id"]),
                )
            else:
                insert_and_get_id(
                    conn,
                    "INSERT INTO marketplace_cart_items (actor_id, catalog_item_id, quantity) VALUES (?, ?, ?)",
                    (actor_id, catalog_item_id, quantity),
                )
        return self.get_cart(actor_id)

    def update_cart_item(self, actor_id: str, cart_item_id: int, quantity: float) -> dict[str, Any]:
        if quantity <= 0:
            raise ValidationError("quantity must be > 0")
        with self.database.transaction() as conn:
            row = conn.execute(
                "SELECT id FROM marketplace_cart_items WHERE id = ? AND actor_id = ?",
                (cart_item_id, actor_id),
            ).fetchone()
            if row is None:
                raise NotFoundError(f"cart item {cart_item_id} not found")
            conn.execute(
                "UPDATE marketplace_cart_items SET quantity = ?, updated_at = NOW() WHERE id = ?",
                (quantity, cart_item_id),
            )
        return self.get_cart(actor_id)

    def remove_from_cart(self, actor_id: str, cart_item_id: int) -> dict[str, Any]:
        with self.database.transaction() as conn:
            conn.execute(
                "DELETE FROM marketplace_cart_items WHERE id = ? AND actor_id = ?",
                (cart_item_id, actor_id),
            )
        return self.get_cart(actor_id)

    def checkout_cart(
        self,
        actor_id: str,
        warehouse_id: int | None,
        notes: str | None,
        source: str = "qpartner",
    ) -> list[dict[str, Any]]:
        """Create one marketplace inquiry per cart item (grouped per supplier offer) and clear the cart."""
        source = self._validate_marketplace_inquiry_source(source) or "qpartner"
        cart = self.get_cart(actor_id)
        if not cart["items"]:
            raise ValidationError("Cart is empty")
        created: list[dict[str, Any]] = []
        errors: list[str] = []
        for entry in cart["items"]:
            try:
                inquiry = self.create_marketplace_inquiry(
                    catalog_item_id=entry["catalog_item_id"],
                    actor_id=actor_id,
                    quantity=float(entry["quantity"]),
                    notes=notes,
                    warehouse_id=warehouse_id,
                    source=source,
                )
                created.append(inquiry)
                with self.database.transaction() as conn:
                    conn.execute("DELETE FROM marketplace_cart_items WHERE id = ?", (entry["id"],))
            except Exception as error:  # noqa: BLE001 - collect per-item failures, keep checkout going
                errors.append(f"{entry['product_name']}: {error}")
        if not created and errors:
            raise ValidationError("; ".join(errors))
        return created

    # ── Production marketplace orders and payments ─────────────────────────

    def create_marketplace_orders_from_cart(
        self,
        actor_id: str,
        *,
        warehouse_id: int | None,
        source: str = "marqet",
        buyer_name: str | None = None,
        buyer_phone: str | None = None,
        buyer_email: str | None = None,
        delivery_address: str | None = None,
        notes: str | None = None,
        payment_method: str = "cod",
    ) -> list[dict[str, Any]]:
        source = self._validate_marketplace_inquiry_source(source) or "marqet"
        if payment_method not in {"cod", "kaspi", "bank", "card_online"}:
            raise ValidationError("Unsupported payment method")
        initial_status = "pending_payment" if payment_method == "card_online" else "pending"
        with self.database.transaction() as conn:
            rows = conn.execute(
                """SELECT cc.id AS cart_item_id, cc.catalog_item_id, cc.quantity,
                          ci.product_id, ci.product_name, ci.sku, ci.unit, ci.unit_price,
                          ci.is_active, ci.supplier_id, s.name AS supplier_name,
                          s.kaspi_phone, s.bank_iban, s.bank_name
                   FROM marketplace_cart_items cc
                   JOIN supplier_catalog_items ci ON ci.id = cc.catalog_item_id
                   JOIN suppliers s ON s.id = ci.supplier_id
                   WHERE cc.actor_id = ? AND ci.is_active = TRUE
                   ORDER BY ci.supplier_id, cc.created_at""",
                (actor_id,),
            ).fetchall()
            if not rows:
                raise ValidationError("Cart is empty")

            groups: dict[int, list[dict[str, Any]]] = {}
            for row in rows:
                item = dict(row)
                groups.setdefault(int(item["supplier_id"]), []).append(item)

            created_ids: list[int] = []
            now = now_iso()
            for supplier_id, items in groups.items():
                subtotal = sum(
                    Decimal(str(item["unit_price"] or "0")) * Decimal(str(item["quantity"]))
                    for item in items
                )
                temp_number = f"MQ-TMP-{uuid.uuid4().hex[:16]}"
                seller_payment_details = None
                if payment_method == "kaspi" and items[0].get("kaspi_phone"):
                    seller_payment_details = f"Kaspi: {items[0]['kaspi_phone']}"
                elif payment_method == "bank" and items[0].get("bank_iban"):
                    bank_label = items[0].get("bank_name") or "Банк"
                    seller_payment_details = f"{bank_label}: {items[0]['bank_iban']}"
                order_id = insert_and_get_id(
                    conn,
                    """INSERT INTO marketplace_orders(
                         order_number, actor_id, supplier_id, warehouse_id, source, status, payment_method,
                         currency, subtotal_amount, delivery_amount, discount_amount, total_amount,
                         buyer_name, buyer_phone, buyer_email, delivery_address, notes, seller_payment_details,
                         created_at, updated_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, 'KZT', ?, 0, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        temp_number,
                        actor_id,
                        supplier_id,
                        warehouse_id,
                        source,
                        initial_status,
                        payment_method,
                        decimal_to_db(subtotal),
                        decimal_to_db(subtotal),
                        buyer_name,
                        buyer_phone,
                        buyer_email,
                        delivery_address,
                        notes,
                        seller_payment_details,
                        now,
                        now,
                    ),
                )
                order_number = f"MQ-{100000 + order_id}"
                conn.execute("UPDATE marketplace_orders SET order_number = ? WHERE id = ?", (order_number, order_id))
                for item in items:
                    quantity = Decimal(str(item["quantity"]))
                    unit_price = Decimal(str(item["unit_price"] or "0"))
                    line_total = quantity * unit_price
                    insert_and_get_id(
                        conn,
                        """INSERT INTO marketplace_order_items(
                             order_id, catalog_item_id, product_id, product_name, sku, unit,
                             quantity, unit_price, line_total, created_at
                           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            order_id,
                            item["catalog_item_id"],
                            item.get("product_id"),
                            item["product_name"],
                            item.get("sku"),
                            item.get("unit") or "шт",
                            decimal_to_db(quantity),
                            decimal_to_db(unit_price),
                            decimal_to_db(line_total),
                            now,
                        ),
                    )
                created_ids.append(order_id)

            conn.execute("DELETE FROM marketplace_cart_items WHERE actor_id = ?", (actor_id,))

        return [self.get_marketplace_order(actor_id, order_id) for order_id in created_ids]

    def list_marketplace_orders(
        self,
        actor_id: str,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        safe_limit = max(1, min(limit, 100))
        safe_offset = max(0, offset)
        where = ["mo.actor_id = ?"]
        params: list[Any] = [actor_id]
        if status:
            where.append("mo.status = ?")
            params.append(status)
        where_clause = " AND ".join(where)
        connection = self.database.connect()
        try:
            total = connection.execute(
                f"SELECT COUNT(*) AS total FROM marketplace_orders mo WHERE {where_clause}",
                tuple(params),
            ).fetchone()["total"]
            rows = connection.execute(
                f"""SELECT mo.*, s.name AS supplier_name,
                           (SELECT COUNT(*) FROM marketplace_order_items oi WHERE oi.order_id = mo.id) AS items_count,
                           (SELECT oi.product_name
                              FROM marketplace_order_items oi
                             WHERE oi.order_id = mo.id
                             ORDER BY oi.id
                             LIMIT 1) AS product_name,
                           (SELECT mp.status
                              FROM marketplace_payments mp
                             WHERE mp.order_id = mo.id
                             ORDER BY mp.created_at DESC, mp.id DESC
                             LIMIT 1) AS payment_status
                    FROM marketplace_orders mo
                    JOIN suppliers s ON s.id = mo.supplier_id
                    WHERE {where_clause}
                    ORDER BY mo.created_at DESC
                    LIMIT ? OFFSET ?""",
                tuple(params + [safe_limit, safe_offset]),
            ).fetchall()
            return {"items": [self._order_list_row(dict(row)) for row in rows], "total": int(total)}
        finally:
            self._close_connection(connection)

    def list_supplier_marketplace_orders(
        self,
        supplier_id: int,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        safe_limit = max(1, min(limit, 100))
        safe_offset = max(0, offset)
        where = ["mo.supplier_id = ?"]
        params: list[Any] = [supplier_id]
        if status:
            where.append("mo.status = ?")
            params.append(status)
        where_clause = " AND ".join(where)
        connection = self.database.connect()
        try:
            total = connection.execute(
                f"SELECT COUNT(*) AS total FROM marketplace_orders mo WHERE {where_clause}",
                tuple(params),
            ).fetchone()["total"]
            rows = connection.execute(
                f"""SELECT mo.*, s.name AS supplier_name,
                           (SELECT COUNT(*) FROM marketplace_order_items oi WHERE oi.order_id = mo.id) AS items_count,
                           (SELECT oi.product_name
                              FROM marketplace_order_items oi
                             WHERE oi.order_id = mo.id
                             ORDER BY oi.id
                             LIMIT 1) AS product_name,
                           (SELECT mp.status
                              FROM marketplace_payments mp
                             WHERE mp.order_id = mo.id
                             ORDER BY mp.created_at DESC, mp.id DESC
                             LIMIT 1) AS payment_status
                    FROM marketplace_orders mo
                    JOIN suppliers s ON s.id = mo.supplier_id
                    WHERE {where_clause}
                    ORDER BY mo.created_at DESC
                    LIMIT ? OFFSET ?""",
                tuple(params + [safe_limit, safe_offset]),
            ).fetchall()
            return {"items": [self._order_list_row(dict(row)) for row in rows], "total": int(total)}
        finally:
            self._close_connection(connection)

    def get_marketplace_order(self, actor_id: str, order_id: int) -> dict[str, Any]:
        order = self._get_marketplace_order_for_actor(actor_id, order_id)
        return self._marketplace_order_detail(order)

    def get_supplier_marketplace_order(self, supplier_id: int, order_id: int) -> dict[str, Any]:
        order = self._get_marketplace_order_for_supplier(supplier_id, order_id)
        return self._marketplace_order_detail(order)

    def get_supplier_payment_details(self, supplier_id: int) -> dict[str, Any]:
        connection = self.database.connect()
        try:
            row = connection.execute(
                "SELECT kaspi_phone, bank_iban, bank_name FROM suppliers WHERE id = ?",
                (supplier_id,),
            ).fetchone()
            if row is None:
                raise NotFoundError(f"supplier {supplier_id} not found")
            return dict(row)
        finally:
            self._close_connection(connection)

    def update_supplier_payment_details(
        self, supplier_id: int, *, kaspi_phone: str | None,
        bank_iban: str | None, bank_name: str | None,
    ) -> dict[str, Any]:
        with self.database.transaction() as connection:
            row = connection.execute("SELECT id FROM suppliers WHERE id = ?", (supplier_id,)).fetchone()
            if row is None:
                raise NotFoundError(f"supplier {supplier_id} not found")
            connection.execute(
                "UPDATE suppliers SET kaspi_phone = ?, bank_iban = ?, bank_name = ? WHERE id = ?",
                (kaspi_phone, bank_iban, bank_name, supplier_id),
            )
        return self.get_supplier_payment_details(supplier_id)

    def update_marketplace_order_tracking(
        self, supplier_id: int, order_id: int, *, tracking_number: str,
        tracking_carrier: str, estimated_delivery: date | None,
        seller_note: str | None,
    ) -> dict[str, Any]:
        today = datetime.now(UTC).date()
        if estimated_delivery is not None and not today <= estimated_delivery <= today + timedelta(days=365):
            raise ValidationError("Estimated delivery must be within the next 365 days")
        with self.database.transaction() as connection:
            order = connection.execute(
                "SELECT id, status FROM marketplace_orders WHERE id = ? AND supplier_id = ?",
                (order_id, supplier_id),
            ).fetchone()
            if order is None:
                raise NotFoundError(f"marketplace order {order_id} not found")
            if order["status"] not in {"accepted", "preparing", "shipped"}:
                raise ValidationError("Tracking can only be changed for accepted or shipped orders")
            connection.execute(
                """UPDATE marketplace_orders
                   SET tracking_number = ?, tracking_carrier = ?, estimated_delivery = ?,
                       seller_note = ?, updated_at = ? WHERE id = ?""",
                (
                    tracking_number, tracking_carrier,
                    estimated_delivery.isoformat() if estimated_delivery else None,
                    seller_note, now_iso(), order_id,
                ),
            )
        return self.get_supplier_marketplace_order(supplier_id, order_id)

    def update_manual_marketplace_payment_status(
        self, actor_id: str, supplier_id: int | None, order_id: int, payment_status: str,
    ) -> dict[str, Any]:
        with self.database.transaction() as connection:
            order = connection.execute("SELECT * FROM marketplace_orders WHERE id = ?", (order_id,)).fetchone()
            if order is None:
                raise NotFoundError(f"marketplace order {order_id} not found")
            if payment_status == "awaiting":
                if str(order["actor_id"]) != str(actor_id):
                    raise NotFoundError(f"marketplace order {order_id} not found")
                if order["payment_method"] not in {"kaspi", "bank"}:
                    raise ValidationError("Payment claim is only available for Kaspi or bank transfer")
                if order["payment_status"] not in {"pending", "awaiting"}:
                    raise ValidationError("Payment status cannot be changed")
                connection.execute(
                    "UPDATE marketplace_orders SET payment_status = 'awaiting', updated_at = ? WHERE id = ?",
                    (now_iso(), order_id),
                )
            elif payment_status == "paid":
                if supplier_id is None or int(order["supplier_id"]) != int(supplier_id):
                    raise NotFoundError(f"marketplace order {order_id} not found")
                if order["payment_method"] in {"kaspi", "bank"} and order["payment_status"] != "awaiting":
                    raise ValidationError("Buyer has not submitted a payment claim")
                if order["payment_method"] not in {"cod", "kaspi", "bank"}:
                    raise ValidationError("Online card payments are confirmed only by signed webhook")
                now = now_iso()
                connection.execute(
                    """UPDATE marketplace_orders
                       SET payment_status = 'paid',
                           status = CASE WHEN status IN ('pending','pending_payment') THEN 'paid' ELSE status END,
                           paid_at = COALESCE(paid_at, ?), updated_at = ? WHERE id = ?""",
                    (now, now, order_id),
                )
            else:
                raise ValidationError("Unsupported payment status")
        if supplier_id is not None and int(order["supplier_id"]) == int(supplier_id):
            return self.get_supplier_marketplace_order(supplier_id, order_id)
        return self.get_marketplace_order(actor_id, order_id)

    def get_supplier_marketplace_wallet(self, supplier_id: int) -> dict[str, Any]:
        connection = self.database.connect()
        try:
            account = connection.execute(
                """SELECT supplier_id, currency, available_amount, pending_amount, created_at, updated_at
                   FROM marketplace_seller_accounts
                   WHERE supplier_id = ?""",
                (supplier_id,),
            ).fetchone()
            totals = connection.execute(
                """SELECT
                       COALESCE(SUM(CASE WHEN entry_type IN ('credit','release') AND status = 'posted' THEN amount ELSE 0 END), 0) AS posted_credit,
                       COALESCE(SUM(CASE WHEN entry_type IN ('debit','refund') AND status = 'posted' THEN amount ELSE 0 END), 0) AS posted_debit,
                       COALESCE(SUM(CASE WHEN status = 'pending' THEN amount ELSE 0 END), 0) AS pending_ledger,
                       COUNT(*) AS ledger_entries
                   FROM marketplace_seller_ledger
                   WHERE supplier_id = ?""",
                (supplier_id,),
            ).fetchone()
            if account is None:
                return {
                    "supplier_id": supplier_id,
                    "currency": "KZT",
                    "available_amount": 0.0,
                    "pending_amount": 0.0,
                    "posted_credit": float(totals["posted_credit"] or 0),
                    "posted_debit": float(totals["posted_debit"] or 0),
                    "pending_ledger": float(totals["pending_ledger"] or 0),
                    "ledger_entries": int(totals["ledger_entries"] or 0),
                    "created_at": None,
                    "updated_at": None,
                }
            return {
                "supplier_id": int(account["supplier_id"]),
                "currency": account["currency"] or "KZT",
                "available_amount": float(account["available_amount"] or 0),
                "pending_amount": float(account["pending_amount"] or 0),
                "posted_credit": float(totals["posted_credit"] or 0),
                "posted_debit": float(totals["posted_debit"] or 0),
                "pending_ledger": float(totals["pending_ledger"] or 0),
                "ledger_entries": int(totals["ledger_entries"] or 0),
                "created_at": account["created_at"],
                "updated_at": account["updated_at"],
            }
        finally:
            self._close_connection(connection)

    def list_supplier_marketplace_ledger(
        self,
        supplier_id: int,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        safe_limit = max(1, min(limit, 100))
        safe_offset = max(0, offset)
        connection = self.database.connect()
        try:
            total = connection.execute(
                "SELECT COUNT(*) AS total FROM marketplace_seller_ledger WHERE supplier_id = ?",
                (supplier_id,),
            ).fetchone()["total"]
            rows = connection.execute(
                """SELECT l.id, l.order_id, l.payment_id, l.entry_type, l.status, l.amount,
                          l.currency, l.description, l.source_type, l.source_id, l.created_at,
                          mo.order_number, mp.provider, mp.provider_payment_id
                   FROM marketplace_seller_ledger l
                   LEFT JOIN marketplace_orders mo ON mo.id = l.order_id
                   LEFT JOIN marketplace_payments mp ON mp.id = l.payment_id
                   WHERE l.supplier_id = ?
                   ORDER BY l.created_at DESC, l.id DESC
                   LIMIT ? OFFSET ?""",
                (supplier_id, safe_limit, safe_offset),
            ).fetchall()
            return {
                "items": [
                    {
                        "id": row["id"],
                        "order_id": row["order_id"],
                        "order_number": row["order_number"],
                        "payment_id": row["payment_id"],
                        "provider": row["provider"],
                        "provider_payment_id": row["provider_payment_id"],
                        "entry_type": row["entry_type"],
                        "status": row["status"],
                        "amount": float(row["amount"] or 0),
                        "currency": row["currency"] or "KZT",
                        "description": row["description"],
                        "source_type": row["source_type"],
                        "source_id": row["source_id"],
                        "created_at": row["created_at"],
                    }
                    for row in rows
                ],
                "total": int(total),
            }
        finally:
            self._close_connection(connection)

    def update_supplier_marketplace_order_status(
        self,
        supplier_id: int,
        order_id: int,
        *,
        status: str,
        cancel_reason: str | None = None,
    ) -> dict[str, Any]:
        status = status.strip().lower()
        allowed = {
            "pending": {"accepted", "cancelled"},
            "pending_payment": {"cancelled"},
            "paid": {"accepted", "cancelled"},
            "accepted": {"preparing", "cancelled"},
            "preparing": {"shipped", "cancelled"},
            "shipped": {"delivered"},
            "delivered": {"completed"},
            "completed": set(),
            "cancelled": set(),
            "refunded": set(),
        }
        if status not in {"accepted", "preparing", "shipped", "delivered", "completed", "cancelled"}:
            raise ValidationError("Unsupported marketplace order status")
        if status == "cancelled" and not (cancel_reason or "").strip():
            raise ValidationError("cancel_reason is required when cancelling an order")
        timestamp_columns = {
            "accepted": "accepted_at",
            "shipped": "shipped_at",
            "delivered": "delivered_at",
            "completed": "completed_at",
            "cancelled": "cancelled_at",
        }
        with self.database.transaction() as conn:
            order = conn.execute(
                "SELECT * FROM marketplace_orders WHERE id = ? AND supplier_id = ?",
                (order_id, supplier_id),
            ).fetchone()
            if order is None:
                raise NotFoundError(f"marketplace order {order_id} not found")
            current_status = str(order["status"] or "")
            if status == current_status:
                pass
            else:
                if status not in allowed.get(current_status, set()):
                    raise ValidationError(f"Cannot move marketplace order from {current_status} to {status}")
                now = now_iso()
                assignments = ["status = ?", "updated_at = ?"]
                params: list[Any] = [status, now]
                timestamp_col = timestamp_columns.get(status)
                if timestamp_col:
                    assignments.append(f"{timestamp_col} = COALESCE({timestamp_col}, ?)")
                    params.append(now)
                if status == "preparing":
                    assignments.append("accepted_at = COALESCE(accepted_at, ?)")
                    params.append(now)
                if status == "cancelled":
                    assignments.append("cancel_reason = ?")
                    params.append(cancel_reason.strip() if cancel_reason else None)
                params.append(order_id)
                conn.execute(
                    f"UPDATE marketplace_orders SET {', '.join(assignments)} WHERE id = ?",
                    tuple(params),
                )
                if status == "completed":
                    self._release_marketplace_order_hold(conn, order_id)
                elif status == "cancelled":
                    self._cancel_marketplace_order_hold(conn, order_id, cancel_reason=cancel_reason)
        return self.get_supplier_marketplace_order(supplier_id, order_id)

    def bind_marketplace_payment_method(
        self,
        actor_id: str,
        *,
        provider: str,
        provider_token: str,
        brand: str = "unknown",
        last4: str,
        expiry_month: int | None = None,
        expiry_year: int | None = None,
        holder_name: str | None = None,
        is_default: bool = False,
    ) -> dict[str, Any]:
        provider = provider.strip().lower()
        provider_token = provider_token.strip()
        last4 = "".join(ch for ch in last4 if ch.isdigit())[-4:]
        if not provider or not provider_token:
            raise ValidationError("provider and provider_token are required")
        token_digits = "".join(ch for ch in provider_token if ch.isdigit())
        if 12 <= len(token_digits) <= 19 and token_digits == provider_token.replace(" ", "").replace("-", ""):
            raise ValidationError("Raw card numbers are not accepted; use a PSP token")
        if provider_token.isdigit() and len(provider_token) in {3, 4}:
            raise ValidationError("CVV is not accepted")
        if len(last4) != 4:
            raise ValidationError("Only masked card last4 is accepted")
        token_fingerprint = self._marketplace_payment_token_fingerprint(provider, provider_token)
        with self.database.transaction() as conn:
            if is_default:
                conn.execute(
                    "UPDATE marketplace_payment_methods SET is_default = FALSE, updated_at = ? WHERE actor_id = ?",
                    (now_iso(), actor_id),
                )
            method_id = insert_and_get_id(
                conn,
                """INSERT INTO marketplace_payment_methods(
                     actor_id, provider, provider_token, brand, last4, expiry_month,
                     expiry_year, holder_name, is_default, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    actor_id,
                    provider,
                    token_fingerprint,
                    brand.strip().lower() or "unknown",
                    last4,
                    expiry_month,
                    expiry_year,
                    holder_name,
                    bool(is_default),
                    now_iso(),
                    now_iso(),
                ),
            )
        return self.get_marketplace_payment_method(actor_id, method_id)

    def list_marketplace_payment_methods(self, actor_id: str) -> dict[str, Any]:
        connection = self.database.connect()
        try:
            rows = connection.execute(
                """SELECT id, provider, brand, last4, expiry_month, expiry_year,
                          holder_name, is_default, status, created_at, updated_at
                   FROM marketplace_payment_methods
                   WHERE actor_id = ? AND status <> 'disabled'
                   ORDER BY is_default DESC, created_at DESC""",
                (actor_id,),
            ).fetchall()
            return {"items": [self._payment_method_public(dict(row)) for row in rows]}
        finally:
            self._close_connection(connection)

    def get_marketplace_payment_method(self, actor_id: str, method_id: int) -> dict[str, Any]:
        connection = self.database.connect()
        try:
            row = connection.execute(
                """SELECT id, provider, brand, last4, expiry_month, expiry_year,
                          holder_name, is_default, status, created_at, updated_at
                   FROM marketplace_payment_methods
                   WHERE id = ? AND actor_id = ? AND status <> 'disabled'""",
                (method_id, actor_id),
            ).fetchone()
            if row is None:
                raise NotFoundError(f"payment method {method_id} not found")
            return self._payment_method_public(dict(row))
        finally:
            self._close_connection(connection)

    def set_default_marketplace_payment_method(self, actor_id: str, method_id: int) -> dict[str, Any]:
        with self.database.transaction() as conn:
            row = conn.execute(
                "SELECT id FROM marketplace_payment_methods WHERE id = ? AND actor_id = ? AND status = 'active'",
                (method_id, actor_id),
            ).fetchone()
            if row is None:
                raise NotFoundError(f"payment method {method_id} not found")
            conn.execute(
                "UPDATE marketplace_payment_methods SET is_default = FALSE, updated_at = ? WHERE actor_id = ?",
                (now_iso(), actor_id),
            )
            conn.execute(
                "UPDATE marketplace_payment_methods SET is_default = TRUE, updated_at = ? WHERE id = ?",
                (now_iso(), method_id),
            )
        return self.get_marketplace_payment_method(actor_id, method_id)

    def delete_marketplace_payment_method(self, actor_id: str, method_id: int) -> None:
        with self.database.transaction() as conn:
            row = conn.execute(
                "SELECT id FROM marketplace_payment_methods WHERE id = ? AND actor_id = ?",
                (method_id, actor_id),
            ).fetchone()
            if row is None:
                raise NotFoundError(f"payment method {method_id} not found")
            conn.execute(
                "UPDATE marketplace_payment_methods SET status = 'disabled', is_default = FALSE, updated_at = ? WHERE id = ?",
                (now_iso(), method_id),
            )

    def create_marketplace_payment(
        self,
        actor_id: str,
        order_id: int,
        *,
        provider: str = "manual",
        payment_method_id: int | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        with self.database.transaction() as conn:
            order = self._get_marketplace_order_for_actor_conn(conn, actor_id, order_id)
            if order["status"] not in {"pending_payment", "draft"}:
                raise ValidationError("Order is not awaiting payment")
            if idempotency_key:
                existing = conn.execute(
                    "SELECT * FROM marketplace_payments WHERE actor_id = ? AND idempotency_key = ?",
                    (actor_id, idempotency_key),
                ).fetchone()
                if existing is not None:
                    if int(existing["order_id"]) != int(order_id):
                        raise ConflictError("Idempotency key was already used for another order")
                    return dict(existing)
            if payment_method_id is not None:
                method = conn.execute(
                    "SELECT id, provider FROM marketplace_payment_methods WHERE id = ? AND actor_id = ? AND status = 'active'",
                    (payment_method_id, actor_id),
                ).fetchone()
                if method is None:
                    raise NotFoundError(f"payment method {payment_method_id} not found")
                provider = str(method["provider"])
            payment_id = insert_and_get_id(
                conn,
                """INSERT INTO marketplace_payments(
                     order_id, actor_id, supplier_id, payment_method_id, provider, method,
                     status, amount, currency, idempotency_key, metadata, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, 'KZT', ?, ?, ?, ?)""",
                (
                    order_id,
                    actor_id,
                    order["supplier_id"],
                    payment_method_id,
                    provider.strip().lower() or "manual",
                    "saved_card" if payment_method_id else "redirect",
                    decimal_to_db(Decimal(str(order["total_amount"]))),
                    idempotency_key,
                    {},
                    now_iso(),
                    now_iso(),
                ),
            )
        return self.get_marketplace_payment(actor_id, payment_id)

    def cancel_marketplace_order(
        self,
        actor_id: str,
        order_id: int,
        *,
        reason: str,
    ) -> dict[str, Any]:
        reason = reason.strip()
        if len(reason) < 3:
            raise ValidationError("Cancellation reason is required")
        with self.database.transaction() as conn:
            order = conn.execute(
                "SELECT * FROM marketplace_orders WHERE id = ? AND actor_id = ?",
                (order_id, actor_id),
            ).fetchone()
            if order is None:
                raise NotFoundError(f"marketplace order {order_id} not found")
            current_status = str(order["status"] or "")
            if current_status in {"cancelled", "refunded", "completed"}:
                raise ValidationError(f"Cannot cancel marketplace order in status {current_status}")
            paid_payment = conn.execute(
                """SELECT id FROM marketplace_payments
                   WHERE order_id = ? AND status IN ('authorized','paid')
                   ORDER BY created_at DESC, id DESC
                   LIMIT 1""",
                (order_id,),
            ).fetchone()
            if paid_payment is not None:
                raise ValidationError("Paid marketplace orders require a refund request")
            now = now_iso()
            conn.execute(
                """UPDATE marketplace_orders
                   SET status = 'cancelled', cancel_reason = ?, cancelled_at = COALESCE(cancelled_at, ?), updated_at = ?
                   WHERE id = ?""",
                (reason, now, now, order_id),
            )
            conn.execute(
                """UPDATE marketplace_payments
                   SET status = 'cancelled', updated_at = ?
                   WHERE order_id = ? AND status IN ('pending','requires_action')""",
                (now, order_id),
            )
            self._cancel_marketplace_order_hold(conn, order_id, cancel_reason=reason)
        return self.get_marketplace_order(actor_id, order_id)

    def request_marketplace_order_refund(
        self,
        actor_id: str,
        order_id: int,
        *,
        reason: str,
    ) -> dict[str, Any]:
        reason = reason.strip()
        if len(reason) < 3:
            raise ValidationError("Refund reason is required")
        with self.database.transaction() as conn:
            order = conn.execute(
                "SELECT * FROM marketplace_orders WHERE id = ? AND actor_id = ?",
                (order_id, actor_id),
            ).fetchone()
            if order is None:
                raise NotFoundError(f"marketplace order {order_id} not found")
            current_status = str(order["status"] or "")
            if current_status in {"cancelled", "refunded"}:
                raise ValidationError(f"Cannot request refund for marketplace order in status {current_status}")
            if current_status == "refund_requested":
                existing_refund = conn.execute(
                    """SELECT id FROM marketplace_refund_requests
                       WHERE order_id = ? AND status IN ('requested','approved','processing')
                       ORDER BY created_at DESC, id DESC
                       LIMIT 1""",
                    (order_id,),
                ).fetchone()
                if existing_refund is None:
                    paid_payment = conn.execute(
                        """SELECT id, amount, currency FROM marketplace_payments
                           WHERE order_id = ? AND status IN ('authorized','paid')
                           ORDER BY created_at DESC, id DESC
                           LIMIT 1""",
                        (order_id,),
                    ).fetchone()
                    if paid_payment is not None:
                        now = now_iso()
                        insert_and_get_id(
                            conn,
                            """INSERT INTO marketplace_refund_requests(
                                 order_id, payment_id, actor_id, supplier_id, amount, currency,
                                 reason, status, created_at, updated_at
                               ) VALUES (?, ?, ?, ?, ?, ?, ?, 'requested', ?, ?)""",
                            (
                                order_id,
                                paid_payment["id"],
                                actor_id,
                                order["supplier_id"],
                                decimal_to_db(Decimal(str(paid_payment["amount"]))),
                                paid_payment["currency"] or order["currency"] or "KZT",
                                reason,
                                now,
                                now,
                            ),
                        )
                        conn.execute(
                            """UPDATE marketplace_orders
                               SET cancel_reason = COALESCE(cancel_reason, ?), updated_at = ?
                               WHERE id = ?""",
                            (reason, now, order_id),
                        )
                return self.get_marketplace_order(actor_id, order_id)
            paid_payment = conn.execute(
                """SELECT id, amount, currency FROM marketplace_payments
                   WHERE order_id = ? AND status IN ('authorized','paid')
                   ORDER BY created_at DESC, id DESC
                   LIMIT 1""",
                (order_id,),
            ).fetchone()
            if paid_payment is None:
                raise ValidationError("Only authorized or paid marketplace orders can request a refund")
            now = now_iso()
            insert_and_get_id(
                conn,
                """INSERT INTO marketplace_refund_requests(
                     order_id, payment_id, actor_id, supplier_id, amount, currency,
                     reason, status, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, 'requested', ?, ?)""",
                (
                    order_id,
                    paid_payment["id"],
                    actor_id,
                    order["supplier_id"],
                    decimal_to_db(Decimal(str(paid_payment["amount"]))),
                    paid_payment["currency"] or order["currency"] or "KZT",
                    reason,
                    now,
                    now,
                ),
            )
            conn.execute(
                """UPDATE marketplace_orders
                   SET status = 'refund_requested', cancel_reason = ?, updated_at = ?
                   WHERE id = ?""",
                (reason, now, order_id),
            )
        return self.get_marketplace_order(actor_id, order_id)

    def get_marketplace_payment(self, actor_id: str, payment_id: int) -> dict[str, Any]:
        connection = self.database.connect()
        try:
            row = connection.execute(
                "SELECT * FROM marketplace_payments WHERE id = ? AND actor_id = ?",
                (payment_id, actor_id),
            ).fetchone()
            if row is None:
                raise NotFoundError(f"payment {payment_id} not found")
            return dict(row)
        finally:
            self._close_connection(connection)

    def apply_marketplace_payment_event(
        self,
        *,
        provider: str,
        provider_event_id: str,
        provider_payment_id: str,
        payment_id: int,
        status: str,
        amount: Decimal,
        currency: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if status not in {"paid", "failed", "cancelled", "refunded", "authorized"}:
            raise ValidationError("Unsupported payment event status")
        provider = provider.strip().lower()
        provider_payment_id = provider_payment_id.strip()
        currency = currency.strip().upper()
        if not provider or not provider_event_id.strip() or not provider_payment_id:
            raise ValidationError("provider, provider_event_id and provider_payment_id are required")
        with self.database.transaction() as conn:
            existing = conn.execute(
                """SELECT payment_id FROM marketplace_payment_events
                   WHERE provider = ? AND provider_event_id = ?""",
                (provider, provider_event_id),
            ).fetchone()
            if existing:
                if int(existing["payment_id"]) != int(payment_id):
                    raise ConflictError("Payment event id is already linked to another payment")
                payment = conn.execute("SELECT * FROM marketplace_payments WHERE id = ?", (payment_id,)).fetchone()
                if payment is None:
                    raise NotFoundError(f"payment {payment_id} not found")
                return dict(payment)
            payment = conn.execute("SELECT * FROM marketplace_payments WHERE id = ?", (payment_id,)).fetchone()
            if payment is None:
                raise NotFoundError(f"payment {payment_id} not found")
            if str(payment["provider"]).lower() != provider:
                raise ValidationError("Payment provider mismatch")
            if str(payment["currency"]).upper() != currency:
                raise ValidationError("Payment currency mismatch")
            if Decimal(str(payment["amount"])) != Decimal(str(amount)):
                raise ValidationError("Payment amount mismatch")
            previous_status = str(payment["status"] or "pending")
            allowed_transitions = {
                "pending": {"authorized", "paid", "failed", "cancelled"},
                "authorized": {"paid", "failed", "cancelled"},
                "paid": {"refunded"},
                "failed": set(),
                "cancelled": set(),
                "refunded": set(),
            }
            if status != previous_status and status not in allowed_transitions.get(previous_status, set()):
                raise ValidationError(f"Cannot move marketplace payment from {previous_status} to {status}")
            existing_provider_payment = conn.execute(
                """SELECT id FROM marketplace_payments
                   WHERE provider = ? AND provider_payment_id = ? AND id <> ?""",
                (provider, provider_payment_id, payment_id),
            ).fetchone()
            if existing_provider_payment is not None:
                raise ConflictError("Provider payment id is already linked to another payment")
            event_id = insert_and_get_id(
                conn,
                """INSERT INTO marketplace_payment_events(
                     payment_id, provider, provider_event_id, event_type, payload, received_at, processed_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    payment_id,
                    provider,
                    provider_event_id,
                    status,
                    payload,
                    now_iso(),
                    now_iso(),
                ),
            )
            conn.execute(
                """UPDATE marketplace_payments
                   SET provider_payment_id = COALESCE(provider_payment_id, ?)
                   WHERE id = ?""",
                (provider_payment_id, payment_id),
            )
            timestamp_col = {
                "paid": "paid_at",
                "failed": "failed_at",
                "refunded": "refunded_at",
                "authorized": "authorized_at",
            }.get(status)
            if timestamp_col:
                conn.execute(
                    f"UPDATE marketplace_payments SET status = ?, updated_at = ?, {timestamp_col} = ? WHERE id = ?",
                    (status, now_iso(), now_iso(), payment_id),
                )
            else:
                conn.execute(
                    "UPDATE marketplace_payments SET status = ?, updated_at = ? WHERE id = ?",
                    (status, now_iso(), payment_id),
                )
            if status == "paid" and previous_status != "paid":
                self._mark_marketplace_order_paid(conn, int(payment["order_id"]), int(payment["id"]))
            elif status == "refunded" and previous_status != "refunded":
                self._refund_marketplace_order_payment(conn, int(payment["order_id"]), int(payment["id"]))
            updated = conn.execute("SELECT * FROM marketplace_payments WHERE id = ?", (payment_id,)).fetchone()
            result = dict(updated)
            result["event_id"] = event_id
            return result

    def get_marketplace_account_summary(self, actor_id: str) -> dict[str, Any]:
        connection = self.database.connect()
        try:
            row = connection.execute(
                """SELECT
                     SUM(CASE WHEN status IN ('pending_payment','paid','accepted','preparing','shipped') THEN 1 ELSE 0 END) AS active_orders,
                     SUM(CASE WHEN status IN ('delivered','completed') THEN 1 ELSE 0 END) AS delivered_orders,
                     COALESCE(SUM(CASE
                       WHEN status = 'completed'
                        AND EXISTS (
                            SELECT 1 FROM marketplace_payments mp
                             WHERE mp.order_id = marketplace_orders.id
                               AND mp.status = 'paid'
                        )
                        AND NOT EXISTS (
                            SELECT 1 FROM marketplace_payments mp
                             WHERE mp.order_id = marketplace_orders.id
                               AND mp.status = 'refunded'
                        )
                       THEN total_amount ELSE 0 END), 0) AS completed_spend
                   FROM marketplace_orders WHERE actor_id = ?""",
                (actor_id,),
            ).fetchone()
            methods = connection.execute(
                "SELECT COUNT(*) AS n FROM marketplace_payment_methods WHERE actor_id = ? AND status = 'active'",
                (actor_id,),
            ).fetchone()
            return {
                "active_orders": int(row["active_orders"] or 0),
                "delivered_orders": int(row["delivered_orders"] or 0),
                "bonus_points": self._marketplace_loyalty_points(row["completed_spend"] or 0),
                "saved_payment_methods": int(methods["n"] or 0),
                "open_messages": 0,
                "seller_listings": 0,
            }
        finally:
            self._close_connection(connection)

    def get_marketplace_loyalty(self, actor_id: str) -> dict[str, Any]:
        connection = self.database.connect()
        try:
            totals = connection.execute(
                """SELECT
                     COALESCE(SUM(CASE WHEN mo.status = 'completed' THEN mo.total_amount ELSE 0 END), 0) AS completed_spend,
                     COALESCE(SUM(CASE WHEN mo.status IN ('paid','accepted','preparing','shipped','delivered') THEN mo.total_amount ELSE 0 END), 0) AS pending_spend
                   FROM marketplace_orders mo
                   WHERE mo.actor_id = ?
                     AND total_amount IS NOT NULL
                     AND mo.status NOT IN ('cancelled','refund_requested','refunded')
                     AND EXISTS (
                         SELECT 1 FROM marketplace_payments mp
                          WHERE mp.order_id = mo.id
                            AND mp.status = 'paid'
                     )
                     AND NOT EXISTS (
                         SELECT 1 FROM marketplace_payments mp
                          WHERE mp.order_id = mo.id
                            AND mp.status = 'refunded'
                     )""",
                (actor_id,),
            ).fetchone()
            completed_spend = Decimal(str(totals["completed_spend"] or 0))
            pending_spend = Decimal(str(totals["pending_spend"] or 0))
            points_balance = self._marketplace_loyalty_points(completed_spend)
            points_pending = self._marketplace_loyalty_points(pending_spend)
            tier, next_tier_points = self._marketplace_loyalty_tier(points_balance)
            rows = connection.execute(
                """SELECT id, order_number, status, total_amount,
                          COALESCE(completed_at, paid_at, updated_at, created_at) AS event_at
                   FROM marketplace_orders mo
                   WHERE actor_id = ?
                     AND total_amount IS NOT NULL
                     AND status IN ('completed','paid','accepted','preparing','shipped','delivered')
                     AND EXISTS (
                         SELECT 1 FROM marketplace_payments mp
                          WHERE mp.order_id = mo.id
                            AND mp.status = 'paid'
                     )
                     AND NOT EXISTS (
                         SELECT 1 FROM marketplace_payments mp
                          WHERE mp.order_id = mo.id
                            AND mp.status = 'refunded'
                     )
                   ORDER BY event_at DESC, id DESC
                   LIMIT 20""",
                (actor_id,),
            ).fetchall()
            history: list[dict[str, Any]] = []
            for row in rows:
                points = self._marketplace_loyalty_points(row["total_amount"] or 0)
                if points <= 0:
                    continue
                is_completed = row["status"] == "completed"
                number = row["order_number"] or f"MQ-{row['id']}"
                history.append(
                    {
                        "id": f"order-{row['id']}",
                        "type": "earn",
                        "title": (
                            f"Начисление за заказ {number}"
                            if is_completed
                            else f"Ожидает начисления за заказ {number}"
                        ),
                        "points_delta": points,
                        "created_at": row["event_at"],
                        "order_number": number,
                    }
                )
            return {
                "tier": tier,
                "points_balance": points_balance,
                "points_pending": points_pending,
                "next_tier_points": next_tier_points,
                "lifetime_spend": float(completed_spend),
                "currency": "KZT",
                "history": history,
            }
        finally:
            self._close_connection(connection)

    @staticmethod
    def _marketplace_loyalty_points(amount: Any) -> int:
        value = Decimal(str(amount or 0))
        if value <= 0:
            return 0
        return int(value // Decimal(1000))

    @staticmethod
    def _marketplace_loyalty_tier(points: int) -> tuple[str, int]:
        thresholds = [
            ("bronze", 5000),
            ("silver", 15000),
            ("gold", 50000),
            ("platinum", 50000),
        ]
        if points < 5000:
            return thresholds[0]
        if points < 15000:
            return thresholds[1]
        if points < 50000:
            return thresholds[2]
        return thresholds[3]

    def create_marketplace_inquiry(
        self, catalog_item_id: int, actor_id: str, quantity: float,
        notes: str | None, warehouse_id: int | None,
        purchase_request_id: int | None = None,
        source: str = "marqet",
    ) -> dict[str, Any]:
        source = self._validate_marketplace_inquiry_source(source) or "marqet"
        connection = self.database.connect()
        try:
            item = connection.execute(
                "SELECT * FROM supplier_catalog_items WHERE id = ? AND is_active = TRUE",
                (catalog_item_id,)
            ).fetchone()
            if item is None:
                raise ValueError(f"Catalog item {catalog_item_id} not found or inactive")
            # Duplicate guard — warn if open inquiry already exists for this actor+supplier+product
            existing = connection.execute(
                """SELECT id FROM marketplace_inquiries
                   WHERE catalog_item_id = ? AND actor_id = ? AND status IN ('pending','responded')
                   LIMIT 1""",
                (catalog_item_id, actor_id),
            ).fetchone()
        finally:
            self._close_connection(connection)
        if existing:
            raise ValidationError(f"Уже есть открытый запрос #{existing['id']} на этот товар у этого поставщика")
        with self.database.transaction() as conn:
            row_id = insert_and_get_id(
                conn,
                """INSERT INTO marketplace_inquiries
                   (catalog_item_id, supplier_id, warehouse_id, actor_id, quantity, unit_price, notes, purchase_request_id, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    catalog_item_id,
                    item["supplier_id"],
                    warehouse_id,
                    actor_id,
                    quantity,
                    item["unit_price"],
                    notes,
                    purchase_request_id,
                    source,
                ),
            )
            # Auto-link purchase request status if provided
            if purchase_request_id:
                conn.execute(
                    "UPDATE purchase_requests SET status = 'ordered' WHERE id = ? AND status = 'draft'",
                    (purchase_request_id,),
                )
            row = conn.execute("SELECT * FROM marketplace_inquiries WHERE id = ?", (row_id,)).fetchone()
            result = dict(row) if row else {}
            # Seed initial buyer message
            if notes:
                conn.execute(
                    "INSERT INTO inquiry_messages (inquiry_id, actor_id, role, body) VALUES (?, ?, 'buyer', ?)"
,                    (row_id, actor_id, notes),
                )
            # Reliable email notification to supplier — outbox, atomic with the inquiry
            try:
                _sup = conn.execute(
                    "SELECT name, email FROM suppliers WHERE id = ?",
                    (item["supplier_id"],),
                ).fetchone()
                if _sup:
                    self._enqueue_outbox(
                        conn,
                        "marketplace.inquiry.created",
                        {
                            "supplier_email": _sup["email"],
                            "supplier_name": _sup["name"],
                            "product_name": item["product_name"],
                            "quantity": quantity,
                            "unit": item["unit"],
                            "notes": notes,
                            "inquiry_id": row_id,
                        },
                    )
            except Exception as _email_exc:
                import logging; logging.getLogger(__name__).warning("Outbox enqueue error: %s", _email_exc)
        return result

    def list_marketplace_inquiries(
        self,
        supplier_id: int | None = None,
        actor_id: str | None = None,
        status: str | None = None,
        source: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        source = self._validate_marketplace_inquiry_source(source)
        status = self._validate_marketplace_inquiry_status(status)
        where = []
        params: list[Any] = []
        if supplier_id is not None:
            where.append("mi.supplier_id = ?")
            params.append(supplier_id)
        if actor_id is not None:
            where.append("mi.actor_id = ?")
            params.append(actor_id)
        if status:
            where.append("mi.status = ?")
            params.append(status)
        if source:
            where.append("mi.source = ?")
            params.append(source)
        where_clause = f"WHERE {' AND '.join(where)}" if where else ""
        connection = self.database.connect()
        try:
            total_row = connection.execute(
                f"SELECT COUNT(*) AS n FROM marketplace_inquiries mi {where_clause}", tuple(params)
            ).fetchone()
            total = total_row["n"] if total_row else 0
            rows = connection.execute(
                f"""
                SELECT mi.*, ci.product_name, ci.unit, ci.sku,
                       s.name AS supplier_name, s.phone AS supplier_phone, s.email AS supplier_email,
                       w.name AS warehouse_name
                FROM marketplace_inquiries mi
                JOIN supplier_catalog_items ci ON ci.id = mi.catalog_item_id
                JOIN suppliers s ON s.id = mi.supplier_id
                LEFT JOIN warehouses w ON w.id = mi.warehouse_id
                {where_clause}
                ORDER BY mi.created_at DESC
                LIMIT ? OFFSET ?
                """,
                tuple(params) + (limit, offset),
            ).fetchall()
            items = [dict(r) for r in rows]
            ids = [i["id"] for i in items]
            if ids:
                placeholders = ", ".join(["?"] * len(ids))
                po_rows = connection.execute(
                    f"""SELECT inquiry_id, id, po_number, status, created_at, sent_at, accepted_at
                        FROM purchase_orders WHERE inquiry_id IN ({placeholders})
                        ORDER BY created_at DESC""",
                    tuple(ids),
                ).fetchall()
                po_by_inquiry: dict[int, dict] = {}
                for po in po_rows:
                    po_by_inquiry.setdefault(po["inquiry_id"], dict(po))
                refs = [f"INQ-{i}" for i in ids]
                ref_placeholders = ", ".join(["?"] * len(refs))
                sh_rows = connection.execute(
                    f"""SELECT reference, id, status, current_city, estimated_arrival, updated_at
                        FROM shipments WHERE reference IN ({ref_placeholders})
                        ORDER BY created_at DESC""",
                    tuple(refs),
                ).fetchall()
                sh_by_ref: dict[str, dict] = {}
                for sh in sh_rows:
                    sh_by_ref.setdefault(sh["reference"], dict(sh))
                for item in items:
                    item["purchase_order"] = po_by_inquiry.get(item["id"])
                    item["shipment"] = sh_by_ref.get(f"INQ-{item['id']}")
            return {"items": items, "total": total}
        finally:
            self._close_connection(connection)

    def respond_to_inquiry(
        self, inquiry_id: int, supplier_id: int, response_text: str
    ) -> dict[str, Any]:
        with self.database.transaction() as conn:
            row = conn.execute(
                "SELECT id, supplier_id FROM marketplace_inquiries WHERE id = ?", (inquiry_id,)
            ).fetchone()
            if row is None or row["supplier_id"] != supplier_id:
                raise PermissionError("Inquiry not found or not yours")
            conn.execute(
                "UPDATE marketplace_inquiries SET status = 'responded', supplier_response = ?, responded_at = NOW() WHERE id = ?",
                (response_text, inquiry_id),
            )
            # Record supplier reply as chat message
            supplier_actor = f"supplier-actor:{supplier_id}"
            conn.execute(
                "INSERT INTO inquiry_messages (inquiry_id, actor_id, role, body) VALUES (?, ?, 'supplier', ?)"
,                (inquiry_id, supplier_actor, response_text),
            )
            updated = conn.execute(
                """SELECT mi.*, ci.product_name, ci.unit, s.name AS supplier_name
                   FROM marketplace_inquiries mi
                   JOIN supplier_catalog_items ci ON ci.id = mi.catalog_item_id
                   JOIN suppliers s ON s.id = mi.supplier_id
                   WHERE mi.id = ?""",
                (inquiry_id,)
            ).fetchone()
            result2 = dict(updated) if updated else {}
            # Reliable email notification to buyer — outbox, atomic with the response
            try:
                _actor_id = result2.get("actor_id", "")
                _tetis_id = _actor_id.removeprefix("tetis-actor:")
                _buyer = conn.execute(
                    "SELECT email FROM sklad_users WHERE username = ?",
                    (f"tetis:{_tetis_id}",)
                ).fetchone()
                if _buyer and _buyer["email"] and result2:
                    self._enqueue_outbox(
                        conn,
                        "marketplace.inquiry.responded",
                        {
                            "buyer_email": _buyer["email"],
                            "supplier_name": result2.get("supplier_name", ""),
                            "product_name": result2.get("product_name", ""),
                            "response_text": response_text,
                            "inquiry_id": inquiry_id,
                        },
                    )
            except Exception as _email_exc2:
                import logging; logging.getLogger(__name__).warning("Outbox enqueue error: %s", _email_exc2)
        return result2

    def list_inquiry_messages(
        self, inquiry_id: int, actor_id: str
    ) -> list[dict]:
        """Return all messages for an inquiry. Caller must be the buyer or the supplier."""
        connection = self.database.connect()
        try:
            inq = connection.execute(
                "SELECT actor_id, supplier_id FROM marketplace_inquiries WHERE id = ?",
                (inquiry_id,)
            ).fetchone()
            if inq is None:
                raise NotFoundError(f"Inquiry {inquiry_id} not found")
            # Verify access: buyer (actor_id match) or supplier
            supplier_actor = f"supplier-actor:{inq['supplier_id']}"
            if actor_id != inq["actor_id"] and actor_id != supplier_actor:
                raise PermissionError("Access denied to inquiry messages")
            rows = connection.execute(
                """SELECT id, actor_id, role, body, created_at
                   FROM inquiry_messages
                   WHERE inquiry_id = ?
                   ORDER BY created_at, id""",
                (inquiry_id,)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            self._close_connection(connection)

    def add_inquiry_message(
        self, inquiry_id: int, actor_id: str, body: str
    ) -> dict:
        """Buyer or supplier sends a follow-up message on an existing inquiry."""
        body = (body or "").strip()
        if not body:
            raise ValidationError("Message body cannot be empty")
        with self.database.transaction() as conn:
            inq = conn.execute(
                "SELECT actor_id, supplier_id, status FROM marketplace_inquiries WHERE id = ?",
                (inquiry_id,)
            ).fetchone()
            if inq is None:
                raise NotFoundError(f"Inquiry {inquiry_id} not found")
            if inq["status"] in ("cancelled", "closed"):
                raise ValidationError("Cannot add message to a closed/cancelled inquiry")
            supplier_actor = f"supplier-actor:{inq['supplier_id']}"
            if actor_id == inq["actor_id"]:
                role = "buyer"
            elif actor_id == supplier_actor:
                role = "supplier"
            else:
                raise PermissionError("Access denied")
            msg_id = insert_and_get_id(
                conn,
                "INSERT INTO inquiry_messages (inquiry_id, actor_id, role, body) VALUES (?, ?, ?, ?)",
                (inquiry_id, actor_id, role, body),
            )
            # Touch inquiry updated_at / status if supplier is replying
            if role == "supplier" and inq["status"] == "pending":
                conn.execute(
                    "UPDATE marketplace_inquiries SET status = 'responded', responded_at = NOW() WHERE id = ?",
                    (inquiry_id,)
                )
            row = conn.execute(
                "SELECT id, inquiry_id, actor_id, role, body, created_at FROM inquiry_messages WHERE id = ?",
                (msg_id,)
            ).fetchone()
            return dict(row) if row else {}

    def update_inquiry_status(
        self, inquiry_id: int, actor_id: str, new_status: str
    ) -> dict[str, Any]:
        """Buyer-side status update — mark inquiry as ordered or closed."""
        if new_status not in ("ordered", "closed"):
            raise ValueError(f"Invalid status: {new_status}")
        with self.database.transaction() as conn:
            row = conn.execute(
                "SELECT id, actor_id FROM marketplace_inquiries WHERE id = ?", (inquiry_id,)
            ).fetchone()
            if row is None or row["actor_id"] != actor_id:
                raise PermissionError("Inquiry not found or not yours")
            conn.execute(
                "UPDATE marketplace_inquiries SET status = ? WHERE id = ?",
                (new_status, inquiry_id),
            )
            updated = conn.execute(
                """SELECT mi.*, ci.product_name, ci.unit, s.name AS supplier_name,
                          s.phone AS supplier_phone, s.email AS supplier_email
                   FROM marketplace_inquiries mi
                   JOIN supplier_catalog_items ci ON ci.id = mi.catalog_item_id
                   JOIN suppliers s ON s.id = mi.supplier_id
                   WHERE mi.id = ?""",
                (inquiry_id,)
            ).fetchone()
            return dict(updated) if updated else {}

    def create_shipment_from_inquiry(
        self, inquiry_id: int, supplier_id: int, data: dict[str, Any]
    ) -> dict[str, Any]:
        """Supplier creates a shipment record from an accepted inquiry."""
        with self.database.transaction() as conn:
            inq = conn.execute(
                "SELECT * FROM marketplace_inquiries WHERE id = ? AND supplier_id = ?",
                (inquiry_id, supplier_id),
            ).fetchone()
            if inq is None:
                raise PermissionError("Inquiry not found or not yours")
            # Build shipment fields
            warehouse_id = inq["warehouse_id"] or data.get("destination_warehouse_id")
            reference = data.get("reference") or f"INQ-{inquiry_id}"
            notes = data.get("notes") or inq["notes"]
            sid = insert_and_get_id(
                conn,
                """INSERT INTO shipments (supplier_id, reference, status, origin_city,
                   destination_warehouse_id, estimated_arrival, notes)
                   VALUES (?, ?, 'planned', ?, ?, ?, ?)""",
                (
                    supplier_id,
                    reference,
                    data.get("origin_city"),
                    warehouse_id,
                    data.get("estimated_arrival"),
                    notes,
                ),
            )
            conn.execute(
                "UPDATE marketplace_inquiries SET status = 'ordered' WHERE id = ?",
                (inquiry_id,),
            )
            shipment = conn.execute("SELECT * FROM shipments WHERE id = ?", (sid,)).fetchone()
            return dict(shipment) if shipment else {}

    def create_bulk_inquiry(
        self,
        product_name: str,
        actor_id: str,
        quantity: float,
        notes: str | None,
        warehouse_id: int | None,
        source: str = "qpartner",
    ) -> dict[str, Any]:
        """Send inquiry to all suppliers that have matching catalog items."""
        source = self._validate_marketplace_inquiry_source(source) or "qpartner"
        connection = self.database.connect()
        try:
            items = connection.execute(
                """SELECT ci.*, s.name AS supplier_name FROM supplier_catalog_items ci
                   JOIN suppliers s ON s.id = ci.supplier_id
                   WHERE ci.is_active = TRUE AND ci.product_name ILIKE ?
                   ORDER BY ci.unit_price ASC""",
                (f"%{product_name}%",),
            ).fetchall()
        finally:
            self._close_connection(connection)

        if not items:
            return {"items": [], "total": 0}

        # One inquiry per supplier (pick cheapest item per supplier)
        seen_suppliers: set[int] = set()
        created = []
        with self.database.transaction() as conn:
            for item in items:
                sid = item["supplier_id"]
                if sid in seen_suppliers:
                    continue
                seen_suppliers.add(sid)
                row_id = insert_and_get_id(
                    conn,
                    """INSERT INTO marketplace_inquiries
                       (catalog_item_id, supplier_id, warehouse_id, actor_id, quantity, unit_price, notes, source)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (item["id"], sid, warehouse_id, actor_id, quantity, item["unit_price"], notes, source),
                )
                row = conn.execute("SELECT * FROM marketplace_inquiries WHERE id = ?", (row_id,)).fetchone()
                if row:
                    created.append({**dict(row), "supplier_name": item["supplier_name"]})

        return {"items": created, "total": len(created)}

    def import_catalog_csv(
        self, supplier_id: int, rows: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Bulk-insert catalog items from parsed CSV rows."""
        allowed_fields = {"product_name", "sku", "unit", "unit_price", "min_order_qty",
                          "stock_qty", "delivery_days", "category", "description"}
        inserted = 0
        skipped = 0
        errors: list[str] = []
        with self.database.transaction() as conn:
            for i, row in enumerate(rows, 1):
                try:
                    product_name = str(row.get("product_name") or "").strip()
                    unit_price_raw = row.get("unit_price")
                    if not product_name or unit_price_raw is None:
                        skipped += 1
                        errors.append(f"Строка {i}: пропущена (нет названия или цены)")
                        continue
                    unit_price = float(str(unit_price_raw).replace(",", "."))
                    unit = str(row.get("unit") or "шт").strip() or "шт"
                    min_order_qty = float(str(row.get("min_order_qty") or 1).replace(",", ".") or 1)
                    stock_qty_raw = row.get("stock_qty")
                    stock_qty = float(str(stock_qty_raw).replace(",", ".")) if stock_qty_raw not in (None, "") else None
                    delivery_days_raw = row.get("delivery_days")
                    delivery_days = int(float(str(delivery_days_raw).replace(",", "."))) if delivery_days_raw not in (None, "") else None
                    insert_and_get_id(
                        conn,
                        """INSERT INTO supplier_catalog_items
                           (supplier_id, product_name, sku, unit, unit_price, min_order_qty,
                            stock_qty, delivery_days, category, description, is_active)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, TRUE)""",
                        (
                            supplier_id,
                            product_name,
                            str(row.get("sku") or "").strip() or None,
                            unit,
                            unit_price,
                            min_order_qty,
                            stock_qty,
                            delivery_days,
                            str(row.get("category") or "").strip() or None,
                            str(row.get("description") or "").strip() or None,
                        ),
                    )
                    inserted += 1
                except Exception as exc:
                    skipped += 1
                    errors.append(f"Строка {i}: {exc}")
        return {"inserted": inserted, "skipped": skipped, "errors": errors}

    def get_catalog_item_inquiry_stats(self, supplier_id: int) -> list[dict[str, Any]]:
        """Return inquiry counts per catalog item for a supplier."""
        connection = self.database.connect()
        try:
            rows = connection.execute(
                """SELECT ci.id, ci.product_name, ci.unit_price, ci.unit, ci.is_active,
                          COUNT(mi.id) AS inquiries_total,
                          COUNT(mi.id) FILTER (WHERE mi.status = 'pending') AS inquiries_pending,
                          COUNT(mi.id) FILTER (WHERE mi.status IN ('ordered')) AS inquiries_ordered
                   FROM supplier_catalog_items ci
                   LEFT JOIN marketplace_inquiries mi ON mi.catalog_item_id = ci.id
                   WHERE ci.supplier_id = ?
                   GROUP BY ci.id
                   ORDER BY inquiries_total DESC, ci.id""",
                (supplier_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            self._close_connection(connection)

    # ────────────────────────────────────────────────────────────────────────

    def review_supplier_application(
        self,
        application_id: int,
        data: SupplierApplicationReview,
        reviewer_id: str,
        password_hash: str | None = None,
    ) -> dict[str, Any]:
        with self.database.transaction() as connection:
            application = self._get_supplier_application(connection, application_id)
            supplier_id = data.supplier_id or application.get("supplier_id")
            if data.status == "approved":
                if supplier_id is None:
                    matched = None
                    if application.get("bin"):
                        matched = connection.execute(
                            "SELECT id FROM suppliers WHERE bin = ? ORDER BY id LIMIT 1",
                            (application["bin"],),
                        ).fetchone()
                    if matched is None:
                        matched = connection.execute(
                            "SELECT id FROM suppliers WHERE lower(email) = lower(?) ORDER BY id LIMIT 1",
                            (application["email"],),
                        ).fetchone()
                    supplier_id = int(matched["id"]) if matched else None
                if supplier_id is None:
                    supplier_id = insert_and_get_id(
                        connection,
                        """
                        INSERT INTO suppliers(
                          name, bin, phone, address, rating, is_preferred,
                          contact_person, email, contract_number, contract_expires_on,
                          payment_terms, notes, lat, lng, city, delivery_days
                        ) VALUES (?, ?, ?, ?, NULL, ?, ?, ?, NULL, NULL, NULL, ?, NULL, NULL, ?, ?)
                        """,
                        (
                            application["name"],
                            application.get("bin"),
                            application.get("phone"),
                            application.get("address"),
                            0,
                            application.get("contact_person"),
                            application.get("email"),
                            application.get("notes"),
                            application.get("city"),
                            application.get("delivery_days"),
                        ),
                    )
                else:
                    self._require(connection, "suppliers", supplier_id)
                    connection.execute(
                        """
                        UPDATE suppliers
                        SET name = ?,
                            bin = COALESCE(?, bin),
                            phone = COALESCE(?, phone),
                            address = COALESCE(?, address),
                            contact_person = COALESCE(?, contact_person),
                            email = COALESCE(?, email),
                            notes = COALESCE(?, notes),
                            city = COALESCE(?, city),
                            delivery_days = COALESCE(?, delivery_days)
                        WHERE id = ?
                        """,
                        (
                            application["name"],
                            application.get("bin"),
                            application.get("phone"),
                            application.get("address"),
                            application.get("contact_person"),
                            application.get("email"),
                            application.get("notes"),
                            application.get("city"),
                            application.get("delivery_days"),
                            supplier_id,
                        ),
                    )
                if password_hash:
                    connection.execute(
                        "UPDATE suppliers SET password_hash = ?, portal_access_enabled = TRUE WHERE id = ?",
                        (password_hash, supplier_id),
                    )
                requester = application.get("actor_id") or ""
                if requester.startswith("tetis-actor:"):
                    self._link_requester_to_supplier(connection, requester.removeprefix("tetis-actor:"), supplier_id)
            now = now_iso()
            connection.execute(
                """
                UPDATE supplier_applications
                SET status = ?,
                    supplier_id = ?,
                    review_reason = ?,
                    reviewed_by = ?,
                    reviewed_at = ?
                WHERE id = ?
                """,
                (
                    data.status,
                    supplier_id,
                    data.reason,
                    reviewer_id,
                    now,
                    application_id,
                ),
            )
            updated = self._get_supplier_application(connection, application_id)
            self._audit(
                connection,
                reviewer_id,
                AuditAction.UPDATE,
                "supplier_application",
                application_id,
                {"before": application, "after": updated},
            )
            return updated

    def _link_requester_to_supplier(self, connection, requester_actor_id: str, supplier_id: int) -> None:
        """Auto-link the tetis user who submitted an approved supplier application
        to that supplier, so they can switch into supplier mode without an admin
        having to manually type a supplier ID into the Users screen."""
        import secrets
        if requester_actor_id.isdigit():
            row = connection.execute(
                "SELECT id FROM sklad_users WHERE id = ?", (int(requester_actor_id),)
            ).fetchone()
            if row:
                connection.execute(
                    "UPDATE sklad_users SET supplier_id = ? WHERE id = ?",
                    (supplier_id, row["id"]),
                )
                return
        username = f"tetis:{requester_actor_id}"
        existing = connection.execute(
            "SELECT id FROM sklad_users WHERE username = ?", (username,)
        ).fetchone()
        if existing:
            connection.execute(
                "UPDATE sklad_users SET supplier_id = ? WHERE id = ?",
                (supplier_id, existing["id"]),
            )
            return
        connection.execute(
            "INSERT INTO sklad_users (username, full_name, password_hash, roles, warehouse_ids, supplier_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (username, "Поставщик", secrets.token_hex(32), "warehouse_manager", "[]", supplier_id),
        )
