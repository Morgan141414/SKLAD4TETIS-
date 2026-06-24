import sqlite3
import tempfile
from pathlib import Path
from unittest import TestCase

from app.storage.sqlite import SQLiteDatabase


class SQLiteMigrationTest(TestCase):
    def test_existing_suppliers_table_gets_profile_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            db_path = Path(tempdir) / "legacy_suppliers.db"
            connection = sqlite3.connect(db_path)
            try:
                connection.executescript(
                    """
                    CREATE TABLE suppliers (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      name TEXT NOT NULL,
                      bin TEXT,
                      phone TEXT
                    );
                    """
                )
                connection.commit()
            finally:
                connection.close()

            SQLiteDatabase(db_path).init_schema()

            migrated = sqlite3.connect(db_path)
            try:
                columns = {
                    row[1]
                    for row in migrated.execute("PRAGMA table_info(suppliers)").fetchall()
                }
            finally:
                migrated.close()

        self.assertIn("address", columns)
        self.assertIn("rating", columns)
        self.assertIn("is_preferred", columns)
        self.assertIn("contact_person", columns)
        self.assertIn("email", columns)
        self.assertIn("contract_number", columns)
        self.assertIn("contract_expires_on", columns)
        self.assertIn("payment_terms", columns)
        self.assertIn("notes", columns)

    def test_existing_notifications_table_gets_batch_id_before_expiry_index(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            db_path = Path(tempdir) / "legacy.db"
            connection = sqlite3.connect(db_path)
            try:
                connection.executescript(
                    """
                    CREATE TABLE notifications (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      notification_type TEXT NOT NULL,
                      product_id INTEGER,
                      warehouse_id INTEGER,
                      title TEXT NOT NULL,
                      message TEXT NOT NULL,
                      is_read INTEGER NOT NULL DEFAULT 0,
                      created_at TEXT NOT NULL,
                      read_at TEXT
                    );
                    """
                )
                connection.commit()
            finally:
                connection.close()

            SQLiteDatabase(db_path).init_schema()

            migrated = sqlite3.connect(db_path)
            try:
                columns = {
                    row[1]
                    for row in migrated.execute("PRAGMA table_info(notifications)").fetchall()
                }
                indexes = {
                    row[1]
                    for row in migrated.execute("PRAGMA index_list(notifications)").fetchall()
                }
            finally:
                migrated.close()

        self.assertIn("batch_id", columns)
        self.assertIn("device_id", columns)
        self.assertIn("sensor_reading_id", columns)
        self.assertIn("uq_notifications_unread_expiry_warehouse_batch", indexes)
        self.assertIn("uq_notifications_unread_sensor_warning_device", indexes)

    def test_existing_products_table_gets_product_passport_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            db_path = Path(tempdir) / "legacy.db"
            connection = sqlite3.connect(db_path)
            try:
                connection.executescript(
                    """
                    CREATE TABLE categories (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      name TEXT NOT NULL UNIQUE
                    );
                    CREATE TABLE products (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      name TEXT NOT NULL,
                      sku TEXT NOT NULL UNIQUE,
                      unit TEXT NOT NULL,
                      category_id INTEGER NOT NULL REFERENCES categories(id),
                      reorder_point TEXT NOT NULL DEFAULT '0',
                      safety_stock TEXT NOT NULL DEFAULT '0',
                      is_controlled INTEGER NOT NULL DEFAULT 0
                    );
                    """
                )
                connection.commit()
            finally:
                connection.close()

            SQLiteDatabase(db_path).init_schema()

            migrated = sqlite3.connect(db_path)
            try:
                columns = {
                    row[1]
                    for row in migrated.execute("PRAGMA table_info(products)").fetchall()
                }
            finally:
                migrated.close()

        self.assertIn("barcode", columns)
        self.assertIn("description", columns)
        self.assertIn("certificate_ref", columns)
        self.assertIn("is_active", columns)

    def test_existing_batches_and_document_lines_get_serial_number_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            db_path = Path(tempdir) / "legacy_batches.db"
            connection = sqlite3.connect(db_path)
            try:
                connection.executescript(
                    """
                    CREATE TABLE batches (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      product_id INTEGER NOT NULL,
                      supplier_id INTEGER NOT NULL,
                      received_at TEXT NOT NULL,
                      lot TEXT NOT NULL,
                      expires_on TEXT,
                      unit_price TEXT NOT NULL,
                      status TEXT NOT NULL
                    );
                    CREATE TABLE stock_document_lines (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      document_id INTEGER NOT NULL,
                      product_id INTEGER,
                      batch_id INTEGER,
                      quantity TEXT NOT NULL,
                      unit_price TEXT,
                      lot TEXT,
                      expires_on TEXT,
                      quarantine INTEGER NOT NULL DEFAULT 0
                    );
                    """
                )
                connection.commit()
            finally:
                connection.close()

            SQLiteDatabase(db_path).init_schema()

            migrated = sqlite3.connect(db_path)
            try:
                batch_columns = {
                    row[1]
                    for row in migrated.execute("PRAGMA table_info(batches)").fetchall()
                }
                line_columns = {
                    row[1]
                    for row in migrated.execute("PRAGMA table_info(stock_document_lines)").fetchall()
                }
            finally:
                migrated.close()

        self.assertIn("serial_number", batch_columns)
        self.assertIn("serial_number", line_columns)

    def test_existing_warehouses_table_gets_tetis_mapping_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            db_path = Path(tempdir) / "legacy.db"
            connection = sqlite3.connect(db_path)
            try:
                connection.executescript(
                    """
                    CREATE TABLE warehouses (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      name TEXT NOT NULL,
                      department TEXT,
                      inventory_lock INTEGER NOT NULL DEFAULT 0
                    );
                    """
                )
                connection.commit()
            finally:
                connection.close()

            SQLiteDatabase(db_path).init_schema()

            migrated = sqlite3.connect(db_path)
            try:
                columns = {
                    row[1]
                    for row in migrated.execute("PRAGMA table_info(warehouses)").fetchall()
                }
            finally:
                migrated.close()

        self.assertIn("tetis_org_id", columns)
        self.assertIn("external_tetis_id", columns)
        self.assertIn("storage_zone", columns)
        self.assertIn("capacity_limit", columns)
        self.assertIn("storage_conditions", columns)
        self.assertIn("responsible_person", columns)

    def test_schema_creates_abc_xyz_history_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            db_path = Path(tempdir) / "history.db"
            SQLiteDatabase(db_path).init_schema()

            connection = sqlite3.connect(db_path)
            try:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ).fetchall()
                }
                run_indexes = {
                    row[1]
                    for row in connection.execute("PRAGMA index_list(abc_xyz_runs)").fetchall()
                }
            finally:
                connection.close()

        self.assertIn("abc_xyz_runs", tables)
        self.assertIn("abc_xyz_run_items", tables)
        self.assertIn("uq_abc_xyz_runs_period", run_indexes)

    def test_schema_creates_quarantine_review_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            db_path = Path(tempdir) / "quarantine.db"
            SQLiteDatabase(db_path).init_schema()

            connection = sqlite3.connect(db_path)
            try:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ).fetchall()
                }
                indexes = {
                    row[1]
                    for row in connection.execute("PRAGMA index_list(quarantine_reviews)").fetchall()
                }
            finally:
                connection.close()

        self.assertIn("quarantine_reviews", tables)
        self.assertIn("idx_quarantine_reviews_warehouse_status_due", indexes)

    def test_schema_creates_sensor_condition_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            db_path = Path(tempdir) / "sensors.db"
            SQLiteDatabase(db_path).init_schema()

            connection = sqlite3.connect(db_path)
            try:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ).fetchall()
                }
                reading_indexes = {
                    row[1]
                    for row in connection.execute("PRAGMA index_list(sensor_readings)").fetchall()
                }
            finally:
                connection.close()

        self.assertIn("sensor_devices", tables)
        self.assertIn("sensor_readings", tables)
        self.assertIn("idx_sensor_readings_warehouse_recorded", reading_indexes)

    def test_schema_creates_repack_tables_and_line_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            db_path = Path(tempdir) / "repack.db"
            SQLiteDatabase(db_path).init_schema()

            connection = sqlite3.connect(db_path)
            try:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ).fetchall()
                }
                line_columns = {
                    row[1]
                    for row in connection.execute("PRAGMA table_info(stock_document_lines)").fetchall()
                }
                movement_columns = {
                    row[1]
                    for row in connection.execute("PRAGMA table_info(stock_movements)").fetchall()
                }
                indexes = {
                    row[1]
                    for row in connection.execute("PRAGMA index_list(batch_transformations)").fetchall()
                }
            finally:
                connection.close()

        self.assertIn("batch_transformations", tables)
        self.assertIn("target_product_id", line_columns)
        self.assertIn("target_quantity", line_columns)
        self.assertIn("conversion_factor", line_columns)
        self.assertIn("loss_quantity", line_columns)
        self.assertIn("second_approver_id", line_columns)
        self.assertIn("second_approval_note", line_columns)
        self.assertIn("second_approver_id", movement_columns)
        self.assertIn("second_approval_note", movement_columns)
        self.assertIn("idx_batch_transformations_source_batch", indexes)

    def test_schema_adds_stock_document_approval_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            db_path = Path(tempdir) / "approval.db"
            SQLiteDatabase(db_path).init_schema()

            connection = sqlite3.connect(db_path)
            try:
                columns = {
                    row[1]
                    for row in connection.execute("PRAGMA table_info(stock_documents)").fetchall()
                }
            finally:
                connection.close()

        self.assertIn("approved_by", columns)
        self.assertIn("approved_at", columns)

    def test_schema_creates_batch_recall_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            db_path = Path(tempdir) / "recalls.db"
            SQLiteDatabase(db_path).init_schema()

            connection = sqlite3.connect(db_path)
            try:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ).fetchall()
                }
                indexes = {
                    row[1]
                    for row in connection.execute("PRAGMA index_list(batch_recalls)").fetchall()
                }
            finally:
                connection.close()

        self.assertIn("batch_recalls", tables)
        self.assertIn("idx_batch_recalls_batch_created", indexes)
