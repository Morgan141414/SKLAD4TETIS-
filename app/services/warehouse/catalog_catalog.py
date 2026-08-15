from __future__ import annotations

from typing import Any

from app.domain.enums import AuditAction
from app.domain.errors import (
    NotFoundError,
    ValidationError,
)
from app.domain.schemas import (
    CategoryCreate,
    CategoryUpdate,
    SupplierApplicationCreate,
    SupplierCreate,
    SupplierUpdate,
)
from app.services.warehouse.base import PRODUCT_UNITS, WarehouseServiceBase
from app.storage.sqlite import (
    insert_and_get_id,
    now_iso,
)


class CatalogCatalogMixin(WarehouseServiceBase):
    def list_product_units(self) -> list[str]:
        return list(PRODUCT_UNITS)

    def _normalize_product_unit(self, unit: str) -> str:
        normalized = unit.strip()
        for allowed_unit in PRODUCT_UNITS:
            if normalized.casefold() == allowed_unit.casefold():
                return allowed_unit
        raise ValidationError(f"Unsupported product unit: {unit}")

    def _validate_marketplace_inquiry_source(self, source: str | None) -> str | None:
        if source is None:
            return None
        if source not in {"marqet", "qpartner", "api"}:
            raise ValidationError("Marketplace inquiry source must be marqet, qpartner, or api")
        return source

    def _validate_marketplace_inquiry_status(self, status: str | None) -> str | None:
        if status is None:
            return None
        if status not in {"pending", "responded", "ordered", "closed"}:
            raise ValidationError("Marketplace inquiry status must be pending, responded, ordered, or closed")
        return status

    def create_category(self, data: CategoryCreate, actor_id: str = "system") -> dict[str, Any]:
        with self.database.transaction() as connection:
            category_id = insert_and_get_id(
                connection, "INSERT INTO categories(name, is_active) VALUES (?, ?)", (data.name, 1)
            )
            self._audit(connection, actor_id, AuditAction.CREATE, "category", category_id, data)
            return self._get_by_id(connection, "categories", category_id)

    def list_categories(
        self, limit: int = 100, offset: int = 0, q: str | None = None
    ) -> list[dict[str, Any]]:
        if not q or not q.strip():
            return self._list_table("categories", "name, id", limit, offset, where="is_active = 1")
        safe_limit = max(1, min(limit, 500))
        safe_offset = max(0, offset)
        search = q.strip().casefold()
        connection = self.database.connect()
        try:
            rows = connection.execute(
                """
                SELECT * FROM categories
                WHERE is_active = 1
                ORDER BY name, id
                """
            ).fetchall()
            filtered = [
                dict(row)
                for row in rows
                if search in str(row["name"]).casefold()
            ]
            return filtered[safe_offset : safe_offset + safe_limit]
        finally:
            self._close_connection(connection)

    def update_category(
        self, category_id: int, data: CategoryUpdate, actor_id: str = "system"
    ) -> dict[str, Any]:
        with self.database.transaction() as connection:
            before = self._get_by_id(connection, "categories", category_id)
            connection.execute(
                "UPDATE categories SET name = ? WHERE id = ?",
                (data.name, category_id),
            )
            updated = self._get_by_id(connection, "categories", category_id)
            self._audit(
                connection,
                actor_id,
                AuditAction.UPDATE,
                "category",
                category_id,
                {"before": before, "after": updated},
            )
            return updated

    def delete_category(self, category_id: int, actor_id: str = "system") -> dict[str, Any]:
        with self.database.transaction() as connection:
            before = self._get_by_id(connection, "categories", category_id)
            active_products = connection.execute(
                """
                SELECT COUNT(*) AS total
                FROM products
                WHERE category_id = ? AND is_active = 1
                """,
                (category_id,),
            ).fetchone()
            if active_products and int(active_products["total"]) > 0:
                raise ValidationError("Category has active products")
            connection.execute("UPDATE categories SET is_active = ? WHERE id = ?", (0, category_id))
            updated = self._get_by_id(connection, "categories", category_id)
            self._audit(
                connection,
                actor_id,
                AuditAction.DELETE,
                "category",
                category_id,
                {"before": before, "after": updated},
            )
            return updated

    def create_supplier(self, data: SupplierCreate, actor_id: str = "system") -> dict[str, Any]:
        with self.database.transaction() as connection:
            supplier_id = insert_and_get_id(
                connection,
                """
                INSERT INTO suppliers(
                  name, bin, phone, address, rating, is_preferred,
                  contact_person, email, contract_number, contract_expires_on, payment_terms, notes,
                  lat, lng, city, delivery_days
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data.name,
                    data.bin,
                    data.phone,
                    data.address,
                    data.rating,
                    1 if data.is_preferred else 0,
                    data.contact_person,
                    data.email,
                    data.contract_number,
                    data.contract_expires_on.isoformat() if data.contract_expires_on else None,
                    data.payment_terms,
                    data.notes,
                    getattr(data, "lat", None),
                    getattr(data, "lng", None),
                    getattr(data, "city", None),
                    getattr(data, "delivery_days", None),
                ),
            )
            self._audit(connection, actor_id, AuditAction.CREATE, "supplier", supplier_id, data)
            return self._get_by_id(connection, "suppliers", supplier_id)

    def list_suppliers(
        self, limit: int = 100, offset: int = 0, q: str | None = None
    ) -> list[dict[str, Any]]:
        if not q or not q.strip():
            return self._list_table("suppliers", "name, id", limit, offset)
        safe_limit = max(1, min(limit, 500))
        safe_offset = max(0, offset)
        search = q.strip().casefold()
        connection = self.database.connect()
        try:
            rows = connection.execute(
                """
                SELECT * FROM suppliers
                ORDER BY name, id
                """
            ).fetchall()
            searchable_fields = (
                "name",
                "bin",
                "phone",
                "address",
                "contact_person",
                "email",
                "contract_number",
                "payment_terms",
                "notes",
            )
            filtered = []
            for row in rows:
                item = dict(row)
                haystack = " ".join(str(item.get(field) or "") for field in searchable_fields).casefold()
                if search in haystack:
                    filtered.append(item)
            return filtered[safe_offset : safe_offset + safe_limit]
        finally:
            self._close_connection(connection)

    def update_supplier(
        self, supplier_id: int, data: SupplierUpdate, actor_id: str = "system"
    ) -> dict[str, Any]:
        with self.database.transaction() as connection:
            before = self._get_by_id(connection, "suppliers", supplier_id)
            connection.execute(
                """
                UPDATE suppliers
                SET name = ?,
                    bin = ?,
                    phone = ?,
                    address = ?,
                    rating = ?,
                    is_preferred = ?,
                    contact_person = ?,
                    email = ?,
                    contract_number = ?,
                    contract_expires_on = ?,
                    payment_terms = ?,
                    notes = ?,
                    lat = ?,
                    lng = ?,
                    city = ?,
                    delivery_days = ?
                WHERE id = ?
                """,
                (
                    data.name,
                    data.bin,
                    data.phone,
                    data.address,
                    data.rating,
                    1 if data.is_preferred else 0,
                    data.contact_person,
                    data.email,
                    data.contract_number,
                    data.contract_expires_on.isoformat() if data.contract_expires_on else None,
                    data.payment_terms,
                    data.notes,
                    getattr(data, "lat", None),
                    getattr(data, "lng", None),
                    getattr(data, "city", None),
                    getattr(data, "delivery_days", None),
                    supplier_id,
                ),
            )
            updated = self._get_by_id(connection, "suppliers", supplier_id)
            self._audit(
                connection,
                actor_id,
                AuditAction.UPDATE,
                "supplier",
                supplier_id,
                {"before": before, "after": updated},
            )
            return updated

    def submit_supplier_application(
        self, data: SupplierApplicationCreate, actor_id: str = "public"
    ) -> dict[str, Any]:
        with self.database.transaction() as connection:
            existing = connection.execute(
                """
                SELECT id FROM supplier_applications
                WHERE lower(email) = lower(?)
                  AND status IN ('pending', 'needs_changes')
                """,
                (data.email,),
            ).fetchone()
            if existing:
                raise ValidationError("Active supplier application already exists for this email")
            now = now_iso()
            application_id = insert_and_get_id(
                connection,
                """
                INSERT INTO supplier_applications(
                  actor_id, supplier_id, status, name, bin, phone, email,
                  contact_person, address, city, delivery_days, notes,
                  review_reason, submitted_at, reviewed_by, reviewed_at
                ) VALUES (?, NULL, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL, NULL)
                """,
                (
                    actor_id,
                    data.name,
                    data.bin,
                    data.phone,
                    data.email,
                    data.contact_person,
                    data.address,
                    data.city,
                    data.delivery_days,
                    data.notes,
                    now,
                ),
            )
            application = self._get_supplier_application(connection, application_id)
            self._audit(connection, actor_id, AuditAction.CREATE, "supplier_application", application_id, application)
            return application

    def get_supplier_application(self, application_id: int) -> dict[str, Any]:
        connection = self.database.connect()
        try:
            return self._get_supplier_application(connection, application_id)
        finally:
            self._close_connection(connection)

    def list_supplier_applications(
        self, status: str | None = None, limit: int = 100, offset: int = 0
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 500))
        safe_offset = max(0, offset)
        params: tuple[Any, ...] = ()
        where = ""
        if status:
            where = "WHERE sa.status = ?"
            params = (status,)
        connection = self.database.connect()
        try:
            rows = connection.execute(
                f"""
                SELECT sa.*, s.name AS supplier_name
                FROM supplier_applications sa
                LEFT JOIN suppliers s ON s.id = sa.supplier_id
                {where}
                ORDER BY sa.submitted_at DESC, sa.id DESC
                LIMIT ? OFFSET ?
                """,
                (*params, safe_limit, safe_offset),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            self._close_connection(connection)

    def count_supplier_applications(self, status: str | None = None) -> int:
        connection = self.database.connect()
        try:
            if status:
                row = connection.execute(
                    "SELECT COUNT(*) AS total FROM supplier_applications WHERE status = ?",
                    (status,),
                ).fetchone()
            else:
                row = connection.execute("SELECT COUNT(*) AS total FROM supplier_applications").fetchone()
            return int(row["total"])
        finally:
            self._close_connection(connection)

    def get_my_supplier_applications(self, actor_id: str) -> list[dict[str, Any]]:
        """Return applications submitted by this actor (tetis-actor:{actor_id} or actor_id directly)."""
        connection = self.database.connect()
        patterns = [f"tetis-actor:{actor_id}", actor_id]
        rows = connection.execute(
            """
            SELECT id, name, bin, email, phone, contact_person, city, address,
                   delivery_days, notes, status, actor_id, review_reason,
                   reviewed_by, reviewed_at, supplier_id, submitted_at
            FROM supplier_applications
            WHERE actor_id IN (?, ?)
            ORDER BY id DESC
            """,
            tuple(patterns),
        ).fetchall()
        return [dict(r) for r in rows]

    def resubmit_supplier_application(
        self, application_id: int, data: dict[str, Any], actor_id: str
    ) -> dict[str, Any]:
        """Update application fields and reset status to pending (only allowed if needs_changes)."""
        with self.database.transaction() as connection:
            app = self._get_supplier_application(connection, application_id)
            # Verify actor owns this application
            expected = [f"tetis-actor:{actor_id}", actor_id]
            if app.get("actor_id") not in expected:
                raise PermissionError("Cannot edit another actor's application")
            if app["status"] != "needs_changes":
                raise ValueError(f"Cannot resubmit application with status '{app['status']}'")
            update_fields = {k: v for k, v in data.items() if k in (
                "name", "bin", "email", "phone", "contact_person",
                "city", "address", "delivery_days", "notes"
            ) if v is not None}
            if update_fields:
                set_clause = ", ".join(f"{k} = ?" for k in update_fields)
                connection.execute(
                    f"UPDATE supplier_applications SET {set_clause}, status = 'pending', review_reason = NULL, reviewed_by = NULL, reviewed_at = NULL WHERE id = ?",
                    (*update_fields.values(), application_id),
                )
            else:
                connection.execute(
                    "UPDATE supplier_applications SET status = 'pending', review_reason = NULL, reviewed_by = NULL, reviewed_at = NULL WHERE id = ?",
                    (application_id,),
                )
            return self._get_supplier_application(connection, application_id)

    def get_supplier_by_id(self, supplier_id: int) -> dict[str, Any]:
        """Get a single supplier record by ID."""
        connection = self.database.connect()
        row = connection.execute(
            """
            SELECT id, name, bin, email, phone, contact_person, city, address,
                   delivery_days, rating, notes, is_preferred, contract_number,
                   contract_expires_on, payment_terms, lat, lng,
                   bank_details, website, inn, is_verified, verified_at, legal_name, verification_comment
            FROM suppliers WHERE id = ?
            """,
            (supplier_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"Supplier {supplier_id} not found")
        return dict(row)

    def update_supplier_self(
        self, supplier_id: int, data: dict[str, Any], actor_id: str
    ) -> dict[str, Any]:
        """Update supplier's own profile — only contact fields, not name/rating/contract."""
        allowed = {"email", "phone", "contact_person", "city", "address", "delivery_days", "notes", "bank_details", "website", "inn"}
        updates = {k: v for k, v in data.items() if k in allowed and v is not None}
        if not updates:
            return self.get_supplier_by_id(supplier_id)
        with self.database.transaction() as connection:
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            connection.execute(
                f"UPDATE suppliers SET {set_clause} WHERE id = ?",
                (*updates.values(), supplier_id),
            )
            row = connection.execute(
                """
                SELECT id, name, bin, email, phone, contact_person, city, address,
                       delivery_days, rating, notes, is_preferred, contract_number,
                       contract_expires_on, payment_terms, lat, lng,
                       bank_details, website, inn
                FROM suppliers WHERE id = ?
                """,
                (supplier_id,),
            ).fetchone()
            return dict(row) if row else {}

    def add_supplier_verification_doc(
        self, supplier_id: int, doc_type: str, file_url: str,
        original_name: str | None, actor_id: str
    ) -> dict:
        with self.database.transaction() as conn:
            doc_id = insert_and_get_id(
                conn,
                """INSERT INTO supplier_verification_docs
                   (supplier_id, doc_type, file_url, original_name, uploaded_by)
                   VALUES (?, ?, ?, ?, ?)""",
                (supplier_id, doc_type, file_url, original_name, actor_id),
            )
            row = conn.execute(
                "SELECT * FROM supplier_verification_docs WHERE id = ?", (doc_id,)
            ).fetchone()
            return dict(row) if row else {}

    def list_supplier_verification_docs(self, supplier_id: int) -> list[dict]:
        connection = self.database.connect()
        try:
            rows = connection.execute(
                """SELECT id, supplier_id, doc_type, file_url, original_name, uploaded_at, uploaded_by
                   FROM supplier_verification_docs
                   WHERE supplier_id = ?
                   ORDER BY uploaded_at""",
                (supplier_id,)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            self._close_connection(connection)

    def delete_supplier_verification_doc(self, doc_id: int, supplier_id: int) -> None:
        with self.database.transaction() as conn:
            row = conn.execute(
                "SELECT id FROM supplier_verification_docs WHERE id = ? AND supplier_id = ?",
                (doc_id, supplier_id)
            ).fetchone()
            if row is None:
                raise NotFoundError(f"Document {doc_id} not found")
            conn.execute("DELETE FROM supplier_verification_docs WHERE id = ?", (doc_id,))

    def set_supplier_verified(
        self, supplier_id: int, is_verified: bool, comment: str | None, actor_id: str
    ) -> dict:
        with self.database.transaction() as conn:
            if is_verified:
                conn.execute(
                    """UPDATE suppliers SET is_verified = TRUE, verified_at = NOW(),
                       verification_comment = ? WHERE id = ?""",
                    (comment, supplier_id),
                )
            else:
                conn.execute(
                    """UPDATE suppliers SET is_verified = FALSE, verified_at = NULL,
                       verification_comment = ? WHERE id = ?""",
                    (comment, supplier_id),
                )
            row = conn.execute(
                """SELECT id, name, bin, email, phone, city, is_verified, verified_at,
                          legal_name, verification_comment
                   FROM suppliers WHERE id = ?""",
                (supplier_id,)
            ).fetchone()
            return dict(row) if row else {}

    def create_purchase_order(
        self, inquiry_id: int, actor_id: str, buyer_data: dict
    ) -> dict:
        """Create or return existing PO for an inquiry."""
        with self.database.transaction() as conn:
            inq = conn.execute(
                """SELECT mi.*, ci.product_name, ci.unit, s.name AS supplier_name,
                          s.bin AS supplier_bin, s.address AS supplier_address,
                          s.phone AS supplier_phone, s.email AS supplier_email,
                          s.city AS supplier_city
                   FROM marketplace_inquiries mi
                   JOIN supplier_catalog_items ci ON ci.id = mi.catalog_item_id
                   JOIN suppliers s ON s.id = mi.supplier_id
                   WHERE mi.id = ? AND mi.actor_id = ?""",
                (inquiry_id, actor_id)
            ).fetchone()
            if inq is None:
                raise PermissionError("Inquiry not found or not yours")
            # Return existing PO if already created
            existing = conn.execute(
                "SELECT * FROM purchase_orders WHERE inquiry_id = ?", (inquiry_id,)
            ).fetchone()
            if existing:
                return dict(existing)
            # Generate PO number: PO-YYYY-NNNNNN
            from datetime import datetime as _dt
            year = _dt.now().year
            seq = conn.execute("SELECT nextval('purchase_order_seq') AS n").fetchone()["n"]
            po_number = f"PO-{year}-{seq:06d}"
            po_id = insert_and_get_id(
                conn,
                """INSERT INTO purchase_orders
                   (po_number, inquiry_id, buyer_name, buyer_bin, buyer_address,
                    buyer_contact, delivery_address, payment_terms, notes, status,
                    delivery_type, delivery_price, delivery_included, escrow_amount)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?, ?)""",
                (
                    po_number,
                    inquiry_id,
                    buyer_data.get("buyer_name"),
                    buyer_data.get("buyer_bin"),
                    buyer_data.get("buyer_address"),
                    buyer_data.get("buyer_contact"),
                    buyer_data.get("delivery_address"),
                    buyer_data.get("payment_terms", "По договорённости"),
                    buyer_data.get("notes"),
                    buyer_data.get("delivery_type"),
                    buyer_data.get("delivery_price"),
                    buyer_data.get("delivery_included", False),
                    buyer_data.get("escrow_amount"),
                ),
            )
            # Also mark inquiry as ordered if pending/responded
            if inq["status"] in ("pending", "responded"):
                conn.execute(
                    "UPDATE marketplace_inquiries SET status = 'ordered' WHERE id = ?",
                    (inquiry_id,)
                )
            row = conn.execute("SELECT * FROM purchase_orders WHERE id = ?", (po_id,)).fetchone()
            return dict(row) if row else {}

    def get_purchase_order(self, inquiry_id: int, actor_id: str) -> dict:
        connection = self.database.connect()
        try:
            inq = connection.execute(
                """SELECT mi.*, ci.product_name, ci.unit, ci.description AS item_description,
                          ci.image_url,
                          s.name AS supplier_name, s.bin AS supplier_bin,
                          s.address AS supplier_address, s.phone AS supplier_phone,
                          s.email AS supplier_email, s.city AS supplier_city,
                          s.bank_details AS supplier_bank_details,
                          s.inn AS supplier_inn, s.is_verified AS supplier_verified,
                          w.name AS warehouse_name
                   FROM marketplace_inquiries mi
                   JOIN supplier_catalog_items ci ON ci.id = mi.catalog_item_id
                   JOIN suppliers s ON s.id = mi.supplier_id
                   LEFT JOIN warehouses w ON w.id = mi.warehouse_id
                   WHERE mi.id = ? AND mi.actor_id = ?""",
                (inquiry_id, actor_id)
            ).fetchone()
            if inq is None:
                raise PermissionError("Inquiry not found or not yours")
            po = connection.execute(
                "SELECT * FROM purchase_orders WHERE inquiry_id = ?", (inquiry_id,)
            ).fetchone()
            result = {"inquiry": dict(inq), "po": dict(po) if po else None}
            return result
        finally:
            self._close_connection(connection)

    def list_catalog_categories(self, parent_id: int | None = None) -> list[dict]:
        """Return all categories optionally filtered by parent."""
        connection = self.database.connect()
        try:
            if parent_id is not None:
                rows = connection.execute(
                    "SELECT id, parent_id, name, slug, icon, sort_order FROM catalog_categories WHERE parent_id = ? ORDER BY sort_order, name",
                    (parent_id,)
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT id, parent_id, name, slug, icon, sort_order FROM catalog_categories ORDER BY sort_order, name"
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            self._close_connection(connection)

    def create_catalog_category(self, data: dict, actor_id: str) -> dict:
        import re
        name = (data.get("name") or "").strip()
        if not name:
            raise ValidationError("Category name is required")
        slug = data.get("slug") or re.sub(r"[^a-z0-9-]", "-", name.lower().strip())
        with self.database.transaction() as conn:
            cat_id = insert_and_get_id(
                conn,
                "INSERT INTO catalog_categories (parent_id, name, slug, icon, sort_order) VALUES (?, ?, ?, ?, ?)",
                (data.get("parent_id"), name, slug, data.get("icon"), data.get("sort_order", 0)),
            )
            row = conn.execute("SELECT * FROM catalog_categories WHERE id = ?", (cat_id,)).fetchone()
            return dict(row) if row else {}

    def get_price_tiers(self, catalog_item_id: int) -> list[dict]:
        """Get volume pricing tiers for a catalog item."""
        connection = self.database.connect()
        try:
            rows = connection.execute(
                """SELECT id, catalog_item_id, min_quantity, unit_price, label, created_at
                   FROM catalog_item_price_tiers
                   WHERE catalog_item_id = ?
                   ORDER BY min_quantity""",
                (catalog_item_id,)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            self._close_connection(connection)

    def set_price_tiers(self, catalog_item_id: int, supplier_id: int, tiers: list[dict]) -> list[dict]:
        """Replace all price tiers for a catalog item."""
        with self.database.transaction() as conn:
            # Verify ownership
            item = conn.execute(
                "SELECT id FROM supplier_catalog_items WHERE id = ? AND supplier_id = ?",
                (catalog_item_id, supplier_id)
            ).fetchone()
            if item is None:
                raise PermissionError("Catalog item not found or not yours")
            # Validate tiers
            for t in tiers:
                if float(t.get("min_quantity", 0)) <= 0:
                    raise ValidationError("min_quantity must be > 0")
                if float(t.get("unit_price", 0)) <= 0:
                    raise ValidationError("unit_price must be > 0")
            # Replace
            conn.execute(
                "DELETE FROM catalog_item_price_tiers WHERE catalog_item_id = ?",
                (catalog_item_id,)
            )
            for t in tiers:
                conn.execute(
                    """INSERT INTO catalog_item_price_tiers (catalog_item_id, min_quantity, unit_price, label)
                       VALUES (?, ?, ?, ?)""",
                    (catalog_item_id, float(t["min_quantity"]), float(t["unit_price"]), t.get("label"))
                )
            rows = conn.execute(
                "SELECT * FROM catalog_item_price_tiers WHERE catalog_item_id = ? ORDER BY min_quantity",
                (catalog_item_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    def resolve_price_for_quantity(self, catalog_item_id: int, quantity: float) -> float | None:
        """Return best (lowest) unit price for a given quantity using tier pricing."""
        connection = self.database.connect()
        try:
            item = connection.execute(
                "SELECT unit_price FROM supplier_catalog_items WHERE id = ?",
                (catalog_item_id,)
            ).fetchone()
            if item is None:
                return None
            base_price = float(item["unit_price"]) if item["unit_price"] else None
            tiers = connection.execute(
                """SELECT unit_price FROM catalog_item_price_tiers
                   WHERE catalog_item_id = ? AND min_quantity <= ?
                   ORDER BY min_quantity DESC LIMIT 1""",
                (catalog_item_id, quantity)
            ).fetchone()
            if tiers:
                tier_price = float(tiers["unit_price"])
                return tier_price if (base_price is None or tier_price < base_price) else base_price
            return base_price
        finally:
            self._close_connection(connection)

    # ── Supplier catalog (marketplace) ──────────────────────────────────────

    def list_supplier_catalog(
        self,
        supplier_id: int | None = None,
        category: str | None = None,
        search: str | None = None,
        min_price: float | None = None,
        max_price: float | None = None,
        active_only: bool = True,
        sort: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        where = []
        params: list[Any] = []
        if active_only:
            where.append("ci.is_active = TRUE")
        if supplier_id is not None:
            where.append("ci.supplier_id = ?")
            params.append(supplier_id)
        if category:
            where.append("ci.category = ?")
            params.append(category)
        if search:
            # Use trigram similarity if available, fallback to ILIKE
            where.append("((ci.product_name || ' ' || COALESCE(ci.sku,'') || ' ' || COALESCE(ci.description,'') || ' ' || COALESCE(ci.category,'')) ILIKE ?)")
            params.extend([f"%{search}%"])
        if min_price is not None:
            where.append("ci.unit_price >= ?")
            params.append(min_price)
        if max_price is not None:
            where.append("ci.unit_price <= ?")
            params.append(max_price)
        where_clause = f"WHERE {' AND '.join(where)}" if where else ""
        _sort_map = {
            "price_asc": "ci.unit_price ASC",
            "price_desc": "ci.unit_price DESC",
            "delivery_asc": "COALESCE(ci.delivery_days, s.delivery_days, 999) ASC",
            "name_asc": "ci.product_name ASC",
        }
        order_clause = _sort_map.get(sort or "", "ci.updated_at DESC")
        connection = self.database.connect()
        try:
            total_row = connection.execute(
                f"SELECT COUNT(*) AS n FROM supplier_catalog_items ci JOIN suppliers s ON s.id = ci.supplier_id {where_clause}", tuple(params)
            ).fetchone()
            total = total_row["n"] if total_row else 0
            rows = connection.execute(
                f"""
                SELECT ci.*, s.name AS supplier_name, s.city AS supplier_city,
                       s.rating AS supplier_rating, s.phone AS supplier_phone,
                       s.email AS supplier_email, s.delivery_days AS supplier_delivery_days,
                       s.is_verified AS supplier_is_verified,
                       p.name AS linked_product_name,
                       r.avg_rating, r.review_count,
                       COALESCE(f.likes_count, 0) AS likes_count
                FROM supplier_catalog_items ci
                JOIN suppliers s ON s.id = ci.supplier_id
                LEFT JOIN products p ON p.id = ci.product_id
                LEFT JOIN (
                    SELECT catalog_item_id, ROUND(AVG(rating), 1) AS avg_rating, COUNT(*) AS review_count
                    FROM catalog_item_reviews WHERE status = 'approved' GROUP BY catalog_item_id
                ) r ON r.catalog_item_id = ci.id
                LEFT JOIN (
                    SELECT catalog_item_id, COUNT(*) AS likes_count
                    FROM marketplace_favorites GROUP BY catalog_item_id
                ) f ON f.catalog_item_id = ci.id
                {where_clause}
                ORDER BY {order_clause}
                LIMIT ? OFFSET ?
                """,
                tuple(params) + (limit, offset),
            ).fetchall()
            return {"items": [dict(r) for r in rows], "total": total}
        finally:
            self._close_connection(connection)

    def get_catalog_item(self, item_id: int) -> dict[str, Any] | None:
        connection = self.database.connect()
        try:
            row = connection.execute(
                """
                SELECT ci.*, s.name AS supplier_name, s.city AS supplier_city,
                       s.rating AS supplier_rating, s.phone AS supplier_phone,
                       s.email AS supplier_email, s.delivery_days AS supplier_delivery_days,
                       s.is_verified AS supplier_is_verified,
                       r.avg_rating, r.review_count,
                       COALESCE(f.likes_count, 0) AS likes_count
                FROM supplier_catalog_items ci
                JOIN suppliers s ON s.id = ci.supplier_id
                LEFT JOIN (
                    SELECT catalog_item_id, ROUND(AVG(rating), 1) AS avg_rating, COUNT(*) AS review_count
                    FROM catalog_item_reviews WHERE status = 'approved' GROUP BY catalog_item_id
                ) r ON r.catalog_item_id = ci.id
                LEFT JOIN (
                    SELECT catalog_item_id, COUNT(*) AS likes_count
                    FROM marketplace_favorites GROUP BY catalog_item_id
                ) f ON f.catalog_item_id = ci.id
                WHERE ci.id = ?
                """,
                (item_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            self._close_connection(connection)

    def get_catalog_item_favorite_state(self, catalog_item_id: int, actor_id: str) -> dict[str, Any]:
        connection = self.database.connect()
        try:
            self._require_active(connection, "supplier_catalog_items", catalog_item_id)
            favorite = connection.execute(
                "SELECT id FROM marketplace_favorites WHERE actor_id = ? AND catalog_item_id = ?",
                (actor_id, catalog_item_id),
            ).fetchone()
            likes_count = connection.execute(
                "SELECT COUNT(*) AS n FROM marketplace_favorites WHERE catalog_item_id = ?",
                (catalog_item_id,),
            ).fetchone()
            return {"favorited": favorite is not None, "likes_count": likes_count["n"] if likes_count else 0}
        finally:
            self._close_connection(connection)

    def toggle_catalog_item_favorite(self, catalog_item_id: int, actor_id: str) -> dict[str, Any]:
        with self.database.transaction() as connection:
            self._require_active(connection, "supplier_catalog_items", catalog_item_id)
            existing = connection.execute(
                "SELECT id FROM marketplace_favorites WHERE actor_id = ? AND catalog_item_id = ?",
                (actor_id, catalog_item_id),
            ).fetchone()
            if existing:
                connection.execute("DELETE FROM marketplace_favorites WHERE id = ?", (existing["id"],))
                favorited = False
            else:
                connection.execute(
                    "INSERT INTO marketplace_favorites (actor_id, catalog_item_id) VALUES (?, ?)",
                    (actor_id, catalog_item_id),
                )
                favorited = True
            likes_count = connection.execute(
                "SELECT COUNT(*) AS n FROM marketplace_favorites WHERE catalog_item_id = ?",
                (catalog_item_id,),
            ).fetchone()
            return {"favorited": favorited, "likes_count": likes_count["n"] if likes_count else 0}

    def list_catalog_item_favorites(self, actor_id: str, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        connection = self.database.connect()
        try:
            total_row = connection.execute(
                """SELECT COUNT(*) AS n
                   FROM marketplace_favorites mf
                   JOIN supplier_catalog_items ci ON ci.id = mf.catalog_item_id
                   WHERE mf.actor_id = ? AND ci.is_active = TRUE""",
                (actor_id,),
            ).fetchone()
            rows = connection.execute(
                """
                SELECT ci.*, s.name AS supplier_name, s.city AS supplier_city,
                       s.rating AS supplier_rating, s.phone AS supplier_phone,
                       s.email AS supplier_email, s.delivery_days AS supplier_delivery_days,
                       s.is_verified AS supplier_is_verified,
                       r.avg_rating, r.review_count,
                       COALESCE(f.likes_count, 0) AS likes_count,
                       mf.created_at AS favorited_at
                FROM marketplace_favorites mf
                JOIN supplier_catalog_items ci ON ci.id = mf.catalog_item_id
                JOIN suppliers s ON s.id = ci.supplier_id
                LEFT JOIN (
                    SELECT catalog_item_id, ROUND(AVG(rating), 1) AS avg_rating, COUNT(*) AS review_count
                    FROM catalog_item_reviews WHERE status = 'approved' GROUP BY catalog_item_id
                ) r ON r.catalog_item_id = ci.id
                LEFT JOIN (
                    SELECT catalog_item_id, COUNT(*) AS likes_count
                    FROM marketplace_favorites GROUP BY catalog_item_id
                ) f ON f.catalog_item_id = ci.id
                WHERE mf.actor_id = ? AND ci.is_active = TRUE
                ORDER BY mf.created_at DESC
                LIMIT ? OFFSET ?
                """,
                (actor_id, limit, offset),
            ).fetchall()
            return {"items": [dict(r) for r in rows], "total": total_row["n"] if total_row else 0}
        finally:
            self._close_connection(connection)

    # ── Catalog item reviews (product-level ratings, like Kaspi/Amazon) ─────

    def create_catalog_item_review(
        self,
        catalog_item_id: int,
        rating: int,
        comment: str | None,
        reviewer_id: str,
        *,
        image_url: str | None = None,
        reviewer_name: str | None = None,
    ) -> dict[str, Any]:
        if not 1 <= rating <= 5:
            raise ValidationError("Rating must be between 1 and 5")
        image_url = image_url.strip() if image_url else None
        reviewer_name = reviewer_name.strip() if reviewer_name else None
        if image_url and not (
            image_url.startswith("https://")
            or image_url.startswith("http://")
            or image_url.startswith("/uploads/")
        ):
            raise ValidationError("Review image URL must be an absolute URL or uploaded media path")
        with self.database.transaction() as connection:
            self._require(connection, "supplier_catalog_items", catalog_item_id)
            row = connection.execute(
                """INSERT INTO catalog_item_reviews (
                     catalog_item_id, rating, comment, reviewer_id, image_url, reviewer_name, status
                   )
                   VALUES (?, ?, ?, ?, ?, ?, 'approved')
                   RETURNING *""",
                (catalog_item_id, rating, comment, reviewer_id, image_url, reviewer_name),
            ).fetchone()
            return dict(row)

    def list_catalog_item_reviews(self, catalog_item_id: int, status: str = "approved") -> list[dict[str, Any]]:
        connection = self.database.connect()
        try:
            rows = connection.execute(
                "SELECT * FROM catalog_item_reviews WHERE catalog_item_id = ? AND status = ? ORDER BY created_at DESC",
                (catalog_item_id, status),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            self._close_connection(connection)

    def moderate_catalog_item_review(self, review_id: int, action: str) -> dict[str, Any]:
        if action not in ("approve", "reject"):
            raise ValidationError("action must be approve or reject")
        with self.database.transaction() as connection:
            row = connection.execute("SELECT * FROM catalog_item_reviews WHERE id = ?", (review_id,)).fetchone()
            if not row:
                raise NotFoundError(f"catalog_item_reviews#{review_id} not found")
            new_status = "approved" if action == "approve" else "rejected"
            connection.execute("UPDATE catalog_item_reviews SET status = ? WHERE id = ?", (new_status, review_id))
            updated = connection.execute("SELECT * FROM catalog_item_reviews WHERE id = ?", (review_id,)).fetchone()
            return dict(updated)

    def create_catalog_item(self, supplier_id: int, data: dict[str, Any]) -> dict[str, Any]:
        with self.database.transaction() as conn:
            row_id = insert_and_get_id(
                conn,
                """INSERT INTO supplier_catalog_items
                   (supplier_id, product_id, product_name, sku, unit, unit_price,
                    min_order_qty, stock_qty, delivery_days, category, description, is_active,
                    valid_until, condition, delivery_type, delivery_price,
                    delivery_included, delivery_regions, image_url)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    supplier_id,
                    data.get("product_id"),
                    data["product_name"],
                    data.get("sku"),
                    data.get("unit", "шт"),
                    data["unit_price"],
                    data.get("min_order_qty", 1),
                    data.get("stock_qty"),
                    data.get("delivery_days"),
                    data.get("category"),
                    data.get("description"),
                    data.get("is_active", True),
                    data.get("valid_until"),
                    data.get("condition", "new"),
                    data.get("delivery_type", "buyer_arranges"),
                    data.get("delivery_price"),
                    data.get("delivery_included", False),
                    data.get("delivery_regions"),
                    data.get("image_url"),
                ),
            )
            row = conn.execute("SELECT * FROM supplier_catalog_items WHERE id = ?", (row_id,)).fetchone()
            return dict(row) if row else {}

    def update_catalog_item(self, item_id: int, supplier_id: int, data: dict[str, Any]) -> dict[str, Any] | None:
        allowed = {
            "product_name", "sku", "unit", "unit_price", "min_order_qty",
            "stock_qty", "delivery_days", "category", "description", "is_active", "product_id",
            "valid_until", "condition", "delivery_type", "delivery_price",
            "delivery_included", "delivery_regions", "image_url",
        }
        updates = {k: v for k, v in data.items() if k in allowed}
        if not updates:
            return self.get_catalog_item(item_id)
        with self.database.transaction() as conn:
            row = conn.execute(
                "SELECT id, supplier_id FROM supplier_catalog_items WHERE id = ?", (item_id,)
            ).fetchone()
            if row is None or row["supplier_id"] != supplier_id:
                return None
            updates["updated_at"] = now_iso()
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            conn.execute(
                f"UPDATE supplier_catalog_items SET {set_clause} WHERE id = ?",
                (*updates.values(), item_id),
            )
            updated = conn.execute("SELECT * FROM supplier_catalog_items WHERE id = ?", (item_id,)).fetchone()
            return dict(updated) if updated else None

    def delete_catalog_item(self, item_id: int, supplier_id: int) -> bool:
        with self.database.transaction() as conn:
            row = conn.execute(
                "SELECT id, supplier_id FROM supplier_catalog_items WHERE id = ?", (item_id,)
            ).fetchone()
            if row is None or row["supplier_id"] != supplier_id:
                return False
            conn.execute("DELETE FROM supplier_catalog_items WHERE id = ?", (item_id,))
            return True

    # ── Gov procurement ───────────────────────────────────────────────────────

    _GOV_STATUS_NEXT = {"demand": "accepting", "accepting": "closed"}

    def advance_gov_status(self, request_id: int, actor_id: str) -> dict[str, Any]:
        with self.database.transaction() as conn:
            row = conn.execute(
                "SELECT id, is_gov_procurement, gov_status FROM purchase_requests WHERE id = ?",
                (request_id,)
            ).fetchone()
            if row is None:
                raise NotFoundError(f"purchase_requests#{request_id} not found")
            if not row["is_gov_procurement"]:
                raise ValidationError("This request is not a gov procurement request")
            current = row["gov_status"] or "demand"
            nxt = self._GOV_STATUS_NEXT.get(current)
            if nxt is None:
                raise ValidationError(f"Cannot advance from status '{current}'")
            conn.execute(
                "UPDATE purchase_requests SET gov_status = ? WHERE id = ?",
                (nxt, request_id)
            )
            updated = conn.execute("SELECT * FROM purchase_requests WHERE id = ?", (request_id,)).fetchone()
            return dict(updated)

    def add_gov_feedback(
        self, request_id: int, feedback_text: str, rating: int, actor_id: str
    ) -> dict[str, Any]:
        with self.database.transaction() as conn:
            row = conn.execute(
                "SELECT id, is_gov_procurement, gov_status FROM purchase_requests WHERE id = ?",
                (request_id,)
            ).fetchone()
            if row is None:
                raise NotFoundError(f"purchase_requests#{request_id} not found")
            if not row["is_gov_procurement"]:
                raise ValidationError("Not a gov procurement request")
            if row["gov_status"] != "closed":
                raise ValidationError("Feedback can only be added when status is 'closed'")
            conn.execute(
                """UPDATE purchase_requests
                   SET gov_feedback_text = ?, gov_feedback_rating = ?, gov_status = 'feedback'
                   WHERE id = ?""",
                (feedback_text, rating, request_id)
            )
            updated = conn.execute("SELECT * FROM purchase_requests WHERE id = ?", (request_id,)).fetchone()
            return dict(updated)

    # ── Purchase Order escrow + delivery ─────────────────────────────────────

    def update_po_escrow(self, inquiry_id: int, action: str, actor_id: str) -> dict[str, Any]:
        import datetime as _dt
        valid = {"reserve", "release", "refund"}
        if action not in valid:
            raise ValidationError(f"action must be one of {valid}")
        with self.database.transaction() as conn:
            inq = conn.execute(
                "SELECT id, actor_id FROM marketplace_inquiries WHERE id = ?", (inquiry_id,)
            ).fetchone()
            if inq is None or inq["actor_id"] != actor_id:
                raise PermissionError("Inquiry not found or not yours")
            po = conn.execute(
                "SELECT id, escrow_status FROM purchase_orders WHERE inquiry_id = ?", (inquiry_id,)
            ).fetchone()
            if po is None:
                raise NotFoundError("Purchase order not found — create it first")
            now = _dt.datetime.now(_dt.UTC).isoformat()
            if action == "reserve":
                conn.execute(
                    """UPDATE purchase_orders
                       SET escrow_status = 'reserved', escrow_reserved_at = ?
                       WHERE id = ?""",
                    (now, po["id"])
                )
            elif action == "release":
                conn.execute(
                    """UPDATE purchase_orders
                       SET escrow_status = 'released', escrow_released_at = ?
                       WHERE id = ?""",
                    (now, po["id"])
                )
            else:  # refund
                conn.execute(
                    """UPDATE purchase_orders
                       SET escrow_status = 'refunded', escrow_released_at = ?
                       WHERE id = ?""",
                    (now, po["id"])
                )
            updated = conn.execute("SELECT * FROM purchase_orders WHERE id = ?", (po["id"],)).fetchone()
            return dict(updated)

    def update_po_delivery(
        self, inquiry_id: int, data: dict[str, Any], actor_id: str
    ) -> dict[str, Any]:
        import datetime as _dt
        with self.database.transaction() as conn:
            inq = conn.execute(
                "SELECT id, actor_id FROM marketplace_inquiries WHERE id = ?", (inquiry_id,)
            ).fetchone()
            if inq is None or inq["actor_id"] != actor_id:
                raise PermissionError("Inquiry not found or not yours")
            po = conn.execute(
                "SELECT id, escrow_status FROM purchase_orders WHERE inquiry_id = ?", (inquiry_id,)
            ).fetchone()
            if po is None:
                raise NotFoundError("Purchase order not found")
            allowed = {
                "delivery_status", "delivery_tracking_number",
                "delivery_type", "delivery_price", "delivery_included",
            }
            updates = {k: v for k, v in data.items() if k in allowed}
            now = _dt.datetime.now(_dt.UTC).isoformat()
            if updates.get("delivery_status") == "shipped":
                updates["delivery_shipped_at"] = now
            elif updates.get("delivery_status") == "delivered":
                updates["delivery_delivered_at"] = now
                if po.get("escrow_status") == "held":
                    updates["escrow_status"] = "released"
                    updates["escrow_released_at"] = now
            if updates:
                set_clause = ", ".join(f"{k} = ?" for k in updates)
                conn.execute(
                    f"UPDATE purchase_orders SET {set_clause} WHERE id = ?",
                    (*updates.values(), po["id"])
                )
            updated = conn.execute("SELECT * FROM purchase_orders WHERE id = ?", (po["id"],)).fetchone()
            return dict(updated)

    # ── Auction escrow ────────────────────────────────────────────────────────

    def update_auction_escrow(self, auction_id: int, action: str, actor_id: str) -> dict[str, Any]:
        import datetime as _dt
        valid = {"reserve", "release", "refund"}
        if action not in valid:
            raise ValidationError(f"action must be one of {valid}")
        with self.database.transaction() as conn:
            auction = conn.execute(
                "SELECT id, status, winner_supplier_id, escrow_status FROM auctions WHERE id = ?",
                (auction_id,)
            ).fetchone()
            if auction is None:
                raise NotFoundError(f"auctions#{auction_id} not found")
            now = _dt.datetime.now(_dt.UTC).isoformat()
            if action == "reserve":
                conn.execute(
                    """UPDATE auctions
                       SET escrow_status = 'reserved', escrow_reserved_at = ?
                       WHERE id = ?""",
                    (now, auction_id)
                )
            elif action == "release":
                conn.execute(
                    """UPDATE auctions
                       SET escrow_status = 'released', escrow_released_at = ?
                       WHERE id = ?""",
                    (now, auction_id)
                )
            else:
                conn.execute(
                    """UPDATE auctions
                       SET escrow_status = 'refunded', escrow_released_at = ?
                       WHERE id = ?""",
                    (now, auction_id)
                )
            updated = conn.execute("SELECT * FROM auctions WHERE id = ?", (auction_id,)).fetchone()
            return dict(updated)

    def list_suppliers_directory(
        self,
        city: str | None = None,
        category: str | None = None,
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Return all suppliers that are active in the marketplace (portal-enabled or have catalog items)."""
        where = ["(s.portal_access_enabled = TRUE OR EXISTS (SELECT 1 FROM supplier_catalog_items ci2 WHERE ci2.supplier_id = s.id AND ci2.is_active = TRUE))"]
        params: list[Any] = []
        if city:
            where.append("s.city ILIKE ?")
            params.append(f"%{city}%")
        if search:
            where.append("(s.name ILIKE ? OR s.contact_person ILIKE ?)")
            params.extend([f"%{search}%", f"%{search}%"])
        if category:
            where.append("EXISTS (SELECT 1 FROM supplier_catalog_items ci WHERE ci.supplier_id = s.id AND ci.category = ? AND ci.is_active = TRUE)")
            params.append(category)
        where_clause = f"WHERE {' AND '.join(where)}"
        connection = self.database.connect()
        try:
            total_row = connection.execute(f"SELECT COUNT(*) AS n FROM suppliers s {where_clause}", tuple(params)).fetchone()
            total = total_row["n"] if total_row else 0
            rows = connection.execute(
                f"""
                SELECT s.id, s.name, s.city, s.address, s.phone, s.email,
                       s.contact_person, s.delivery_days, s.rating, s.notes,
                       s.is_preferred, s.payment_terms, s.is_verified,
                       COUNT(ci.id) FILTER (WHERE ci.is_active) AS catalog_items_count,
                       MIN(ci.unit_price) AS min_price,
                       MAX(ci.unit_price) AS max_price,
                       array_agg(DISTINCT ci.category) FILTER (WHERE ci.category IS NOT NULL AND ci.is_active) AS categories
                FROM suppliers s
                LEFT JOIN supplier_catalog_items ci ON ci.supplier_id = s.id
                {where_clause}
                GROUP BY s.id
                ORDER BY s.is_preferred DESC, s.rating DESC NULLS LAST, catalog_items_count DESC, s.id
                LIMIT ? OFFSET ?
                """,
                tuple(params) + (limit, offset),
            ).fetchall()
            return {"items": [dict(r) for r in rows], "total": total}
        finally:
            self._close_connection(connection)

    def get_supplier_stats(self, supplier_id: int) -> dict[str, Any]:
        """Return dashboard stats for a supplier."""
        connection = self.database.connect()
        try:
            catalog_row = connection.execute(
                "SELECT COUNT(*) AS total, COUNT(*) FILTER (WHERE is_active) AS active FROM supplier_catalog_items WHERE supplier_id = ?",
                (supplier_id,)
            ).fetchone()
            inquiry_row = connection.execute(
                "SELECT COUNT(*) AS total, COUNT(*) FILTER (WHERE status = 'pending') AS pending FROM marketplace_inquiries WHERE supplier_id = ?",
                (supplier_id,)
            ).fetchone()
            auction_row = connection.execute(
                "SELECT COUNT(*) AS won FROM auctions WHERE winner_supplier_id = ?",
                (supplier_id,)
            ).fetchone()
            review_row = connection.execute(
                "SELECT COUNT(*) AS total, AVG(rating) AS avg FROM supplier_reviews WHERE supplier_id = ? AND status = 'approved'",
                (supplier_id,)
            ).fetchone()
            shipment_row = connection.execute(
                "SELECT COUNT(*) AS active FROM shipments WHERE supplier_id = ? AND status IN ('in_transit','delayed')",
                (supplier_id,)
            ).fetchone()
            return {
                "catalog_total": catalog_row["total"] if catalog_row else 0,
                "catalog_active": catalog_row["active"] if catalog_row else 0,
                "inquiries_total": inquiry_row["total"] if inquiry_row else 0,
                "inquiries_pending": inquiry_row["pending"] if inquiry_row else 0,
                "auctions_won": auction_row["won"] if auction_row else 0,
                "reviews_total": review_row["total"] if review_row else 0,
                "reviews_avg": float(review_row["avg"]) if review_row and review_row["avg"] else None,
                "shipments_active": shipment_row["active"] if shipment_row else 0,
            }
        finally:
            self._close_connection(connection)

    def get_supplier_profile(self, supplier_id: int) -> dict[str, Any] | None:
        """Public storefront view of a supplier: profile, rating, catalog and reviews."""
        connection = self.database.connect()
        try:
            supplier = connection.execute(
                """SELECT id, name, legal_name, city, address, phone, email, contact_person,
                          delivery_days, rating, is_preferred, is_verified, verified_at, payment_terms
                   FROM suppliers WHERE id = ?""",
                (supplier_id,),
            ).fetchone()
            if supplier is None:
                return None
            stats = connection.execute(
                """SELECT COUNT(*) FILTER (WHERE is_active) AS catalog_items_count,
                          MIN(unit_price) FILTER (WHERE is_active) AS min_price,
                          MAX(unit_price) FILTER (WHERE is_active) AS max_price
                   FROM supplier_catalog_items WHERE supplier_id = ?""",
                (supplier_id,),
            ).fetchone()
            review_stats = connection.execute(
                "SELECT COUNT(*) AS total, ROUND(AVG(rating), 1) AS avg FROM supplier_reviews WHERE supplier_id = ? AND status = 'approved'",
                (supplier_id,),
            ).fetchone()
            catalog_items = connection.execute(
                """SELECT id, product_name, sku, unit, unit_price, stock_qty, image_url, category
                   FROM supplier_catalog_items WHERE supplier_id = ? AND is_active = TRUE
                   ORDER BY updated_at DESC LIMIT 24""",
                (supplier_id,),
            ).fetchall()
            reviews = connection.execute(
                """SELECT id, rating, comment, reviewer_id, created_at FROM supplier_reviews
                   WHERE supplier_id = ? AND status = 'approved' ORDER BY created_at DESC LIMIT 10""",
                (supplier_id,),
            ).fetchall()
            result = dict(supplier)
            result["catalog_items_count"] = stats["catalog_items_count"] if stats else 0
            result["min_price"] = stats["min_price"] if stats else None
            result["max_price"] = stats["max_price"] if stats else None
            result["reviews_count"] = review_stats["total"] if review_stats else 0
            result["reviews_avg"] = float(review_stats["avg"]) if review_stats and review_stats["avg"] is not None else None
            result["catalog_items"] = [dict(r) for r in catalog_items]
            result["reviews"] = [dict(r) for r in reviews]
            return result
        finally:
            self._close_connection(connection)
