"""Tests for generate_quarantine_review_overdue_notifications."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest import TestCase

from app.domain.enums import QuarantineReviewStatus
from app.domain.errors import ValidationError
from app.domain.schemas import (
    CategoryCreate,
    ProductCreate,
    QuarantineReviewUpdate,
    ReceiptCreate,
    SupplierCreate,
    WarehouseCreate,
)
from app.services.warehouse import WarehouseService
from app.storage.sqlite import SQLiteDatabase


class QuarantineReviewOverdueTest(TestCase):
    def setUp(self) -> None:
        self.database = SQLiteDatabase(":memory:")
        self.database.init_schema()
        self.service = WarehouseService(self.database)
        cat = self.service.create_category(CategoryCreate(name="Медикаменты"))
        self.supplier = self.service.create_supplier(SupplierCreate(name="ТОО Тест"))
        self.warehouse = self.service.create_warehouse(WarehouseCreate(name="Склад"))
        self.product = self.service.create_product(
            ProductCreate(name="Физраствор", sku="NACL-001", unit="флакон", category_id=cat["id"])
        )

    def _receive_quarantine(self, lot: str = "Q-001") -> dict:
        return self.service.receive(
            ReceiptCreate(
                product_id=self.product["id"],
                supplier_id=self.supplier["id"],
                warehouse_id=self.warehouse["id"],
                quantity=Decimal("10"),
                unit_price=Decimal("100"),
                lot=lot,
                quarantine=True,
            )
        )

    def _set_in_review_and_age(self, review_id: int, age_days: int) -> None:
        """Put review into in_review and backdate updated_at."""
        self.service.update_quarantine_review(
            review_id,
            QuarantineReviewUpdate(
                status=QuarantineReviewStatus.IN_REVIEW,
                responsible_id="qa-lead",
            ),
            actor_id="qa-lead",
        )
        old_ts = (datetime.now(UTC) - timedelta(days=age_days)).isoformat()
        with self.database.transaction() as conn:
            conn.execute(
                "UPDATE quarantine_reviews SET updated_at = ? WHERE id = ?",
                (old_ts, review_id),
            )

    def _get_review(self) -> dict:
        return self.service.list_quarantine_reviews(warehouse_id=self.warehouse["id"])[0]

    # ── tests ──────────────────────────────────────────────────────────────

    def test_no_notification_for_pending_review(self) -> None:
        self._receive_quarantine()
        result = self.service.generate_quarantine_review_overdue_notifications(days=7)
        self.assertEqual(result, [])

    def test_no_notification_for_recent_in_review(self) -> None:
        self._receive_quarantine()
        review = self._get_review()
        self.service.update_quarantine_review(
            review["id"],
            QuarantineReviewUpdate(status=QuarantineReviewStatus.IN_REVIEW, responsible_id="qa"),
            actor_id="qa",
        )
        result = self.service.generate_quarantine_review_overdue_notifications(days=7)
        self.assertEqual(result, [])

    def test_notification_created_for_overdue_in_review(self) -> None:
        self._receive_quarantine()
        review = self._get_review()
        self._set_in_review_and_age(review["id"], age_days=10)

        result = self.service.generate_quarantine_review_overdue_notifications(days=7)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["notification_type"], "quarantine")
        self.assertEqual(result[0]["batch_id"], review["batch_id"])
        self.assertIn("просрочена", result[0]["title"])
        self.assertIn("Физраствор", result[0]["title"])

    def test_notification_deduped_on_second_call(self) -> None:
        self._receive_quarantine()
        review = self._get_review()
        self._set_in_review_and_age(review["id"], age_days=10)

        first = self.service.generate_quarantine_review_overdue_notifications(days=7)
        second = self.service.generate_quarantine_review_overdue_notifications(days=7)

        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 1)
        self.assertEqual(first[0]["id"], second[0]["id"])

    def test_no_notification_for_approved_review(self) -> None:
        self._receive_quarantine()
        review = self._get_review()
        self.service.update_quarantine_review(
            review["id"],
            QuarantineReviewUpdate(
                status=QuarantineReviewStatus.APPROVED,
                responsible_id="qa",
                decision_reason="Всё ок",
            ),
            actor_id="qa",
        )
        result = self.service.generate_quarantine_review_overdue_notifications(days=7)
        self.assertEqual(result, [])

    def test_multiple_overdue_reviews_each_notified(self) -> None:
        b1 = self._receive_quarantine("LOT-1")
        b2 = self._receive_quarantine("LOT-2")
        reviews = self.service.list_quarantine_reviews(warehouse_id=self.warehouse["id"])
        for r in reviews:
            self._set_in_review_and_age(r["id"], age_days=8)

        result = self.service.generate_quarantine_review_overdue_notifications(days=7)
        self.assertEqual(len(result), 2)

    def test_rejects_days_less_than_one(self) -> None:
        with self.assertRaises(ValidationError):
            self.service.generate_quarantine_review_overdue_notifications(days=0)

    def test_message_contains_responsible_and_lot(self) -> None:
        self._receive_quarantine(lot="Q-RESP")
        review = self._get_review()
        self._set_in_review_and_age(review["id"], age_days=9)

        result = self.service.generate_quarantine_review_overdue_notifications(days=7)

        self.assertEqual(len(result), 1)
        self.assertIn("Q-RESP", result[0]["message"])
        self.assertIn("qa-lead", result[0]["message"])
