from __future__ import annotations

import math
from datetime import (
    UTC,
    datetime,
    timedelta,
)
from decimal import Decimal
from sqlite3 import Connection
from typing import Any

from app.domain.enums import (
    AuditAction,
    MovementType,
)
from app.domain.errors import ValidationError
from app.domain.schemas import (
    PurchaseRequestCreate,
    PurchaseRequestStatusUpdate,
)
from app.services.warehouse.base import WarehouseServiceBase
from app.storage.sqlite import (
    decimal_to_db,
    insert_and_get_id,
    now_iso,
)


class ProcurementAnalyticsMixin(WarehouseServiceBase):
    def abc_xyz_analysis(
        self, analysis_days: int = 90, warehouse_id: int | None = None
    ) -> dict[str, Any]:
        if analysis_days < 1:
            raise ValidationError("Analysis period must be at least one day")
        generated_at = datetime.now(UTC)
        since = generated_at - timedelta(days=analysis_days)
        bucket_count = 3
        bucket_seconds = max(1, analysis_days * 24 * 60 * 60 / bucket_count)
        connection = self.database.connect()
        try:
            if warehouse_id is not None:
                self._require(connection, "warehouses", warehouse_id)
            products = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT id, name, sku, reorder_point, safety_stock
                    FROM products
                    ORDER BY name, id
                    """
                ).fetchall()
            ]
            balance_filter = ""
            balance_params: tuple[Any, ...] = ()
            if warehouse_id is not None:
                balance_filter = " WHERE sb.warehouse_id = ?"
                balance_params = (warehouse_id,)
            balance_rows = connection.execute(
                f"""
                SELECT b.product_id,
                       SUM(CAST(sb.quantity AS REAL) - CAST(sb.reserved_quantity AS REAL))
                         AS free_quantity
                FROM stock_balances sb
                JOIN batches b ON b.id = sb.batch_id
                {balance_filter}
                GROUP BY b.product_id
                """,
                balance_params,
            ).fetchall()
            free_by_product = {
                row["product_id"]: Decimal(str(row["free_quantity"] or 0))
                for row in balance_rows
            }

            movement_filters = [
                "sm.movement_type IN (?, ?, ?)",
                "sm.created_at >= ?",
            ]
            movement_params: tuple[Any, ...] = (
                MovementType.WRITE_OFF,
                MovementType.TRANSFER_OUT,
                MovementType.RETURN_TO_SUPPLIER,
                since.isoformat(),
            )
            if warehouse_id is not None:
                movement_filters.append("sm.warehouse_id = ?")
                movement_params = (*movement_params, warehouse_id)
            movement_rows = connection.execute(
                f"""
                SELECT
                  b.product_id,
                  sm.quantity,
                  sm.created_at,
                  b.unit_price
                FROM stock_movements sm
                JOIN batches b ON b.id = sm.batch_id
                WHERE {" AND ".join(movement_filters)}
                ORDER BY sm.created_at, sm.id
                """,
                movement_params,
            ).fetchall()
        finally:
            self._close_connection(connection)

        stats: dict[int, dict[str, Any]] = {
            product["id"]: {
                "quantity": Decimal(0),
                "value": Decimal(0),
                "buckets": [Decimal(0) for _ in range(bucket_count)],
                "movement_count": 0,
            }
            for product in products
        }
        for row in movement_rows:
            product_id = row["product_id"]
            if product_id not in stats:
                continue
            quantity = Decimal(row["quantity"])
            unit_price = Decimal(row["unit_price"])
            movement_created_at = self._datetime_from_db(row["created_at"]).astimezone(UTC)
            bucket_index = int((movement_created_at - since).total_seconds() // bucket_seconds)
            bucket_index = max(0, min(bucket_count - 1, bucket_index))
            stats[product_id]["quantity"] += quantity
            stats[product_id]["value"] += quantity * unit_price
            stats[product_id]["buckets"][bucket_index] += quantity
            stats[product_id]["movement_count"] += 1

        total_value = sum((item["value"] for item in stats.values()), Decimal(0))
        sorted_products = sorted(
            products,
            key=lambda product: (
                -stats[product["id"]]["value"],
                product["name"],
                product["id"],
            ),
        )
        cumulative_value = Decimal(0)
        items: list[dict[str, Any]] = []
        for product in sorted_products:
            product_stats = stats[product["id"]]
            if total_value <= 0 or product_stats["value"] <= 0:
                abc_class = "C"
            else:
                cumulative_share_before = cumulative_value / total_value
                if cumulative_share_before < Decimal("0.80"):
                    abc_class = "A"
                elif cumulative_share_before < Decimal("0.95"):
                    abc_class = "B"
                else:
                    abc_class = "C"
            cumulative_value += product_stats["value"]
            xyz_class = self._xyz_class(product_stats["buckets"])
            current_free = free_by_product.get(product["id"], Decimal(0))
            reorder_point = Decimal(product["reorder_point"])
            safety_stock = Decimal(product["safety_stock"])
            recommended_order = max(
                Decimal(0),
                reorder_point + safety_stock - current_free,
            )
            items.append(
                {
                    "product_id": product["id"],
                    "product_name": product["name"],
                    "sku": product["sku"],
                    "abc_class": abc_class,
                    "xyz_class": xyz_class,
                    "consumption_quantity": self._report_decimal(product_stats["quantity"]),
                    "consumption_value": self._report_decimal(product_stats["value"]),
                    "current_free_quantity": self._report_decimal(current_free),
                    "reorder_point": product["reorder_point"],
                    "safety_stock": product["safety_stock"],
                    "recommended_order_quantity": self._report_decimal(recommended_order),
                    "recommendation": self._abc_xyz_recommendation(
                        abc_class, xyz_class, recommended_order
                    ),
                    "movement_count": product_stats["movement_count"],
                    "suggested_reorder_point": self._report_decimal(
                        self._xyz_suggested_reorder_point(xyz_class, product_stats["quantity"], analysis_days)
                    ),
                }
            )
        return {
            "items": items,
            "analysis_days": analysis_days,
            "warehouse_id": warehouse_id,
            "generated_at": generated_at.isoformat(),
        }


    def apply_xyz_reorder_suggestions(
        self, analysis_days=90, warehouse_id=None, actor_id="system"
    ):
        """Update product reorder_points based on XYZ-analysis suggestions."""
        analysis = self.abc_xyz_analysis(analysis_days=analysis_days, warehouse_id=warehouse_id)
        updated = []
        with self.database.transaction() as connection:
            for item in analysis["items"]:
                suggested = Decimal(str(item["suggested_reorder_point"] or 0))
                current = Decimal(str(item["reorder_point"] or 0))
                if suggested <= 0 or suggested == current:
                    continue
                connection.execute(
                    "UPDATE products SET reorder_point = ? WHERE id = ?",
                    (decimal_to_db(suggested), item["product_id"]),
                )
                self._audit(
                    connection, actor_id, AuditAction.UPDATE, "product", item["product_id"],
                    {"reorder_point": {"from": str(current), "to": str(suggested), "source": "xyz_suggestion"}},
                )
                updated.append({"product_id": item["product_id"], "product_name": item["product_name"], "old_reorder_point": str(current), "new_reorder_point": str(suggested), "xyz_class": item["xyz_class"]})
        return {"updated": len(updated), "items": updated}
    def save_abc_xyz_analysis_snapshot(
        self,
        analysis_days: int = 90,
        warehouse_id: int | None = None,
        actor_id: str = "system",
        source: str = "manual",
        period_start: datetime | None = None,
        period_end: datetime | None = None,
    ) -> dict[str, Any]:
        if source not in {"manual", "background"}:
            raise ValidationError("ABC/XYZ source must be manual or background")
        analysis = self.abc_xyz_analysis(analysis_days=analysis_days, warehouse_id=warehouse_id)
        generated_at = self._datetime_from_db(analysis["generated_at"])
        if period_end is None:
            period_end = generated_at
        if period_start is None:
            period_start = period_end - timedelta(days=analysis_days)
        if period_start >= period_end:
            raise ValidationError("ABC/XYZ period start must be before period end")
        with self.database.transaction() as connection:
            if warehouse_id is not None:
                self._require(connection, "warehouses", warehouse_id)
            existing = connection.execute(
                """
                SELECT id
                FROM abc_xyz_runs
                WHERE COALESCE(warehouse_id, 0) = COALESCE(?, 0)
                  AND analysis_days = ?
                  AND period_start = ?
                  AND period_end = ?
                  AND source = ?
                  AND status = 'succeeded'
                """,
                (warehouse_id, analysis_days, period_start.isoformat(), period_end.isoformat(), source),
            ).fetchone()
            if existing:
                return self._get_abc_xyz_run(connection, int(existing["id"]))
            run_id = insert_and_get_id(
                connection,
                """
                INSERT INTO abc_xyz_runs(
                  warehouse_id, analysis_days, period_start, period_end, source, status,
                  items_count, error, generated_by, generated_at
                ) VALUES (?, ?, ?, ?, ?, 'succeeded', ?, NULL, ?, ?)
                """,
                (
                    warehouse_id,
                    analysis_days,
                    period_start.isoformat(),
                    period_end.isoformat(),
                    source,
                    len(analysis["items"]),
                    actor_id,
                    generated_at.isoformat(),
                ),
            )
            for item in analysis["items"]:
                connection.execute(
                    """
                    INSERT INTO abc_xyz_run_items(
                      run_id, product_id, product_name, sku, abc_class, xyz_class,
                      consumption_quantity, consumption_value, current_free_quantity,
                      reorder_point, safety_stock, recommended_order_quantity,
                      recommendation, movement_count
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        item["product_id"],
                        item["product_name"],
                        item["sku"],
                        item["abc_class"],
                        item["xyz_class"],
                        decimal_to_db(item["consumption_quantity"]),
                        decimal_to_db(item["consumption_value"]),
                        decimal_to_db(item["current_free_quantity"]),
                        decimal_to_db(item["reorder_point"]),
                        decimal_to_db(item["safety_stock"]),
                        decimal_to_db(item["recommended_order_quantity"]),
                        item["recommendation"],
                        item["movement_count"],
                    ),
                )
            self._audit(
                connection,
                actor_id,
                AuditAction.CREATE,
                "abc_xyz_run",
                run_id,
                {
                    "warehouse_id": warehouse_id,
                    "analysis_days": analysis_days,
                    "source": source,
                    "items_count": len(analysis["items"]),
                },
                warehouse_id=warehouse_id,
            )
            return self._get_abc_xyz_run(connection, run_id)

    def save_monthly_abc_xyz_analysis_snapshot(
        self,
        *,
        warehouse_id: int | None = None,
        analysis_days: int = 90,
        actor_id: str = "system-scheduler",
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current = now or datetime.now(UTC)
        current = current.astimezone(UTC)
        period_start = current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if period_start.month == 12:
            period_end = period_start.replace(year=period_start.year + 1, month=1)
        else:
            period_end = period_start.replace(month=period_start.month + 1)
        return self.save_abc_xyz_analysis_snapshot(
            analysis_days=analysis_days,
            warehouse_id=warehouse_id,
            actor_id=actor_id,
            source="background",
            period_start=period_start,
            period_end=period_end,
        )

    def list_abc_xyz_runs(
        self,
        warehouse_id: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 500))
        safe_offset = max(0, offset)
        query = "SELECT * FROM abc_xyz_runs"
        params: tuple[Any, ...] = ()
        if warehouse_id is not None:
            query += " WHERE warehouse_id = ?"
            params = (warehouse_id,)
        query += " ORDER BY generated_at DESC, id DESC LIMIT ? OFFSET ?"
        connection = self.database.connect()
        try:
            rows = connection.execute(query, (*params, safe_limit, safe_offset)).fetchall()
            return [dict(row) for row in rows]
        finally:
            self._close_connection(connection)

    def count_abc_xyz_runs(self, warehouse_id: int | None = None) -> int:
        query = "SELECT COUNT(*) AS total FROM abc_xyz_runs"
        params: tuple[Any, ...] = ()
        if warehouse_id is not None:
            query += " WHERE warehouse_id = ?"
            params = (warehouse_id,)
        connection = self.database.connect()
        try:
            row = connection.execute(query, params).fetchone()
            return int(row["total"])
        finally:
            self._close_connection(connection)

    def get_abc_xyz_run(self, run_id: int) -> dict[str, Any]:
        connection = self.database.connect()
        try:
            return self._get_abc_xyz_run(connection, run_id)
        finally:
            self._close_connection(connection)

    def _report_decimal(self, value: Decimal) -> str:
        normalized = value.normalize()
        if normalized == normalized.to_integral():
            return str(normalized.quantize(Decimal(1)))
        return format(normalized, "f")

    def _xyz_class(self, buckets: list[Decimal]) -> str:
        total = sum(buckets, Decimal(0))
        if total <= 0:
            return "Z"
        mean = total / Decimal(len(buckets))
        if mean <= 0:
            return "Z"
        variance = sum((bucket - mean) ** 2 for bucket in buckets) / Decimal(len(buckets))
        coefficient = Decimal(str(math.sqrt(float(variance)))) / mean
        if coefficient <= Decimal("0.50"):
            return "X"
        if coefficient <= Decimal("1.00"):
            return "Y"
        return "Z"

    def _xyz_suggested_reorder_point(
        self, xyz_class: str, total_consumption: Decimal, analysis_days: int
    ) -> Decimal:
        """Suggest reorder point based on XYZ class: X=7d, Y=14d, Z=21d buffer."""
        if analysis_days <= 0 or total_consumption <= 0:
            return Decimal(0)
        daily = total_consumption / Decimal(str(analysis_days))
        buffer_days = {"X": 7, "Y": 14, "Z": 21}.get(xyz_class, 14)
        return (daily * Decimal(str(buffer_days))).quantize(Decimal("0.001"))

    def _abc_xyz_recommendation(
        self, abc_class: str, xyz_class: str, recommended_order: Decimal
    ) -> str:
        if recommended_order > 0:
            if abc_class == "A":
                return "Заказать в первую очередь"
            return "Пополнить запас"
        if abc_class == "A" and xyz_class == "Z":
            return "Проверить нестабильный спрос"
        if abc_class == "A":
            return "Держать под постоянным контролем"
        if xyz_class == "Z":
            return "Наблюдать за нерегулярным спросом"
        return "Запас достаточный"

    def create_purchase_request(
        self, data: PurchaseRequestCreate, actor_id: str = "system"
    ) -> dict[str, Any]:
        with self.database.transaction() as connection:
            self._require(connection, "warehouses", data.warehouse_id)
            product = self._require(connection, "products", data.product_id)
            current_free = self._current_free_quantity(
                connection, data.product_id, data.warehouse_id
            )
            reorder_point = Decimal(product["reorder_point"])
            safety_stock = Decimal(product["safety_stock"])
            existing = connection.execute(
                """
                SELECT id FROM purchase_requests
                WHERE warehouse_id = ?
                  AND product_id = ?
                  AND status = 'draft'
                """,
                (data.warehouse_id, data.product_id),
            ).fetchone()
            if existing:
                connection.execute(
                    """
                    UPDATE purchase_requests
                    SET current_free_quantity = ?,
                        reorder_point = ?,
                        safety_stock = ?,
                        recommended_quantity = ?,
                        reason = ?,
                        source = ?,
                        created_by = ?
                    WHERE id = ?
                    """,
                    (
                        self._report_decimal(current_free),
                        self._report_decimal(reorder_point),
                        self._report_decimal(safety_stock),
                        self._report_decimal(data.quantity),
                        data.reason,
                        data.source,
                        actor_id,
                        existing["id"],
                    ),
                )
                request_id = existing["id"]
                action = AuditAction.UPDATE
            elif self._is_postgresql(connection):
                request_id = self._upsert_purchase_request_postgresql(
                    connection,
                    warehouse_id=data.warehouse_id,
                    product_id=data.product_id,
                    current_free=current_free,
                    reorder_point=reorder_point,
                    safety_stock=safety_stock,
                    recommended_quantity=data.quantity,
                    reason=data.reason,
                    source=data.source,
                    actor_id=actor_id,
                )
                action = AuditAction.CREATE
            else:
                request_id = insert_and_get_id(
                    connection,
                    """
                    INSERT INTO purchase_requests(
                      warehouse_id, product_id, status, current_free_quantity,
                      reorder_point, safety_stock, recommended_quantity,
                      reason, source, created_by, created_at
                    ) VALUES (?, ?, 'draft', ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        data.warehouse_id,
                        data.product_id,
                        self._report_decimal(current_free),
                        self._report_decimal(reorder_point),
                        self._report_decimal(safety_stock),
                        self._report_decimal(data.quantity),
                        data.reason,
                        data.source,
                        actor_id,
                        now_iso(),
                    ),
                )
                action = AuditAction.CREATE
            # Set gov-procurement fields (not in ON CONFLICT upsert above)
            condition_accepted = getattr(data, "condition_accepted", "any") or "any"
            is_gov = getattr(data, "is_gov_procurement", False) or False
            connection.execute(
                """UPDATE purchase_requests
                   SET condition_accepted = ?, is_gov_procurement = ?,
                       gov_status = CASE WHEN ? THEN COALESCE(gov_status, 'demand') ELSE gov_status END
                   WHERE id = ?""",
                (condition_accepted, is_gov, is_gov, request_id),
            )
            self._audit(
                connection,
                actor_id,
                action,
                "purchase_request",
                request_id,
                {
                    "warehouse_id": data.warehouse_id,
                    "product_id": data.product_id,
                    "recommended_quantity": data.quantity,
                    "reason": data.reason,
                    "source": data.source,
                    "condition_accepted": condition_accepted,
                    "is_gov_procurement": is_gov,
                },
                warehouse_id=data.warehouse_id,
            )
            return self._get_purchase_request(connection, request_id)

    def _upsert_purchase_request_postgresql(
        self,
        connection: Connection,
        *,
        warehouse_id: int,
        product_id: int,
        current_free: Decimal,
        reorder_point: Decimal,
        safety_stock: Decimal,
        recommended_quantity: Decimal,
        reason: str,
        source: str,
        actor_id: str,
    ) -> int:
        row = connection.execute(
            """
            INSERT INTO purchase_requests(
              warehouse_id, product_id, status, current_free_quantity,
              reorder_point, safety_stock, recommended_quantity,
              reason, source, created_by, created_at
            ) VALUES (?, ?, 'draft', ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (warehouse_id, product_id) WHERE status = 'draft'
            DO UPDATE SET
              current_free_quantity = EXCLUDED.current_free_quantity,
              reorder_point = EXCLUDED.reorder_point,
              safety_stock = EXCLUDED.safety_stock,
              recommended_quantity = EXCLUDED.recommended_quantity,
              reason = EXCLUDED.reason,
              source = EXCLUDED.source,
              created_by = EXCLUDED.created_by
            RETURNING id
            """,
            (
                warehouse_id,
                product_id,
                self._report_decimal(current_free),
                self._report_decimal(reorder_point),
                self._report_decimal(safety_stock),
                self._report_decimal(recommended_quantity),
                reason,
                source,
                actor_id,
                now_iso(),
            ),
        ).fetchone()
        if row is None:
            raise RuntimeError("PostgreSQL purchase request upsert did not return an id")
        return int(row["id"])

    def _insert_purchase_request_if_absent_postgresql(
        self,
        connection: Connection,
        *,
        warehouse_id: int,
        product_id: int,
        current_free: Decimal,
        reorder_point: Decimal,
        safety_stock: Decimal,
        recommended_quantity: Decimal,
        reason: str,
        actor_id: str,
    ) -> int | None:
        row = connection.execute(
            """
            INSERT INTO purchase_requests(
              warehouse_id, product_id, status, current_free_quantity,
              reorder_point, safety_stock, recommended_quantity,
              reason, source, created_by, created_at
            ) VALUES (?, ?, 'draft', ?, ?, ?, ?, ?, 'auto', ?, ?)
            ON CONFLICT (warehouse_id, product_id) WHERE status = 'draft'
            DO NOTHING
            RETURNING id
            """,
            (
                warehouse_id,
                product_id,
                self._report_decimal(current_free),
                self._report_decimal(reorder_point),
                self._report_decimal(safety_stock),
                self._report_decimal(recommended_quantity),
                reason,
                actor_id,
                now_iso(),
            ),
        ).fetchone()
        return None if row is None else int(row["id"])

    def generate_purchase_requests(
        self, warehouse_id: int, actor_id: str = "system"
    ) -> list[dict[str, Any]]:
        with self.database.transaction() as connection:
            self._require(connection, "warehouses", warehouse_id)
            rows = connection.execute(
                """
                SELECT
                  p.id AS product_id,
                  p.reorder_point,
                  p.safety_stock,
                  COALESCE(SUM(
                    CAST(sb.quantity AS REAL) - CAST(sb.reserved_quantity AS REAL)
                  ), 0) AS free_quantity
                FROM products p
                LEFT JOIN batches b ON b.product_id = p.id
                LEFT JOIN stock_balances sb
                  ON sb.batch_id = b.id AND sb.warehouse_id = ?
                GROUP BY p.id
                HAVING CAST(p.reorder_point AS REAL) > 0
                   AND COALESCE(SUM(
                    CAST(sb.quantity AS REAL) - CAST(sb.reserved_quantity AS REAL)
                  ), 0) < CAST(p.reorder_point AS REAL)
                ORDER BY p.name, p.id
                """,
                (warehouse_id,),
            ).fetchall()
            requests: list[dict[str, Any]] = []
            for row in rows:
                existing = connection.execute(
                    """
                    SELECT id FROM purchase_requests
                    WHERE warehouse_id = ?
                      AND product_id = ?
                      AND status = 'draft'
                    """,
                    (warehouse_id, row["product_id"]),
                ).fetchone()
                if existing:
                    requests.append(self._get_purchase_request(connection, existing["id"]))
                    continue

                current_free = Decimal(str(row["free_quantity"] or 0))
                reorder_point = Decimal(row["reorder_point"])
                safety_stock = Decimal(row["safety_stock"])
                recommended_quantity = max(
                    Decimal(0),
                    reorder_point + safety_stock - current_free,
                )
                if self._is_postgresql(connection):
                    request_id = self._insert_purchase_request_if_absent_postgresql(
                        connection,
                        warehouse_id=warehouse_id,
                        product_id=row["product_id"],
                        current_free=current_free,
                        reorder_point=reorder_point,
                        safety_stock=safety_stock,
                        recommended_quantity=recommended_quantity,
                        reason="Ниже точки заказа",
                        actor_id=actor_id,
                    )
                    if request_id is None:
                        existing = connection.execute(
                            """
                            SELECT id FROM purchase_requests
                            WHERE warehouse_id = ?
                              AND product_id = ?
                              AND status = 'draft'
                            """,
                            (warehouse_id, row["product_id"]),
                        ).fetchone()
                        if existing is None:
                            raise RuntimeError("Draft purchase request conflict was not recoverable")
                        requests.append(self._get_purchase_request(connection, existing["id"]))
                        continue
                else:
                    request_id = insert_and_get_id(
                        connection,
                        """
                        INSERT INTO purchase_requests(
                          warehouse_id, product_id, status, current_free_quantity,
                          reorder_point, safety_stock, recommended_quantity,
                          reason, source, created_by, created_at
                        ) VALUES (?, ?, 'draft', ?, ?, ?, ?, ?, 'auto', ?, ?)
                        """,
                        (
                            warehouse_id,
                            row["product_id"],
                            self._report_decimal(current_free),
                            self._report_decimal(reorder_point),
                            self._report_decimal(safety_stock),
                            self._report_decimal(recommended_quantity),
                            "Ниже точки заказа",
                            actor_id,
                            now_iso(),
                        ),
                    )
                self._audit(
                    connection,
                    actor_id,
                    AuditAction.CREATE,
                    "purchase_request",
                    request_id,
                    {
                        "warehouse_id": warehouse_id,
                        "product_id": row["product_id"],
                        "recommended_quantity": recommended_quantity,
                    },
                    warehouse_id=warehouse_id,
                )
                requests.append(self._get_purchase_request(connection, request_id))
            return requests

    def list_purchase_requests(
        self,
        warehouse_id: int | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 500))
        safe_offset = max(0, offset)
        query = """
            SELECT
              pr.*,
              p.name AS product_name,
              p.sku
            FROM purchase_requests pr
            JOIN products p ON p.id = pr.product_id
        """
        params: tuple[Any, ...] = ()
        filters: list[str] = []
        if warehouse_id is not None:
            filters.append("pr.warehouse_id = ?")
            params = (*params, warehouse_id)
        if status is not None:
            filters.append("pr.status = ?")
            params = (*params, status)
        if filters:
            query += " WHERE " + " AND ".join(filters)
        query += " ORDER BY pr.created_at DESC, pr.id DESC LIMIT ? OFFSET ?"
        connection = self.database.connect()
        try:
            rows = connection.execute(query, (*params, safe_limit, safe_offset)).fetchall()
            return [dict(row) for row in rows]
        finally:
            self._close_connection(connection)

    def get_purchase_request(self, request_id: int) -> dict[str, Any]:
        connection = self.database.connect()
        try:
            return self._get_purchase_request(connection, request_id)
        finally:
            self._close_connection(connection)

    def update_purchase_request_status(
        self,
        request_id: int,
        data: PurchaseRequestStatusUpdate,
        actor_id: str = "system",
    ) -> dict[str, Any]:
        if data.status not in {"ordered", "cancelled"}:
            raise ValidationError("Purchase request can only be ordered or cancelled")
        with self.database.transaction() as connection:
            before = self._get_purchase_request(connection, request_id)
            if before["status"] == data.status:
                return before
            if before["status"] != "draft":
                raise ValidationError("Only draft purchase requests can change status")
            connection.execute(
                "UPDATE purchase_requests SET status = ? WHERE id = ?",
                (data.status, request_id),
            )
            updated = self._get_purchase_request(connection, request_id)
            self._audit(
                connection,
                actor_id,
                AuditAction.UPDATE,
                "purchase_request",
                request_id,
                {"before": before, "after": updated},
                warehouse_id=updated["warehouse_id"],
            )
            if data.status == "ordered":
                self._fire_accounting_webhook(connection, updated)
            return updated
