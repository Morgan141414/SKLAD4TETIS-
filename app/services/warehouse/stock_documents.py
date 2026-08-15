from __future__ import annotations

import json
import logging
from datetime import (
    UTC,
    datetime,
)
from decimal import Decimal
from sqlite3 import Connection
from typing import Any

from app.domain.enums import (
    AuditAction,
    BatchStatus,
    InventoryStatus,
    MovementType,
    QuarantineReviewStatus,
    ReservationStatus,
    StockDocumentStatus,
    StockDocumentType,
)
from app.domain.errors import (
    InsufficientStockError,
    InventoryLockedError,
    NotFoundError,
    ValidationError,
)
from app.domain.schemas import (
    BatchRecallCreate,
    DepartmentReturnCreate,
    DepartmentReturnDocumentCreate,
    InventoryCreate,
    InventoryLineCountUpdate,
    QuarantineReviewUpdate,
    ReceiptCreate,
    ReceiptDocumentCreate,
    RepackDocumentCreate,
    ReservationCreate,
    ReservationUseCreate,
    SupplierReturnCreate,
    SupplierReturnDocumentCreate,
    TransferCreate,
    TransferDocumentCreate,
    WriteOffCreate,
    WriteOffDocumentCreate,
    WriteOffFefoCreate,
)
from app.services.warehouse.base import WarehouseServiceBase
from app.storage.sqlite import (
    decimal_to_db,
    insert_and_get_id,
    now_iso,
)

logger = logging.getLogger(__name__)


class StockDocumentsMixin(WarehouseServiceBase):
    def receive(self, data: ReceiptCreate, actor_id: str = "system") -> dict[str, Any]:
        with self.database.transaction() as connection:
            batch_id = self._apply_receipt_line(
                connection,
                supplier_id=data.supplier_id,
                warehouse_id=data.warehouse_id,
                product_id=data.product_id,
                quantity=data.quantity,
                unit_price=data.unit_price,
                lot=data.lot,
                serial_number=data.serial_number,
                expires_on=data.expires_on,
                quarantine=data.quarantine,
                actor_id=actor_id,
            )
            self._audit(
                connection,
                actor_id,
                AuditAction.RECEIPT,
                "batch",
                batch_id,
                data,
                warehouse_id=data.warehouse_id,
            )
            return self._get_batch(connection, batch_id)

    def list_supplier_price_history(
        self,
        supplier_id: int,
        product_id: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 500))
        safe_offset = max(0, offset)
        query = """
            SELECT
              h.id,
              h.supplier_id,
              s.name AS supplier_name,
              h.product_id,
              p.name AS product_name,
              p.sku,
              h.batch_id,
              h.lot,
              h.unit_price,
              h.source,
              h.recorded_at
            FROM supplier_price_history h
            JOIN suppliers s ON s.id = h.supplier_id
            JOIN products p ON p.id = h.product_id
            WHERE h.supplier_id = ?
        """
        params: tuple[Any, ...] = (supplier_id,)
        if product_id is not None:
            query += " AND h.product_id = ?"
            params = (*params, product_id)
        query += " ORDER BY h.recorded_at DESC, h.id DESC LIMIT ? OFFSET ?"
        connection = self.database.connect()
        try:
            self._require(connection, "suppliers", supplier_id)
            rows = connection.execute(query, (*params, safe_limit, safe_offset)).fetchall()
            history = []
            for row in rows:
                item = dict(row)
                item["unit_price"] = Decimal(str(item["unit_price"]))
                history.append(item)
            return history
        finally:
            self._close_connection(connection)

    def count_supplier_price_history(self, supplier_id: int, product_id: int | None = None) -> int:
        query = "SELECT COUNT(*) AS total FROM supplier_price_history WHERE supplier_id = ?"
        params: tuple[Any, ...] = (supplier_id,)
        if product_id is not None:
            query += " AND product_id = ?"
            params = (*params, product_id)
        connection = self.database.connect()
        try:
            self._require(connection, "suppliers", supplier_id)
            row = connection.execute(query, params).fetchone()
            return int(row["total"])
        finally:
            self._close_connection(connection)

    def create_receipt_document(
        self, data: ReceiptDocumentCreate, actor_id: str = "system"
    ) -> dict[str, Any]:
        if not data.lines:
            raise ValidationError("Receipt document must contain at least one line")
        with self.database.transaction() as connection:
            self._ensure_warehouse_open(connection, data.warehouse_id)
            self._require(connection, "suppliers", data.supplier_id)
            document_id = self._create_document(
                connection,
                StockDocumentType.RECEIPT,
                data.warehouse_id,
                actor_id,
                supplier_id=data.supplier_id,
                external_ref=getattr(data, "external_ref", None),
                notes=getattr(data, "notes", None),
            )
            for line in data.lines:
                self._require(connection, "products", line.product_id)
                connection.execute(
                    """
                    INSERT INTO stock_document_lines(
                      document_id, product_id, quantity, unit_price, lot, serial_number, expires_on, quarantine
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        document_id,
                        line.product_id,
                        decimal_to_db(line.quantity),
                        decimal_to_db(line.unit_price),
                        line.lot,
                        line.serial_number,
                        line.expires_on.isoformat() if line.expires_on else None,
                        1 if line.quarantine else 0,
                    ),
                )
            self._audit(
                connection,
                actor_id,
                AuditAction.CREATE,
                "stock_document",
                document_id,
                data,
                warehouse_id=data.warehouse_id,
            )
            return self._get_document(connection, document_id)

    def create_writeoff_document(
        self, data: WriteOffDocumentCreate, actor_id: str = "system"
    ) -> dict[str, Any]:
        if not data.lines:
            raise ValidationError("Write-off document must contain at least one line")
        with self.database.transaction() as connection:
            self._ensure_warehouse_open(connection, data.warehouse_id)
            document_id = self._create_document(
                connection, StockDocumentType.WRITE_OFF, data.warehouse_id, actor_id
            )
            for line in data.lines:
                self._ensure_batch_available(connection, line.batch_id)
                connection.execute(
                    """
                    INSERT INTO stock_document_lines(
                      document_id, batch_id, quantity, reason,
                      patient_id, doctor_id, medical_record_no,
                      second_approver_id, second_approval_note
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        document_id,
                        line.batch_id,
                        decimal_to_db(line.quantity),
                        line.reason,
                        line.patient_id,
                        line.doctor_id,
                        line.medical_record_no,
                        line.second_approver_id,
                        line.second_approval_note,
                    ),
                )
            self._audit(
                connection,
                actor_id,
                AuditAction.CREATE,
                "stock_document",
                document_id,
                data,
                warehouse_id=data.warehouse_id,
            )
            return self._get_document(connection, document_id)

    def create_transfer_document(
        self, data: TransferDocumentCreate, actor_id: str = "system"
    ) -> dict[str, Any]:
        if not data.lines:
            raise ValidationError("Transfer document must contain at least one line")
        with self.database.transaction() as connection:
            self._ensure_warehouse_open(connection, data.source_warehouse_id)
            document_id = self._create_document(
                connection, StockDocumentType.TRANSFER, data.source_warehouse_id, actor_id
            )
            for line in data.lines:
                if data.source_warehouse_id == line.target_warehouse_id:
                    raise ValidationError("Source and target warehouses must be different")
                self._ensure_warehouse_open(connection, line.target_warehouse_id)
                self._ensure_batch_available(connection, line.batch_id)
                connection.execute(
                    """
                    INSERT INTO stock_document_lines(
                      document_id, batch_id, target_warehouse_id, quantity, reason
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        document_id,
                        line.batch_id,
                        line.target_warehouse_id,
                        decimal_to_db(line.quantity),
                        line.reason,
                    ),
                )
            self._audit(
                connection,
                actor_id,
                AuditAction.CREATE,
                "stock_document",
                document_id,
                data,
                warehouse_id=data.source_warehouse_id,
            )
            return self._get_document(connection, document_id)

    def create_department_return_document(
        self, data: DepartmentReturnDocumentCreate, actor_id: str = "system"
    ) -> dict[str, Any]:
        if not data.lines:
            raise ValidationError("Department return document must contain at least one line")
        with self.database.transaction() as connection:
            self._ensure_warehouse_open(connection, data.source_warehouse_id)
            document_id = self._create_document(
                connection, StockDocumentType.DEPARTMENT_RETURN, data.source_warehouse_id, actor_id
            )
            for line in data.lines:
                if data.source_warehouse_id == line.target_warehouse_id:
                    raise ValidationError("Source and target warehouses must be different")
                self._ensure_warehouse_open(connection, line.target_warehouse_id)
                self._ensure_batch_available(connection, line.batch_id)
                connection.execute(
                    """
                    INSERT INTO stock_document_lines(
                      document_id, batch_id, target_warehouse_id, quantity, reason
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        document_id,
                        line.batch_id,
                        line.target_warehouse_id,
                        decimal_to_db(line.quantity),
                        line.reason,
                    ),
                )
            self._audit(
                connection,
                actor_id,
                AuditAction.CREATE,
                "stock_document",
                document_id,
                data,
                warehouse_id=data.source_warehouse_id,
            )
            return self._get_document(connection, document_id)

    def create_supplier_return_document(
        self, data: SupplierReturnDocumentCreate, actor_id: str = "system"
    ) -> dict[str, Any]:
        if not data.lines:
            raise ValidationError("Supplier return document must contain at least one line")
        with self.database.transaction() as connection:
            self._ensure_warehouse_open(connection, data.warehouse_id)
            self._require(connection, "suppliers", data.supplier_id)
            document_id = self._create_document(
                connection,
                StockDocumentType.SUPPLIER_RETURN,
                data.warehouse_id,
                actor_id,
                supplier_id=data.supplier_id,
            )
            for line in data.lines:
                self._ensure_batch_available(connection, line.batch_id)
                connection.execute(
                    """
                    INSERT INTO stock_document_lines(
                      document_id, batch_id, quantity, reason
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        document_id,
                        line.batch_id,
                        decimal_to_db(line.quantity),
                        line.reason,
                    ),
                )
            self._audit(
                connection,
                actor_id,
                AuditAction.CREATE,
                "stock_document",
                document_id,
                data,
                warehouse_id=data.warehouse_id,
            )
            return self._get_document(connection, document_id)

    def create_repack_document(
        self, data: RepackDocumentCreate, actor_id: str = "system"
    ) -> dict[str, Any]:
        if not data.lines:
            raise ValidationError("Repack document must contain at least one line")
        with self.database.transaction() as connection:
            self._ensure_warehouse_open(connection, data.warehouse_id)
            document_id = self._create_document(
                connection, StockDocumentType.REPACK, data.warehouse_id, actor_id
            )
            for line in data.lines:
                self._validate_repack_numbers(
                    source_quantity=line.quantity,
                    target_quantity=line.target_quantity,
                    conversion_factor=line.conversion_factor,
                    loss_quantity=line.loss_quantity,
                )
                self._ensure_batch_available(connection, line.batch_id)
                self._require(connection, "products", line.target_product_id)
                connection.execute(
                    """
                    INSERT INTO stock_document_lines(
                      document_id, batch_id, target_product_id, quantity,
                      target_quantity, conversion_factor, loss_quantity,
                      target_unit_price, target_lot, target_expires_on,
                      quarantine, reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        document_id,
                        line.batch_id,
                        line.target_product_id,
                        decimal_to_db(line.quantity),
                        decimal_to_db(line.target_quantity),
                        decimal_to_db(line.conversion_factor),
                        decimal_to_db(line.loss_quantity),
                        decimal_to_db(line.target_unit_price) if line.target_unit_price is not None else None,
                        line.target_lot,
                        line.target_expires_on.isoformat() if line.target_expires_on else None,
                        1 if line.quarantine else 0,
                        line.reason,
                    ),
                )
            self._audit(
                connection,
                actor_id,
                AuditAction.CREATE,
                "stock_document",
                document_id,
                data,
                warehouse_id=data.warehouse_id,
            )
            return self._get_document(connection, document_id)

    def post_stock_document(self, document_id: int, actor_id: str = "system") -> dict[str, Any]:
        with self.database.transaction() as connection:
            document = self._get_document(connection, document_id)
            if document["status"] == StockDocumentStatus.POSTED:
                return document
            if document["status"] not in {StockDocumentStatus.DRAFT, StockDocumentStatus.APPROVED}:
                raise ValidationError(f"Cannot post document in status {document['status']}")
            self._ensure_warehouse_open(connection, document["warehouse_id"])
            lines = connection.execute(
                "SELECT * FROM stock_document_lines WHERE document_id = ? ORDER BY id",
                (document_id,),
            ).fetchall()
            if not lines:
                raise ValidationError("Cannot post empty document")
            if document["document_type"] == StockDocumentType.RECEIPT:
                for line in lines:
                    self._apply_receipt_line(
                        connection,
                        supplier_id=document["supplier_id"],
                        warehouse_id=document["warehouse_id"],
                        product_id=line["product_id"],
                        quantity=Decimal(line["quantity"]),
                        unit_price=Decimal(line["unit_price"]),
                        lot=line["lot"],
                        serial_number=line["serial_number"],
                        expires_on=self._date_from_db(line["expires_on"]) if line["expires_on"] else None,
                        quarantine=bool(line["quarantine"]),
                        actor_id=actor_id,
                    )
            elif document["document_type"] == StockDocumentType.WRITE_OFF:
                for line in lines:
                    self._apply_writeoff_line(
                        connection,
                        batch_id=line["batch_id"],
                        warehouse_id=document["warehouse_id"],
                        quantity=Decimal(line["quantity"]),
                        reason=line["reason"],
                        patient_id=line["patient_id"],
                        doctor_id=line["doctor_id"],
                        medical_record_no=line["medical_record_no"],
                        second_approver_id=line["second_approver_id"],
                        second_approval_note=line["second_approval_note"],
                    )
            elif document["document_type"] == StockDocumentType.TRANSFER:
                for line in lines:
                    self._apply_transfer(
                        connection,
                        TransferCreate(
                            batch_id=line["batch_id"],
                            source_warehouse_id=document["warehouse_id"],
                            target_warehouse_id=line["target_warehouse_id"],
                            quantity=Decimal(line["quantity"]),
                            reason=line["reason"],
                        ),
                    )
            elif document["document_type"] == StockDocumentType.DEPARTMENT_RETURN:
                for line in lines:
                    self._apply_transfer(
                        connection,
                        TransferCreate(
                            batch_id=line["batch_id"],
                            source_warehouse_id=document["warehouse_id"],
                            target_warehouse_id=line["target_warehouse_id"],
                            quantity=Decimal(line["quantity"]),
                            reason=f"Возврат от отделения: {line['reason']}",
                        ),
                    )
            elif document["document_type"] == StockDocumentType.SUPPLIER_RETURN:
                for line in lines:
                    self._apply_supplier_return_line(
                        connection,
                        batch_id=line["batch_id"],
                        warehouse_id=document["warehouse_id"],
                        supplier_id=document["supplier_id"],
                        quantity=Decimal(line["quantity"]),
                        reason=line["reason"],
                    )
            elif document["document_type"] == StockDocumentType.REPACK:
                for line in lines:
                    self._apply_repack_line(
                        connection,
                        document_id=document_id,
                        warehouse_id=document["warehouse_id"],
                        source_batch_id=line["batch_id"],
                        target_product_id=line["target_product_id"],
                        source_quantity=Decimal(line["quantity"]),
                        target_quantity=Decimal(line["target_quantity"]),
                        conversion_factor=Decimal(line["conversion_factor"]),
                        loss_quantity=Decimal(line["loss_quantity"] or "0"),
                        target_unit_price=Decimal(line["target_unit_price"]) if line["target_unit_price"] is not None else None,
                        target_lot=line["target_lot"],
                        target_expires_on=self._date_from_db(line["target_expires_on"]) if line["target_expires_on"] else None,
                        quarantine=bool(line["quarantine"]),
                        reason=line["reason"],
                        actor_id=actor_id,
                    )
            else:
                raise ValidationError(f"Unsupported document type: {document['document_type']}")
            connection.execute(
                """
                UPDATE stock_documents
                SET status = ?, posted_at = ?
                WHERE id = ?
                """,
                (StockDocumentStatus.POSTED, now_iso(), document_id),
            )
            self._audit(
                connection,
                actor_id,
                AuditAction.REPACK if document["document_type"] == StockDocumentType.REPACK else AuditAction.UPDATE,
                "stock_document",
                document_id,
                {"status": StockDocumentStatus.POSTED},
                warehouse_id=document["warehouse_id"],
            )
            return self._get_document(connection, document_id)

    def approve_stock_document(self, document_id: int, actor_id: str = "system") -> dict[str, Any]:
        with self.database.transaction() as connection:
            document = self._get_document(connection, document_id)
            if document["status"] == StockDocumentStatus.APPROVED:
                return document
            if document["status"] != StockDocumentStatus.DRAFT:
                raise ValidationError(f"Cannot approve document in status {document['status']}")
            connection.execute(
                """
                UPDATE stock_documents
                SET status = ?, approved_by = ?, approved_at = ?
                WHERE id = ?
                """,
                (StockDocumentStatus.APPROVED, actor_id, now_iso(), document_id),
            )
            self._audit(
                connection,
                actor_id,
                AuditAction.UPDATE,
                "stock_document",
                document_id,
                {"status": StockDocumentStatus.APPROVED},
                warehouse_id=document["warehouse_id"],
            )
            return self._get_document(connection, document_id)

    def cancel_stock_document(self, document_id: int, actor_id: str = "system") -> dict[str, Any]:
        with self.database.transaction() as connection:
            document = self._get_document(connection, document_id)
            if document["status"] == StockDocumentStatus.CANCELLED:
                return document
            if document["status"] not in {StockDocumentStatus.DRAFT, StockDocumentStatus.APPROVED}:
                raise ValidationError(f"Cannot cancel document in status {document['status']}")
            connection.execute(
                """
                UPDATE stock_documents
                SET status = ?
                WHERE id = ?
                """,
                (StockDocumentStatus.CANCELLED, document_id),
            )
            self._audit(
                connection,
                actor_id,
                AuditAction.UPDATE,
                "stock_document",
                document_id,
                {"status": StockDocumentStatus.CANCELLED},
                warehouse_id=document["warehouse_id"],
            )
            return self._get_document(connection, document_id)

    def update_batch_status(
        self, batch_id: int, status: BatchStatus, reason: str | None, actor_id: str = "system"
    ) -> dict[str, Any]:
        with self.database.transaction() as connection:
            self._require(connection, "batches", batch_id)
            warehouse_ids = self._batch_warehouse_ids(connection, batch_id)
            if not warehouse_ids:
                raise ValidationError("Batch has no stock balances")
            batch = self._get_batch(connection, batch_id)
            if batch["status"] == status:
                return batch
            connection.execute("UPDATE batches SET status = ? WHERE id = ?", (status, batch_id))
            if status == BatchStatus.QUARANTINE:
                for warehouse_id in warehouse_ids:
                    self._ensure_quarantine_review(
                        connection,
                        batch_id=batch_id,
                        warehouse_id=warehouse_id,
                        actor_id=actor_id,
                    )
            elif status == BatchStatus.AVAILABLE:
                self._close_open_quarantine_reviews(
                    connection,
                    batch_id=batch_id,
                    status=QuarantineReviewStatus.APPROVED,
                    actor_id=actor_id,
                    reason=reason,
                )
            elif status == BatchStatus.BLOCKED:
                self._close_open_quarantine_reviews(
                    connection,
                    batch_id=batch_id,
                    status=QuarantineReviewStatus.REJECTED,
                    actor_id=actor_id,
                    reason=reason,
                )
            payload = {"status": status, "reason": reason, "warehouse_ids": warehouse_ids}
            for warehouse_id in warehouse_ids:
                self._audit(
                    connection,
                    actor_id,
                    AuditAction.UPDATE,
                    "batch",
                    batch_id,
                    payload,
                    warehouse_id=warehouse_id,
                )
            return self._get_batch(connection, batch_id)

    def recall_batch(
        self, batch_id: int, data: BatchRecallCreate, actor_id: str = "system"
    ) -> dict[str, Any]:
        with self.database.transaction() as connection:
            batch = dict(self._require(connection, "batches", batch_id))
            balances = self._batch_balances(connection, batch_id)
            affected_balances = [
                balance
                for balance in balances
                if Decimal(balance["total_quantity"]) > Decimal(0)
            ]
            if not affected_balances:
                raise ValidationError("Cannot recall a batch with no stock balances")
            connection.execute(
                "UPDATE batches SET status = ? WHERE id = ?",
                (BatchStatus.BLOCKED, batch_id),
            )
            recall_id = insert_and_get_id(
                connection,
                """
                INSERT INTO batch_recalls(
                  batch_id, product_id, reason, source, reference, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    batch_id,
                    batch["product_id"],
                    data.reason,
                    data.source,
                    data.reference,
                    actor_id,
                    now_iso(),
                ),
            )
            notifications = [
                self._ensure_recall_notification(
                    connection,
                    batch_id=batch_id,
                    product_id=batch["product_id"],
                    warehouse_id=balance["warehouse_id"],
                    lot=batch["lot"],
                    reason=data.reason,
                    free_quantity=balance["free_quantity"],
                )
                for balance in affected_balances
            ]
            payload = {
                "reason": data.reason,
                "source": data.source,
                "reference": data.reference,
                "affected_warehouse_ids": [row["warehouse_id"] for row in affected_balances],
            }
            for balance in affected_balances:
                self._audit(
                    connection,
                    actor_id,
                    AuditAction.RECALL,
                    "batch",
                    batch_id,
                    payload,
                    warehouse_id=balance["warehouse_id"],
                )
            return {
                "recall": self._get_batch_recall(connection, recall_id),
                "batch": self._get_batch(connection, batch_id),
                "affected_warehouses": affected_balances,
                "notifications": notifications,
            }

    def list_batch_recalls(
        self,
        batch_id: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 500))
        safe_offset = max(0, offset)
        connection = self.database.connect()
        try:
            return self._batch_recalls(
                connection,
                batch_id=batch_id,
                limit=safe_limit,
                offset=safe_offset,
            )
        finally:
            self._close_connection(connection)

    def count_batch_recalls(self, batch_id: int | None = None) -> int:
        connection = self.database.connect()
        try:
            query = "SELECT COUNT(*) AS total FROM batch_recalls"
            params: tuple[Any, ...] = ()
            if batch_id is not None:
                query += " WHERE batch_id = ?"
                params = (batch_id,)
            row = connection.execute(query, params).fetchone()
            return int(row["total"])
        finally:
            self._close_connection(connection)

    def unblock_batch(self, batch_id: int, reason: str = "", actor_id: str = "system") -> dict:
        with self.database.transaction() as connection:
            batch = dict(self._require(connection, "batches", batch_id))
            if batch["status"] != "blocked":
                from app.domain.errors import ValidationError as VE
                raise VE(f"Batch {batch_id} is not blocked (status={batch['status']})")
            connection.execute(
                "UPDATE batches SET status = ? WHERE id = ?",
                ("active", batch_id),
            )
            payload = {"reason": reason, "prev_status": "blocked"}
            # Audit in all warehouses that hold this batch
            balances = self._batch_balances(connection, batch_id)
            warehouse_ids = list({b["warehouse_id"] for b in balances})
            for wid in warehouse_ids:
                self._audit(connection, actor_id, "unblock", "batch", batch_id, payload, warehouse_id=wid)
            return self._get_batch(connection, batch_id)

    def get_recall_stats(self) -> dict:
        with self.database.transaction() as connection:
            total = (connection.execute("SELECT COUNT(*) AS c FROM batch_recalls").fetchone() or {}).get("c", 0)
            blocked = (connection.execute("SELECT COUNT(*) AS c FROM batches WHERE status = 'blocked'").fetchone() or {}).get("c", 0)
            by_source = connection.execute(
                "SELECT source, COUNT(*) AS cnt FROM batch_recalls GROUP BY source ORDER BY cnt DESC"
            ).fetchall() or []
            recent = connection.execute(
                "SELECT br.id, br.batch_id, br.reason, br.source, br.reference, br.created_by, br.created_at, "
                "p.name AS product_name, b.lot, b.serial_number, b.status AS batch_status "
                "FROM batch_recalls br "
                "JOIN batches b ON b.id = br.batch_id "
                "JOIN products p ON p.id = br.product_id "
                "ORDER BY br.created_at DESC LIMIT 5"
            ).fetchall() or []
        return {
            "total_recalls": int(total),
            "blocked_batches": int(blocked),
            "by_source": [dict(r) for r in by_source],
            "recent": [dict(r) for r in recent],
        }

    def list_quarantine_reviews(
        self,
        warehouse_id: int | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 500))
        safe_offset = max(0, offset)
        with self.database.transaction() as connection:
            self._ensure_quarantine_reviews_for_open_batches(connection, warehouse_id=warehouse_id)
            query = """
                SELECT
                  qr.*,
                  b.product_id,
                  b.lot,
                  p.name AS product_name
                FROM quarantine_reviews qr
                JOIN batches b ON b.id = qr.batch_id
                JOIN products p ON p.id = b.product_id
            """
            params: tuple[Any, ...] = ()
            filters: list[str] = []
            if warehouse_id is not None:
                filters.append("qr.warehouse_id = ?")
                params = (*params, warehouse_id)
            if status is not None:
                filters.append("qr.status = ?")
                params = (*params, status)
            if filters:
                query += " WHERE " + " AND ".join(filters)
            query += " ORDER BY qr.due_at IS NULL, qr.due_at, qr.created_at DESC, qr.id DESC LIMIT ? OFFSET ?"
            rows = connection.execute(query, (*params, safe_limit, safe_offset)).fetchall()
            return [dict(row) for row in rows]

    def count_quarantine_reviews(
        self, warehouse_id: int | None = None, status: str | None = None
    ) -> int:
        with self.database.transaction() as connection:
            self._ensure_quarantine_reviews_for_open_batches(connection, warehouse_id=warehouse_id)
            query = "SELECT COUNT(*) AS total FROM quarantine_reviews"
            params: tuple[Any, ...] = ()
            filters: list[str] = []
            if warehouse_id is not None:
                filters.append("warehouse_id = ?")
                params = (*params, warehouse_id)
            if status is not None:
                filters.append("status = ?")
                params = (*params, status)
            if filters:
                query += " WHERE " + " AND ".join(filters)
            row = connection.execute(query, params).fetchone()
            return int(row["total"])

    def get_quarantine_review(self, review_id: int) -> dict[str, Any]:
        connection = self.database.connect()
        try:
            return self._get_quarantine_review(connection, review_id)
        finally:
            self._close_connection(connection)

    def get_quarantine_review_protocol(self, review_id: int) -> dict[str, Any]:
        connection = self.database.connect()
        try:
            review = self._get_quarantine_review(connection, review_id)
            warehouse = dict(self._require(connection, "warehouses", review["warehouse_id"]))
            protocol = {
                "review_id": review["id"],
                "batch_id": review["batch_id"],
                "product_name": review["product_name"],
                "lot": review["lot"],
                "warehouse_id": review["warehouse_id"],
                "warehouse_name": warehouse["name"],
                "status": review["status"],
                "responsible_id": review["responsible_id"],
                "due_at": review["due_at"],
                "decision_reason": review["decision_reason"],
                "created_by": review["created_by"],
                "decided_by": review["decided_by"],
                "created_at": review["created_at"],
                "updated_at": review["updated_at"],
                "decided_at": review["decided_at"],
            }
            return {**protocol, "csv": self._quarantine_protocol_csv(protocol)}
        finally:
            self._close_connection(connection)

    def update_quarantine_review(
        self,
        review_id: int,
        data: QuarantineReviewUpdate,
        actor_id: str = "system",
    ) -> dict[str, Any]:
        with self.database.transaction() as connection:
            before = self._get_quarantine_review(connection, review_id)
            if data.status in {QuarantineReviewStatus.APPROVED, QuarantineReviewStatus.REJECTED}:
                if not data.decision_reason or not data.decision_reason.strip():
                    raise ValidationError("Decision reason is required for quarantine decision")
            now = now_iso()
            decided_by = actor_id if data.status in {
                QuarantineReviewStatus.APPROVED,
                QuarantineReviewStatus.REJECTED,
            } else None
            decided_at = now if decided_by else None
            commission_json = json.dumps(data.commission_members) if data.commission_members else None
            resolution_type = data.resolution_type
            disposal_quantity = data.disposal_quantity
            connection.execute(
                """
                UPDATE quarantine_reviews
                SET status = ?,
                    responsible_id = ?,
                    due_at = ?,
                    decision_reason = ?,
                    decided_by = ?,
                    updated_at = ?,
                    decided_at = ?,
                    commission_members = ?,
                    resolution_type = ?,
                    disposal_quantity = ?
                WHERE id = ?
                """,
                (
                    data.status,
                    data.responsible_id,
                    data.due_at.isoformat() if data.due_at else None,
                    data.decision_reason,
                    decided_by,
                    now,
                    decided_at,
                    commission_json,
                    resolution_type,
                    disposal_quantity,
                    review_id,
                ),
            )
            if data.status == QuarantineReviewStatus.APPROVED:
                new_batch_status = BatchStatus.AVAILABLE
            elif data.status == QuarantineReviewStatus.REJECTED:
                new_batch_status = BatchStatus.BLOCKED
            else:
                new_batch_status = BatchStatus.QUARANTINE
            connection.execute(
                "UPDATE batches SET status = ? WHERE id = ?",
                (new_batch_status, before["batch_id"]),
            )
            # Auto-disposal: when rejected with resolution_type=disposal, write off the stock
            if (
                data.status == QuarantineReviewStatus.REJECTED
                and resolution_type == "disposal"
                and disposal_quantity and disposal_quantity > 0
            ):
                try:
                    self._apply_writeoff_line(
                        connection,
                        batch_id=before["batch_id"],
                        warehouse_id=before["warehouse_id"],
                        quantity=Decimal(str(disposal_quantity)),
                        reason=f"Утилизация по результатам карантинной проверки #{review_id}: {data.decision_reason or ''}",
                        patient_id=None,
                        doctor_id=None,
                        medical_record_no=None,
                        second_approver_id=None,
                        second_approval_note=None,
                    )
                except Exception:
                    logger.exception("Failed to auto-dispose quarantine batch %s", before["batch_id"])
            updated = self._get_quarantine_review(connection, review_id)
            self._audit(
                connection,
                actor_id,
                AuditAction.UPDATE,
                "quarantine_review",
                review_id,
                {"before": before, "after": updated},
                warehouse_id=updated["warehouse_id"],
            )
            return updated

    def write_off(self, data: WriteOffCreate, actor_id: str = "system") -> dict[str, Any]:
        with self.database.transaction() as connection:
            movement_id = self._apply_writeoff_line(
                connection,
                batch_id=data.batch_id,
                warehouse_id=data.warehouse_id,
                quantity=data.quantity,
                reason=data.reason,
                patient_id=data.patient_id,
                doctor_id=data.doctor_id,
                medical_record_no=data.medical_record_no,
                second_approver_id=data.second_approver_id,
                second_approval_note=data.second_approval_note,
            )
            self._audit(
                connection,
                actor_id,
                AuditAction.WRITE_OFF,
                "movement",
                movement_id,
                data,
                warehouse_id=data.warehouse_id,
            )
            batch_row = connection.execute(
                "SELECT product_id FROM batches WHERE id = ?", (data.batch_id,)
            ).fetchone()
            if batch_row:
                self._check_and_create_reorder_requests(
                    connection, data.warehouse_id, [int(batch_row["product_id"])]
                )
            return self._get_by_id(connection, "stock_movements", movement_id)

    def write_off_fefo(
        self, data: WriteOffFefoCreate, actor_id: str = "system"
    ) -> dict[str, Any]:
        with self.database.transaction() as connection:
            return self._write_off_fefo_within(
                connection,
                actor_id=actor_id,
                product_id=data.product_id,
                warehouse_id=data.warehouse_id,
                quantity=data.quantity,
                reason=data.reason,
                patient_id=data.patient_id,
                doctor_id=data.doctor_id,
                medical_record_no=data.medical_record_no,
                second_approver_id=data.second_approver_id,
                second_approval_note=data.second_approval_note,
            )

    def _write_off_fefo_within(
        self,
        connection: Connection,
        *,
        actor_id: str,
        product_id: int,
        warehouse_id: int,
        quantity: Decimal,
        reason: str,
        patient_id: str | None = None,
        doctor_id: str | None = None,
        medical_record_no: str | None = None,
        second_approver_id: str | None = None,
        second_approval_note: str | None = None,
    ) -> dict[str, Any]:
        self._ensure_warehouse_open(connection, warehouse_id)
        self._require(connection, "products", product_id)
        self._require_controlled_writeoff_metadata(
            connection,
            product_id=product_id,
            patient_id=patient_id,
            doctor_id=doctor_id,
            medical_record_no=medical_record_no,
            second_approver_id=second_approver_id,
        )
        rows = connection.execute(
            """
            SELECT
              sb.batch_id,
              sb.quantity,
              sb.reserved_quantity
            FROM stock_balances sb
            JOIN batches b ON b.id = sb.batch_id
            WHERE b.product_id = ?
              AND sb.warehouse_id = ?
              AND b.status = ?
              AND CAST(sb.quantity AS REAL) - CAST(sb.reserved_quantity AS REAL) > 0
            ORDER BY b.expires_on IS NULL, b.expires_on, sb.batch_id
            """,
            (product_id, warehouse_id, BatchStatus.AVAILABLE),
        ).fetchall()
        remaining = quantity
        movement_ids: list[int] = []
        for row in rows:
            if remaining <= 0:
                break
            free = Decimal(row["quantity"]) - Decimal(row["reserved_quantity"])
            line_quantity = min(free, remaining)
            movement_ids.append(
                self._apply_writeoff_line(
                    connection,
                    batch_id=row["batch_id"],
                    warehouse_id=warehouse_id,
                    quantity=line_quantity,
                    reason=reason,
                    patient_id=patient_id,
                    doctor_id=doctor_id,
                    medical_record_no=medical_record_no,
                    second_approver_id=second_approver_id,
                    second_approval_note=second_approval_note,
                )
            )
            remaining -= line_quantity
        if remaining > 0:
            raise InsufficientStockError("Not enough FEFO stock for write-off")
        self._audit(
            connection,
            actor_id,
            AuditAction.WRITE_OFF,
            "product",
            product_id,
            {
                "request": {
                    "product_id": product_id,
                    "warehouse_id": warehouse_id,
                    "quantity": decimal_to_db(quantity),
                    "reason": reason,
                },
                "movement_ids": movement_ids,
            },
            warehouse_id=warehouse_id,
        )
        return {
            "product_id": product_id,
            "warehouse_id": warehouse_id,
            "quantity": decimal_to_db(quantity),
            "movement_ids": movement_ids,
        }

    def transfer(self, data: TransferCreate, actor_id: str = "system") -> dict[str, Any]:
        if data.source_warehouse_id == data.target_warehouse_id:
            raise ValidationError("Source and target warehouses must be different")
        with self.database.transaction() as connection:
            result = self._apply_transfer(connection, data)
            self._audit(
                connection,
                actor_id,
                AuditAction.TRANSFER,
                "batch",
                data.batch_id,
                {
                    "request": data,
                    "out_movement_id": result["out_movement_id"],
                    "in_movement_id": result["in_movement_id"],
                },
                warehouse_id=data.source_warehouse_id,
            )
            return result

    def return_from_department(
        self, data: DepartmentReturnCreate, actor_id: str = "system"
    ) -> dict[str, Any]:
        with self.database.transaction() as connection:
            transfer = self._apply_transfer(
                connection,
                TransferCreate(
                    batch_id=data.batch_id,
                    source_warehouse_id=data.source_warehouse_id,
                    target_warehouse_id=data.target_warehouse_id,
                    quantity=data.quantity,
                    reason=f"Возврат от отделения: {data.reason}",
                ),
            )
            self._audit(
                connection,
                actor_id,
                AuditAction.RETURN,
                "batch",
                data.batch_id,
                {"return_type": "from_department", "request": data, "transfer": transfer},
                warehouse_id=data.source_warehouse_id,
            )
            return transfer

    def return_to_supplier(
        self, data: SupplierReturnCreate, actor_id: str = "system"
    ) -> dict[str, Any]:
        with self.database.transaction() as connection:
            result = self._apply_supplier_return_line(
                connection,
                batch_id=data.batch_id,
                warehouse_id=data.warehouse_id,
                supplier_id=data.supplier_id,
                quantity=data.quantity,
                reason=data.reason,
            )
            self._audit(
                connection,
                actor_id,
                AuditAction.RETURN,
                "batch",
                data.batch_id,
                {
                    "return_type": "to_supplier",
                    "request": data,
                    "movement_id": result["movement_id"],
                },
                warehouse_id=data.warehouse_id,
            )
            return result

    def reserve(self, data: ReservationCreate, actor_id: str = "system") -> dict[str, Any]:
        with self.database.transaction() as connection:
            self._ensure_warehouse_open(connection, data.warehouse_id)
            self._ensure_batch_available(connection, data.batch_id)
            balance = self._balance_for_update(connection, data.batch_id, data.warehouse_id)
            free = Decimal(balance["quantity"]) - Decimal(balance["reserved_quantity"])
            if free < data.quantity:
                raise InsufficientStockError("Not enough free stock for reservation")
            reservation_id = insert_and_get_id(
                connection,
                """
                INSERT INTO reservations(
                  batch_id, warehouse_id, quantity, reserved_for, status, expires_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data.batch_id,
                    data.warehouse_id,
                    decimal_to_db(data.quantity),
                    data.reserved_for,
                    ReservationStatus.RESERVED,
                    data.expires_at.isoformat() if data.expires_at else None,
                    now_iso(),
                ),
            )
            reserved = Decimal(balance["reserved_quantity"]) + data.quantity
            connection.execute(
                """
                UPDATE stock_balances
                SET reserved_quantity = ?
                WHERE batch_id = ? AND warehouse_id = ?
                """,
                (decimal_to_db(reserved), data.batch_id, data.warehouse_id),
            )
            self._movement(
                connection, MovementType.RESERVE, data.batch_id, data.warehouse_id, data.quantity
            )
            self._audit(
                connection,
                actor_id,
                AuditAction.RESERVE,
                "reservation",
                reservation_id,
                data,
                warehouse_id=data.warehouse_id,
            )
            return self._get_by_id(connection, "reservations", reservation_id)

    def release_reservation(
        self, reservation_id: int, actor_id: str = "system"
    ) -> dict[str, Any]:
        with self.database.transaction() as connection:
            return self._release_reservation(connection, reservation_id, actor_id)

    def use_reservation(
        self, reservation_id: int, data: ReservationUseCreate, actor_id: str = "system"
    ) -> dict[str, Any]:
        with self.database.transaction() as connection:
            reservation = self._require(connection, "reservations", reservation_id)
            if reservation["status"] != ReservationStatus.RESERVED:
                return dict(reservation)
            self._ensure_warehouse_open(connection, reservation["warehouse_id"])
            self._ensure_batch_available(connection, reservation["batch_id"])
            self._require_controlled_writeoff_metadata(
                connection,
                batch_id=reservation["batch_id"],
                patient_id=data.patient_id,
                doctor_id=data.doctor_id,
                medical_record_no=data.medical_record_no,
                second_approver_id=data.second_approver_id,
            )
            balance = self._balance_for_update(
                connection, reservation["batch_id"], reservation["warehouse_id"]
            )
            quantity = Decimal(reservation["quantity"])
            total = Decimal(balance["quantity"])
            reserved = Decimal(balance["reserved_quantity"])
            if total < quantity or reserved < quantity:
                raise InsufficientStockError("Not enough reserved stock for write-off")
            new_total = total - quantity
            new_reserved = reserved - quantity
            connection.execute(
                """
                UPDATE stock_balances
                SET quantity = ?, reserved_quantity = ?
                WHERE batch_id = ? AND warehouse_id = ?
                """,
                (
                    decimal_to_db(new_total),
                    decimal_to_db(new_reserved),
                    reservation["batch_id"],
                    reservation["warehouse_id"],
                ),
            )
            movement_id = self._movement(
                connection,
                MovementType.WRITE_OFF,
                reservation["batch_id"],
                reservation["warehouse_id"],
                quantity,
                reason=data.reason,
                patient_id=data.patient_id,
                doctor_id=data.doctor_id,
                medical_record_no=data.medical_record_no,
                second_approver_id=data.second_approver_id,
                second_approval_note=data.second_approval_note,
            )
            connection.execute(
                "UPDATE reservations SET status = ? WHERE id = ?",
                (ReservationStatus.USED, reservation_id),
            )
            self._audit(
                connection,
                actor_id,
                AuditAction.WRITE_OFF,
                "reservation",
                reservation_id,
                {"status": ReservationStatus.USED, "request": data, "movement_id": movement_id},
                warehouse_id=reservation["warehouse_id"],
            )
            return self._get_by_id(connection, "reservations", reservation_id)

    def expire_reservations(
        self,
        now: datetime | None = None,
        actor_id: str = "system",
        warehouse_id: int | None = None,
    ) -> list[dict[str, Any]]:
        cutoff = (now or datetime.now(UTC)).astimezone(UTC).isoformat()
        with self.database.transaction() as connection:
            params: tuple[Any, ...] = (ReservationStatus.RESERVED, cutoff)
            warehouse_filter = ""
            if warehouse_id is not None:
                self._require(connection, "warehouses", warehouse_id)
                warehouse_filter = " AND warehouse_id = ?"
                params = (*params, warehouse_id)
            rows = connection.execute(
                f"""
                SELECT id FROM reservations
                WHERE status = ?
                  AND expires_at IS NOT NULL
                  AND expires_at <= ?
                  {warehouse_filter}
                ORDER BY expires_at, id
                """,
                params,
            ).fetchall()
            return [self._release_reservation(connection, row["id"], actor_id) for row in rows]

    def create_inventory_session(
        self, data: InventoryCreate, actor_id: str = "system"
    ) -> dict[str, Any]:
        with self.database.transaction() as connection:
            warehouse = self._require(connection, "warehouses", data.warehouse_id)
            if int(warehouse["inventory_lock"]):
                raise InventoryLockedError("Warehouse already has active inventory lock")
            connection.execute(
                "UPDATE warehouses SET inventory_lock = 1 WHERE id = ?",
                (data.warehouse_id,),
            )
            session_id = insert_and_get_id(
                connection,
                """
                INSERT INTO inventory_sessions(warehouse_id, status, started_by, started_at)
                VALUES (?, ?, ?, ?)
                """,
                (data.warehouse_id, InventoryStatus.IN_PROGRESS, actor_id, now_iso()),
            )
            responsible_ids = list(dict.fromkeys(item.strip() for item in data.responsible_ids if item.strip()))
            category_ids = list(dict.fromkeys(data.category_ids))
            for category_id in category_ids:
                self._require(connection, "categories", category_id)
                connection.execute(
                    """
                    INSERT INTO inventory_session_categories(session_id, category_id)
                    VALUES (?, ?)
                    """,
                    (session_id, category_id),
                )
            for responsible_id in responsible_ids:
                connection.execute(
                    """
                    INSERT INTO inventory_responsibles(session_id, responsible_id)
                    VALUES (?, ?)
                    """,
                    (session_id, responsible_id),
                )
            category_filter = ""
            params: tuple[Any, ...] = (data.warehouse_id,)
            if category_ids:
                placeholders = ", ".join("?" for _ in category_ids)
                category_filter = f" AND p.category_id IN ({placeholders})"
                params = (*params, *category_ids)
            balances = connection.execute(
                f"""
                SELECT b.product_id, sb.batch_id, sb.quantity
                FROM stock_balances sb
                JOIN batches b ON b.id = sb.batch_id
                JOIN products p ON p.id = b.product_id
                WHERE sb.warehouse_id = ?
                  {category_filter}
                ORDER BY b.product_id, sb.batch_id
                """,
                params,
            ).fetchall()
            for balance in balances:
                connection.execute(
                    """
                    INSERT INTO inventory_lines(
                      session_id, product_id, batch_id, expected_quantity
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        balance["product_id"],
                        balance["batch_id"],
                        balance["quantity"],
                    ),
                )
            self._audit(
                connection,
                actor_id,
                AuditAction.INVENTORY_LOCK,
                "inventory_session",
                session_id,
                {
                    "warehouse_id": data.warehouse_id,
                    "line_count": len(balances),
                    "responsible_ids": responsible_ids,
                    "category_ids": category_ids,
                },
                warehouse_id=data.warehouse_id,
            )
            return self._get_inventory_session(connection, session_id)

    def get_inventory_session(self, session_id: int) -> dict[str, Any]:
        connection = self.database.connect()
        try:
            return self._get_inventory_session(connection, session_id)
        finally:
            self._close_connection(connection)

    def get_inventory_print_form(self, session_id: int) -> dict[str, Any]:
        connection = self.database.connect()
        try:
            session = self._get_inventory_session(connection, session_id)
            warehouse = dict(self._require(connection, "warehouses", session["warehouse_id"]))
            rows = connection.execute(
                """
                SELECT
                  il.id,
                  il.product_id,
                  il.batch_id,
                  il.expected_quantity,
                  il.actual_quantity,
                  il.difference_quantity,
                  p.name AS product_name,
                  p.sku,
                  p.unit,
                  b.lot,
                  b.expires_on
                FROM inventory_lines il
                JOIN products p ON p.id = il.product_id
                JOIN batches b ON b.id = il.batch_id
                WHERE il.session_id = ?
                ORDER BY p.name, p.sku, b.expires_on, b.id
                """,
                (session_id,),
            ).fetchall()
            lines = [
                {
                    "line_no": index,
                    "product_id": row["product_id"],
                    "product_name": row["product_name"],
                    "sku": row["sku"],
                    "unit": row["unit"],
                    "batch_id": row["batch_id"],
                    "lot": row["lot"],
                    "expires_on": row["expires_on"],
                    "expected_quantity": row["expected_quantity"],
                    "actual_quantity": row["actual_quantity"],
                    "difference_quantity": row["difference_quantity"],
                }
                for index, row in enumerate(rows, start=1)
            ]
            return {
                "session_id": session["id"],
                "warehouse_id": session["warehouse_id"],
                "warehouse_name": warehouse["name"],
                "status": session["status"],
                "started_by": session["started_by"],
                "posted_by": session["posted_by"],
                "started_at": session["started_at"],
                "posted_at": session["posted_at"],
                "summary": session["summary"],
                "count_sheet_csv": self._inventory_print_csv(lines, include_actual=False),
                "reconciliation_csv": self._inventory_print_csv(lines, include_actual=True),
                "lines": lines,
            }
        finally:
            self._close_connection(connection)

    def list_inventory_sessions(
        self, warehouse_id: int | None = None, limit: int = 100, offset: int = 0
    ) -> list[dict[str, Any]]:
        return self._list_table(
            "inventory_sessions",
            "started_at DESC, id DESC",
            limit,
            offset,
            where="warehouse_id = ?",
            params=(warehouse_id,),
        ) if warehouse_id is not None else self._list_table(
            "inventory_sessions", "started_at DESC, id DESC", limit, offset
        )

    def update_inventory_line_count(
        self,
        session_id: int,
        line_id: int,
        data: InventoryLineCountUpdate,
        actor_id: str = "system",
    ) -> dict[str, Any]:
        with self.database.transaction() as connection:
            session = self._get_inventory_session(connection, session_id)
            if session["status"] != InventoryStatus.IN_PROGRESS:
                raise ValidationError(f"Cannot update inventory in status {session['status']}")
            line = self._require(connection, "inventory_lines", line_id)
            if line["session_id"] != session_id:
                raise NotFoundError("Inventory line not found in session")
            difference = data.actual_quantity - Decimal(line["expected_quantity"])
            connection.execute(
                """
                UPDATE inventory_lines
                SET actual_quantity = ?, difference_quantity = ?
                WHERE id = ?
                """,
                (decimal_to_db(data.actual_quantity), decimal_to_db(difference), line_id),
            )
            self._audit(
                connection,
                actor_id,
                AuditAction.UPDATE,
                "inventory_line",
                line_id,
                {"actual_quantity": data.actual_quantity, "difference_quantity": difference},
                warehouse_id=session["warehouse_id"],
            )
            return self._get_inventory_line(connection, line_id)

    def post_inventory_session(
        self, session_id: int, actor_id: str = "system"
    ) -> dict[str, Any]:
        with self.database.transaction() as connection:
            session = self._get_inventory_session(connection, session_id)
            if session["status"] == InventoryStatus.POSTED:
                return session
            if session["status"] != InventoryStatus.IN_PROGRESS:
                raise ValidationError(f"Cannot post inventory in status {session['status']}")
            lines = connection.execute(
                "SELECT * FROM inventory_lines WHERE session_id = ? ORDER BY id",
                (session_id,),
            ).fetchall()
            if not lines:
                raise ValidationError("Inventory session has no lines")
            for line in lines:
                if line["actual_quantity"] is None:
                    raise ValidationError("All inventory lines must have actual quantity")
                balance = self._balance_for_update(
                    connection, line["batch_id"], session["warehouse_id"]
                )
                actual = Decimal(line["actual_quantity"])
                reserved = Decimal(balance["reserved_quantity"])
                if actual < reserved:
                    raise ValidationError("Actual quantity cannot be below reserved quantity")
            for line in lines:
                balance = self._balance_for_update(
                    connection, line["batch_id"], session["warehouse_id"]
                )
                actual = Decimal(line["actual_quantity"])
                expected = Decimal(balance["quantity"])
                difference = actual - expected
                if difference == 0:
                    continue
                connection.execute(
                    """
                    UPDATE stock_balances
                    SET quantity = ?
                    WHERE batch_id = ? AND warehouse_id = ?
                    """,
                    (decimal_to_db(actual), line["batch_id"], session["warehouse_id"]),
                )
                movement_type = MovementType.RECEIPT if difference > 0 else MovementType.WRITE_OFF
                self._movement(
                    connection,
                    movement_type,
                    line["batch_id"],
                    session["warehouse_id"],
                    abs(difference),
                    reason=f"Инвентаризация #{session_id}",
                )
            connection.execute(
                """
                UPDATE inventory_sessions
                SET status = ?, posted_by = ?, posted_at = ?
                WHERE id = ?
                """,
                (InventoryStatus.POSTED, actor_id, now_iso(), session_id),
            )
            connection.execute(
                "UPDATE warehouses SET inventory_lock = 0 WHERE id = ?",
                (session["warehouse_id"],),
            )
            self._audit(
                connection,
                actor_id,
                AuditAction.INVENTORY_POST,
                "inventory_session",
                session_id,
                {"status": InventoryStatus.POSTED},
                warehouse_id=session["warehouse_id"],
            )
            return self._get_inventory_session(connection, session_id)

    def cancel_inventory_session(
        self, session_id: int, actor_id: str = "system"
    ) -> dict[str, Any]:
        with self.database.transaction() as connection:
            session = self._get_inventory_session(connection, session_id)
            if session["status"] in (InventoryStatus.POSTED, InventoryStatus.CANCELLED):
                return session
            connection.execute(
                """
                UPDATE inventory_sessions
                SET status = ?, cancelled_at = ?
                WHERE id = ?
                """,
                (InventoryStatus.CANCELLED, now_iso(), session_id),
            )
            connection.execute(
                "UPDATE warehouses SET inventory_lock = 0 WHERE id = ?",
                (session["warehouse_id"],),
            )
            self._audit(
                connection,
                actor_id,
                AuditAction.INVENTORY_CANCEL,
                "inventory_session",
                session_id,
                {"status": InventoryStatus.CANCELLED},
                warehouse_id=session["warehouse_id"],
            )
            return self._get_inventory_session(connection, session_id)

    def list_balances(
        self,
        product_id: int | None = None,
        warehouse_id: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 500))
        safe_offset = max(0, offset)
        query = """
            SELECT
              b.product_id,
              sb.batch_id,
              sb.warehouse_id,
              sb.quantity AS total_quantity,
              sb.reserved_quantity,
              b.status AS batch_status,
              b.expires_on
            FROM stock_balances sb
            JOIN batches b ON b.id = sb.batch_id
        """
        params: tuple[Any, ...] = ()
        filters: list[str] = []
        if product_id is not None:
            filters.append("b.product_id = ?")
            params = (*params, product_id)
        if warehouse_id is not None:
            filters.append("sb.warehouse_id = ?")
            params = (*params, warehouse_id)
        if filters:
            query += " WHERE " + " AND ".join(filters)
        query += " ORDER BY b.expires_on IS NULL, b.expires_on, sb.batch_id LIMIT ? OFFSET ?"
        params = (*params, safe_limit, safe_offset)
        connection = self.database.connect()
        try:
            rows = connection.execute(query, params).fetchall()
            return [self._balance_payload(row) for row in rows]
        finally:
            self._close_connection(connection)

    def count_balances(
        self, product_id: int | None = None, warehouse_id: int | None = None
    ) -> int:
        query = """
            SELECT COUNT(*) AS total
            FROM stock_balances sb
            JOIN batches b ON b.id = sb.batch_id
        """
        params: tuple[Any, ...] = ()
        filters: list[str] = []
        if product_id is not None:
            filters.append("b.product_id = ?")
            params = (*params, product_id)
        if warehouse_id is not None:
            filters.append("sb.warehouse_id = ?")
            params = (*params, warehouse_id)
        if filters:
            query += " WHERE " + " AND ".join(filters)
        connection = self.database.connect()
        try:
            row = connection.execute(query, params).fetchone()
            return int(row["total"])
        finally:
            self._close_connection(connection)

    def list_stock_movements(
        self,
        batch_id: int | None = None,
        product_id: int | None = None,
        warehouse_id: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 500))
        safe_offset = max(0, offset)
        query = """
            SELECT sm.*
            FROM stock_movements sm
            JOIN batches b ON b.id = sm.batch_id
        """
        filters: list[str] = []
        params: tuple[Any, ...] = ()
        if batch_id is not None:
            filters.append("sm.batch_id = ?")
            params = (*params, batch_id)
        if product_id is not None:
            filters.append("b.product_id = ?")
            params = (*params, product_id)
        if warehouse_id is not None:
            filters.append("sm.warehouse_id = ?")
            params = (*params, warehouse_id)
        if filters:
            query += " WHERE " + " AND ".join(filters)
        query += " ORDER BY sm.created_at DESC, sm.id DESC LIMIT ? OFFSET ?"
        params = (*params, safe_limit, safe_offset)
        connection = self.database.connect()
        try:
            rows = connection.execute(query, params).fetchall()
            movements = [dict(row) for row in rows]
            for movement in movements:
                self._redact_movement_payload(movement)
            return movements
        finally:
            self._close_connection(connection)

    def count_stock_movements(
        self,
        batch_id: int | None = None,
        product_id: int | None = None,
        warehouse_id: int | None = None,
    ) -> int:
        query = """
            SELECT COUNT(*) AS total
            FROM stock_movements sm
            JOIN batches b ON b.id = sm.batch_id
        """
        filters: list[str] = []
        params: tuple[Any, ...] = ()
        if batch_id is not None:
            filters.append("sm.batch_id = ?")
            params = (*params, batch_id)
        if product_id is not None:
            filters.append("b.product_id = ?")
            params = (*params, product_id)
        if warehouse_id is not None:
            filters.append("sm.warehouse_id = ?")
            params = (*params, warehouse_id)
        if filters:
            query += " WHERE " + " AND ".join(filters)
        connection = self.database.connect()
        try:
            row = connection.execute(query, params).fetchone()
            return int(row["total"])
        finally:
            self._close_connection(connection)
