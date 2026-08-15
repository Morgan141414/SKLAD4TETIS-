from __future__ import annotations

from typing import Any

from app.domain.enums import AuditAction
from app.domain.errors import (
    ConflictError,
    NotFoundError,
    ValidationError,
)
from app.domain.schemas import (
    ProductCreate,
    ProductUpdate,
    SensorDeviceCreate,
    SensorDeviceUpdate,
    SensorReadingCreate,
    WarehouseCreate,
    WarehouseUpdate,
)
from app.services.warehouse.base import WarehouseServiceBase
from app.storage.sqlite import (
    decimal_to_db,
    insert_and_get_id,
    now_iso,
)


class WarehouseAssetsMixin(WarehouseServiceBase):
    def create_warehouse(self, data: WarehouseCreate, actor_id: str = "system") -> dict[str, Any]:
        with self.database.transaction() as connection:
            warehouse_id = insert_and_get_id(
                connection,
                """
                INSERT INTO warehouses(
                  name, department, tetis_org_id, external_tetis_id,
                  mis_clinic_id, mis_room_id,
                  storage_zone, capacity_limit, storage_conditions, responsible_person
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data.name,
                    data.department,
                    data.tetis_org_id,
                    data.external_tetis_id,
                    data.mis_clinic_id,
                    data.mis_room_id,
                    data.storage_zone,
                    self._optional_decimal_to_db(data.capacity_limit),
                    data.storage_conditions,
                    data.responsible_person,
                ),
            )
            self._audit(
                connection,
                actor_id,
                AuditAction.CREATE,
                "warehouse",
                warehouse_id,
                data,
                warehouse_id=warehouse_id,
            )
            return self._get_by_id(connection, "warehouses", warehouse_id)

    def list_warehouses(
        self, limit: int = 100, offset: int = 0, q: str | None = None
    ) -> list[dict[str, Any]]:
        if not q or not q.strip():
            return self._list_table("warehouses", "name, id", limit, offset)
        safe_limit = max(1, min(limit, 500))
        safe_offset = max(0, offset)
        search = q.strip().casefold()
        connection = self.database.connect()
        try:
            rows = connection.execute(
                """
                SELECT * FROM warehouses
                ORDER BY name, id
                """
            ).fetchall()
            searchable_fields = (
                "name",
                "department",
                "tetis_org_id",
                "external_tetis_id",
                "storage_zone",
                "storage_conditions",
                "responsible_person",
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

    def list_warehouse_ids_for_tetis_org(self, tetis_org_id: str) -> list[int]:
        org_id = tetis_org_id.strip()
        if not org_id:
            return []
        connection = self.database.connect()
        try:
            rows = connection.execute(
                """
                SELECT id
                FROM warehouses
                WHERE tetis_org_id = ?
                ORDER BY id
                """,
                (org_id,),
            ).fetchall()
            return [int(row["id"]) for row in rows]
        finally:
            self._close_connection(connection)

    def get_tetis_org_id_for_warehouses(self, warehouse_ids: list[int]) -> str | None:
        """Reverse lookup: given a list of warehouse IDs, return the shared tetis_org_id."""
        if not warehouse_ids:
            return None
        connection = self.database.connect()
        try:
            placeholders = ','.join('?' * len(warehouse_ids))
            row = connection.execute(
                f"SELECT tetis_org_id FROM warehouses WHERE id IN ({placeholders}) AND tetis_org_id IS NOT NULL LIMIT 1",
                warehouse_ids,
            ).fetchone()
            return row["tetis_org_id"] if row else None
        finally:
            self._close_connection(connection)

    def create_sensor_device(
        self, data: SensorDeviceCreate, actor_id: str = "system"
    ) -> dict[str, Any]:
        self._validate_sensor_thresholds(data)
        with self.database.transaction() as connection:
            self._require(connection, "warehouses", data.warehouse_id)
            now = now_iso()
            device_id = insert_and_get_id(
                connection,
                """
                INSERT INTO sensor_devices(
                  warehouse_id, name, serial_number, sensor_type,
                  min_temperature_c, max_temperature_c,
                  min_humidity_percent, max_humidity_percent,
                  created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data.warehouse_id,
                    data.name,
                    data.serial_number,
                    data.sensor_type,
                    self._optional_decimal_to_db(data.min_temperature_c),
                    self._optional_decimal_to_db(data.max_temperature_c),
                    self._optional_decimal_to_db(data.min_humidity_percent),
                    self._optional_decimal_to_db(data.max_humidity_percent),
                    now,
                    now,
                ),
            )
            device = self._get_by_id(connection, "sensor_devices", device_id)
            self._audit(
                connection,
                actor_id,
                AuditAction.CREATE,
                "sensor_device",
                device_id,
                device,
                warehouse_id=data.warehouse_id,
            )
            return device

    def list_sensor_devices(
        self, warehouse_id: int | None = None, limit: int = 100, offset: int = 0
    ) -> list[dict[str, Any]]:
        if warehouse_id is None:
            return self._list_table("sensor_devices", "warehouse_id, name, id", limit, offset)
        return self._list_table(
            "sensor_devices",
            "name, id",
            limit,
            offset,
            where="warehouse_id = ?",
            params=(warehouse_id,),
        )

    def update_sensor_device(
        self,
        device_id: int,
        data: SensorDeviceUpdate,
        actor_id: str = "system",
    ) -> dict[str, Any]:
        self._validate_sensor_thresholds(data)
        with self.database.transaction() as connection:
            before = self._get_by_id(connection, "sensor_devices", device_id)
            self._require(connection, "warehouses", data.warehouse_id)
            connection.execute(
                """
                UPDATE sensor_devices
                SET warehouse_id = ?,
                    name = ?,
                    serial_number = ?,
                    sensor_type = ?,
                    min_temperature_c = ?,
                    max_temperature_c = ?,
                    min_humidity_percent = ?,
                    max_humidity_percent = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    data.warehouse_id,
                    data.name,
                    data.serial_number,
                    data.sensor_type,
                    self._optional_decimal_to_db(data.min_temperature_c),
                    self._optional_decimal_to_db(data.max_temperature_c),
                    self._optional_decimal_to_db(data.min_humidity_percent),
                    self._optional_decimal_to_db(data.max_humidity_percent),
                    now_iso(),
                    device_id,
                ),
            )
            updated = self._get_by_id(connection, "sensor_devices", device_id)
            self._audit(
                connection,
                actor_id,
                AuditAction.UPDATE,
                "sensor_device",
                device_id,
                {"before": before, "after": updated},
                warehouse_id=updated["warehouse_id"],
            )
            return updated

    def get_sensor_device(self, device_id: int) -> dict[str, Any]:
        connection = self.database.connect()
        try:
            return self._get_by_id(connection, "sensor_devices", device_id)
        finally:
            self._close_connection(connection)

    def record_sensor_reading(
        self, data: SensorReadingCreate, actor_id: str = "sensor"
    ) -> dict[str, Any]:
        self._validate_sensor_reading(data)
        with self.database.transaction() as connection:
            device = self._get_by_id(connection, "sensor_devices", data.device_id)
            recorded_at = data.recorded_at.isoformat() if data.recorded_at else now_iso()
            received_at = now_iso()
            status = self._sensor_reading_status(device, data)
            reading_id = insert_and_get_id(
                connection,
                """
                INSERT INTO sensor_readings(
                  device_id, warehouse_id, temperature_c, humidity_percent,
                  recorded_at, received_at, status, raw_payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data.device_id,
                    device["warehouse_id"],
                    self._optional_decimal_to_db(data.temperature_c),
                    self._optional_decimal_to_db(data.humidity_percent),
                    recorded_at,
                    received_at,
                    status,
                    data.raw_payload,
                ),
            )
            reading = self._get_sensor_reading(connection, reading_id)
            if status == "warning":
                self._ensure_sensor_warning_notification(
                    connection,
                    device=device,
                    reading=reading,
                )
            self._audit(
                connection,
                actor_id,
                AuditAction.CREATE,
                "sensor_reading",
                reading_id,
                {
                    "device_id": data.device_id,
                    "warehouse_id": device["warehouse_id"],
                    "temperature_c": data.temperature_c,
                    "humidity_percent": data.humidity_percent,
                    "status": status,
                },
                warehouse_id=device["warehouse_id"],
            )
            return reading

    def list_sensor_readings(
        self,
        warehouse_id: int | None = None,
        device_id: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 500))
        safe_offset = max(0, offset)
        query = """
            SELECT
              sr.*,
              sd.name AS device_name,
              w.name AS warehouse_name
            FROM sensor_readings sr
            JOIN sensor_devices sd ON sd.id = sr.device_id
            JOIN warehouses w ON w.id = sr.warehouse_id
        """
        params: tuple[Any, ...] = ()
        filters: list[str] = []
        if warehouse_id is not None:
            filters.append("sr.warehouse_id = ?")
            params = (*params, warehouse_id)
        if device_id is not None:
            filters.append("sr.device_id = ?")
            params = (*params, device_id)
        if filters:
            query += " WHERE " + " AND ".join(filters)
        query += " ORDER BY sr.recorded_at DESC, sr.id DESC LIMIT ? OFFSET ?"
        connection = self.database.connect()
        try:
            rows = connection.execute(query, (*params, safe_limit, safe_offset)).fetchall()
            return [dict(row) for row in rows]
        finally:
            self._close_connection(connection)

    def count_sensor_readings(
        self, warehouse_id: int | None = None, device_id: int | None = None
    ) -> int:
        query = "SELECT COUNT(*) AS total FROM sensor_readings"
        params: tuple[Any, ...] = ()
        filters: list[str] = []
        if warehouse_id is not None:
            filters.append("warehouse_id = ?")
            params = (*params, warehouse_id)
        if device_id is not None:
            filters.append("device_id = ?")
            params = (*params, device_id)
        if filters:
            query += " WHERE " + " AND ".join(filters)
        connection = self.database.connect()
        try:
            row = connection.execute(query, params).fetchone()
            return int(row["total"])
        finally:
            self._close_connection(connection)

    def update_warehouse(
        self, warehouse_id: int, data: WarehouseUpdate, actor_id: str = "system"
    ) -> dict[str, Any]:
        with self.database.transaction() as connection:
            before = self._get_by_id(connection, "warehouses", warehouse_id)
            connection.execute(
                """
                UPDATE warehouses
                SET name = ?,
                    department = ?,
                    tetis_org_id = ?,
                    external_tetis_id = ?,
                    mis_clinic_id = ?,
                    mis_room_id = ?,
                    storage_zone = ?,
                    capacity_limit = ?,
                    storage_conditions = ?,
                    responsible_person = ?
                WHERE id = ?
                """,
                (
                    data.name,
                    data.department,
                    data.tetis_org_id,
                    data.external_tetis_id,
                    data.mis_clinic_id,
                    data.mis_room_id,
                    data.storage_zone,
                    self._optional_decimal_to_db(data.capacity_limit),
                    data.storage_conditions,
                    data.responsible_person,
                    warehouse_id,
                ),
            )
            updated = self._get_by_id(connection, "warehouses", warehouse_id)
            self._audit(
                connection,
                actor_id,
                AuditAction.UPDATE,
                "warehouse",
                warehouse_id,
                {"before": before, "after": updated},
                warehouse_id=warehouse_id,
            )
            return updated

    def set_inventory_lock(
        self, warehouse_id: int, locked: bool, actor_id: str = "system"
    ) -> dict[str, Any]:
        with self.database.transaction() as connection:
            self._require(connection, "warehouses", warehouse_id)
            connection.execute(
                "UPDATE warehouses SET inventory_lock = ? WHERE id = ?",
                (1 if locked else 0, warehouse_id),
            )
            self._audit(
                connection,
                actor_id,
                AuditAction.INVENTORY_LOCK,
                "warehouse",
                warehouse_id,
                {"inventory_lock": locked},
                warehouse_id=warehouse_id,
            )
            return self._get_by_id(connection, "warehouses", warehouse_id)

    def create_product(self, data: ProductCreate, actor_id: str = "system") -> dict[str, Any]:
        with self.database.transaction() as connection:
            self._require_active(connection, "categories", data.category_id)
            existing_sku = connection.execute(
                "SELECT id FROM products WHERE sku = ?", [data.sku]
            ).fetchone()
            if existing_sku:
                raise ConflictError(f"Товар с кодом «{data.sku}» уже существует")
            unit = self._normalize_product_unit(data.unit)
            product_id = insert_and_get_id(
                connection,
                """
                INSERT INTO products(
                  name, sku, unit, category_id, reorder_point, safety_stock, is_controlled,
                  barcode, description, certificate_ref, is_active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data.name,
                    data.sku,
                    unit,
                    data.category_id,
                    decimal_to_db(data.reorder_point),
                    decimal_to_db(data.safety_stock),
                    1 if data.is_controlled else 0,
                    data.barcode,
                    data.description,
                    data.certificate_ref,
                    1,
                ),
            )
            self._audit(connection, actor_id, AuditAction.CREATE, "product", product_id, data)
            return self._get_by_id(connection, "products", product_id)

    def list_products(
        self, limit: int = 100, offset: int = 0, q: str | None = None
    ) -> list[dict[str, Any]]:
        if not q or not q.strip():
            return self._list_table("products", "name, id", limit, offset, where="is_active = 1")
        safe_limit = max(1, min(limit, 500))
        safe_offset = max(0, offset)
        search = q.strip().casefold()
        connection = self.database.connect()
        try:
            rows = connection.execute(
                """
                SELECT * FROM products
                WHERE is_active = 1
                ORDER BY name, id
                """
            ).fetchall()
            searchable_fields = ("name", "sku", "barcode", "certificate_ref")
            filtered = []
            for row in rows:
                item = dict(row)
                haystack = " ".join(str(item.get(field) or "") for field in searchable_fields).casefold()
                if search in haystack:
                    filtered.append(item)
            return filtered[safe_offset : safe_offset + safe_limit]
        finally:
            self._close_connection(connection)

    def get_product_by_barcode(self, barcode: str) -> dict[str, Any] | None:
        connection = self.database.connect()
        try:
            row = connection.execute(
                "SELECT * FROM products WHERE is_active = 1 AND barcode = ?",
                [barcode.strip()],
            ).fetchone()
            return dict(row) if row else None
        finally:
            self._close_connection(connection)

    def get_product_barcode_label(self, product_id: int, symbology: str = "code128") -> dict[str, Any]:
        connection = self.database.connect()
        try:
            return self._build_product_barcode_label(connection, product_id, symbology=symbology)
        finally:
            self._close_connection(connection)

    def get_product_barcode_labels(self, product_ids: list[int], symbology: str = "code128") -> dict[str, Any]:
        unique_ids = list(dict.fromkeys(product_ids))
        if not unique_ids:
            raise ValidationError("At least one product is required")
        connection = self.database.connect()
        try:
            labels = [
                self._build_product_barcode_label(connection, product_id, symbology=symbology)
                for product_id in unique_ids
            ]
            return {
                "labels": labels,
                "zpl": "\n".join(label["zpl"] for label in labels),
                "epl": "\n".join(label["epl"] for label in labels),
            }
        finally:
            self._close_connection(connection)

    def get_batch_receipt_print_form(self, batch_id: int) -> dict[str, Any]:
        connection = self.database.connect()
        try:
            row = connection.execute(
                """
                SELECT
                  b.id AS batch_id,
                  b.lot,
                  b.serial_number,
                  b.expires_on,
                  b.unit_price,
                  b.received_at,
                  p.name AS product_name,
                  p.sku,
                  p.unit,
                  p.barcode,
                  s.name AS supplier_name,
                  w.name AS warehouse_name,
                  sb.quantity
                FROM batches b
                JOIN products p ON p.id = b.product_id
                JOIN suppliers s ON s.id = b.supplier_id
                LEFT JOIN stock_balances sb ON sb.batch_id = b.id
                LEFT JOIN warehouses w ON w.id = sb.warehouse_id
                WHERE b.id = ?
                ORDER BY sb.quantity DESC NULLS LAST
                LIMIT 1
                """,
                (batch_id,),
            ).fetchone()
            if row is None:
                raise NotFoundError(f"batches#{batch_id} not found")
            item = dict(row)
            return {
                "document_type": "receipt",
                "batch_id": batch_id,
                "product_name": item["product_name"],
                "sku": item.get("sku"),
                "lot": item["lot"],
                "serial_number": item.get("serial_number"),
                "expires_on": item.get("expires_on"),
                "unit_price": str(item["unit_price"]),
                "quantity": str(item["quantity"]) if item.get("quantity") is not None else "0",
                "unit": item.get("unit"),
                "warehouse_name": item["warehouse_name"] if item.get("warehouse_name") else "—",
                "supplier_name": item["supplier_name"],
                "received_at": str(item["received_at"]),
                "barcode": item.get("barcode"),
            }
        finally:
            self._close_connection(connection)

    def get_batch_price_label(self, batch_id: int, symbology: str = "code128") -> dict[str, Any]:
        connection = self.database.connect()
        try:
            return self._build_batch_price_label(connection, batch_id, symbology=symbology)
        finally:
            self._close_connection(connection)

    def get_batch_price_labels(self, batch_ids: list[int], symbology: str = "code128") -> dict[str, Any]:
        unique_ids = list(dict.fromkeys(batch_ids))
        if not unique_ids:
            raise ValidationError("At least one batch is required")
        connection = self.database.connect()
        try:
            labels = [
                self._build_batch_price_label(connection, batch_id, symbology=symbology)
                for batch_id in unique_ids
            ]
            return {
                "labels": labels,
                "zpl": "\n".join(label["zpl"] for label in labels),
                "epl": "\n".join(label["epl"] for label in labels),
            }
        finally:
            self._close_connection(connection)

    def update_product(
        self, product_id: int, data: ProductUpdate, actor_id: str = "system"
    ) -> dict[str, Any]:
        with self.database.transaction() as connection:
            before = self._get_by_id(connection, "products", product_id)
            self._require_active(connection, "categories", data.category_id)
            existing_sku = connection.execute(
                "SELECT id FROM products WHERE sku = ? AND id != ?", [data.sku, product_id]
            ).fetchone()
            if existing_sku:
                raise ConflictError(f"Товар с кодом «{data.sku}» уже существует")
            unit = self._normalize_product_unit(data.unit)
            connection.execute(
                """
                UPDATE products
                SET name = ?, sku = ?, unit = ?, category_id = ?,
                    reorder_point = ?, safety_stock = ?, is_controlled = ?,
                    barcode = ?, description = ?, certificate_ref = ?
                WHERE id = ?
                """,
                (
                    data.name,
                    data.sku,
                    unit,
                    data.category_id,
                    decimal_to_db(data.reorder_point),
                    decimal_to_db(data.safety_stock),
                    1 if data.is_controlled else 0,
                    data.barcode,
                    data.description,
                    data.certificate_ref,
                    product_id,
                ),
            )
            updated = self._get_by_id(connection, "products", product_id)
            self._audit(
                connection,
                actor_id,
                AuditAction.UPDATE,
                "product",
                product_id,
                {"before": before, "after": updated},
            )
            return updated


    def update_product_certificate_ref(
        self, product_id: int, certificate_ref: str | None, actor_id: str = "system"
    ) -> dict:
        """Update only the certificate_ref field of a product."""
        with self.database.transaction() as connection:
            before = self._get_by_id(connection, "products", product_id)
            connection.execute(
                "UPDATE products SET certificate_ref = ? WHERE id = ?",
                (certificate_ref, product_id),
            )
            updated = self._get_by_id(connection, "products", product_id)
            self._audit(
                connection,
                actor_id,
                AuditAction.UPDATE,
                "product",
                product_id,
                {"before": {"certificate_ref": before.get("certificate_ref")},
                 "after": {"certificate_ref": updated.get("certificate_ref")}},
            )
        return dict(updated)

    def update_product_image_ref(
        self, product_id: int, image_path: str | None, actor_id: str = "system"
    ) -> dict:
        """Update only the image_path field of a product."""
        with self.database.transaction() as connection:
            before = self._get_by_id(connection, "products", product_id)
            connection.execute(
                "UPDATE products SET image_path = ? WHERE id = ?",
                (image_path, product_id),
            )
            updated = self._get_by_id(connection, "products", product_id)
            self._audit(
                connection,
                actor_id,
                AuditAction.UPDATE,
                "product",
                product_id,
                {"before": {"image_path": before.get("image_path")},
                 "after": {"image_path": updated.get("image_path")}},
            )
        return dict(updated)

    def delete_product(self, product_id: int, actor_id: str = "system") -> dict[str, Any]:
        with self.database.transaction() as connection:
            before = self._get_by_id(connection, "products", product_id)
            connection.execute("UPDATE products SET is_active = ? WHERE id = ?", (0, product_id))
            updated = self._get_by_id(connection, "products", product_id)
            self._audit(
                connection,
                actor_id,
                AuditAction.DELETE,
                "product",
                product_id,
                {"before": before, "after": updated},
            )
            return updated
