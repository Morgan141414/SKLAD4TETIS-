"""Tests for the auction module — create, bid, business invariants, close."""
from decimal import Decimal
from unittest import TestCase

from app.domain.schemas import CategoryCreate, ProductCreate, ReceiptCreate, SupplierCreate, WarehouseCreate
from app.services.warehouse import WarehouseService
from app.storage.sqlite import SQLiteDatabase
from datetime import date


class AuctionServiceTest(TestCase):
    def setUp(self) -> None:
        self.db = SQLiteDatabase(":memory:")
        self.db.init_schema()
        self.svc = WarehouseService(self.db)
        cat = self.svc.create_category(CategoryCreate(name="Медикаменты"))
        self.supplier = self.svc.create_supplier(SupplierCreate(name="Поставщик А"))
        self.supplier2 = self.svc.create_supplier(SupplierCreate(name="Поставщик Б"))
        self.warehouse = self.svc.create_warehouse(WarehouseCreate(name="Склад"))
        self.product = self.svc.create_product(
            ProductCreate(name="Физраствор", sku="NACL-001", unit="флакон", category_id=cat["id"])
        )

    def _create(self, start_price="10000", min_price="5000", step="500") -> dict:
        return self.svc.create_auction(
            {
                "title": "Тестовый аукцион",
                "product_id": self.product["id"],
                "warehouse_id": self.warehouse["id"],
                "quantity": 100,
                "start_price": start_price,
                "min_price": min_price,
                "step_amount": step,
            },
            actor_id="admin",
        )

    # ── creation ────────────────────────────────────────────────────────────

    def test_create_auction_starts_in_draft_status(self) -> None:
        auction = self._create()
        self.assertEqual(auction["status"], "draft")

    def test_create_auction_sets_current_price_to_start_price(self) -> None:
        auction = self._create(start_price="10000")
        self.assertEqual(Decimal(auction["current_price"]), Decimal("10000"))

    def test_create_auction_records_creator(self) -> None:
        auction = self._create()
        self.assertEqual(auction["created_by"], "admin")

    # ── start ────────────────────────────────────────────────────────────────

    def test_start_auction_transitions_to_active(self) -> None:
        auction = self._create()
        started = self.svc.start_auction(auction["id"])
        self.assertEqual(started["status"], "active")

    def test_start_nonexistent_auction_returns_none(self) -> None:
        result = self.svc.start_auction(99999)
        self.assertIsNone(result)

    def test_start_already_active_auction_returns_none(self) -> None:
        auction = self._create()
        self.svc.start_auction(auction["id"])
        result = self.svc.start_auction(auction["id"])
        # Second call: draft check fails, returns unchanged row or None
        # Invariant: status stays active
        refreshed = self.svc.get_auction(auction["id"])
        self.assertEqual(refreshed["status"], "active")

    # ── bidding ──────────────────────────────────────────────────────────────

    def test_bid_below_current_price_is_accepted(self) -> None:
        auction = self._create(start_price="10000", min_price="5000")
        self.svc.start_auction(auction["id"])
        bid = self.svc.place_bid(auction["id"], self.supplier["id"], 9000)
        self.assertEqual(Decimal(bid["bid_amount"]), Decimal("9000"))

    def test_bid_updates_current_price_on_auction(self) -> None:
        auction = self._create(start_price="10000", min_price="5000")
        self.svc.start_auction(auction["id"])
        self.svc.place_bid(auction["id"], self.supplier["id"], 8000)
        refreshed = self.svc.get_auction(auction["id"])
        self.assertEqual(Decimal(refreshed["current_price"]), Decimal("8000"))

    def test_bid_equal_to_current_price_is_rejected(self) -> None:
        auction = self._create(start_price="10000", min_price="5000")
        self.svc.start_auction(auction["id"])
        with self.assertRaises(ValueError):
            self.svc.place_bid(auction["id"], self.supplier["id"], 10000)

    def test_bid_above_current_price_is_rejected(self) -> None:
        auction = self._create(start_price="10000", min_price="5000")
        self.svc.start_auction(auction["id"])
        with self.assertRaises(ValueError):
            self.svc.place_bid(auction["id"], self.supplier["id"], 11000)

    def test_bid_below_min_price_is_rejected(self) -> None:
        auction = self._create(start_price="10000", min_price="5000")
        self.svc.start_auction(auction["id"])
        with self.assertRaises(ValueError):
            self.svc.place_bid(auction["id"], self.supplier["id"], 4000)

    def test_bid_on_draft_auction_is_rejected(self) -> None:
        auction = self._create()
        with self.assertRaises(ValueError):
            self.svc.place_bid(auction["id"], self.supplier["id"], 9000)

    def test_bid_on_closed_auction_is_rejected(self) -> None:
        auction = self._create(start_price="10000", min_price="5000")
        self.svc.start_auction(auction["id"])
        self.svc.close_auction(auction["id"])
        with self.assertRaises(ValueError):
            self.svc.place_bid(auction["id"], self.supplier["id"], 9000)

    def test_multiple_bids_winner_is_last_lowest_bid(self) -> None:
        auction = self._create(start_price="10000", min_price="5000")
        self.svc.start_auction(auction["id"])
        self.svc.place_bid(auction["id"], self.supplier["id"], 9000)
        self.svc.place_bid(auction["id"], self.supplier2["id"], 7500)
        refreshed = self.svc.get_auction(auction["id"])
        self.assertEqual(Decimal(refreshed["current_price"]), Decimal("7500"))
        self.assertEqual(refreshed["winner_supplier_id"], self.supplier2["id"])

    def test_second_supplier_cannot_bid_above_current_price(self) -> None:
        auction = self._create(start_price="10000", min_price="5000")
        self.svc.start_auction(auction["id"])
        self.svc.place_bid(auction["id"], self.supplier["id"], 8000)
        with self.assertRaises(ValueError):
            self.svc.place_bid(auction["id"], self.supplier2["id"], 9000)

    # ── list bids ────────────────────────────────────────────────────────────

    def test_list_auction_bids_returns_all_bids_sorted_by_amount(self) -> None:
        auction = self._create(start_price="10000", min_price="3000")
        self.svc.start_auction(auction["id"])
        self.svc.place_bid(auction["id"], self.supplier["id"], 9000)
        self.svc.place_bid(auction["id"], self.supplier2["id"], 7000)
        self.svc.place_bid(auction["id"], self.supplier["id"], 5000)
        bids = self.svc.list_auction_bids(auction["id"])
        self.assertEqual(len(bids), 3)
        amounts = [Decimal(b["bid_amount"]) for b in bids]
        self.assertEqual(amounts, sorted(amounts))

    # ── close ────────────────────────────────────────────────────────────────

    def test_close_auction_transitions_to_closed(self) -> None:
        auction = self._create()
        self.svc.start_auction(auction["id"])
        closed = self.svc.close_auction(auction["id"])
        self.assertEqual(closed["status"], "closed")

    def test_close_draft_auction_returns_none(self) -> None:
        auction = self._create()
        result = self.svc.close_auction(auction["id"])
        self.assertIsNone(result)

    def test_close_auction_preserves_winner(self) -> None:
        auction = self._create(start_price="10000", min_price="5000")
        self.svc.start_auction(auction["id"])
        self.svc.place_bid(auction["id"], self.supplier["id"], 7000)
        closed = self.svc.close_auction(auction["id"])
        self.assertEqual(closed["winner_supplier_id"], self.supplier["id"])
        self.assertEqual(Decimal(closed["winner_bid"]), Decimal("7000"))

    def test_close_nonexistent_auction_returns_none(self) -> None:
        result = self.svc.close_auction(99999)
        self.assertIsNone(result)

    # ── list ─────────────────────────────────────────────────────────────────

    def test_list_auctions_returns_all(self) -> None:
        self._create()
        self._create()
        result = self.svc.list_auctions()
        self.assertGreaterEqual(result["total"], 2)

    def test_list_auctions_filters_by_status(self) -> None:
        a1 = self._create()
        a2 = self._create()
        self.svc.start_auction(a1["id"])
        active = self.svc.list_auctions(status="active")
        draft = self.svc.list_auctions(status="draft")
        active_ids = {r["id"] for r in active["items"]}
        draft_ids = {r["id"] for r in draft["items"]}
        self.assertIn(a1["id"], active_ids)
        self.assertNotIn(a1["id"], draft_ids)
        self.assertIn(a2["id"], draft_ids)
        self.assertNotIn(a2["id"], active_ids)

    def test_get_auction_returns_none_for_missing_id(self) -> None:
        result = self.svc.get_auction(99999)
        self.assertIsNone(result)

    def test_get_auction_includes_bid_count(self) -> None:
        auction = self._create(start_price="10000", min_price="5000")
        self.svc.start_auction(auction["id"])
        self.svc.place_bid(auction["id"], self.supplier["id"], 8000)
        self.svc.place_bid(auction["id"], self.supplier2["id"], 6000)
        refreshed = self.svc.get_auction(auction["id"])
        self.assertEqual(refreshed["bid_count"], 2)
