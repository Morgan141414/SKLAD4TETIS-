from unittest import TestCase

from app.storage.postgresql import adapt_params_for_query, normalize_psycopg_url, translate_sqlite_query


class PostgreSQLAdapterTest(TestCase):
    def test_translate_sqlite_placeholders_and_boolean_constants(self) -> None:
        query = translate_sqlite_query(
            "SELECT * FROM notifications WHERE title LIKE '?' AND is_read = 0 AND id = ?"
        )

        self.assertEqual(
            query,
            "SELECT * FROM notifications WHERE title LIKE '?' AND is_read = FALSE AND id = %s",
        )

    def test_insert_boolean_params_follow_column_order(self) -> None:
        query = translate_sqlite_query(
            """
            INSERT INTO products(
              name, sku, unit, category_id, reorder_point, safety_stock, is_controlled
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """
        )

        params = adapt_params_for_query(
            query,
            ("Натрий хлорид", "NACL", "шт", 1, "10", "5", 1),
        )

        self.assertEqual(params[:-1], ("Натрий хлорид", "NACL", "шт", 1, "10", "5"))
        self.assertIs(params[-1], True)

    def test_update_boolean_params_use_assignment_context(self) -> None:
        query = translate_sqlite_query("UPDATE notifications SET is_read = ?, read_at = ? WHERE id = ?")

        params = adapt_params_for_query(query, (0, None, 12))

        self.assertIs(params[0], False)
        self.assertEqual(params[1:], (None, 12))

    def test_non_boolean_integer_params_are_preserved(self) -> None:
        query = translate_sqlite_query(
            "INSERT INTO stock_balances(batch_id, warehouse_id, quantity) VALUES (?, ?, ?)"
        )

        params = adapt_params_for_query(query, (1, 0, "5"))

        self.assertEqual(params, (1, 0, "5"))

    def test_sqlalchemy_psycopg_url_is_normalized_for_raw_psycopg(self) -> None:
        self.assertEqual(
            normalize_psycopg_url("postgresql+psycopg://user:pass@db/sklad"),
            "postgresql://user:pass@db/sklad",
        )
        self.assertEqual(
            normalize_psycopg_url("postgresql://user:pass@db/sklad"),
            "postgresql://user:pass@db/sklad",
        )
