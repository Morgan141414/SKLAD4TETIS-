from __future__ import annotations

import hashlib
import hmac
import json
from datetime import (
    date,
    datetime,
)
from decimal import Decimal
from enum import Enum
from sqlite3 import (
    Connection,
    Row,
)
from typing import Any

from app.core.config import get_settings
from app.domain.enums import (
    AuditAction,
    BatchStatus,
    MovementType,
    QuarantineReviewStatus,
    ReservationStatus,
    StockDocumentStatus,
    StockDocumentType,
)
from app.domain.errors import (
    BatchUnavailableError,
    InsufficientStockError,
    InventoryLockedError,
    NotFoundError,
    ValidationError,
)
from app.domain.schemas import (
    SensorDeviceCreate,
    SensorDeviceUpdate,
    SensorReadingCreate,
    TransferCreate,
)
from app.services.warehouse.base import WarehouseServiceBase
from app.storage.sqlite import (
    decimal_to_db,
    insert_and_get_id,
    now_iso,
)


class LedgerHelpersMixin(WarehouseServiceBase):
    def _create_document(
        self,
        connection: Connection,
        document_type: StockDocumentType,
        warehouse_id: int,
        actor_id: str,
        supplier_id: int | None = None,
        external_ref: str | None = None,
        notes: str | None = None,
    ) -> int:
        if external_ref is not None or notes is not None:
            return insert_and_get_id(
                connection,
                """
                INSERT INTO stock_documents(
                  document_type, status, warehouse_id, supplier_id, created_by, created_at,
                  external_ref, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_type,
                    StockDocumentStatus.DRAFT,
                    warehouse_id,
                    supplier_id,
                    actor_id,
                    now_iso(),
                    external_ref,
                    notes,
                ),
            )
        return insert_and_get_id(
            connection,
            """
            INSERT INTO stock_documents(
              document_type, status, warehouse_id, supplier_id, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                document_type,
                StockDocumentStatus.DRAFT,
                warehouse_id,
                supplier_id,
                actor_id,
                now_iso(),
            ),
        )


    # ── ПКУ pending (двойная подпись) ──────────────────────────────────────────

    def create_pending_controlled_writeoff(
        self,
        batch_id: int,
        warehouse_id: int,
        quantity: Decimal,
        reason: str | None,
        patient_id: str,
        doctor_id: str,
        medical_record_no: str,
        requested_by: str,
    ) -> dict:
        """
        Шаг 1: врач/медсестра подаёт заявку на списание ПКУ.
        Фактического движения нет — ждёт подтверждения second_approver.
        """
        with self.database.transaction() as connection:
            self._ensure_batch_available(connection, batch_id)
            # Validate it's a controlled product
            self._require_controlled_writeoff_metadata(
                connection,
                batch_id=batch_id,
                patient_id=patient_id,
                doctor_id=doctor_id,
                medical_record_no=medical_record_no,
                second_approver_id="__pending__",  # bypass: will be filled on confirm
            )
            balance = self._balance_for_update(connection, batch_id, warehouse_id)
            free = Decimal(str(balance["quantity"])) - Decimal(str(balance["reserved_quantity"]))
            if free < quantity:
                raise InsufficientStockError("Insufficient free stock for controlled write-off")

            # Reserve the quantity while pending
            connection.execute(
                """
                UPDATE stock_balances
                SET reserved_quantity = reserved_quantity + ?
                WHERE batch_id = ? AND warehouse_id = ?
                """,
                (decimal_to_db(quantity), batch_id, warehouse_id),
            )

            row_id = insert_and_get_id(
                connection,
                """
                INSERT INTO pending_controlled_writeoffs(
                    batch_id, warehouse_id, quantity, reason,
                    patient_id, doctor_id, medical_record_no,
                    requested_by, requested_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                """,
                (
                    batch_id,
                    warehouse_id,
                    decimal_to_db(quantity),
                    reason,
                    patient_id,
                    doctor_id,
                    medical_record_no,
                    requested_by,
                    now_iso(),
                ),
            )
            self._audit(
                connection,
                requested_by,
                AuditAction.UPDATE,
                "batch",
                batch_id,
                {
                    "action": "pending_controlled_writeoff_created",
                    "pending_id": row_id,
                    "quantity": str(quantity),
                    "patient_id": patient_id,
                    "doctor_id": doctor_id,
                    "medical_record_no": medical_record_no,
                },
                warehouse_id=warehouse_id,
            )
            # Notify warehouse managers that a new ПКУ request needs approval
            try:
                batch_row = connection.execute(
                    "SELECT b.id, p.name AS product_name FROM batches b JOIN products p ON p.id = b.product_id WHERE b.id = ?",
                    (batch_id,),
                ).fetchone()
                pname = batch_row["product_name"] if batch_row else f"партия #{batch_id}"
                insert_and_get_id(
                    connection,
                    """
                    INSERT INTO notifications(
                        notification_type, product_id, batch_id, warehouse_id,
                        title, message, is_read, created_at
                    ) VALUES ('pku_pending', ?, ?, ?, ?, ?, 0, ?)
                    """,
                    (
                        batch_row["id"] if batch_row else batch_id,
                        batch_id,
                        warehouse_id,
                        f"Заявка на списание ПКУ: {pname}",
                        f"Пациент: {patient_id} | Врач: {doctor_id} | ИБ: {medical_record_no} | Запросил: {requested_by} | Кол-во: {quantity}. Требуется подтверждение второго подписанта.",
                        now_iso(),
                    ),
                )
            except Exception:
                pass  # notification failure must not break the writeoff workflow
        return self.get_pending_controlled_writeoff(row_id)

    def confirm_pending_controlled_writeoff(
        self,
        pending_id: int,
        second_approver_id: str,
        note: str | None,
        actor_id: str,
    ) -> dict:
        """
        Шаг 2: второй подписант (старшая медсестра) подтверждает заявку.
        Выполняет фактическое движение.
        """
        with self.database.transaction() as connection:
            pending = self._get_pending_writeoff(connection, pending_id)
            if pending["status"] != "pending":
                raise ValidationError(f"Cannot confirm writeoff in status '{pending['status']}'")
            if second_approver_id.strip() == pending["doctor_id"].strip():
                raise ValidationError("Second approver must be different from the doctor")
            if second_approver_id.strip() == pending["requested_by"].strip():
                raise ValidationError("Second approver must be different from the requester")

            quantity = Decimal(str(pending["quantity"]))
            batch_id = pending["batch_id"]
            warehouse_id = pending["warehouse_id"]

            # Release the reservation
            connection.execute(
                """
                UPDATE stock_balances
                SET reserved_quantity = GREATEST(0, reserved_quantity - ?)
                WHERE batch_id = ? AND warehouse_id = ?
                """,
                (decimal_to_db(quantity), batch_id, warehouse_id),
            )

            # Perform the actual write-off
            movement_id = self._apply_writeoff_line(
                connection,
                batch_id=batch_id,
                warehouse_id=warehouse_id,
                quantity=quantity,
                reason=pending.get("reason"),
                patient_id=pending["patient_id"],
                doctor_id=pending["doctor_id"],
                medical_record_no=pending["medical_record_no"],
                second_approver_id=second_approver_id,
                second_approval_note=note,
            )

            connection.execute(
                """
                UPDATE pending_controlled_writeoffs
                SET status = 'confirmed',
                    second_approver_id = ?,
                    second_approval_note = ?,
                    second_approved_at = ?,
                    writeoff_movement_id = ?
                WHERE id = ?
                """,
                (second_approver_id, note, now_iso(), movement_id, pending_id),
            )
            self._audit(
                connection,
                actor_id,
                AuditAction.WRITE_OFF,
                "batch",
                batch_id,
                {
                    "action": "pending_controlled_writeoff_confirmed",
                    "pending_id": pending_id,
                    "second_approver_id": second_approver_id,
                    "movement_id": movement_id,
                },
                warehouse_id=warehouse_id,
            )
            # Auto-create reorder if needed
            self._check_and_create_reorder_requests(connection, warehouse_id, [int(batch_id)])
        return self.get_pending_controlled_writeoff(pending_id)

    def reject_pending_controlled_writeoff(
        self,
        pending_id: int,
        rejected_reason: str,
        actor_id: str,
    ) -> dict:
        """Второй подписант отклоняет заявку — снимает резерв."""
        with self.database.transaction() as connection:
            pending = self._get_pending_writeoff(connection, pending_id)
            if pending["status"] != "pending":
                raise ValidationError(f"Cannot reject writeoff in status '{pending['status']}'")

            quantity = Decimal(str(pending["quantity"]))

            # Release reservation
            connection.execute(
                """
                UPDATE stock_balances
                SET reserved_quantity = GREATEST(0, reserved_quantity - ?)
                WHERE batch_id = ? AND warehouse_id = ?
                """,
                (decimal_to_db(quantity), pending["batch_id"], pending["warehouse_id"]),
            )
            connection.execute(
                """
                UPDATE pending_controlled_writeoffs
                SET status = 'rejected', rejected_reason = ?
                WHERE id = ?
                """,
                (rejected_reason, pending_id),
            )
            self._audit(
                connection,
                actor_id,
                AuditAction.UPDATE,
                "batch",
                pending["batch_id"],
                {"action": "pending_controlled_writeoff_rejected", "pending_id": pending_id, "reason": rejected_reason},
                warehouse_id=pending["warehouse_id"],
            )
        return self.get_pending_controlled_writeoff(pending_id)

    def list_pending_controlled_writeoffs(
        self,
        warehouse_id: int | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        connection = self.database.connect()
        try:
            wheres = []
            params: list = []
            if warehouse_id is not None:
                wheres.append("p.warehouse_id = ?")
                params.append(warehouse_id)
            if status:
                wheres.append("p.status = ?")
                params.append(status)
            where_sql = ("WHERE " + " AND ".join(wheres)) if wheres else ""
            rows = connection.execute(
                f"""
                SELECT p.*,
                       pr.name AS product_name, pr.sku,
                       b.lot, b.unit_price,
                       w.name AS warehouse_name
                FROM pending_controlled_writeoffs p
                JOIN batches b ON b.id = p.batch_id
                JOIN products pr ON pr.id = b.product_id
                JOIN warehouses w ON w.id = p.warehouse_id
                {where_sql}
                ORDER BY p.requested_at DESC
                LIMIT ? OFFSET ?
                """,
                params + [limit, offset],
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            self._close_connection(connection)

    def get_pending_controlled_writeoff(self, pending_id: int) -> dict:
        connection = self.database.connect()
        try:
            row = connection.execute(
                """
                SELECT p.*,
                       pr.name AS product_name, pr.sku,
                       b.lot, b.unit_price,
                       w.name AS warehouse_name
                FROM pending_controlled_writeoffs p
                JOIN batches b ON b.id = p.batch_id
                JOIN products pr ON pr.id = b.product_id
                JOIN warehouses w ON w.id = p.warehouse_id
                WHERE p.id = ?
                """,
                (pending_id,),
            ).fetchone()
            if row is None:
                raise NotFoundError(f"pending_controlled_writeoff#{pending_id} not found")
            return dict(row)
        finally:
            self._close_connection(connection)

    def _get_pending_writeoff(self, connection: Connection, pending_id: int) -> Row:
        row = connection.execute(
            "SELECT * FROM pending_controlled_writeoffs WHERE id = ?",
            (pending_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"pending_controlled_writeoff#{pending_id} not found")
        return row

    def _apply_receipt_line(
        self,
        connection: Connection,
        supplier_id: int,
        warehouse_id: int,
        product_id: int,
        quantity: Decimal,
        unit_price: Decimal,
        lot: str,
        serial_number: str | None,
        expires_on: date | None,
        quarantine: bool,
        actor_id: str = "system",
    ) -> int:
        self._ensure_warehouse_open(connection, warehouse_id)
        self._require(connection, "products", product_id)
        self._require(connection, "suppliers", supplier_id)
        status = BatchStatus.QUARANTINE if quarantine else BatchStatus.AVAILABLE
        batch_id = insert_and_get_id(
            connection,
            """
            INSERT INTO batches(
              product_id, supplier_id, received_at, lot, serial_number, expires_on, unit_price, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                product_id,
                supplier_id,
                now_iso(),
                lot,
                serial_number,
                expires_on.isoformat() if expires_on else None,
                decimal_to_db(unit_price),
                status,
            ),
        )
        connection.execute(
            """
            INSERT INTO stock_balances(batch_id, warehouse_id, quantity, reserved_quantity)
            VALUES (?, ?, ?, '0')
            """,
            (batch_id, warehouse_id, decimal_to_db(quantity)),
        )
        self._movement(connection, MovementType.RECEIPT, batch_id, warehouse_id, quantity)
        self._record_supplier_price_history(
            connection,
            supplier_id=supplier_id,
            product_id=product_id,
            batch_id=batch_id,
            lot=lot,
            unit_price=unit_price,
            source="receipt",
        )
        # Auto-flag product label for reprint when price differs from last receipt
        last_price_row = connection.execute(
            """
            SELECT unit_price FROM batches
            WHERE product_id = ? AND id != ?
            ORDER BY id DESC LIMIT 1
            """,
            (product_id, batch_id),
        ).fetchone()
        if last_price_row is not None:
            last_price = Decimal(str(last_price_row["unit_price"]))
            if last_price != unit_price:
                connection.execute(
                    "UPDATE products SET label_needs_reprint = 1 WHERE id = ?",
                    (product_id,),
                )

        if quarantine:
            self._ensure_quarantine_review(
                connection,
                batch_id=batch_id,
                warehouse_id=warehouse_id,
                actor_id=actor_id,
            )
        return batch_id

    def _apply_writeoff_line(
        self,
        connection: Connection,
        batch_id: int,
        warehouse_id: int,
        quantity: Decimal,
        reason: str | None,
        patient_id: str | None = None,
        doctor_id: str | None = None,
        medical_record_no: str | None = None,
        second_approver_id: str | None = None,
        second_approval_note: str | None = None,
    ) -> int:
        self._ensure_warehouse_open(connection, warehouse_id)
        self._ensure_batch_available(connection, batch_id)
        self._require_controlled_writeoff_metadata(
            connection,
            batch_id=batch_id,
            patient_id=patient_id,
            doctor_id=doctor_id,
            medical_record_no=medical_record_no,
            second_approver_id=second_approver_id,
        )
        balance = self._balance_for_update(connection, batch_id, warehouse_id)
        free = Decimal(balance["quantity"]) - Decimal(balance["reserved_quantity"])
        if free < quantity:
            raise InsufficientStockError("Not enough free stock for write-off")
        new_quantity = Decimal(balance["quantity"]) - quantity
        connection.execute(
            "UPDATE stock_balances SET quantity = ? WHERE batch_id = ? AND warehouse_id = ?",
            (decimal_to_db(new_quantity), batch_id, warehouse_id),
        )
        return self._movement(
            connection,
            MovementType.WRITE_OFF,
            batch_id,
            warehouse_id,
            quantity,
            reason=reason,
            patient_id=patient_id,
            doctor_id=doctor_id,
            medical_record_no=medical_record_no,
            second_approver_id=second_approver_id,
            second_approval_note=second_approval_note,
        )

    def _require_controlled_writeoff_metadata(
        self,
        connection: Connection,
        *,
        patient_id: str | None,
        doctor_id: str | None,
        medical_record_no: str | None,
        second_approver_id: str | None = None,
        batch_id: int | None = None,
        product_id: int | None = None,
    ) -> None:
        if product_id is None:
            if batch_id is None:
                raise ValidationError("Batch or product is required for write-off validation")
            row = connection.execute(
                """
                SELECT p.is_controlled
                FROM batches b
                JOIN products p ON p.id = b.product_id
                WHERE b.id = ?
                """,
                (batch_id,),
            ).fetchone()
            if row is None:
                raise NotFoundError(f"batches id={batch_id} not found")
            is_controlled = bool(row["is_controlled"])
        else:
            product = self._require(connection, "products", product_id)
            is_controlled = bool(product["is_controlled"])
        if not is_controlled:
            return
        required_fields = {
            "patient_id": patient_id,
            "doctor_id": doctor_id,
            "medical_record_no": medical_record_no,
            "second_approver_id": second_approver_id,
        }
        missing = [
            field
            for field, value in required_fields.items()
            if value is None or not value.strip()
        ]
        if missing:
            raise ValidationError(
                "Controlled product write-off requires patient_id, doctor_id, medical_record_no, second_approver_id"
            )
        if second_approver_id and doctor_id and second_approver_id.strip() == doctor_id.strip():
            raise ValidationError("Controlled product write-off requires a second approver different from doctor_id")

    def _apply_transfer(self, connection: Connection, data: TransferCreate) -> dict[str, Any]:
        if data.source_warehouse_id == data.target_warehouse_id:
            raise ValidationError("Source and target warehouses must be different")
        self._ensure_warehouse_open(connection, data.source_warehouse_id)
        self._ensure_warehouse_open(connection, data.target_warehouse_id)
        self._ensure_batch_available(connection, data.batch_id)
        source_balance = self._balance_for_update(
            connection, data.batch_id, data.source_warehouse_id
        )
        source_free = Decimal(source_balance["quantity"]) - Decimal(
            source_balance["reserved_quantity"]
        )
        if source_free < data.quantity:
            raise InsufficientStockError("Not enough free stock for transfer")
        source_quantity = Decimal(source_balance["quantity"]) - data.quantity
        connection.execute(
            """
            UPDATE stock_balances
            SET quantity = ?
            WHERE batch_id = ? AND warehouse_id = ?
            """,
            (decimal_to_db(source_quantity), data.batch_id, data.source_warehouse_id),
        )
        lock_clause = " FOR UPDATE" if getattr(connection, "dialect", None) == "postgresql" else ""
        target_balance = connection.execute(
            """
            SELECT * FROM stock_balances
            WHERE batch_id = ? AND warehouse_id = ?
            """ + lock_clause,
            (data.batch_id, data.target_warehouse_id),
        ).fetchone()
        if target_balance is None:
            connection.execute(
                """
                INSERT INTO stock_balances(batch_id, warehouse_id, quantity, reserved_quantity)
                VALUES (?, ?, ?, '0')
                """,
                (data.batch_id, data.target_warehouse_id, decimal_to_db(data.quantity)),
            )
        else:
            target_quantity = Decimal(target_balance["quantity"]) + data.quantity
            connection.execute(
                """
                UPDATE stock_balances
                SET quantity = ?
                WHERE batch_id = ? AND warehouse_id = ?
                """,
                (decimal_to_db(target_quantity), data.batch_id, data.target_warehouse_id),
            )
        out_movement_id = self._movement(
            connection,
            MovementType.TRANSFER_OUT,
            data.batch_id,
            data.source_warehouse_id,
            data.quantity,
            reason=data.reason,
        )
        in_movement_id = self._movement(
            connection,
            MovementType.TRANSFER_IN,
            data.batch_id,
            data.target_warehouse_id,
            data.quantity,
            reason=data.reason,
        )
        return {
            "batch_id": data.batch_id,
            "source_warehouse_id": data.source_warehouse_id,
            "target_warehouse_id": data.target_warehouse_id,
            "quantity": decimal_to_db(data.quantity),
            "out_movement_id": out_movement_id,
            "in_movement_id": in_movement_id,
        }

    def _apply_supplier_return_line(
        self,
        connection: Connection,
        batch_id: int,
        warehouse_id: int,
        supplier_id: int,
        quantity: Decimal,
        reason: str,
    ) -> dict[str, Any]:
        self._ensure_warehouse_open(connection, warehouse_id)
        batch = self._require(connection, "batches", batch_id)
        self._require(connection, "suppliers", supplier_id)
        if batch["supplier_id"] != supplier_id:
            raise ValidationError("Return supplier must match the original batch supplier")
        self._ensure_batch_available(connection, batch_id)
        balance = self._balance_for_update(connection, batch_id, warehouse_id)
        free = Decimal(balance["quantity"]) - Decimal(balance["reserved_quantity"])
        if free < quantity:
            raise InsufficientStockError("Not enough free stock for supplier return")
        new_quantity = Decimal(balance["quantity"]) - quantity
        connection.execute(
            """
            UPDATE stock_balances
            SET quantity = ?
            WHERE batch_id = ? AND warehouse_id = ?
            """,
            (decimal_to_db(new_quantity), batch_id, warehouse_id),
        )
        movement_id = self._movement(
            connection,
            MovementType.RETURN_TO_SUPPLIER,
            batch_id,
            warehouse_id,
            quantity,
            reason=reason,
        )
        return {
            "batch_id": batch_id,
            "warehouse_id": warehouse_id,
            "supplier_id": supplier_id,
            "quantity": decimal_to_db(quantity),
            "movement_id": movement_id,
        }

    def _validate_repack_numbers(
        self,
        *,
        source_quantity: Decimal,
        target_quantity: Decimal,
        conversion_factor: Decimal,
        loss_quantity: Decimal,
    ) -> None:
        if source_quantity <= 0 or target_quantity <= 0:
            raise ValidationError("Repack quantities must be positive")
        if conversion_factor <= 0:
            raise ValidationError("Repack conversion factor must be positive")
        if loss_quantity < 0:
            raise ValidationError("Repack loss quantity cannot be negative")
        if loss_quantity >= source_quantity:
            raise ValidationError("Repack loss quantity must be less than source quantity")
        expected_target = (source_quantity - loss_quantity) * conversion_factor
        if expected_target.quantize(Decimal("0.001")) != target_quantity.quantize(Decimal("0.001")):
            raise ValidationError(
                "Repack target quantity must equal (source quantity - loss) * conversion factor"
            )

    def _apply_repack_line(
        self,
        connection: Connection,
        *,
        document_id: int,
        warehouse_id: int,
        source_batch_id: int,
        target_product_id: int,
        source_quantity: Decimal,
        target_quantity: Decimal,
        conversion_factor: Decimal,
        loss_quantity: Decimal,
        target_unit_price: Decimal | None,
        target_lot: str,
        target_expires_on: date | None,
        quarantine: bool,
        reason: str | None,
        actor_id: str,
    ) -> dict[str, Any]:
        self._validate_repack_numbers(
            source_quantity=source_quantity,
            target_quantity=target_quantity,
            conversion_factor=conversion_factor,
            loss_quantity=loss_quantity,
        )
        self._ensure_warehouse_open(connection, warehouse_id)
        source_batch = self._require(connection, "batches", source_batch_id)
        self._ensure_batch_available(connection, source_batch_id)
        self._require(connection, "products", target_product_id)
        balance = self._balance_for_update(connection, source_batch_id, warehouse_id)
        free = Decimal(balance["quantity"]) - Decimal(balance["reserved_quantity"])
        if free < source_quantity:
            raise InsufficientStockError("Not enough free stock for repack")
        new_source_quantity = Decimal(balance["quantity"]) - source_quantity
        connection.execute(
            """
            UPDATE stock_balances
            SET quantity = ?
            WHERE batch_id = ? AND warehouse_id = ?
            """,
            (decimal_to_db(new_source_quantity), source_batch_id, warehouse_id),
        )
        if target_unit_price is None:
            target_unit_price = (Decimal(source_batch["unit_price"]) * source_quantity / target_quantity).quantize(
                Decimal("0.0001")
            )
        status = BatchStatus.QUARANTINE if quarantine else BatchStatus.AVAILABLE
        target_batch_id = insert_and_get_id(
            connection,
            """
            INSERT INTO batches(
              product_id, supplier_id, received_at, lot, expires_on, unit_price, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                target_product_id,
                source_batch["supplier_id"],
                now_iso(),
                target_lot,
                target_expires_on.isoformat() if target_expires_on else source_batch["expires_on"],
                decimal_to_db(target_unit_price),
                status,
            ),
        )
        connection.execute(
            """
            INSERT INTO stock_balances(batch_id, warehouse_id, quantity, reserved_quantity)
            VALUES (?, ?, ?, '0')
            """,
            (target_batch_id, warehouse_id, decimal_to_db(target_quantity)),
        )
        out_movement_id = self._movement(
            connection,
            MovementType.REPACK_OUT,
            source_batch_id,
            warehouse_id,
            source_quantity,
            reason=reason,
        )
        in_movement_id = self._movement(
            connection,
            MovementType.REPACK_IN,
            target_batch_id,
            warehouse_id,
            target_quantity,
            reason=reason,
        )
        transformation_id = insert_and_get_id(
            connection,
            """
            INSERT INTO batch_transformations(
              document_id, source_batch_id, target_batch_id, warehouse_id,
              source_product_id, target_product_id, source_quantity,
              target_quantity, conversion_factor, loss_quantity,
              reason, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                document_id,
                source_batch_id,
                target_batch_id,
                warehouse_id,
                source_batch["product_id"],
                target_product_id,
                decimal_to_db(source_quantity),
                decimal_to_db(target_quantity),
                decimal_to_db(conversion_factor),
                decimal_to_db(loss_quantity),
                reason,
                actor_id,
                now_iso(),
            ),
        )
        if quarantine:
            self._ensure_quarantine_review(
                connection,
                batch_id=target_batch_id,
                warehouse_id=warehouse_id,
                actor_id=actor_id,
            )
        return {
            "transformation_id": transformation_id,
            "source_batch_id": source_batch_id,
            "target_batch_id": target_batch_id,
            "warehouse_id": warehouse_id,
            "source_quantity": decimal_to_db(source_quantity),
            "target_quantity": decimal_to_db(target_quantity),
            "loss_quantity": decimal_to_db(loss_quantity),
            "out_movement_id": out_movement_id,
            "in_movement_id": in_movement_id,
        }

    def _release_reservation(
        self, connection: Connection, reservation_id: int, actor_id: str
    ) -> dict[str, Any]:
        reservation = self._require(connection, "reservations", reservation_id)
        if reservation["status"] != ReservationStatus.RESERVED:
            return dict(reservation)
        balance = self._balance_for_update(
            connection, reservation["batch_id"], reservation["warehouse_id"]
        )
        reserved = Decimal(balance["reserved_quantity"]) - Decimal(reservation["quantity"])
        if reserved < 0:
            reserved = Decimal(0)
        connection.execute(
            """
            UPDATE stock_balances
            SET reserved_quantity = ?
            WHERE batch_id = ? AND warehouse_id = ?
            """,
            (decimal_to_db(reserved), reservation["batch_id"], reservation["warehouse_id"]),
        )
        connection.execute(
            "UPDATE reservations SET status = ? WHERE id = ?",
            (ReservationStatus.RELEASED, reservation_id),
        )
        self._movement(
            connection,
            MovementType.RELEASE_RESERVE,
            reservation["batch_id"],
            reservation["warehouse_id"],
            Decimal(reservation["quantity"]),
        )
        self._audit(
            connection,
            actor_id,
            AuditAction.RELEASE_RESERVE,
            "reservation",
            reservation_id,
            {"status": ReservationStatus.RELEASED},
            warehouse_id=reservation["warehouse_id"],
        )
        return self._get_by_id(connection, "reservations", reservation_id)

    def _ensure_warehouse_open(self, connection: Connection, warehouse_id: int) -> None:
        warehouse = self._require(connection, "warehouses", warehouse_id)
        if int(warehouse["inventory_lock"]):
            raise InventoryLockedError("Warehouse operations are locked during inventory")

    def _ensure_batch_available(self, connection: Connection, batch_id: int) -> None:
        batch = self._require(connection, "batches", batch_id)
        if batch["status"] != BatchStatus.AVAILABLE:
            raise BatchUnavailableError(f"Batch is not available: {batch['status']}")

    def _balance_for_update(self, connection: Connection, batch_id: int, warehouse_id: int) -> Row:
        lock_clause = " FOR UPDATE" if getattr(connection, "dialect", None) == "postgresql" else ""
        row = connection.execute(
            """
            SELECT * FROM stock_balances
            WHERE batch_id = ? AND warehouse_id = ?
            """ + lock_clause,
            (batch_id, warehouse_id),
        ).fetchone()
        if row is None:
            raise NotFoundError("Stock balance not found")
        return row

    def _batch_warehouse_ids(self, connection: Connection, batch_id: int) -> list[int]:
        rows = connection.execute(
            """
            SELECT warehouse_id FROM stock_balances
            WHERE batch_id = ?
            ORDER BY warehouse_id
            """,
            (batch_id,),
        ).fetchall()
        return [int(row["warehouse_id"]) for row in rows]

    def _batch_balances(self, connection: Connection, batch_id: int) -> list[dict[str, Any]]:
        rows = connection.execute(
            """
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
            WHERE sb.batch_id = ?
            ORDER BY sb.warehouse_id
            """,
            (batch_id,),
        ).fetchall()
        return [self._balance_payload(row) for row in rows]

    def _batch_movements(
        self,
        connection: Connection,
        batch_id: int,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 500))
        safe_offset = max(0, offset)
        rows = connection.execute(
            """
            SELECT *
            FROM stock_movements
            WHERE batch_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            (batch_id, safe_limit, safe_offset),
        ).fetchall()
        movements = [dict(row) for row in rows]
        for movement in movements:
            self._redact_movement_payload(movement)
        return movements

    def _batch_transformations(
        self,
        connection: Connection,
        *,
        warehouse_id: int | None = None,
        batch_id: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 500))
        safe_offset = max(0, offset)
        query = """
            SELECT
              bt.*,
              sp.name AS source_product_name,
              tp.name AS target_product_name,
              sb.lot AS source_lot,
              tb.lot AS target_lot
            FROM batch_transformations bt
            JOIN products sp ON sp.id = bt.source_product_id
            JOIN products tp ON tp.id = bt.target_product_id
            JOIN batches sb ON sb.id = bt.source_batch_id
            JOIN batches tb ON tb.id = bt.target_batch_id
        """
        filters: list[str] = []
        params: tuple[Any, ...] = ()
        if warehouse_id is not None:
            filters.append("bt.warehouse_id = ?")
            params = (*params, warehouse_id)
        if batch_id is not None:
            filters.append("(bt.source_batch_id = ? OR bt.target_batch_id = ?)")
            params = (*params, batch_id, batch_id)
        if filters:
            query += " WHERE " + " AND ".join(filters)
        query += " ORDER BY bt.created_at DESC, bt.id DESC LIMIT ? OFFSET ?"
        rows = connection.execute(query, (*params, safe_limit, safe_offset)).fetchall()
        return [dict(row) for row in rows]

    def _batch_recalls(
        self,
        connection: Connection,
        *,
        batch_id: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 500))
        safe_offset = max(0, offset)
        query = """
            SELECT
              br.*,
              p.name AS product_name,
              b.lot
            FROM batch_recalls br
            JOIN products p ON p.id = br.product_id
            JOIN batches b ON b.id = br.batch_id
        """
        params: tuple[Any, ...] = ()
        if batch_id is not None:
            query += " WHERE br.batch_id = ?"
            params = (batch_id,)
        query += " ORDER BY br.created_at DESC, br.id DESC LIMIT ? OFFSET ?"
        rows = connection.execute(query, (*params, safe_limit, safe_offset)).fetchall()
        return [dict(row) for row in rows]

    def _get_batch_recall(self, connection: Connection, recall_id: int) -> dict[str, Any]:
        rows = self._batch_recalls(connection, limit=1_000)
        for row in rows:
            if int(row["id"]) == int(recall_id):
                return row
        raise NotFoundError(f"batch_recalls#{recall_id} not found")

    def _ensure_recall_notification(
        self,
        connection: Connection,
        *,
        batch_id: int,
        product_id: int,
        warehouse_id: int,
        lot: str,
        reason: str,
        free_quantity: Decimal,
    ) -> dict[str, Any]:
        existing = connection.execute(
            """
            SELECT id FROM notifications
            WHERE notification_type = 'recall'
              AND batch_id = ?
              AND warehouse_id = ?
              AND is_read = 0
            """,
            (batch_id, warehouse_id),
        ).fetchone()
        if existing:
            return self._get_by_id(connection, "notifications", existing["id"])
        title = f"Отозвана партия #{batch_id}"
        message = (
            f"Партия серия {lot} заблокирована из-за отзыва. "
            f"Свободный остаток на складе: {free_quantity}. Причина: {reason}"
        )
        notification_id = insert_and_get_id(
            connection,
            """
            INSERT INTO notifications(
              notification_type, product_id, batch_id, warehouse_id, title, message, created_at
            ) VALUES ('recall', ?, ?, ?, ?, ?, ?)
            """,
            (product_id, batch_id, warehouse_id, title, message, now_iso()),
        )
        return self._get_by_id(connection, "notifications", notification_id)

    def _movement(
        self,
        connection: Connection,
        movement_type: MovementType,
        batch_id: int,
        warehouse_id: int,
        quantity: Decimal,
        reason: str | None = None,
        patient_id: str | None = None,
        doctor_id: str | None = None,
        medical_record_no: str | None = None,
        second_approver_id: str | None = None,
        second_approval_note: str | None = None,
    ) -> int:
        return insert_and_get_id(
            connection,
            """
            INSERT INTO stock_movements(
              movement_type, batch_id, warehouse_id, quantity, reason,
              patient_id, doctor_id, medical_record_no,
              second_approver_id, second_approval_note, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                movement_type,
                batch_id,
                warehouse_id,
                decimal_to_db(quantity),
                reason,
                patient_id,
                doctor_id,
                medical_record_no,
                second_approver_id,
                second_approval_note,
                now_iso(),
            ),
        )

    def _audit(
        self,
        connection: Connection,
        actor_id: str,
        action: AuditAction,
        entity_type: str,
        entity_id: int,
        payload: Any,
        warehouse_id: int | None = None,
    ) -> None:
        from app.core.request_context import get_ip_address, get_request_id, get_user_agent
        if hasattr(payload, "model_dump"):
            payload = payload.model_dump(mode="json")
        payload = self._json_payload(payload)
        if warehouse_id is None:
            warehouse_id = self._audit_warehouse_id(payload)
        request_id = get_request_id() or None
        ip_address = get_ip_address() or None
        user_agent = get_user_agent() or None
        connection.execute(
            """
            INSERT INTO audit_log(
              actor_id, action, entity_type, entity_id, warehouse_id, payload, created_at,
              request_id, ip_address, user_agent
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                actor_id,
                action,
                entity_type,
                str(entity_id),
                warehouse_id,
                json.dumps(payload),
                now_iso(),
                request_id,
                ip_address,
                user_agent,
            ),
        )

    def _audit_warehouse_id(self, payload: Any) -> int | None:
        if not isinstance(payload, dict):
            return None
        for key in ("warehouse_id", "source_warehouse_id", "target_warehouse_id"):
            value = payload.get(key)
            if isinstance(value, int):
                return value
        return None

    def _redact_audit_payload(self, payload: Any) -> Any:
        sensitive_keys = {"patient_id", "doctor_id", "medical_record_no", "second_approval_note"}
        if isinstance(payload, dict):
            return {
                key: "***" if key in sensitive_keys and value is not None else self._redact_audit_payload(value)
                for key, value in payload.items()
            }
        if isinstance(payload, list):
            return [self._redact_audit_payload(value) for value in payload]
        return payload

    def _redact_movement_payload(self, movement: dict[str, Any]) -> None:
        for key in ("patient_id", "doctor_id", "medical_record_no", "second_approval_note"):
            if movement.get(key) is not None:
                movement[key] = "***"

    def _product_label_zpl(self, name: str, sku: str, barcode: str, symbology: str = "CODE128") -> str:
        safe_name = self._zpl_text(name)[:42]
        safe_sku = self._zpl_text(sku)[:36]
        safe_barcode = self._zpl_barcode(barcode)
        barcode_command = "^BEN,92,Y,N" if symbology == "EAN13" else "^BCN,92,Y,N,N"
        return (
            "^XA\n"
            "^CI28\n"
            "^PW560\n"
            "^LL320\n"
            "^FO28,28^A0N,32,32^FD" + safe_name + "^FS\n"
            "^FO28,70^A0N,24,24^FDSKU: " + safe_sku + "^FS\n"
            "^FO28,112^BY2,2,92" + barcode_command + "^FD" + safe_barcode + "^FS\n"
            "^XZ"
        )

    def _product_label_epl(self, name: str, sku: str, barcode: str, symbology: str = "CODE128") -> str:
        safe_name = self._epl_text(name)[:38]
        safe_sku = self._epl_text(sku)[:34]
        safe_barcode = self._zpl_barcode(barcode)
        barcode_type = "E30" if symbology == "EAN13" else "1"
        return (
            "N\n"
            "q560\n"
            "Q320,24\n"
            f'A28,28,0,3,1,1,N,"{safe_name}"\n'
            f'A28,70,0,2,1,1,N,"SKU: {safe_sku}"\n'
            f'B28,112,0,{barcode_type},2,4,92,B,"{safe_barcode}"\n'
            "P1\n"
        )

    def _price_label_zpl(
        self,
        name: str,
        sku: str,
        lot: str,
        serial_number: str | None,
        expires_on: Any,
        unit_price: Decimal,
        barcode: str,
        symbology: str,
    ) -> str:
        safe_name = self._zpl_text(name)[:42]
        safe_sku = self._zpl_text(sku)[:36]
        safe_lot = self._zpl_text(lot)[:32]
        safe_serial = self._zpl_text(serial_number or "—")[:32]
        safe_expiry = self._zpl_text(expires_on or "без срока")[:24]
        safe_price = self._zpl_text(self._report_decimal(unit_price))[:24]
        safe_barcode = self._zpl_barcode(barcode)
        barcode_command = "^BEN,76,Y,N" if symbology == "EAN13" else "^BCN,76,Y,N,N"
        return (
            "^XA\n"
            "^CI28\n"
            "^PW560\n"
            "^LL390\n"
            "^FO28,24^A0N,32,32^FD" + safe_name + "^FS\n"
            "^FO28,64^A0N,22,22^FDSKU: " + safe_sku + "^FS\n"
            "^FO28,94^A0N,22,22^FDСерия: " + safe_lot + "^FS\n"
            "^FO28,124^A0N,22,22^FDСерийный: " + safe_serial + "^FS\n"
            "^FO28,154^A0N,22,22^FDГоден до: " + safe_expiry + "^FS\n"
            "^FO28,188^A0N,34,34^FDЦена: " + safe_price + "^FS\n"
            "^FO28,248^BY2,2,76" + barcode_command + "^FD" + safe_barcode + "^FS\n"
            "^XZ"
        )

    def _price_label_epl(
        self,
        name: str,
        sku: str,
        lot: str,
        serial_number: str | None,
        expires_on: Any,
        unit_price: Decimal,
        barcode: str,
        symbology: str,
    ) -> str:
        safe_name = self._epl_text(name)[:38]
        safe_sku = self._epl_text(sku)[:34]
        safe_lot = self._epl_text(lot)[:30]
        safe_serial = self._epl_text(serial_number or "—")[:30]
        safe_expiry = self._epl_text(expires_on or "без срока")[:24]
        safe_price = self._epl_text(self._report_decimal(unit_price))[:24]
        safe_barcode = self._zpl_barcode(barcode)
        barcode_type = "E30" if symbology == "EAN13" else "1"
        return (
            "N\n"
            "q560\n"
            "Q360,24\n"
            f'A28,24,0,3,1,1,N,"{safe_name}"\n'
            f'A28,64,0,2,1,1,N,"SKU: {safe_sku}"\n'
            f'A28,94,0,2,1,1,N,"Серия: {safe_lot}"\n'
            f'A28,124,0,2,1,1,N,"Серийный: {safe_serial}"\n'
            f'A28,154,0,2,1,1,N,"Годен до: {safe_expiry}"\n'
            f'A28,188,0,3,1,1,N,"Цена: {safe_price}"\n'
            f'B28,248,0,{barcode_type},2,4,76,B,"{safe_barcode}"\n'
            "P1\n"
        )

    def _build_product_barcode_label(
        self, connection: Connection, product_id: int, symbology: str = "code128"
    ) -> dict[str, Any]:
        product = dict(self._require(connection, "products", product_id))
        normalized_symbology = self._normalize_label_symbology(symbology)
        barcode = self._label_barcode(product.get("barcode"), product_id, normalized_symbology)
        label_text = f"{product['name']} | {product['sku']}"
        return {
            "product_id": product_id,
            "name": product["name"],
            "sku": product["sku"],
            "barcode": barcode,
            "symbology": normalized_symbology,
            "label_text": label_text,
            "zpl": self._product_label_zpl(product["name"], product["sku"], barcode, normalized_symbology),
            "epl": self._product_label_epl(product["name"], product["sku"], barcode, normalized_symbology),
            "svg": self._generate_svg_barcode(barcode, normalized_symbology),
            "label_needs_reprint": bool(product.get("label_needs_reprint", False)),
        }

    def _build_batch_price_label(
        self, connection: Connection, batch_id: int, symbology: str = "code128"
    ) -> dict[str, Any]:
        row = connection.execute(
            """
            SELECT
              b.id AS batch_id,
              b.product_id,
              b.lot,
              b.serial_number,
              b.expires_on,
              b.unit_price,
              p.name,
              p.sku,
              p.barcode
            FROM batches b
            JOIN products p ON p.id = b.product_id
            WHERE b.id = ?
            """,
            (batch_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"batches#{batch_id} not found")
        item = dict(row)
        normalized_symbology = self._normalize_label_symbology(symbology)
        barcode = self._label_barcode(item.get("barcode"), item["product_id"], normalized_symbology)
        unit_price = Decimal(str(item["unit_price"]))
        label_text = f"{item['name']} | {item['sku']} | {self._report_decimal(unit_price)}"
        if item.get("serial_number"):
            label_text += f" | serial {item['serial_number']}"
        return {
            "batch_id": batch_id,
            "product_id": item["product_id"],
            "name": item["name"],
            "sku": item["sku"],
            "lot": item["lot"],
            "serial_number": item.get("serial_number"),
            "expires_on": item["expires_on"],
            "unit_price": unit_price,
            "barcode": barcode,
            "symbology": normalized_symbology,
            "label_text": label_text,
            "zpl": self._price_label_zpl(
                item["name"], item["sku"], item["lot"], item.get("serial_number"), item["expires_on"], unit_price, barcode, normalized_symbology
            ),
            "epl": self._price_label_epl(
                item["name"], item["sku"], item["lot"], item.get("serial_number"), item["expires_on"], unit_price, barcode, normalized_symbology
            ),
            "svg": self._generate_svg_barcode(barcode, normalized_symbology),
        }

    def _record_supplier_price_history(
        self,
        connection: Connection,
        supplier_id: int,
        product_id: int,
        batch_id: int | None,
        lot: str | None,
        unit_price: Decimal,
        source: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO supplier_price_history(
              supplier_id, product_id, batch_id, lot, unit_price, source, recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                supplier_id,
                product_id,
                batch_id,
                lot,
                decimal_to_db(unit_price),
                source,
                now_iso(),
            ),
        )


    def mark_product_reprinted(self, product_id: int) -> dict:
        with self.database.transaction() as connection:
            row = self._require(connection, "products", product_id)
            connection.execute(
                "UPDATE products SET label_needs_reprint = ? WHERE id = ?",
                (False, product_id),
            )
            return dict(row)

    def create_supplier_review(self, supplier_id: int, rating: int, comment: str | None, reviewer_id: str) -> dict:
        if not 1 <= rating <= 5:
            raise ValidationError("Rating must be between 1 and 5")
        with self.database.transaction() as connection:
            self._require(connection, "suppliers", supplier_id)
            row = connection.execute(
                """INSERT INTO supplier_reviews(supplier_id, rating, comment, reviewer_id, status, created_at)
                   VALUES (?, ?, ?, ?, 'pending', ?)
                   RETURNING *""",
                (supplier_id, rating, comment, reviewer_id, now_iso()),
            ).fetchone()
            return dict(row)

    def list_supplier_reviews(self, supplier_id: int, status: str | None = None) -> list[dict]:
        connection = self.database.connect()
        try:
            q = "SELECT * FROM supplier_reviews WHERE supplier_id = ?"
            params: list = [supplier_id]
            if status:
                q += " AND status = ?"
                params.append(status)
            q += " ORDER BY created_at DESC"
            rows = connection.execute(q, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            self._close_connection(connection)

    def moderate_supplier_review(self, review_id: int, action: str) -> dict:
        if action not in ("approve", "reject"):
            raise ValidationError("action must be approve or reject")
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM supplier_reviews WHERE id = ?", (review_id,)
            ).fetchone()
            if not row:
                raise NotFoundError(f"supplier_reviews#{review_id} not found")
            new_status = "approved" if action == "approve" else "rejected"
            connection.execute(
                "UPDATE supplier_reviews SET status = ? WHERE id = ?",
                (new_status, review_id),
            )
            # Recompute average rating from approved reviews
            if action == "approve":
                avg_row = connection.execute(
                    "SELECT ROUND(AVG(rating)) AS avg_rating FROM supplier_reviews WHERE supplier_id = ? AND status = 'approved'",
                    (row["supplier_id"],),
                ).fetchone()
                if avg_row and avg_row["avg_rating"] is not None:
                    new_rating = int(avg_row["avg_rating"])
                    connection.execute(
                        "UPDATE suppliers SET rating = ? WHERE id = ?",
                        (new_rating, row["supplier_id"]),
                    )
            updated = connection.execute(
                "SELECT * FROM supplier_reviews WHERE id = ?", (review_id,)
            ).fetchone()
            return dict(updated)

    def reply_to_review(self, review_id: int, supplier_id: int, reply_text: str) -> dict:
        if not reply_text or not reply_text.strip():
            raise ValidationError("reply_text cannot be empty")
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM supplier_reviews WHERE id = ? AND supplier_id = ?",
                (review_id, supplier_id),
            ).fetchone()
            if not row:
                raise NotFoundError(f"supplier_reviews#{review_id} not found for this supplier")
            if row["status"] != "approved":
                raise ValidationError("Can only reply to approved reviews")
            connection.execute(
                "UPDATE supplier_reviews SET supplier_reply = ?, replied_at = ? WHERE id = ?",
                (reply_text.strip(), now_iso(), review_id),
            )
            updated = connection.execute(
                "SELECT * FROM supplier_reviews WHERE id = ?", (review_id,)
            ).fetchone()
            return dict(updated)

    def list_supplier_orders(
        self,
        supplier_id: int,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Completed/ordered inquiries for supplier — their order history."""
        connection = self.database.connect()
        try:
            where = ["mi.supplier_id = ?"]
            params: list = [supplier_id]
            if status:
                where.append("mi.status = ?")
                params.append(status)
            else:
                where.append("mi.status IN ('ordered', 'closed')")
            where_clause = "WHERE " + " AND ".join(where)
            total_row = connection.execute(
                f"SELECT COUNT(*) AS n FROM marketplace_inquiries mi {where_clause}", params
            ).fetchone()
            rows = connection.execute(
                f"""SELECT mi.*, ci.product_name, ci.sku, ci.unit,
                           s.name AS supplier_name,
                           w.name AS warehouse_name,
                           COALESCE(mi.quantity * mi.unit_price, 0) AS total_amount
                    FROM marketplace_inquiries mi
                    JOIN supplier_catalog_items ci ON ci.id = mi.catalog_item_id
                    JOIN suppliers s ON s.id = mi.supplier_id
                    LEFT JOIN warehouses w ON w.id = mi.warehouse_id
                    {where_clause}
                    ORDER BY mi.created_at DESC
                    LIMIT ? OFFSET ?""",
                params + [limit, offset],
            ).fetchall()
            items = [dict(r) for r in rows]
            return {"items": items, "total": total_row["n"] if total_row else 0}
        finally:
            self._close_connection(connection)

    def bulk_update_catalog_prices(
        self,
        supplier_id: int,
        item_ids: list[int] | None,
        percent_change: float,
    ) -> dict[str, Any]:
        """Apply a percentage price change to selected (or all) catalog items."""
        if not -99 < percent_change < 1000:
            raise ValidationError("percent_change must be between -99 and 1000")
        multiplier = 1 + percent_change / 100
        with self.database.transaction() as connection:
            if item_ids:
                placeholders = ",".join("?" * len(item_ids))
                connection.execute(
                    f"""UPDATE supplier_catalog_items
                        SET unit_price = ROUND(unit_price * ?, 2), updated_at = ?
                        WHERE supplier_id = ? AND id IN ({placeholders})""",
                    [multiplier, now_iso(), supplier_id] + list(item_ids),
                )
                updated_count = len(item_ids)
            else:
                result = connection.execute(
                    """UPDATE supplier_catalog_items
                       SET unit_price = ROUND(unit_price * ?, 2), updated_at = ?
                       WHERE supplier_id = ?""",
                    (multiplier, now_iso(), supplier_id),
                )
                updated_count = result.rowcount if hasattr(result, "rowcount") else 0
            updated_rows = connection.execute(
                "SELECT id, product_name, unit_price FROM supplier_catalog_items WHERE supplier_id = ? ORDER BY updated_at DESC",
                (supplier_id,),
            ).fetchall()
            return {"updated": updated_count, "items": [dict(r) for r in updated_rows]}

    def compare_catalog_items(self, item_ids: list[int]) -> list[dict[str, Any]]:
        """Fetch multiple catalog items with supplier info for side-by-side comparison."""
        if not item_ids or len(item_ids) > 6:
            raise ValidationError("Provide 1–6 item IDs to compare")
        connection = self.database.connect()
        try:
            placeholders = ",".join("?" * len(item_ids))
            rows = connection.execute(
                f"""SELECT ci.*, s.name AS supplier_name, s.city AS supplier_city,
                           s.rating AS supplier_rating, s.delivery_days AS supplier_delivery_days,
                           s.is_preferred AS supplier_is_preferred
                    FROM supplier_catalog_items ci
                    JOIN suppliers s ON s.id = ci.supplier_id
                    WHERE ci.id IN ({placeholders}) AND ci.is_active = TRUE
                    ORDER BY ci.unit_price ASC""",
                item_ids,
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            self._close_connection(connection)

    def _generate_svg_barcode(self, barcode_value: str, symbology: str) -> str:
        try:
            import io

            import barcode as bc
            from barcode.writer import SVGWriter
            bc_class = bc.get_barcode_class("code128" if symbology == "CODE128" else "ean13")
            writer = SVGWriter()
            code = bc_class(barcode_value, writer=writer)
            buf = io.BytesIO()
            code.write(buf)
            return buf.getvalue().decode("utf-8")
        except Exception:
            return ""

    def _normalize_label_symbology(self, symbology: str) -> str:
        value = str(symbology or "code128").strip().lower().replace("-", "")
        if value in {"code128", "code"}:
            return "CODE128"
        if value in {"ean13", "ean"}:
            return "EAN13"
        raise ValidationError("Unsupported label symbology")

    def _label_barcode(self, raw_barcode: Any, entity_id: int, symbology: str) -> str:
        if symbology == "EAN13":
            return self._ean13_barcode(raw_barcode, entity_id)
        barcode = (str(raw_barcode or "").strip() or f"SKLAD-{int(entity_id):08d}").strip()
        return self._zpl_barcode(barcode)

    def _ean13_barcode(self, raw_barcode: Any, entity_id: int) -> str:
        digits = "".join(char for char in str(raw_barcode or "") if char.isdigit())
        if len(digits) == 13 and self._ean13_check_digit(digits[:12]) == int(digits[-1]):
            return digits
        if len(digits) == 12:
            return digits + str(self._ean13_check_digit(digits))
        base = f"20{int(entity_id):010d}"[-12:]
        return base + str(self._ean13_check_digit(base))

    def _ean13_check_digit(self, first_12_digits: str) -> int:
        if len(first_12_digits) != 12 or not first_12_digits.isdigit():
            raise ValidationError("EAN-13 requires 12 numeric digits before checksum")
        total = 0
        for index, char in enumerate(first_12_digits):
            digit = int(char)
            total += digit if index % 2 == 0 else digit * 3
        return (10 - (total % 10)) % 10

    def _csv_cell(self, value: Any) -> str:
        text = str(value)
        if any(char in text for char in ('"', ";", "\n", "\r")):
            return '"' + text.replace('"', '""') + '"'
        return text

    def _epl_text(self, value: Any) -> str:
        return (
            str(value)
            .replace('"', "'")
            .replace("\n", " ")
            .replace("\r", " ")
            .strip()
        )

    def _zpl_text(self, value: str) -> str:
        return str(value).replace("^", " ").replace("~", " ").replace("\n", " ").strip()

    def _zpl_barcode(self, value: str) -> str:
        cleaned = self._zpl_text(value).replace(" ", "")
        if not cleaned:
            raise ValidationError("Barcode value cannot be empty")
        return cleaned[:64]

    def _json_payload(self, payload: Any) -> Any:
        if hasattr(payload, "model_dump"):
            return payload.model_dump(mode="json")
        if isinstance(payload, Decimal):
            return str(payload)
        if isinstance(payload, (date, datetime)):
            return payload.isoformat()
        if isinstance(payload, Enum):
            return payload.value
        if isinstance(payload, dict):
            return {key: self._json_payload(value) for key, value in payload.items()}
        if isinstance(payload, list):
            return [self._json_payload(value) for value in payload]
        return payload

    def _order_list_row(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "number": row["order_number"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row.get("updated_at"),
            "total_amount": float(row["total_amount"]) if row.get("total_amount") is not None else None,
            "currency": row.get("currency") or "KZT",
            "items_count": int(row.get("items_count") or 0),
            "supplier_id": row.get("supplier_id"),
            "supplier_name": row.get("supplier_name"),
            "product_name": row.get("product_name"),
            "payment_status": row.get("payment_status") or ("paid" if row.get("status") == "paid" else "unpaid"),
            "delivery_status": self._delivery_status_for_order(row.get("status")),
        }

    def _delivery_status_for_order(self, status_value: Any) -> str:
        status_text = str(status_value or "")
        if status_text in {"delivered", "completed"}:
            return "delivered"
        if status_text == "shipped":
            return "in_transit"
        if status_text in {"accepted", "preparing"}:
            return "preparing"
        return "not_started"

    def _get_marketplace_order_for_actor_conn(
        self, connection: Connection, actor_id: str, order_id: int
    ) -> dict[str, Any]:
        row = connection.execute(
            """SELECT mo.*, s.name AS supplier_name
               FROM marketplace_orders mo
               JOIN suppliers s ON s.id = mo.supplier_id
               WHERE mo.id = ? AND mo.actor_id = ?""",
            (order_id, actor_id),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"marketplace order {order_id} not found")
        return dict(row)

    def _get_marketplace_order_for_actor(self, actor_id: str, order_id: int) -> dict[str, Any]:
        connection = self.database.connect()
        try:
            return self._get_marketplace_order_for_actor_conn(connection, actor_id, order_id)
        finally:
            self._close_connection(connection)

    def _get_marketplace_order_for_supplier(self, supplier_id: int, order_id: int) -> dict[str, Any]:
        connection = self.database.connect()
        try:
            row = connection.execute(
                """SELECT mo.*, s.name AS supplier_name
                   FROM marketplace_orders mo
                   JOIN suppliers s ON s.id = mo.supplier_id
                   WHERE mo.id = ? AND mo.supplier_id = ?""",
                (order_id, supplier_id),
            ).fetchone()
            if row is None:
                raise NotFoundError(f"marketplace order {order_id} not found")
            return dict(row)
        finally:
            self._close_connection(connection)

    def _marketplace_order_detail(self, order: dict[str, Any]) -> dict[str, Any]:
        connection = self.database.connect()
        try:
            items = connection.execute(
                """SELECT oi.id, oi.catalog_item_id, oi.product_id, oi.product_name, oi.sku, oi.unit,
                          oi.quantity, oi.unit_price, oi.line_total,
                          sci.image_url AS image_url
                   FROM marketplace_order_items oi
                   LEFT JOIN supplier_catalog_items sci ON sci.id = oi.catalog_item_id
                   WHERE oi.order_id = ?
                   ORDER BY oi.id""",
                (order["id"],),
            ).fetchall()
            payment = connection.execute(
                """SELECT id, provider, status, amount, currency, payment_url, created_at, updated_at
                   FROM marketplace_payments
                   WHERE order_id = ?
                   ORDER BY created_at DESC, id DESC
                   LIMIT 1""",
                (order["id"],),
            ).fetchone()
            detail = self._order_list_row({
                **order,
                "items_count": len(items),
                "product_name": items[0]["product_name"] if items else None,
                "payment_status": payment["status"] if payment else order.get("payment_status"),
            })
            detail.update(
                {
                    "buyer_name": order.get("buyer_name"),
                    "buyer_phone": order.get("buyer_phone"),
                    "buyer_email": order.get("buyer_email"),
                    "delivery_address": order.get("delivery_address"),
                    "notes": order.get("notes"),
                    "items": [
                        {
                            "id": row["id"],
                            "catalog_item_id": row["catalog_item_id"],
                            "product_id": row["product_id"],
                            "product_name": row["product_name"],
                            "sku": row["sku"],
                            "quantity": float(row["quantity"]),
                            "unit": row["unit"],
                            "unit_price": float(row["unit_price"]) if row["unit_price"] is not None else None,
                            "line_total": float(row["line_total"]) if row["line_total"] is not None else None,
                            "image_url": row["image_url"],
                        }
                        for row in items
                    ],
                    "latest_payment": dict(payment) if payment else None,
                    "timeline": self._marketplace_order_timeline(order, payment),
                }
            )
            return detail
        finally:
            self._close_connection(connection)

    def _marketplace_order_timeline(self, order: dict[str, Any], payment: Row | None) -> list[dict[str, Any]]:
        timeline = [
            {
                "id": "created",
                "title": "Заказ создан",
                "description": "Заказ сформирован из корзины.",
                "created_at": order["created_at"],
                "status": "draft",
            }
        ]
        if payment:
            timeline.append(
                {
                    "id": f"payment-{payment['id']}",
                    "title": "Оплата подтверждена" if payment["status"] == "paid" else "Платеж создан",
                    "description": "Статус поступает от платежного провайдера.",
                    "created_at": payment["updated_at"] or payment["created_at"],
                    "status": order["status"],
                }
            )
        milestones = [
            ("paid", "paid_at", "Заказ оплачен", "Деньги зафиксированы в платежном контуре marqet.kz."),
            ("accepted", "accepted_at", "Продавец принял заказ", "Заказ принят продавцом в работу."),
            ("shipped", "shipped_at", "Заказ отправлен", "Заказ передан в доставку или покупателю."),
            ("delivered", "delivered_at", "Заказ доставлен", "Покупатель получил заказ."),
            ("completed", "completed_at", "Заказ завершен", "Средства доступны продавцу после завершения заказа."),
            ("cancelled", "cancelled_at", "Заказ отменен", order.get("cancel_reason") or "Заказ отменен."),
        ]
        seen = {item["id"] for item in timeline}
        for status, column, title, description in milestones:
            created_at = order.get(column)
            if created_at and status not in seen:
                timeline.append(
                    {
                        "id": status,
                        "title": title,
                        "description": description,
                        "created_at": created_at,
                        "status": status,
                    }
                )
                seen.add(status)
        if order.get("status") in {"refund_requested", "refunded"} and "refund" not in seen:
            timeline.append(
                {
                    "id": "refund",
                    "title": "Запрошен возврат" if order.get("status") == "refund_requested" else "Возврат оформлен",
                    "description": order.get("cancel_reason") or "Запрос на возврат передан в обработку.",
                    "created_at": order.get("updated_at") or order["created_at"],
                    "status": order.get("status"),
                }
            )
        timeline.sort(key=lambda item: str(item.get("created_at") or ""))
        return timeline

    def _payment_method_public(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "provider": row.get("provider"),
            "brand": row.get("brand") or "unknown",
            "last4": row.get("last4"),
            "expiry_month": row.get("expiry_month"),
            "expiry_year": row.get("expiry_year"),
            "holder_name": row.get("holder_name"),
            "is_default": bool(row.get("is_default")),
            "status": row.get("status") or "active",
        }

    @staticmethod
    def _marketplace_payment_token_fingerprint(provider: str, provider_token: str) -> str:
        settings = get_settings()
        secret = settings.marketplace_payment_token_secret
        if not secret:
            if settings.deployment_mode == "production":
                raise ValidationError("Payment token fingerprint secret is not configured")
            secret = (
                settings.jwt_hmac_secret
                or settings.marketplace_payment_webhook_secret
                or "sklad-demo-payment-token-secret"
            )
        payload = f"{provider.strip().lower()}:{provider_token.strip()}".encode()
        digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
        return f"hmac-sha256:{digest}"

    def _mark_marketplace_order_paid(
        self, connection: Connection, order_id: int, payment_id: int
    ) -> None:
        payment = connection.execute(
            "SELECT * FROM marketplace_payments WHERE id = ?",
            (payment_id,),
        ).fetchone()
        if payment is None:
            raise NotFoundError(f"payment {payment_id} not found")
        order = connection.execute(
            "SELECT * FROM marketplace_orders WHERE id = ?",
            (order_id,),
        ).fetchone()
        if order is None:
            raise NotFoundError(f"marketplace order {order_id} not found")
        now = now_iso()
        connection.execute(
            """UPDATE marketplace_orders
               SET status = 'paid', paid_at = ?, updated_at = ?
               WHERE id = ? AND status IN ('draft', 'pending_payment')""",
            (now, now, order_id),
        )
        supplier_id = int(order["supplier_id"])
        amount = Decimal(str(payment["amount"]))
        self._ensure_marketplace_seller_account(connection, supplier_id, now)
        source_id = str(payment_id)
        existing = connection.execute(
            """SELECT id FROM marketplace_seller_ledger
               WHERE source_type = 'payment' AND source_id = ? AND entry_type = 'hold'""",
            (source_id,),
        ).fetchone()
        if existing is None:
            insert_and_get_id(
                connection,
                """INSERT INTO marketplace_seller_ledger(
                     supplier_id, order_id, payment_id, entry_type, status, amount,
                     currency, description, source_type, source_id, created_at
                   ) VALUES (?, ?, ?, 'hold', 'pending', ?, 'KZT', ?, 'payment', ?, ?)""",
                (
                    supplier_id,
                    order_id,
                    payment_id,
                    decimal_to_db(amount),
                    f"Холд оплаты заказа {order['order_number']}",
                    source_id,
                    now,
                ),
            )
            connection.execute(
                """UPDATE marketplace_seller_accounts
                   SET pending_amount = CAST(pending_amount AS NUMERIC) + CAST(? AS NUMERIC),
                       updated_at = ?
                   WHERE supplier_id = ?""",
                (decimal_to_db(amount), now, supplier_id),
            )

    def _ensure_marketplace_seller_account(
        self, connection: Connection, supplier_id: int, now: str
    ) -> None:
        account = connection.execute(
            "SELECT id FROM marketplace_seller_accounts WHERE supplier_id = ?",
            (supplier_id,),
        ).fetchone()
        if account is None:
            insert_and_get_id(
                connection,
                """INSERT INTO marketplace_seller_accounts(
                     supplier_id, currency, available_amount, pending_amount, created_at, updated_at
                   ) VALUES (?, 'KZT', 0, 0, ?, ?)""",
                (supplier_id, now, now),
            )

    def _release_marketplace_order_hold(
        self, connection: Connection, order_id: int
    ) -> None:
        order = connection.execute(
            "SELECT * FROM marketplace_orders WHERE id = ?",
            (order_id,),
        ).fetchone()
        if order is None:
            raise NotFoundError(f"marketplace order {order_id} not found")
        now = now_iso()
        supplier_id = int(order["supplier_id"])
        self._ensure_marketplace_seller_account(connection, supplier_id, now)
        holds = connection.execute(
            """SELECT * FROM marketplace_seller_ledger
               WHERE order_id = ? AND entry_type = 'hold' AND status = 'pending'
               ORDER BY id""",
            (order_id,),
        ).fetchall()
        for hold in holds:
            amount = Decimal(str(hold["amount"]))
            source_id = str(hold["source_id"] or hold["payment_id"] or hold["id"])
            existing_release = connection.execute(
                """SELECT id FROM marketplace_seller_ledger
                   WHERE source_type = 'payment' AND source_id = ? AND entry_type = 'release'""",
                (source_id,),
            ).fetchone()
            if existing_release is not None:
                continue
            insert_and_get_id(
                connection,
                """INSERT INTO marketplace_seller_ledger(
                     supplier_id, order_id, payment_id, entry_type, status, amount,
                     currency, description, source_type, source_id, created_at
                   ) VALUES (?, ?, ?, 'release', 'posted', ?, 'KZT', ?, 'payment', ?, ?)""",
                (
                    supplier_id,
                    order_id,
                    hold["payment_id"],
                    decimal_to_db(amount),
                    f"Выплата продавцу по заказу {order['order_number']}",
                    source_id,
                    now,
                ),
            )
            connection.execute(
                "UPDATE marketplace_seller_ledger SET status = 'posted' WHERE id = ?",
                (hold["id"],),
            )
            connection.execute(
                """UPDATE marketplace_seller_accounts
                   SET pending_amount = CAST(pending_amount AS NUMERIC) - CAST(? AS NUMERIC),
                       available_amount = CAST(available_amount AS NUMERIC) + CAST(? AS NUMERIC),
                       updated_at = ?
                   WHERE supplier_id = ?""",
                (decimal_to_db(amount), decimal_to_db(amount), now, supplier_id),
            )

    def _cancel_marketplace_order_hold(
        self,
        connection: Connection,
        order_id: int,
        *,
        cancel_reason: str | None = None,
    ) -> None:
        order = connection.execute(
            "SELECT * FROM marketplace_orders WHERE id = ?",
            (order_id,),
        ).fetchone()
        if order is None:
            raise NotFoundError(f"marketplace order {order_id} not found")
        now = now_iso()
        supplier_id = int(order["supplier_id"])
        self._ensure_marketplace_seller_account(connection, supplier_id, now)
        holds = connection.execute(
            """SELECT * FROM marketplace_seller_ledger
               WHERE order_id = ? AND entry_type = 'hold' AND status = 'pending'
               ORDER BY id""",
            (order_id,),
        ).fetchall()
        for hold in holds:
            amount = Decimal(str(hold["amount"]))
            source_id = str(hold["source_id"] or hold["payment_id"] or hold["id"])
            existing_refund = connection.execute(
                """SELECT id FROM marketplace_seller_ledger
                   WHERE source_type = 'payment' AND source_id = ? AND entry_type = 'refund'""",
                (source_id,),
            ).fetchone()
            if existing_refund is not None:
                continue
            insert_and_get_id(
                connection,
                """INSERT INTO marketplace_seller_ledger(
                     supplier_id, order_id, payment_id, entry_type, status, amount,
                     currency, description, source_type, source_id, created_at
                   ) VALUES (?, ?, ?, 'refund', 'posted', ?, 'KZT', ?, 'payment', ?, ?)""",
                (
                    supplier_id,
                    order_id,
                    hold["payment_id"],
                    decimal_to_db(amount),
                    cancel_reason or f"Возврат холда по заказу {order['order_number']}",
                    source_id,
                    now,
                ),
            )
            connection.execute(
                "UPDATE marketplace_seller_ledger SET status = 'cancelled' WHERE id = ?",
                (hold["id"],),
            )
            connection.execute(
                """UPDATE marketplace_seller_accounts
                   SET pending_amount = CAST(pending_amount AS NUMERIC) - CAST(? AS NUMERIC),
                       updated_at = ?
                   WHERE supplier_id = ?""",
                (decimal_to_db(amount), now, supplier_id),
            )

    def _refund_marketplace_order_payment(
        self, connection: Connection, order_id: int, payment_id: int
    ) -> None:
        order = connection.execute(
            "SELECT * FROM marketplace_orders WHERE id = ?",
            (order_id,),
        ).fetchone()
        if order is None:
            raise NotFoundError(f"marketplace order {order_id} not found")
        payment = connection.execute(
            "SELECT * FROM marketplace_payments WHERE id = ?",
            (payment_id,),
        ).fetchone()
        if payment is None:
            raise NotFoundError(f"payment {payment_id} not found")
        now = now_iso()
        supplier_id = int(order["supplier_id"])
        self._ensure_marketplace_seller_account(connection, supplier_id, now)
        source_id = str(payment_id)
        existing_refund = connection.execute(
            """SELECT id FROM marketplace_seller_ledger
               WHERE source_type = 'payment' AND source_id = ? AND entry_type = 'refund'""",
            (source_id,),
        ).fetchone()
        if existing_refund is not None:
            connection.execute(
                """UPDATE marketplace_refund_requests
                   SET status = 'refunded', updated_at = ?
                   WHERE order_id = ?
                     AND (payment_id = ? OR payment_id IS NULL)
                     AND status IN ('requested','approved','processing')""",
                (now, order_id, payment_id),
            )
            return
        amount = Decimal(str(payment["amount"]))
        pending_hold = connection.execute(
            """SELECT id FROM marketplace_seller_ledger
               WHERE source_type = 'payment' AND source_id = ? AND entry_type = 'hold' AND status = 'pending'""",
            (source_id,),
        ).fetchone()
        released = connection.execute(
            """SELECT id FROM marketplace_seller_ledger
               WHERE source_type = 'payment' AND source_id = ? AND entry_type = 'release' AND status = 'posted'""",
            (source_id,),
        ).fetchone()
        if pending_hold is None and released is None:
            return
        insert_and_get_id(
            connection,
            """INSERT INTO marketplace_seller_ledger(
                 supplier_id, order_id, payment_id, entry_type, status, amount,
                 currency, description, source_type, source_id, created_at
               ) VALUES (?, ?, ?, 'refund', 'posted', ?, 'KZT', ?, 'payment', ?, ?)""",
            (
                supplier_id,
                order_id,
                payment_id,
                decimal_to_db(amount),
                f"Возврат оплаты заказа {order['order_number']}",
                source_id,
                now,
            ),
        )
        if pending_hold is not None:
            connection.execute(
                """UPDATE marketplace_seller_ledger
                   SET status = 'cancelled'
                   WHERE source_type = 'payment' AND source_id = ? AND entry_type = 'hold'""",
                (source_id,),
            )
            connection.execute(
                """UPDATE marketplace_seller_accounts
                   SET pending_amount = CAST(pending_amount AS NUMERIC) - CAST(? AS NUMERIC),
                       updated_at = ?
                   WHERE supplier_id = ?""",
                (decimal_to_db(amount), now, supplier_id),
            )
        elif released is not None:
            connection.execute(
                """UPDATE marketplace_seller_accounts
                   SET available_amount = CAST(available_amount AS NUMERIC) - CAST(? AS NUMERIC),
                       updated_at = ?
                   WHERE supplier_id = ?""",
                (decimal_to_db(amount), now, supplier_id),
            )
        connection.execute(
            """UPDATE marketplace_orders
               SET status = 'refunded', updated_at = ?
               WHERE id = ?""",
            (now, order_id),
        )
        connection.execute(
            """UPDATE marketplace_refund_requests
               SET status = 'refunded', updated_at = ?
               WHERE order_id = ?
                 AND (payment_id = ? OR payment_id IS NULL)
                 AND status IN ('requested','approved','processing')""",
            (now, order_id, payment_id),
        )

    def _optional_decimal_to_db(self, value: Decimal | int | str | None) -> str | None:
        if value is None:
            return None
        return decimal_to_db(value)

    def _validate_sensor_thresholds(
        self, data: SensorDeviceCreate | SensorDeviceUpdate
    ) -> None:
        if (
            data.min_temperature_c is not None
            and data.max_temperature_c is not None
            and data.min_temperature_c > data.max_temperature_c
        ):
            raise ValidationError("Minimum temperature cannot be greater than maximum temperature")
        if (
            data.min_humidity_percent is not None
            and data.max_humidity_percent is not None
            and data.min_humidity_percent > data.max_humidity_percent
        ):
            raise ValidationError("Minimum humidity cannot be greater than maximum humidity")
        for value in (data.min_humidity_percent, data.max_humidity_percent):
            if value is not None and (value < Decimal(0) or value > Decimal(100)):
                raise ValidationError("Humidity threshold must be between 0 and 100")

    def _validate_sensor_reading(self, data: SensorReadingCreate) -> None:
        if data.temperature_c is None and data.humidity_percent is None:
            raise ValidationError("Sensor reading requires temperature or humidity")
        if data.humidity_percent is not None and (
            data.humidity_percent < Decimal(0) or data.humidity_percent > Decimal(100)
        ):
            raise ValidationError("Humidity reading must be between 0 and 100")

    def _sensor_reading_status(
        self, device: dict[str, Any], data: SensorReadingCreate
    ) -> str:
        if data.temperature_c is not None:
            min_temperature = device.get("min_temperature_c")
            max_temperature = device.get("max_temperature_c")
            if min_temperature is not None and data.temperature_c < Decimal(str(min_temperature)):
                return "warning"
            if max_temperature is not None and data.temperature_c > Decimal(str(max_temperature)):
                return "warning"
        if data.humidity_percent is not None:
            min_humidity = device.get("min_humidity_percent")
            max_humidity = device.get("max_humidity_percent")
            if min_humidity is not None and data.humidity_percent < Decimal(str(min_humidity)):
                return "warning"
            if max_humidity is not None and data.humidity_percent > Decimal(str(max_humidity)):
                return "warning"
        return "ok"

    def _sensor_warning_details(
        self, device: dict[str, Any], reading: dict[str, Any]
    ) -> list[str]:
        details: list[str] = []
        temperature = reading.get("temperature_c")
        if temperature is not None:
            value = Decimal(str(temperature))
            min_temperature = device.get("min_temperature_c")
            max_temperature = device.get("max_temperature_c")
            norm = self._format_sensor_range(min_temperature, max_temperature, "°C")
            if min_temperature is not None and value < Decimal(str(min_temperature)):
                details.append(f"температура {value} °C ниже нормы {norm}")
            elif max_temperature is not None and value > Decimal(str(max_temperature)):
                details.append(f"температура {value} °C выше нормы {norm}")
        humidity = reading.get("humidity_percent")
        if humidity is not None:
            value = Decimal(str(humidity))
            min_humidity = device.get("min_humidity_percent")
            max_humidity = device.get("max_humidity_percent")
            norm = self._format_sensor_range(min_humidity, max_humidity, "%")
            if min_humidity is not None and value < Decimal(str(min_humidity)):
                details.append(f"влажность {value} % ниже нормы {norm}")
            elif max_humidity is not None and value > Decimal(str(max_humidity)):
                details.append(f"влажность {value} % выше нормы {norm}")
        if not details:
            details.append("значение вне настроенных порогов датчика")
        return details

    def _format_sensor_range(self, low: Any, high: Any, unit: str) -> str:
        if low is not None and high is not None:
            return f"{low}…{high} {unit}"
        if low is not None:
            return f"от {low} {unit}"
        if high is not None:
            return f"до {high} {unit}"
        return f"не задана {unit}"

    def _require(self, connection: Connection, table: str, entity_id: int) -> Row:
        row = connection.execute(f"SELECT * FROM {table} WHERE id = ?", (entity_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"{table}#{entity_id} not found")
        return row

    def _require_active(self, connection: Connection, table: str, entity_id: int) -> Row:
        row = self._require(connection, table, entity_id)
        if "is_active" in row.keys() and not bool(row["is_active"]):
            raise ValidationError(f"{table}#{entity_id} is inactive")
        return row

    def _get_purchase_request(
        self, connection: Connection, request_id: int
    ) -> dict[str, Any]:
        row = connection.execute(
            """
            SELECT
              pr.*,
              p.name AS product_name,
              p.sku
            FROM purchase_requests pr
            JOIN products p ON p.id = pr.product_id
            WHERE pr.id = ?
            """,
            (request_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"purchase_requests#{request_id} not found")
        return dict(row)

    def _get_supplier_application(
        self, connection: Connection, application_id: int
    ) -> dict[str, Any]:
        row = connection.execute(
            """
            SELECT
              sa.*,
              s.name AS supplier_name
            FROM supplier_applications sa
            LEFT JOIN suppliers s ON s.id = sa.supplier_id
            WHERE sa.id = ?
            """,
            (application_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"supplier_applications#{application_id} not found")
        return dict(row)

    def _get_abc_xyz_run(self, connection: Connection, run_id: int) -> dict[str, Any]:
        run = dict(self._require(connection, "abc_xyz_runs", run_id))
        rows = connection.execute(
            """
            SELECT
              product_id,
              product_name,
              sku,
              abc_class,
              xyz_class,
              consumption_quantity,
              consumption_value,
              current_free_quantity,
              reorder_point,
              safety_stock,
              recommended_order_quantity,
              recommendation,
              movement_count
            FROM abc_xyz_run_items
            WHERE run_id = ?
            ORDER BY product_name, product_id
            """,
            (run_id,),
        ).fetchall()
        run["items"] = [dict(row) for row in rows]
        return run

    def _get_quarantine_review(self, connection: Connection, review_id: int) -> dict[str, Any]:
        row = connection.execute(
            """
            SELECT
              qr.*,
              b.product_id,
              b.lot,
              p.name AS product_name
            FROM quarantine_reviews qr
            JOIN batches b ON b.id = qr.batch_id
            JOIN products p ON p.id = b.product_id
            WHERE qr.id = ?
            """,
            (review_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"quarantine_reviews#{review_id} not found")
        return dict(row)

    def _get_sensor_reading(self, connection: Connection, reading_id: int) -> dict[str, Any]:
        row = connection.execute(
            """
            SELECT
              sr.*,
              sd.name AS device_name,
              w.name AS warehouse_name
            FROM sensor_readings sr
            JOIN sensor_devices sd ON sd.id = sr.device_id
            JOIN warehouses w ON w.id = sr.warehouse_id
            WHERE sr.id = ?
            """,
            (reading_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"sensor_readings#{reading_id} not found")
        return dict(row)

    def _ensure_quarantine_review(
        self,
        connection: Connection,
        *,
        batch_id: int,
        warehouse_id: int,
        actor_id: str,
    ) -> int:
        existing = connection.execute(
            """
            SELECT id FROM quarantine_reviews
            WHERE batch_id = ? AND warehouse_id = ?
            """,
            (batch_id, warehouse_id),
        ).fetchone()
        if existing:
            return int(existing["id"])
        now = now_iso()
        return insert_and_get_id(
            connection,
            """
            INSERT INTO quarantine_reviews(
              batch_id, warehouse_id, status, responsible_id, due_at, decision_reason,
              created_by, decided_by, created_at, updated_at, decided_at
            ) VALUES (?, ?, ?, NULL, NULL, NULL, ?, NULL, ?, ?, NULL)
            """,
            (
                batch_id,
                warehouse_id,
                QuarantineReviewStatus.PENDING,
                actor_id,
                now,
                now,
            ),
        )

    def _ensure_quarantine_reviews_for_open_batches(
        self, connection: Connection, warehouse_id: int | None = None
    ) -> None:
        params: tuple[Any, ...] = ()
        warehouse_filter = ""
        if warehouse_id is not None:
            warehouse_filter = " AND sb.warehouse_id = ?"
            params = (warehouse_id,)
        rows = connection.execute(
            f"""
            SELECT b.id AS batch_id, sb.warehouse_id
            FROM stock_balances sb
            JOIN batches b ON b.id = sb.batch_id
            LEFT JOIN quarantine_reviews qr
              ON qr.batch_id = b.id AND qr.warehouse_id = sb.warehouse_id
            WHERE b.status = ?
              AND qr.id IS NULL
              AND CAST(sb.quantity AS REAL) - CAST(sb.reserved_quantity AS REAL) > 0
              {warehouse_filter}
            ORDER BY b.id, sb.warehouse_id
            """,
            (BatchStatus.QUARANTINE, *params),
        ).fetchall()
        for row in rows:
            self._ensure_quarantine_review(
                connection,
                batch_id=row["batch_id"],
                warehouse_id=row["warehouse_id"],
                actor_id="system",
            )

    def _close_open_quarantine_reviews(
        self,
        connection: Connection,
        *,
        batch_id: int,
        status: QuarantineReviewStatus,
        actor_id: str,
        reason: str | None,
    ) -> None:
        now = now_iso()
        connection.execute(
            """
            UPDATE quarantine_reviews
            SET status = ?,
                decision_reason = COALESCE(?, decision_reason),
                decided_by = ?,
                updated_at = ?,
                decided_at = ?
            WHERE batch_id = ?
              AND status IN (?, ?)
            """,
            (
                status,
                reason,
                actor_id,
                now,
                now,
                batch_id,
                QuarantineReviewStatus.PENDING,
                QuarantineReviewStatus.IN_REVIEW,
            ),
        )

    def _get_by_id(self, connection: Connection, table: str, entity_id: int) -> dict[str, Any]:
        return dict(self._require(connection, table, entity_id))

    def _list_table(
        self,
        table: str,
        order_by: str,
        limit: int = 100,
        offset: int = 0,
        *,
        where: str | None = None,
        params: tuple[Any, ...] = (),
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 500))
        safe_offset = max(0, offset)
        query = f"SELECT * FROM {table}"
        if where:
            query += f" WHERE {where}"
        query += f" ORDER BY {order_by} LIMIT ? OFFSET ?"
        connection = self.database.connect()
        try:
            rows = connection.execute(query, (*params, safe_limit, safe_offset)).fetchall()
            return [dict(row) for row in rows]
        finally:
            self._close_connection(connection)

    def _get_batch(self, connection: Connection, batch_id: int) -> dict[str, Any]:
        row = self._require(connection, "batches", batch_id)
        return dict(row)

    def _get_document(self, connection: Connection, document_id: int) -> dict[str, Any]:
        document = dict(self._require(connection, "stock_documents", document_id))
        document["lines"] = [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM stock_document_lines WHERE document_id = ? ORDER BY id",
                (document_id,),
            ).fetchall()
        ]
        return document

    def _get_inventory_session(self, connection: Connection, session_id: int) -> dict[str, Any]:
        session = dict(self._require(connection, "inventory_sessions", session_id))
        session["responsible_ids"] = [
            row["responsible_id"]
            for row in connection.execute(
                """
                SELECT responsible_id
                FROM inventory_responsibles
                WHERE session_id = ?
                ORDER BY responsible_id
                """,
                (session_id,),
            ).fetchall()
        ]
        session["category_ids"] = [
            row["category_id"]
            for row in connection.execute(
                """
                SELECT category_id
                FROM inventory_session_categories
                WHERE session_id = ?
                ORDER BY category_id
                """,
                (session_id,),
            ).fetchall()
        ]
        session["lines"] = [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM inventory_lines WHERE session_id = ? ORDER BY id",
                (session_id,),
            ).fetchall()
        ]
        session["summary"] = self._inventory_summary(session["lines"])
        return session

    def _inventory_print_csv(self, lines: list[dict[str, Any]], include_actual: bool) -> str:
        headers = [
            "N",
            "Товар",
            "SKU",
            "Ед.",
            "Партия",
            "Срок годности",
            "Ожидается",
            "Факт",
        ]
        if include_actual:
            headers.append("Расхождение")
        rows = [headers]
        for line in lines:
            row = [
                line["line_no"],
                line["product_name"],
                line["sku"],
                line["unit"],
                line["lot"],
                line["expires_on"] or "",
                self._report_decimal(Decimal(str(line["expected_quantity"]))),
                "" if line["actual_quantity"] is None else self._report_decimal(Decimal(str(line["actual_quantity"]))),
            ]
            if include_actual:
                difference = line["difference_quantity"]
                row.append("" if difference is None else self._report_decimal(Decimal(str(difference))))
            rows.append(row)
        return "\n".join(";".join(self._csv_cell(cell) for cell in row) for row in rows)

    def _repack_print_csv(self, lines: list[dict[str, Any]]) -> str:
        rows: list[list[Any]] = [
            [
                "N",
                "Исходный товар",
                "Исходная партия",
                "Полученный товар",
                "Полученная партия",
                "ID полученной партии",
                "Взяли",
                "Получили",
                "Коэффициент",
                "Потери",
                "Цена результата",
                "Причина",
            ]
        ]
        for line in lines:
            target_unit_price = line["target_unit_price"]
            rows.append(
                [
                    line["line_no"],
                    line["source_product_name"],
                    line["source_lot"],
                    line["target_product_name"],
                    line["target_lot"],
                    line["target_batch_id"] or "",
                    self._report_decimal(Decimal(str(line["source_quantity"]))),
                    self._report_decimal(Decimal(str(line["target_quantity"]))),
                    self._report_decimal(Decimal(str(line["conversion_factor"]))),
                    self._report_decimal(Decimal(str(line["loss_quantity"]))),
                    "" if target_unit_price is None else self._report_decimal(Decimal(str(target_unit_price))),
                    line["reason"] or "",
                ]
            )
        return "\n".join(";".join(self._csv_cell(cell) for cell in row) for row in rows)

    def _transfer_print_csv(self, lines: list[dict[str, Any]]) -> str:
        rows: list[list[Any]] = [
            [
                "N",
                "Товар",
                "Партия",
                "Откуда",
                "Куда",
                "Количество",
                "Основание",
            ]
        ]
        for line in lines:
            rows.append(
                [
                    line["line_no"],
                    line["product_name"],
                    line["lot"],
                    line["source_warehouse_name"],
                    line["target_warehouse_name"],
                    self._report_decimal(Decimal(str(line["quantity"]))),
                    line["reason"] or "",
                ]
            )
        return "\n".join(";".join(self._csv_cell(cell) for cell in row) for row in rows)

    def _quarantine_protocol_csv(self, protocol: dict[str, Any]) -> str:
        rows: list[list[Any]] = [
            ["Поле", "Значение"],
            ["Номер проверки", protocol["review_id"]],
            ["Партия", protocol["batch_id"]],
            ["Товар", protocol["product_name"]],
            ["Серия", protocol["lot"]],
            ["Склад", protocol["warehouse_name"]],
            ["Статус", protocol["status"]],
            ["Ответственный", protocol["responsible_id"] or ""],
            ["Срок проверки", protocol["due_at"] or ""],
            ["Решение / причина", protocol["decision_reason"] or ""],
            ["Создал", protocol["created_by"]],
            ["Принял решение", protocol["decided_by"] or ""],
            ["Создано", protocol["created_at"]],
            ["Обновлено", protocol["updated_at"]],
            ["Дата решения", protocol["decided_at"] or ""],
        ]
        return "\n".join(";".join(self._csv_cell(cell) for cell in row) for row in rows)

    def _get_inventory_line(self, connection: Connection, line_id: int) -> dict[str, Any]:
        return dict(self._require(connection, "inventory_lines", line_id))

    def _inventory_summary(self, lines: list[dict[str, Any]]) -> dict[str, Any]:
        total_expected = Decimal(0)
        total_actual = Decimal(0)
        total_surplus = Decimal(0)
        total_shortage = Decimal(0)
        filled = 0
        surplus_lines = 0
        shortage_lines = 0
        matched_lines = 0
        for line in lines:
            expected = Decimal(line["expected_quantity"])
            total_expected += expected
            actual_value = line.get("actual_quantity")
            difference_value = line.get("difference_quantity")
            if actual_value is None:
                continue
            filled += 1
            actual = Decimal(actual_value)
            total_actual += actual
            difference = Decimal(difference_value) if difference_value is not None else actual - expected
            if difference > 0:
                surplus_lines += 1
                total_surplus += difference
            elif difference < 0:
                shortage_lines += 1
                total_shortage += abs(difference)
            else:
                matched_lines += 1
        return {
            "total_lines": len(lines),
            "filled_lines": filled,
            "missing_lines": max(0, len(lines) - filled),
            "surplus_lines": surplus_lines,
            "shortage_lines": shortage_lines,
            "matched_lines": matched_lines,
            "total_expected_quantity": total_expected,
            "total_actual_quantity": total_actual,
            "total_surplus_quantity": total_surplus,
            "total_shortage_quantity": total_shortage,
        }

    def _current_free_quantity(
        self, connection: Connection, product_id: int, warehouse_id: int
    ) -> Decimal:
        row = connection.execute(
            """
            SELECT COALESCE(SUM(
              CAST(sb.quantity AS REAL) - CAST(sb.reserved_quantity AS REAL)
            ), 0) AS free_quantity
            FROM batches b
            LEFT JOIN stock_balances sb
              ON sb.batch_id = b.id AND sb.warehouse_id = ?
            WHERE b.product_id = ?
            """,
            (warehouse_id, product_id),
        ).fetchone()
        return Decimal(str(row["free_quantity"] or 0))

    def _balance_payload(self, row: Row) -> dict[str, Any]:
        total = Decimal(row["total_quantity"])
        reserved = Decimal(row["reserved_quantity"])
        return {
            "product_id": row["product_id"],
            "batch_id": row["batch_id"],
            "warehouse_id": row["warehouse_id"],
            "total_quantity": total,
            "reserved_quantity": reserved,
            "free_quantity": total - reserved,
            "batch_status": row["batch_status"],
            "expires_on": self._date_from_db(row["expires_on"]) if row["expires_on"] else None,
        }
