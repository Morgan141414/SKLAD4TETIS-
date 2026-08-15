from __future__ import annotations

import json
from datetime import (
    UTC,
    date,
    datetime,
    timedelta,
)
from decimal import Decimal
from sqlite3 import Connection
from typing import Any

from app.domain.enums import StockDocumentType
from app.domain.errors import ValidationError
from app.services.warehouse.base import WarehouseServiceBase
from app.storage.sqlite import (
    decimal_to_db,
    insert_and_get_id,
    now_iso,
)


class ReportsMixin(WarehouseServiceBase):
    def list_batches(
        self,
        warehouse_id: int | None = None,
        limit: int = 100,
        offset: int = 0,
        product_id: int | None = None,
        supplier_id: int | None = None,
        status: str | None = None,
        expires_before: date | None = None,
        expires_after: date | None = None,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 500))
        safe_offset = max(0, offset)
        query = "SELECT DISTINCT b.* FROM batches b"
        filters: list[str] = []
        params: tuple[Any, ...] = ()
        if warehouse_id is not None:
            query += " JOIN stock_balances sb ON sb.batch_id = b.id"
            filters.append("sb.warehouse_id = ?")
            params = (*params, warehouse_id)
        if product_id is not None:
            filters.append("b.product_id = ?")
            params = (*params, product_id)
        if supplier_id is not None:
            filters.append("b.supplier_id = ?")
            params = (*params, supplier_id)
        if status is not None:
            filters.append("b.status = ?")
            params = (*params, status)
        if expires_before is not None:
            filters.append("b.expires_on IS NOT NULL AND b.expires_on <= ?")
            params = (*params, expires_before.isoformat())
        if expires_after is not None:
            filters.append("b.expires_on IS NOT NULL AND b.expires_on >= ?")
            params = (*params, expires_after.isoformat())
        if filters:
            query += " WHERE " + " AND ".join(filters)
        query += " ORDER BY b.received_at DESC, b.id DESC LIMIT ? OFFSET ?"
        connection = self.database.connect()
        try:
            rows = connection.execute(query, (*params, safe_limit, safe_offset)).fetchall()
            return [dict(row) for row in rows]
        finally:
            self._close_connection(connection)

    def list_stock_documents(
        self,
        warehouse_id: int | None = None,
        limit: int = 100,
        offset: int = 0,
        document_type: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 500))
        safe_offset = max(0, offset)
        connection = self.database.connect()
        try:
            query = "SELECT * FROM stock_documents"
            filters: list[str] = []
            params: tuple[Any, ...] = ()
            if warehouse_id is not None:
                filters.append("warehouse_id = ?")
                params = (*params, warehouse_id)
            if document_type is not None:
                filters.append("document_type = ?")
                params = (*params, document_type)
            if status is not None:
                filters.append("status = ?")
                params = (*params, status)
            if filters:
                query += " WHERE " + " AND ".join(filters)
            query += " ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?"
            rows = connection.execute(query, (*params, safe_limit, safe_offset)).fetchall()
            return [dict(row) for row in rows]
        finally:
            self._close_connection(connection)

    def count_stock_documents(
        self,
        warehouse_id: int | None = None,
        document_type: str | None = None,
        status: str | None = None,
    ) -> int:
        connection = self.database.connect()
        try:
            query = "SELECT COUNT(*) AS total FROM stock_documents"
            filters: list[str] = []
            params: tuple[Any, ...] = ()
            if warehouse_id is not None:
                filters.append("warehouse_id = ?")
                params = (*params, warehouse_id)
            if document_type is not None:
                filters.append("document_type = ?")
                params = (*params, document_type)
            if status is not None:
                filters.append("status = ?")
                params = (*params, status)
            if filters:
                query += " WHERE " + " AND ".join(filters)
            row = connection.execute(query, params).fetchone()
            return int(row["total"])
        finally:
            self._close_connection(connection)

    def list_reservations(
        self, warehouse_id: int | None = None, limit: int = 100, offset: int = 0
    ) -> list[dict[str, Any]]:
        return self._list_table(
            "reservations",
            "created_at DESC, id DESC",
            limit,
            offset,
            where="warehouse_id = ?",
            params=(warehouse_id,),
        ) if warehouse_id is not None else self._list_table(
            "reservations", "created_at DESC, id DESC", limit, offset
        )

    def get_batch(self, batch_id: int) -> dict[str, Any]:
        connection = self.database.connect()
        try:
            return self._get_batch(connection, batch_id)
        finally:
            self._close_connection(connection)

    def get_batch_detail(
        self, batch_id: int, movement_limit: int = 100, movement_offset: int = 0
    ) -> dict[str, Any]:
        connection = self.database.connect()
        try:
            batch = self._get_batch(connection, batch_id)
            balances = self._batch_balances(connection, batch_id)
            movements = self._batch_movements(
                connection, batch_id, movement_limit, movement_offset
            )
            return {"batch": batch, "balances": balances, "movements": movements}
        finally:
            self._close_connection(connection)

    def get_batch_traceability(
        self, batch_id: int, movement_limit: int = 100, movement_offset: int = 0
    ) -> dict[str, Any]:
        connection = self.database.connect()
        try:
            batch = self._get_batch(connection, batch_id)
            balances = self._batch_balances(connection, batch_id)
            movements = self._batch_movements(
                connection, batch_id, movement_limit, movement_offset
            )
            document_rows = connection.execute(
                """
                SELECT DISTINCT sd.id
                FROM stock_documents sd
                JOIN stock_document_lines sdl ON sdl.document_id = sd.id
                WHERE sdl.batch_id = ?
                ORDER BY sd.created_at DESC, sd.id DESC
                """,
                (batch_id,),
            ).fetchall()
            documents = [self._get_document(connection, int(row["id"])) for row in document_rows]
            return {
                "batch": batch,
                "balances": balances,
                "movements": movements,
                "documents": documents,
                "transformations": self._batch_transformations(connection, batch_id=batch_id),
                "recalls": self._batch_recalls(connection, batch_id=batch_id),
            }
        finally:
            self._close_connection(connection)

    def list_batch_transformations(
        self,
        warehouse_id: int | None = None,
        batch_id: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 500))
        safe_offset = max(0, offset)
        connection = self.database.connect()
        try:
            return self._batch_transformations(
                connection,
                warehouse_id=warehouse_id,
                batch_id=batch_id,
                limit=safe_limit,
                offset=safe_offset,
            )
        finally:
            self._close_connection(connection)

    def count_batch_transformations(
        self,
        warehouse_id: int | None = None,
        batch_id: int | None = None,
    ) -> int:
        connection = self.database.connect()
        try:
            query = "SELECT COUNT(*) AS total FROM batch_transformations"
            filters: list[str] = []
            params: tuple[Any, ...] = ()
            if warehouse_id is not None:
                filters.append("warehouse_id = ?")
                params = (*params, warehouse_id)
            if batch_id is not None:
                filters.append("(source_batch_id = ? OR target_batch_id = ?)")
                params = (*params, batch_id, batch_id)
            if filters:
                query += " WHERE " + " AND ".join(filters)
            row = connection.execute(query, params).fetchone()
            return int(row["total"])
        finally:
            self._close_connection(connection)

    def get_batch_warehouse_ids(self, batch_id: int) -> list[int]:
        connection = self.database.connect()
        try:
            self._require(connection, "batches", batch_id)
            return self._batch_warehouse_ids(connection, batch_id)
        finally:
            self._close_connection(connection)

    def get_stock_document(self, document_id: int) -> dict[str, Any]:
        connection = self.database.connect()
        try:
            return self._get_document(connection, document_id)
        finally:
            self._close_connection(connection)

    def get_repack_print_form(self, document_id: int) -> dict[str, Any]:
        connection = self.database.connect()
        try:
            document = self._get_document(connection, document_id)
            if document["document_type"] != StockDocumentType.REPACK:
                raise ValidationError("Print form is available only for repack documents")
            warehouse = dict(self._require(connection, "warehouses", document["warehouse_id"]))
            transformation_rows = {
                int(row["source_batch_id"]): dict(row)
                for row in connection.execute(
                    """
                    SELECT * FROM batch_transformations
                    WHERE document_id = ?
                    ORDER BY id
                    """,
                    (document_id,),
                ).fetchall()
            }
            rows = connection.execute(
                """
                SELECT
                  sdl.id,
                  sdl.batch_id AS source_batch_id,
                  sdl.target_product_id,
                  sdl.quantity AS source_quantity,
                  sdl.target_quantity,
                  sdl.conversion_factor,
                  sdl.loss_quantity,
                  sdl.target_unit_price,
                  sdl.target_lot,
                  sdl.reason,
                  sb.lot AS source_lot,
                  sp.name AS source_product_name,
                  tp.name AS target_product_name
                FROM stock_document_lines sdl
                JOIN batches sb ON sb.id = sdl.batch_id
                JOIN products sp ON sp.id = sb.product_id
                JOIN products tp ON tp.id = sdl.target_product_id
                WHERE sdl.document_id = ?
                ORDER BY sdl.id
                """,
                (document_id,),
            ).fetchall()
            lines = []
            for index, row in enumerate(rows, start=1):
                item = dict(row)
                transformation = transformation_rows.get(int(item["source_batch_id"]))
                target_batch_id = transformation["target_batch_id"] if transformation else None
                lines.append(
                    {
                        "line_no": index,
                        "source_batch_id": item["source_batch_id"],
                        "source_product_name": item["source_product_name"],
                        "source_lot": item["source_lot"],
                        "target_batch_id": target_batch_id,
                        "target_product_name": item["target_product_name"],
                        "target_lot": item["target_lot"],
                        "source_quantity": item["source_quantity"],
                        "target_quantity": item["target_quantity"],
                        "conversion_factor": item["conversion_factor"],
                        "loss_quantity": item["loss_quantity"],
                        "target_unit_price": item["target_unit_price"],
                        "reason": item["reason"],
                    }
                )
            return {
                "document_id": document_id,
                "status": document["status"],
                "warehouse_id": document["warehouse_id"],
                "warehouse_name": warehouse["name"],
                "created_by": document["created_by"],
                "created_at": document["created_at"],
                "posted_at": document["posted_at"],
                "csv": self._repack_print_csv(lines),
                "lines": lines,
            }
        finally:
            self._close_connection(connection)

    def get_transfer_print_form(self, document_id: int) -> dict[str, Any]:
        connection = self.database.connect()
        try:
            document = self._get_document(connection, document_id)
            if document["document_type"] != StockDocumentType.TRANSFER:
                raise ValidationError("Print form is available only for transfer documents")
            source_warehouse = dict(self._require(connection, "warehouses", document["warehouse_id"]))
            rows = connection.execute(
                """
                SELECT
                  sdl.id,
                  sdl.batch_id,
                  sdl.target_warehouse_id,
                  sdl.quantity,
                  sdl.reason,
                  b.lot,
                  p.name AS product_name,
                  source.name AS source_warehouse_name,
                  target.name AS target_warehouse_name
                FROM stock_document_lines sdl
                JOIN batches b ON b.id = sdl.batch_id
                JOIN products p ON p.id = b.product_id
                JOIN warehouses source ON source.id = ?
                JOIN warehouses target ON target.id = sdl.target_warehouse_id
                WHERE sdl.document_id = ?
                ORDER BY sdl.id
                """,
                (document["warehouse_id"], document_id),
            ).fetchall()
            lines = []
            for index, row in enumerate(rows, start=1):
                item = dict(row)
                lines.append(
                    {
                        "line_no": index,
                        "batch_id": item["batch_id"],
                        "product_name": item["product_name"],
                        "lot": item["lot"],
                        "source_warehouse_id": document["warehouse_id"],
                        "source_warehouse_name": item["source_warehouse_name"],
                        "target_warehouse_id": item["target_warehouse_id"],
                        "target_warehouse_name": item["target_warehouse_name"],
                        "quantity": item["quantity"],
                        "reason": item["reason"],
                    }
                )
            return {
                "document_id": document_id,
                "status": document["status"],
                "source_warehouse_id": document["warehouse_id"],
                "source_warehouse_name": source_warehouse["name"],
                "created_by": document["created_by"],
                "created_at": document["created_at"],
                "approved_by": document["approved_by"],
                "approved_at": document["approved_at"],
                "posted_at": document["posted_at"],
                "csv": self._transfer_print_csv(lines),
                "lines": lines,
            }
        finally:
            self._close_connection(connection)

    def get_reservation(self, reservation_id: int) -> dict[str, Any]:
        connection = self.database.connect()
        try:
            return self._get_by_id(connection, "reservations", reservation_id)
        finally:
            self._close_connection(connection)

    def list_controlled_substance_ledger(
        self,
        warehouse_id: int | None = None,
        product_id: int | None = None,
        batch_id: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 500))
        safe_offset = max(0, offset)
        query = """
            SELECT
              sm.id AS movement_id,
              sm.movement_type,
              p.id AS product_id,
              p.name AS product_name,
              p.sku,
              b.id AS batch_id,
              b.lot,
              sm.warehouse_id,
              sm.quantity,
              sm.reason,
              sm.patient_id,
              sm.doctor_id,
              sm.medical_record_no,
              sm.second_approver_id,
              sm.second_approval_note,
              sm.created_at
            FROM stock_movements sm
            JOIN batches b ON b.id = sm.batch_id
            JOIN products p ON p.id = b.product_id
            WHERE p.is_controlled = ?
        """
        params: tuple[Any, ...] = (True,)
        if warehouse_id is not None:
            query += " AND sm.warehouse_id = ?"
            params = (*params, warehouse_id)
        if product_id is not None:
            query += " AND p.id = ?"
            params = (*params, product_id)
        if batch_id is not None:
            query += " AND b.id = ?"
            params = (*params, batch_id)
        query += " ORDER BY sm.created_at DESC, sm.id DESC LIMIT ? OFFSET ?"
        params = (*params, safe_limit, safe_offset)
        connection = self.database.connect()
        try:
            rows = connection.execute(query, params).fetchall()
            return [dict(row) for row in rows]
        finally:
            self._close_connection(connection)

    def count_controlled_substance_ledger(
        self,
        warehouse_id: int | None = None,
        product_id: int | None = None,
        batch_id: int | None = None,
    ) -> int:
        query = """
            SELECT COUNT(*) AS total
            FROM stock_movements sm
            JOIN batches b ON b.id = sm.batch_id
            JOIN products p ON p.id = b.product_id
            WHERE p.is_controlled = ?
        """
        params: tuple[Any, ...] = (True,)
        if warehouse_id is not None:
            query += " AND sm.warehouse_id = ?"
            params = (*params, warehouse_id)
        if product_id is not None:
            query += " AND p.id = ?"
            params = (*params, product_id)
        if batch_id is not None:
            query += " AND b.id = ?"
            params = (*params, batch_id)
        connection = self.database.connect()
        try:
            row = connection.execute(query, params).fetchone()
            return int(row["total"])
        finally:
            self._close_connection(connection)

    def export_controlled_substance_ledger(
        self,
        warehouse_id: int | None = None,
        product_id: int | None = None,
        batch_id: int | None = None,
    ) -> dict[str, Any]:
        rows = self.list_controlled_substance_ledger(
            warehouse_id=warehouse_id,
            product_id=product_id,
            batch_id=batch_id,
            limit=500,
            offset=0,
        )
        columns = [
            "Дата",
            "Движение",
            "Товар",
            "SKU",
            "Партия",
            "Склад",
            "Количество",
            "Причина",
            "Пациент",
            "Врач",
            "История болезни",
            "Второе подтверждение",
        ]
        csv_rows: list[list[Any]] = [columns]
        for row in rows:
            csv_rows.append(
                [
                    row["created_at"],
                    row["movement_type"],
                    row["product_name"],
                    row["sku"],
                    row["lot"],
                    row["warehouse_id"],
                    self._report_decimal(Decimal(str(row["quantity"]))),
                    row["reason"] or "",
                    row["patient_id"] or "",
                    row["doctor_id"] or "",
                    row["medical_record_no"] or "",
                    row["second_approver_id"] or "",
                ]
            )
        return {
            "filename": "sklad-controlled-substances-ledger.csv",
            "csv": "\n".join(";".join(self._csv_cell(cell) for cell in csv_row) for csv_row in csv_rows),
        }

    def generate_low_stock_notifications(
        self, warehouse_id: int | None = None
    ) -> list[dict[str, Any]]:
        with self.database.transaction() as connection:
            if warehouse_id is not None:
                self._require(connection, "warehouses", warehouse_id)
            params: tuple[Any, ...] = ()
            warehouse_filter = ""
            if warehouse_id is not None:
                warehouse_filter = " WHERE w.id = ?"
                params = (warehouse_id,)
            rows = connection.execute(
                f"""
                SELECT
                  p.id AS product_id,
                  p.name AS product_name,
                  p.reorder_point,
                  w.id AS warehouse_id,
                  COALESCE(SUM(
                    CAST(sb.quantity AS REAL) - CAST(sb.reserved_quantity AS REAL)
                  ), 0) AS free_quantity
                FROM products p
                CROSS JOIN warehouses w
                LEFT JOIN batches b ON b.product_id = p.id
                LEFT JOIN stock_balances sb ON sb.batch_id = b.id AND sb.warehouse_id = w.id
                {warehouse_filter}
                GROUP BY p.id, p.name, p.reorder_point, w.id
                HAVING CAST(p.reorder_point AS REAL) > 0
                   AND COALESCE(SUM(
                    CAST(sb.quantity AS REAL) - CAST(sb.reserved_quantity AS REAL)
                  ), 0) < CAST(p.reorder_point AS REAL)
                ORDER BY p.name, w.id
                """,
                params,
            ).fetchall()
            notifications: list[dict[str, Any]] = []
            for row in rows:
                existing = connection.execute(
                    """
                    SELECT id FROM notifications
                    WHERE notification_type = 'low_stock'
                      AND product_id = ?
                      AND warehouse_id = ?
                      AND is_read = 0
                    """,
                    (row["product_id"], row["warehouse_id"]),
                ).fetchone()
                if existing:
                    notifications.append(self._get_by_id(connection, "notifications", existing["id"]))
                    continue
                title = f"Низкий остаток: {row['product_name']}"
                message = (
                    f"Свободный остаток {Decimal(str(row['free_quantity']))} "
                    f"ниже точки заказа {Decimal(row['reorder_point'])}."
                )
                if self._is_postgresql(connection):
                    notification_id = self._insert_low_stock_notification_if_absent_postgresql(
                        connection,
                        product_id=row["product_id"],
                        warehouse_id=row["warehouse_id"],
                        title=title,
                        message=message,
                    )
                    if notification_id is None:
                        existing = connection.execute(
                            """
                            SELECT id FROM notifications
                            WHERE notification_type = 'low_stock'
                              AND product_id = ?
                              AND warehouse_id = ?
                              AND is_read = 0
                            """,
                            (row["product_id"], row["warehouse_id"]),
                        ).fetchone()
                        if existing is None:
                            raise RuntimeError("Low-stock notification conflict was not recoverable")
                        notifications.append(self._get_by_id(connection, "notifications", existing["id"]))
                        continue
                else:
                    notification_id = insert_and_get_id(
                        connection,
                        """
                        INSERT INTO notifications(
                          notification_type, product_id, warehouse_id, title, message, created_at
                        ) VALUES ('low_stock', ?, ?, ?, ?, ?)
                        """,
                        (row["product_id"], row["warehouse_id"], title, message, now_iso()),
                    )
                notifications.append(self._get_by_id(connection, "notifications", notification_id))
            return notifications

    def _insert_low_stock_notification_if_absent_postgresql(
        self,
        connection: Connection,
        *,
        product_id: int,
        warehouse_id: int,
        title: str,
        message: str,
    ) -> int | None:
        row = connection.execute(
            """
            INSERT INTO notifications(
              notification_type, product_id, warehouse_id, title, message, created_at
            ) VALUES ('low_stock', ?, ?, ?, ?, ?)
            ON CONFLICT (warehouse_id, product_id)
              WHERE notification_type = 'low_stock' AND is_read = FALSE
            DO NOTHING
            RETURNING id
            """,
            (product_id, warehouse_id, title, message, now_iso()),
        ).fetchone()
        return None if row is None else int(row["id"])

    def _insert_expiry_notification_if_absent_postgresql(
        self,
        connection: Connection,
        *,
        product_id: int,
        batch_id: int,
        warehouse_id: int,
        title: str,
        message: str,
    ) -> int | None:
        row = connection.execute(
            """
            INSERT INTO notifications(
              notification_type, product_id, batch_id, warehouse_id, title, message, created_at
            ) VALUES ('expiry', ?, ?, ?, ?, ?, ?)
            ON CONFLICT (warehouse_id, batch_id)
              WHERE notification_type = 'expiry' AND is_read = FALSE
            DO NOTHING
            RETURNING id
            """,
            (product_id, batch_id, warehouse_id, title, message, now_iso()),
        ).fetchone()
        return None if row is None else int(row["id"])

    def generate_expiry_notifications(
        self, days: int = 30, warehouse_id: int | None = None
    ) -> list[dict[str, Any]]:
        if days < 0:
            raise ValidationError("Expiry reminder window cannot be negative")
        today = datetime.now(UTC).date()
        cutoff = today + timedelta(days=days)
        with self.database.transaction() as connection:
            if warehouse_id is not None:
                self._require(connection, "warehouses", warehouse_id)
            self._ensure_quarantine_reviews_for_open_batches(connection, warehouse_id=warehouse_id)
            params: tuple[Any, ...] = (cutoff.isoformat(),)
            warehouse_filter = ""
            if warehouse_id is not None:
                warehouse_filter = " AND sb.warehouse_id = ?"
                params = (*params, warehouse_id)
            rows = connection.execute(
                f"""
                SELECT
                  b.id AS batch_id,
                  b.product_id,
                  b.lot,
                  b.expires_on,
                  p.name AS product_name,
                  sb.warehouse_id,
                  sb.quantity,
                  sb.reserved_quantity
                FROM stock_balances sb
                JOIN batches b ON b.id = sb.batch_id
                JOIN products p ON p.id = b.product_id
                WHERE b.expires_on IS NOT NULL
                  AND b.expires_on <= ?
                  AND CAST(sb.quantity AS REAL) - CAST(sb.reserved_quantity AS REAL) > 0
                  {warehouse_filter}
                ORDER BY b.expires_on, b.id, sb.warehouse_id
                """,
                params,
            ).fetchall()
            notifications: list[dict[str, Any]] = []
            for row in rows:
                existing = connection.execute(
                    """
                    SELECT id FROM notifications
                    WHERE notification_type = 'expiry'
                      AND batch_id = ?
                      AND warehouse_id = ?
                      AND is_read = 0
                    """,
                    (row["batch_id"], row["warehouse_id"]),
                ).fetchone()
                if existing:
                    notifications.append(self._get_by_id(connection, "notifications", existing["id"]))
                    continue
                days_left = (self._date_from_db(row["expires_on"]) - today).days
                if days_left < 0:
                    title = f"Просрочен срок: {row['product_name']}"
                    message = (
                        f"Партия #{row['batch_id']} серия {row['lot']} годна до {row['expires_on']}. "
                        f"Просрочено дней: {abs(days_left)}."
                    )
                else:
                    title = f"Скоро истекает срок: {row['product_name']}"
                    message = (
                        f"Партия #{row['batch_id']} серия {row['lot']} годна до {row['expires_on']}. "
                        f"Осталось дней: {days_left}."
                    )
                if self._is_postgresql(connection):
                    notification_id = self._insert_expiry_notification_if_absent_postgresql(
                        connection,
                        product_id=row["product_id"],
                        batch_id=row["batch_id"],
                        warehouse_id=row["warehouse_id"],
                        title=title,
                        message=message,
                    )
                    if notification_id is None:
                        existing = connection.execute(
                            """
                            SELECT id FROM notifications
                            WHERE notification_type = 'expiry'
                              AND batch_id = ?
                              AND warehouse_id = ?
                              AND is_read = 0
                            """,
                            (row["batch_id"], row["warehouse_id"]),
                        ).fetchone()
                        if existing is None:
                            raise RuntimeError("Expiry notification conflict was not recoverable")
                        notifications.append(self._get_by_id(connection, "notifications", existing["id"]))
                        continue
                else:
                    notification_id = insert_and_get_id(
                        connection,
                        """
                        INSERT INTO notifications(
                          notification_type, product_id, batch_id, warehouse_id, title, message, created_at
                        ) VALUES ('expiry', ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            row["product_id"],
                            row["batch_id"],
                            row["warehouse_id"],
                            title,
                            message,
                            now_iso(),
                        ),
                    )
                notifications.append(self._get_by_id(connection, "notifications", notification_id))
            return notifications



    def list_controlled_limits(self, warehouse_id):
        connection = self.database.connect()
        try:
            rows = connection.execute(
                "SELECT cl.*, p.name AS product_name, p.sku FROM controlled_substance_limits cl JOIN products p ON p.id = cl.product_id WHERE cl.warehouse_id = ? ORDER BY p.name",
                (warehouse_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            self._close_connection(connection)

    def upsert_controlled_limit(self, warehouse_id, product_id, max_quantity, unit=None):
        with self.database.transaction() as connection:
            self._require(connection, "warehouses", warehouse_id)
            self._require(connection, "products", product_id)
            existing = connection.execute(
                "SELECT id FROM controlled_substance_limits WHERE warehouse_id = ? AND product_id = ?",
                (warehouse_id, product_id),
            ).fetchone()
            if existing:
                connection.execute(
                    "UPDATE controlled_substance_limits SET max_quantity = ?, unit = ?, updated_at = ? WHERE id = ?",
                    (decimal_to_db(Decimal(str(max_quantity))), unit, now_iso(), existing["id"]),
                )
                return self._get_by_id(connection, "controlled_substance_limits", existing["id"])
            else:
                new_id = insert_and_get_id(
                    connection,
                    "INSERT INTO controlled_substance_limits(warehouse_id, product_id, max_quantity, unit, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (warehouse_id, product_id, decimal_to_db(Decimal(str(max_quantity))), unit, now_iso(), now_iso()),
                )
                return self._get_by_id(connection, "controlled_substance_limits", new_id)

    def delete_controlled_limit(self, limit_id):
        with self.database.transaction() as connection:
            self._require(connection, "controlled_substance_limits", limit_id)
            connection.execute("DELETE FROM controlled_substance_limits WHERE id = ?", (limit_id,))

    def check_controlled_limit_violations(self, warehouse_id):
        connection = self.database.connect()
        try:
            rows = connection.execute(
                """
                SELECT cl.product_id, cl.max_quantity, cl.unit, p.name AS product_name,
                       COALESCE(SUM(CAST(sb.quantity AS REAL)), 0) AS current_quantity
                FROM controlled_substance_limits cl
                JOIN products p ON p.id = cl.product_id
                LEFT JOIN batches b ON b.product_id = cl.product_id
                LEFT JOIN stock_balances sb ON sb.batch_id = b.id AND sb.warehouse_id = cl.warehouse_id
                WHERE cl.warehouse_id = ?
                GROUP BY cl.product_id, cl.max_quantity, cl.unit, p.name
                HAVING COALESCE(SUM(CAST(sb.quantity AS REAL)), 0) > CAST(cl.max_quantity AS REAL)
                """,
                (warehouse_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            self._close_connection(connection)
    def generate_controlled_inventory_reminder(
        self, warehouse_id=None
    ):
        """Create monthly ПКУ inventory reminder notifications."""
        with self.database.transaction() as connection:
            params = ()
            wf = ""
            if warehouse_id is not None:
                self._require(connection, "warehouses", warehouse_id)
                wf = " AND sb.warehouse_id = ?"
                params = (warehouse_id,)
            rows = connection.execute(
                f"""
                SELECT DISTINCT p.id AS product_id, p.name AS product_name, sb.warehouse_id
                FROM products p
                JOIN batches b ON b.product_id = p.id
                JOIN stock_balances sb ON sb.batch_id = b.id
                WHERE p.is_controlled = 1
                  AND CAST(sb.quantity AS REAL) > 0
                  {wf}
                ORDER BY p.name, sb.warehouse_id
                """,
                params,
            ).fetchall()
            notif_type = "low_stock"
            notifications = []
            for row in rows:
                existing = connection.execute(
                    "SELECT id FROM notifications WHERE notification_type = ? AND product_id = ? AND warehouse_id = ? AND title LIKE ? AND is_read = 0",
                    (notif_type, row["product_id"], row["warehouse_id"], "% ПКУ %"),
                ).fetchone()
                if existing:
                    notifications.append(self._get_by_id(connection, "notifications", existing["id"]))
                    continue
                notif_id = insert_and_get_id(
                    connection,
                    "INSERT INTO notifications(notification_type, warehouse_id, product_id, title, message, is_read, created_at) VALUES (?, ?, ?, ?, ?, 0, ?)",
                    (notif_type, row["warehouse_id"], row["product_id"],
                     f"Плановая ПКУ инвентаризация: {row['product_name']}",
                     f"Требуется провести ежемесячную инвентаризацию ПКУ по товару {row['product_name']}.",
                     now_iso()),
                )
                notifications.append(self._get_by_id(connection, "notifications", notif_id))
            return notifications
    def generate_quarantine_notifications(
        self, days: int = 3, warehouse_id: int | None = None
    ) -> list[dict[str, Any]]:
        if days < 0:
            raise ValidationError("Quarantine reminder window cannot be negative")
        cutoff = datetime.now(UTC) - timedelta(days=days)
        with self.database.transaction() as connection:
            if warehouse_id is not None:
                self._require(connection, "warehouses", warehouse_id)
            params: tuple[Any, ...] = (cutoff.isoformat(),)
            warehouse_filter = ""
            if warehouse_id is not None:
                warehouse_filter = " AND sb.warehouse_id = ?"
                params = (*params, warehouse_id)
            rows = connection.execute(
                f"""
                SELECT
                  b.id AS batch_id,
                  b.product_id,
                  b.lot,
                  b.received_at,
                  p.name AS product_name,
                  sb.warehouse_id,
                  sb.quantity,
                  sb.reserved_quantity
                FROM stock_balances sb
                JOIN batches b ON b.id = sb.batch_id
                JOIN products p ON p.id = b.product_id
                WHERE b.status = 'quarantine'
                  AND b.received_at <= ?
                  AND CAST(sb.quantity AS REAL) - CAST(sb.reserved_quantity AS REAL) > 0
                  {warehouse_filter}
                ORDER BY b.received_at, b.id, sb.warehouse_id
                """,
                params,
            ).fetchall()
            notifications: list[dict[str, Any]] = []
            for row in rows:
                existing = connection.execute(
                    """
                    SELECT id FROM notifications
                    WHERE notification_type = 'quarantine'
                      AND batch_id = ?
                      AND warehouse_id = ?
                      AND is_read = 0
                    """,
                    (row["batch_id"], row["warehouse_id"]),
                ).fetchone()
                if existing:
                    notifications.append(self._get_by_id(connection, "notifications", existing["id"]))
                    continue
                received_at = self._datetime_from_db(row["received_at"])
                age_days = max(0, (datetime.now(UTC) - received_at).days)
                title = f"Партия в карантине: {row['product_name']}"
                message = (
                    f"Партия #{row['batch_id']} серия {row['lot']} находится в карантине "
                    f"{age_days} дн. Проверьте документы и статус партии."
                )
                notification_id = insert_and_get_id(
                    connection,
                    """
                    INSERT INTO notifications(
                      notification_type, product_id, batch_id, warehouse_id, title, message, created_at
                    ) VALUES ('quarantine', ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["product_id"],
                        row["batch_id"],
                        row["warehouse_id"],
                        title,
                        message,
                        now_iso(),
                    ),
                )
                notifications.append(self._get_by_id(connection, "notifications", notification_id))
            return notifications

    def generate_quarantine_review_overdue_notifications(
        self, days: int = 7
    ) -> list[dict[str, Any]]:
        """Notify when a quarantine review has been stuck in in_review for more than `days` days."""
        if days < 1:
            raise ValidationError("Overdue days must be at least 1")
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        with self.database.transaction() as connection:
            rows = connection.execute(
                """
                SELECT
                  qr.id AS review_id,
                  qr.batch_id,
                  p.name AS product_name,
                  qr.responsible_id,
                  qr.updated_at AS started_at,
                  b.lot,
                  qr.warehouse_id
                FROM quarantine_reviews qr
                JOIN batches b ON b.id = qr.batch_id
                JOIN products p ON p.id = b.product_id
                WHERE qr.status = 'in_review'
                  AND qr.updated_at <= ?
                ORDER BY qr.updated_at, qr.id
                """,
                (cutoff,),
            ).fetchall()
            notifications: list[dict[str, Any]] = []
            for row in rows:
                existing = connection.execute(
                    """
                    SELECT id FROM notifications
                    WHERE notification_type = 'quarantine'
                      AND batch_id = ?
                      AND is_read = 0
                      AND title LIKE '%проверка%просрочена%'
                    """,
                    (row["batch_id"],),
                ).fetchone()
                if existing:
                    notifications.append(self._get_by_id(connection, "notifications", existing["id"]))
                    continue
                started = self._datetime_from_db(row["started_at"])
                age = max(0, (datetime.now(UTC) - started).days)
                title = f"Карантинная проверка просрочена: {row['product_name']}"
                message = (
                    f"Проверка #{row['review_id']} по партии {row['lot']} находится в статусе"
                    f" «На проверке» уже {age} дн. Ответственный: {row['responsible_id'] or '—'}."
                )
                wh = row["warehouse_id"] or 0
                notification_id = insert_and_get_id(
                    connection,
                    """
                    INSERT INTO notifications(
                      notification_type, batch_id, warehouse_id, title, message, created_at
                    ) VALUES ('quarantine', ?, ?, ?, ?, ?)
                    """,
                    (row["batch_id"], wh, title, message, now_iso()),
                )
                notifications.append(self._get_by_id(connection, "notifications", notification_id))
            return notifications


    def generate_supplier_contract_expiry_notifications(
        self, days: int = 30
    ) -> list[dict[str, Any]]:
        """Notify when a supplier contract expires within the next `days` days."""
        if days < 0:
            raise ValidationError("Expiry window cannot be negative")
        today = datetime.now(UTC).date()
        cutoff = (today + timedelta(days=days)).isoformat()
        today_str = today.isoformat()
        with self.database.transaction() as connection:
            rows = connection.execute(
                """
                SELECT id, name, contract_expires_on
                FROM suppliers
                WHERE contract_expires_on IS NOT NULL
                  AND contract_expires_on >= ?
                  AND contract_expires_on <= ?
                ORDER BY contract_expires_on, id
                """,
                (today_str, cutoff),
            ).fetchall()
            notifications: list[dict[str, Any]] = []
            for row in rows:
                existing = connection.execute(
                    """
                    SELECT id FROM notifications
                    WHERE notification_type = 'supplier_contract_expiry'
                      AND title LIKE ?
                      AND is_read = 0
                    """,
                    (f"%{row['name']}%",),
                ).fetchone()
                if existing:
                    notifications.append(self._get_by_id(connection, "notifications", existing["id"]))
                    continue
                expires = row["contract_expires_on"]
                try:
                    from datetime import date as _date
                    exp_date = _date.fromisoformat(str(expires))
                    days_left = max(0, (exp_date - today).days)
                except Exception:
                    days_left = days
                title = f"Истекает договор поставщика: {row['name']}"
                message = (
                    f"Договор с поставщиком «{row['name']}» истекает {expires} "
                    f"(через {days_left} дн.). Свяжитесь с поставщиком для продления."
                )
                notification_id = insert_and_get_id(
                    connection,
                    """INSERT INTO notifications(
                      notification_type, title, message, created_at
                    ) VALUES ('supplier_contract_expiry', ?, ?, ?)""",
                    (title, message, now_iso()),
                )
                notifications.append(self._get_by_id(connection, "notifications", notification_id))
            return notifications

    def _ensure_sensor_warning_notification(
        self,
        connection: Connection,
        *,
        device: dict[str, Any],
        reading: dict[str, Any],
    ) -> dict[str, Any]:
        title = f"Нарушены условия хранения: {device['name']}"
        details = self._sensor_warning_details(device, reading)
        warehouse_name = reading.get("warehouse_name") or f"склад #{reading['warehouse_id']}"
        message = (
            f"{warehouse_name}. {'; '.join(details)}. "
            f"Время показания: {reading['recorded_at']}. Проверьте помещение, питание оборудования "
            "и перенесите чувствительные партии при необходимости."
        )
        if self._is_postgresql(connection):
            notification_id = self._upsert_sensor_warning_notification_postgresql(
                connection,
                device_id=reading["device_id"],
                sensor_reading_id=reading["id"],
                warehouse_id=reading["warehouse_id"],
                title=title,
                message=message,
            )
            return self._get_by_id(connection, "notifications", notification_id)

        existing = connection.execute(
            """
            SELECT id FROM notifications
            WHERE notification_type = 'sensor_warning'
              AND device_id = ?
              AND is_read = 0
            """,
            (reading["device_id"],),
        ).fetchone()
        if existing:
            connection.execute(
                """
                UPDATE notifications
                SET sensor_reading_id = ?,
                    warehouse_id = ?,
                    title = ?,
                    message = ?,
                    created_at = ?
                WHERE id = ?
                """,
                (
                    reading["id"],
                    reading["warehouse_id"],
                    title,
                    message,
                    now_iso(),
                    existing["id"],
                ),
            )
            return self._get_by_id(connection, "notifications", existing["id"])

        notification_id = insert_and_get_id(
            connection,
            """
            INSERT INTO notifications(
              notification_type, device_id, sensor_reading_id, warehouse_id,
              title, message, created_at
            ) VALUES ('sensor_warning', ?, ?, ?, ?, ?, ?)
            """,
            (
                reading["device_id"],
                reading["id"],
                reading["warehouse_id"],
                title,
                message,
                now_iso(),
            ),
        )
        return self._get_by_id(connection, "notifications", notification_id)

    def _upsert_sensor_warning_notification_postgresql(
        self,
        connection: Connection,
        *,
        device_id: int,
        sensor_reading_id: int,
        warehouse_id: int,
        title: str,
        message: str,
    ) -> int:
        row = connection.execute(
            """
            INSERT INTO notifications(
              notification_type, device_id, sensor_reading_id, warehouse_id,
              title, message, created_at
            ) VALUES ('sensor_warning', ?, ?, ?, ?, ?, ?)
            ON CONFLICT (device_id)
              WHERE notification_type = 'sensor_warning' AND is_read = FALSE
            DO UPDATE SET
              sensor_reading_id = EXCLUDED.sensor_reading_id,
              warehouse_id = EXCLUDED.warehouse_id,
              title = EXCLUDED.title,
              message = EXCLUDED.message,
              created_at = EXCLUDED.created_at
            RETURNING id
            """,
            (device_id, sensor_reading_id, warehouse_id, title, message, now_iso()),
        ).fetchone()
        if row is None:
            raise RuntimeError("Sensor warning notification conflict was not recoverable")
        return int(row["id"])

    def get_stats_summary(self) -> dict[str, Any]:
        connection = self.database.connect()
        try:
            def scalar(sql: str, default: int = 0) -> int:
                try:
                    row = connection.execute(sql).fetchone()
                except Exception:
                    return default
                if row is None:
                    return default
                row_dict = dict(row) if hasattr(row, "keys") else {}
                val = list(row_dict.values())[0] if row_dict else (row[0] if row else default)
                try:
                    return int(float(val or 0))
                except (TypeError, ValueError):
                    return default

            return {
                "products": scalar("SELECT COUNT(*) FROM products WHERE is_active = 1"),
                "batches": scalar("SELECT COUNT(*) FROM batches"),
                "batches_available": scalar("SELECT COUNT(*) FROM batches WHERE status = 'available'"),
                "batches_quarantine": scalar("SELECT COUNT(*) FROM batches WHERE status = 'quarantine'"),
                "warehouses": scalar("SELECT COUNT(*) FROM warehouses"),
                "total_free_quantity": scalar("SELECT COALESCE(SUM(CAST(quantity AS REAL) - CAST(reserved_quantity AS REAL)), 0) FROM stock_balances"),
                "unread_notifications": scalar("SELECT COUNT(*) FROM notifications WHERE is_read = 0"),
                "pending_writeoffs": scalar("SELECT COUNT(*) FROM pending_controlled_writeoffs WHERE status = 'pending'"),
                "active_inventory_sessions": scalar("SELECT COUNT(*) FROM inventory_sessions WHERE status = 'in_progress'"),
            }
        finally:
            self._close_connection(connection)

    def create_grafana_alert_notification(
        self,
        title: str,
        message: str,
        severity: str = "warning",
    ) -> dict[str, Any]:
        with self.database.transaction() as connection:
            notification_id = insert_and_get_id(
                connection,
                "INSERT INTO notifications(notification_type, title, message, created_at) VALUES ('grafana_alert', ?, ?, ?)",
                (title[:255], message[:1000], now_iso()),
            )
            return self._get_by_id(connection, "notifications", notification_id)

    def list_notifications(
        self,
        unread_only: bool = False,
        limit: int = 100,
        offset: int = 0,
        warehouse_id: int | None = None,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 500))
        safe_offset = max(0, offset)
        connection = self.database.connect()
        try:
            query = "SELECT * FROM notifications"
            params: tuple[Any, ...] = ()
            filters: list[str] = []
            if unread_only:
                filters.append("is_read = 0")
            if warehouse_id is not None:
                filters.append("warehouse_id = ?")
                params = (*params, warehouse_id)
            if filters:
                query += " WHERE " + " AND ".join(filters)
            query += " ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?"
            params = (*params, safe_limit, safe_offset)
            return [dict(row) for row in connection.execute(query, params).fetchall()]
        finally:
            self._close_connection(connection)

    def count_notifications(
        self, unread_only: bool = False, warehouse_id: int | None = None
    ) -> int:
        connection = self.database.connect()
        try:
            query = "SELECT COUNT(*) AS total FROM notifications"
            params: tuple[Any, ...] = ()
            filters: list[str] = []
            if unread_only:
                filters.append("is_read = 0")
            if warehouse_id is not None:
                filters.append("warehouse_id = ?")
                params = (*params, warehouse_id)
            if filters:
                query += " WHERE " + " AND ".join(filters)
            row = connection.execute(query, params).fetchone()
            return int(row["total"])
        finally:
            self._close_connection(connection)

    def list_audit_log(
        self,
        entity_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
        warehouse_id: int | None = None,
        actor_id: str | None = None,
        action: str | None = None,
    ) -> list[dict[str, Any]]:
        connection = self.database.connect()
        try:
            safe_limit = max(1, min(limit, 500))
            safe_offset = max(0, offset)
            query = "SELECT * FROM audit_log"
            params: tuple[Any, ...] = ()
            filters: list[str] = []
            if entity_type:
                filters.append("entity_type = ?")
                params = (*params, entity_type)
            if warehouse_id is not None:
                filters.append("warehouse_id = ?")
                params = (*params, warehouse_id)
            if actor_id:
                filters.append("actor_id = ?")
                params = (*params, actor_id)
            if action:
                filters.append("action = ?")
                params = (*params, action)
            if filters:
                query += " WHERE " + " AND ".join(filters)
            query += " ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?"
            params = (*params, safe_limit, safe_offset)
            rows = connection.execute(query, params).fetchall()
            result: list[dict[str, Any]] = []
            for row in rows:
                item = dict(row)
                payload = item["payload"]
                if isinstance(payload, str):
                    payload = json.loads(payload)
                item["payload"] = self._redact_audit_payload(payload)
                result.append(item)
            return result
        finally:
            self._close_connection(connection)

    def count_audit_log(
        self,
        entity_type: str | None = None,
        warehouse_id: int | None = None,
        actor_id: str | None = None,
        action: str | None = None,
    ) -> int:
        connection = self.database.connect()
        try:
            query = "SELECT COUNT(*) AS total FROM audit_log"
            params: tuple[Any, ...] = ()
            filters: list[str] = []
            if entity_type:
                filters.append("entity_type = ?")
                params = (*params, entity_type)
            if warehouse_id is not None:
                filters.append("warehouse_id = ?")
                params = (*params, warehouse_id)
            if actor_id:
                filters.append("actor_id = ?")
                params = (*params, actor_id)
            if action:
                filters.append("action = ?")
                params = (*params, action)
            if filters:
                query += " WHERE " + " AND ".join(filters)
            row = connection.execute(query, params).fetchone()
            return int(row["total"])
        finally:
            self._close_connection(connection)

    def get_notification(self, notification_id: int) -> dict[str, Any]:
        connection = self.database.connect()
        try:
            return self._get_by_id(connection, "notifications", notification_id)
        finally:
            self._close_connection(connection)

    def mark_notification_read(self, notification_id: int, is_read: bool = True) -> dict[str, Any]:
        with self.database.transaction() as connection:
            self._require(connection, "notifications", notification_id)
            connection.execute(
                "UPDATE notifications SET is_read = ?, read_at = ? WHERE id = ?",
                (1 if is_read else 0, now_iso() if is_read else None, notification_id),
            )
            return self._get_by_id(connection, "notifications", notification_id)
