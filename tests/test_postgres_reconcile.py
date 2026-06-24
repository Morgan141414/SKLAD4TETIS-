import sqlite3
from unittest import TestCase

from scripts.sklad_postgres_reconcile import _movement_totals, _stock_balance_totals


class PostgresReconcileTest(TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            CREATE TABLE batches (
              id INTEGER PRIMARY KEY,
              product_id INTEGER NOT NULL
            );
            CREATE TABLE stock_balances (
              batch_id INTEGER NOT NULL,
              warehouse_id INTEGER NOT NULL,
              quantity TEXT NOT NULL,
              reserved_quantity TEXT NOT NULL
            );
            CREATE TABLE stock_movements (
              movement_type TEXT NOT NULL,
              warehouse_id INTEGER NOT NULL,
              quantity TEXT NOT NULL
            );
            """
        )

    def tearDown(self) -> None:
        self.connection.close()

    def test_stock_balance_totals_group_by_warehouse_and_product(self) -> None:
        self.connection.executemany(
            "INSERT INTO batches(id, product_id) VALUES (?, ?)",
            [(1, 10), (2, 10), (3, 20)],
        )
        self.connection.executemany(
            """
            INSERT INTO stock_balances(batch_id, warehouse_id, quantity, reserved_quantity)
            VALUES (?, ?, ?, ?)
            """,
            [
                (1, 100, "5.500", "1.000"),
                (2, 100, "2.250", "0.250"),
                (3, 100, "7.000", "0"),
            ],
        )

        self.assertEqual(
            _stock_balance_totals(self.connection),
            {
                "warehouse:100|product:10": {
                    "rows": 2,
                    "quantity": "7.75",
                    "reserved_quantity": "1.25",
                },
                "warehouse:100|product:20": {
                    "rows": 1,
                    "quantity": "7",
                    "reserved_quantity": "0",
                },
            },
        )

    def test_movement_totals_group_by_type_and_warehouse(self) -> None:
        self.connection.executemany(
            "INSERT INTO stock_movements(movement_type, warehouse_id, quantity) VALUES (?, ?, ?)",
            [
                ("receipt", 100, "5"),
                ("receipt", 100, "1.25"),
                ("write_off", 100, "2.500"),
                ("receipt", 200, "9"),
            ],
        )

        self.assertEqual(
            _movement_totals(self.connection),
            {
                "movement:receipt|warehouse:100": {"rows": 2, "quantity": "6.25"},
                "movement:receipt|warehouse:200": {"rows": 1, "quantity": "9"},
                "movement:write_off|warehouse:100": {"rows": 1, "quantity": "2.5"},
            },
        )
