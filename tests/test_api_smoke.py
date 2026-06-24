import importlib.util
import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch


HAS_API_DEPS = (
    importlib.util.find_spec("fastapi") is not None
    and importlib.util.find_spec("pydantic_settings") is not None
)


@unittest.skipUnless(HAS_API_DEPS, "FastAPI test dependencies are not installed")
class APISmokeTest(TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "smoke.db"
        self.env = patch.dict(
            os.environ,
            {
                "SKLAD_DATABASE_BACKEND": "sqlite",
                "SKLAD_DATABASE_URL": f"sqlite:///{self.db_path}",
                "SKLAD_DEV_AUTH_ENABLED": "true",
                "SKLAD_BACKGROUND_JOBS_ENABLED": "false",
            },
            clear=False,
        )
        self.env.start()

        from app.api import dependencies
        from app.core.config import get_settings

        dependencies._database = None
        get_settings.cache_clear()

        from fastapi.testclient import TestClient
        from app.main import create_app

        self.client = TestClient(create_app())
        self.headers = {
            "X-Actor-Id": "smoke-manager",
            "X-Actor-Roles": "warehouse_manager",
        }

    def tearDown(self) -> None:
        from app.api import dependencies
        from app.core.config import get_settings

        dependencies._database = None
        get_settings.cache_clear()
        self.env.stop()
        self.tempdir.cleanup()

    def post(self, path: str, payload: dict) -> dict:
        response = self.client.post(path, json=payload, headers=self.headers)
        self.assertLess(response.status_code, 400, response.text)
        return response.json()

    def test_print_labels_and_inventory_form_over_http(self) -> None:
        category = self.post("/api/v1/categories", {"name": "Печать"})
        second_category = self.post("/api/v1/categories", {"name": "Фильтр"})
        supplier = self.post(
            "/api/v1/suppliers",
            {
                "name": "ТОО Этикетки",
                "address": "Астана, складская 10",
                "rating": 5,
                "is_preferred": True,
                "contact_person": "Айжан Снабжение",
                "email": "supply@example.kz",
                "contract_number": "SUP-2026-01",
                "contract_expires_on": "2027-12-31",
                "payment_terms": "Оплата в течение 15 дней",
                "notes": "Поставляет расходники и этикетки",
            },
        )
        second_supplier = self.post("/api/v1/suppliers", {"name": "ТОО Фильтр"})
        warehouse = self.post("/api/v1/warehouses", {"name": "Печатный склад"})
        second_warehouse = self.post(
            "/api/v1/warehouses",
            {
                "name": "Кабинет фильтра",
                "department": "Диагностика",
                "tetis_org_id": "ORG-FILTER",
                "external_tetis_id": "WH-FILTER",
                "storage_zone": "Холодильная зона",
                "capacity_limit": "250.500",
                "storage_conditions": "Температура 2-8 C",
                "responsible_person": "Старшая медсестра",
            },
        )
        product = self.post(
            "/api/v1/products",
            {
                "name": "Катетер",
                "sku": "CAT-001",
                "unit": "шт",
                "category_id": category["id"],
                "barcode": "4870200000123",
            },
        )
        units_response = self.client.get("/api/v1/product-units", headers=self.headers)
        self.assertEqual(units_response.status_code, 200, units_response.text)
        self.assertIn("шт", units_response.json())
        self.assertIn("флакон", units_response.json())
        invalid_unit_response = self.client.post(
            "/api/v1/products",
            json={
                "name": "Ошибка единицы",
                "sku": "BAD-UNIT",
                "unit": "штуки",
                "category_id": category["id"],
            },
            headers=self.headers,
        )
        self.assertEqual(invalid_unit_response.status_code, 422, invalid_unit_response.text)
        filtered_product = self.post(
            "/api/v1/products",
            {
                "name": "Бинт",
                "sku": "BND-001",
                "unit": "рулон",
                "category_id": second_category["id"],
            },
        )

        category_search_response = self.client.get(
            "/api/v1/categories?q=печ",
            headers=self.headers,
        )
        self.assertEqual(category_search_response.status_code, 200, category_search_response.text)
        self.assertEqual([item["id"] for item in category_search_response.json()], [category["id"]])
        product_sku_search_response = self.client.get(
            "/api/v1/products?q=cat-001",
            headers=self.headers,
        )
        self.assertEqual(product_sku_search_response.status_code, 200, product_sku_search_response.text)
        self.assertEqual([item["id"] for item in product_sku_search_response.json()], [product["id"]])
        product_barcode_search_response = self.client.get(
            "/api/v1/products?q=4870200000123",
            headers=self.headers,
        )
        self.assertEqual(product_barcode_search_response.status_code, 200, product_barcode_search_response.text)
        self.assertEqual([item["id"] for item in product_barcode_search_response.json()], [product["id"]])
        supplier_search_response = self.client.get(
            "/api/v1/suppliers?q=этик",
            headers=self.headers,
        )
        self.assertEqual(supplier_search_response.status_code, 200, supplier_search_response.text)
        self.assertEqual([item["id"] for item in supplier_search_response.json()], [supplier["id"]])
        self.assertEqual(supplier_search_response.json()[0]["rating"], 5)
        self.assertTrue(supplier_search_response.json()[0]["is_preferred"])
        self.assertEqual(supplier_search_response.json()[0]["contact_person"], "Айжан Снабжение")
        self.assertEqual(supplier_search_response.json()[0]["contract_number"], "SUP-2026-01")
        supplier_address_search_response = self.client.get(
            "/api/v1/suppliers?q=складская",
            headers=self.headers,
        )
        self.assertEqual(supplier_address_search_response.status_code, 200, supplier_address_search_response.text)
        self.assertEqual([item["id"] for item in supplier_address_search_response.json()], [supplier["id"]])
        supplier_contract_search_response = self.client.get(
            "/api/v1/suppliers?q=sup-2026",
            headers=self.headers,
        )
        self.assertEqual(supplier_contract_search_response.status_code, 200, supplier_contract_search_response.text)
        self.assertEqual([item["id"] for item in supplier_contract_search_response.json()], [supplier["id"]])
        warehouse_search_response = self.client.get(
            "/api/v1/warehouses?q=диаг",
            headers=self.headers,
        )
        self.assertEqual(warehouse_search_response.status_code, 200, warehouse_search_response.text)
        self.assertEqual([item["id"] for item in warehouse_search_response.json()], [second_warehouse["id"]])
        self.assertEqual(warehouse_search_response.json()[0]["storage_zone"], "Холодильная зона")
        warehouse_zone_search_response = self.client.get(
            "/api/v1/warehouses?q=холод",
            headers=self.headers,
        )
        self.assertEqual(warehouse_zone_search_response.status_code, 200, warehouse_zone_search_response.text)
        self.assertEqual([item["id"] for item in warehouse_zone_search_response.json()], [second_warehouse["id"]])

        batch = self.post(
            "/api/v1/receipts",
            {
                "product_id": product["id"],
                "supplier_id": supplier["id"],
                "warehouse_id": warehouse["id"],
                "quantity": "5",
                "unit_price": "120",
                "lot": "PRINT-LOT",
                "serial_number": "SN-PRINT-001",
                "expires_on": "2027-02-01",
                "quarantine": False,
            },
        )
        self.assertEqual(batch["serial_number"], "SN-PRINT-001")
        self.post(
            "/api/v1/receipts",
            {
                "product_id": filtered_product["id"],
                "supplier_id": supplier["id"],
                "warehouse_id": warehouse["id"],
                "quantity": "2",
                "unit_price": "25",
                "lot": "FILTER-LOT",
                "expires_on": "2027-03-01",
                "quarantine": False,
            },
        )

        price_history_response = self.client.get(
            f"/api/v1/suppliers/{supplier['id']}/price-history?product_id={filtered_product['id']}",
            headers=self.headers,
        )
        self.assertEqual(price_history_response.status_code, 200, price_history_response.text)
        price_history = price_history_response.json()
        self.assertEqual(price_history["total"], 1)
        self.assertEqual(price_history["items"][0]["unit_price"], "25")

        labels_response = self.client.post(
            "/api/v1/products/barcode-labels",
            json={"product_ids": [product["id"], product["id"]]},
            headers=self.headers,
        )
        self.assertEqual(labels_response.status_code, 200, labels_response.text)
        labels = labels_response.json()
        self.assertEqual(len(labels["labels"]), 1)
        self.assertIn("4870200000123", labels["zpl"])
        self.assertIn("B28,112", labels["epl"])

        ean_response = self.client.get(
            f"/api/v1/products/{product['id']}/barcode-label?symbology=ean13",
            headers=self.headers,
        )
        self.assertEqual(ean_response.status_code, 200, ean_response.text)
        self.assertEqual(ean_response.json()["symbology"], "EAN13")

        price_label_response = self.client.get(
            f"/api/v1/batches/{batch['id']}/price-label?symbology=ean13",
            headers=self.headers,
        )
        self.assertEqual(price_label_response.status_code, 200, price_label_response.text)
        price_label = price_label_response.json()
        self.assertEqual(price_label["batch_id"], batch["id"])
        self.assertEqual(price_label["unit_price"], "120")
        self.assertEqual(price_label["serial_number"], "SN-PRINT-001")
        self.assertIn("PRINT-LOT", price_label["zpl"])
        self.assertIn("SN-PRINT-001", price_label["zpl"])

        price_labels_response = self.client.post(
            "/api/v1/batches/price-labels",
            json={"batch_ids": [batch["id"], batch["id"]]},
            headers=self.headers,
        )
        self.assertEqual(price_labels_response.status_code, 200, price_labels_response.text)
        self.assertEqual(len(price_labels_response.json()["labels"]), 1)

        session = self.post(
            "/api/v1/inventory-sessions",
            {
                "warehouse_id": warehouse["id"],
                "category_ids": [second_category["id"]],
                "responsible_ids": ["manager", "manager", "head-nurse"],
            },
        )
        self.assertEqual(session["category_ids"], [second_category["id"]])
        self.assertEqual(session["responsible_ids"], ["head-nurse", "manager"])
        self.assertEqual(session["lines"][0]["product_id"], filtered_product["id"])
        line = session["lines"][0]
        count_response = self.client.patch(
            f"/api/v1/inventory-sessions/{session['id']}/lines/{line['id']}",
            json={"actual_quantity": "4"},
            headers=self.headers,
        )
        self.assertEqual(count_response.status_code, 200, count_response.text)

        form_response = self.client.get(
            f"/api/v1/inventory-sessions/{session['id']}/print-form",
            headers=self.headers,
        )
        self.assertEqual(form_response.status_code, 200, form_response.text)
        form = form_response.json()
        self.assertEqual(form["warehouse_name"], "Печатный склад")
        self.assertIn("Бинт;BND-001;рулон;FILTER-LOT;2027-03-01;2;", form["count_sheet_csv"])
        self.assertIn("Бинт;BND-001;рулон;FILTER-LOT;2027-03-01;2;4;2", form["reconciliation_csv"])

    def test_receipt_flow_updates_balances_over_http(self) -> None:
        me_response = self.client.get("/api/v1/me", headers=self.headers)
        self.assertEqual(me_response.status_code, 200, me_response.text)
        self.assertEqual(me_response.json()["actor_id"], "smoke-manager")
        self.assertIn("warehouse_manager", me_response.json()["roles"])

        category = self.post("/api/v1/categories", {"name": "Медикаменты"})
        supplier = self.post("/api/v1/suppliers", {"name": "ТОО Поставщик"})
        warehouse = self.post("/api/v1/warehouses", {"name": "Основной склад"})
        product = self.post(
            "/api/v1/products",
            {
                "name": "Физраствор",
                "sku": "NACL-001",
                "unit": "флакон",
                "category_id": category["id"],
                "reorder_point": "10",
            },
        )

        batch = self.post(
            "/api/v1/receipts",
            {
                "product_id": product["id"],
                "supplier_id": supplier["id"],
                "warehouse_id": warehouse["id"],
                "quantity": "12.5",
                "unit_price": "350",
                "lot": "LOT-HTTP",
                "serial_number": "SN-HTTP-001",
                "expires_on": "2027-01-01",
                "quarantine": False,
            },
        )
        self.assertEqual(batch["serial_number"], "SN-HTTP-001")

        balances_response = self.client.get("/api/v1/balances", headers=self.headers)
        self.assertEqual(balances_response.status_code, 200, balances_response.text)
        balances = balances_response.json()

        self.assertEqual(balances["total"], 1)
        self.assertEqual(balances["items"][0]["batch_id"], batch["id"])
        self.assertEqual(balances["items"][0]["free_quantity"], "12.5")

        batches_response = self.client.get(
            (
                f"/api/v1/batches?warehouse_id={warehouse['id']}"
                f"&product_id={product['id']}&supplier_id={supplier['id']}"
                "&status=available&expires_before=2027-12-31"
            ),
            headers=self.headers,
        )
        self.assertEqual(batches_response.status_code, 200, batches_response.text)
        self.assertEqual([row["id"] for row in batches_response.json()], [batch["id"]])
        self.assertEqual(batches_response.json()[0]["serial_number"], "SN-HTTP-001")

        traceability_response = self.client.get(
            f"/api/v1/batches/{batch['id']}/traceability",
            headers=self.headers,
        )
        self.assertEqual(traceability_response.status_code, 200, traceability_response.text)
        traceability = traceability_response.json()
        self.assertEqual(traceability["batch"]["serial_number"], "SN-HTTP-001")

        self.assertEqual(traceability["batch"]["id"], batch["id"])
        self.assertEqual(traceability["balances"][0]["batch_id"], batch["id"])
        self.assertEqual(traceability["balances"][0]["free_quantity"], "12.5")
        self.assertEqual(traceability["movements"][0]["batch_id"], batch["id"])
        self.assertIn("documents", traceability)

    def test_public_access_allows_category_create_with_stale_bearer_token(self) -> None:
        from app.api import dependencies
        from app.core.config import get_settings

        dependencies._database = None
        get_settings.cache_clear()

        with patch.dict(
            os.environ,
            {
                "SKLAD_DEV_AUTH_ENABLED": "false",
                "SKLAD_PUBLIC_ACCESS_ENABLED": "true",
                "SKLAD_JWT_HMAC_SECRET": "secret",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            response = self.client.post(
                "/api/v1/categories",
                json={"name": "Категория с битым токеном"},
                headers={
                    "Authorization": "Bearer stale-browser-token",
                    "X-Actor-Id": "public",
                },
            )

        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["name"], "Категория с битым токеном")

    def test_catalog_soft_delete_over_http(self) -> None:
        category = self.post("/api/v1/categories", {"name": "Скрытие"})
        product = self.post(
            "/api/v1/products",
            {
                "name": "Скрываемый товар",
                "sku": "HIDE-001",
                "unit": "шт",
                "category_id": category["id"],
            },
        )

        blocked_category_response = self.client.delete(
            f"/api/v1/categories/{category['id']}",
            headers=self.headers,
        )
        self.assertEqual(blocked_category_response.status_code, 422, blocked_category_response.text)

        product_response = self.client.delete(
            f"/api/v1/products/{product['id']}",
            headers=self.headers,
        )
        self.assertEqual(product_response.status_code, 200, product_response.text)
        self.assertFalse(product_response.json()["is_active"])
        products_response = self.client.get("/api/v1/products", headers=self.headers)
        self.assertEqual(products_response.status_code, 200, products_response.text)
        self.assertEqual(products_response.json(), [])

        category_response = self.client.delete(
            f"/api/v1/categories/{category['id']}",
            headers=self.headers,
        )
        self.assertEqual(category_response.status_code, 200, category_response.text)
        self.assertFalse(category_response.json()["is_active"])
        categories_response = self.client.get("/api/v1/categories", headers=self.headers)
        self.assertEqual(categories_response.status_code, 200, categories_response.text)
        self.assertEqual(categories_response.json(), [])

    def test_stats_summary_returns_expected_fields_over_http(self) -> None:
        resp = self.client.get("/api/v1/stats/summary", headers=self.headers)
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        for field in ("products", "batches", "batches_available", "batches_quarantine",
                      "warehouses", "total_free_quantity", "unread_notifications",
                      "pending_writeoffs", "active_inventory_sessions"):
            self.assertIn(field, data, f"Missing field: {field}")
            self.assertIsInstance(data[field], (int, float), f"Wrong type for {field}")

    def test_grafana_webhook_creates_notification_over_http(self) -> None:
        payload = {
            "status": "firing",
            "alerts": [
                {
                    "status": "firing",
                    "labels": {"alertname": "TestAlert", "severity": "warning"},
                    "annotations": {"summary": "Test summary", "description": "Test description"},
                    "fingerprint": "test123",
                }
            ],
        }
        resp = self.client.post("/api/v1/webhooks/grafana", json=payload)
        self.assertEqual(resp.status_code, 204, resp.text)
        # Notification appears in list
        notifs = self.client.get("/api/v1/notifications", headers=self.headers)
        self.assertEqual(notifs.status_code, 200, notifs.text)
        types = [n["notification_type"] for n in notifs.json()["items"]]
        self.assertIn("grafana_alert", types)
        # Empty alerts list is accepted (Grafana sends this on resolve with no alerts)
        resp2 = self.client.post("/api/v1/webhooks/grafana", json={"alerts": []})
        self.assertEqual(resp2.status_code, 204, resp2.text)

    def test_mis_procedure_event_requires_valid_token(self) -> None:
        from app.core.config import get_settings

        payload = {
            "mis_clinic_id": "clinic-x",
            "mis_room_id": "room-x",
            "service_code": "INJECTION",
            "mis_event_id": "evt-http-1",
        }
        # Not configured -> 503
        resp = self.client.post("/api/v1/mis/procedure-event", json=payload)
        self.assertEqual(resp.status_code, 503, resp.text)

        with patch.dict(os.environ, {"SKLAD_MIS_INBOUND_WEBHOOK_TOKEN": "secret-token"}):
            get_settings.cache_clear()
            try:
                # Missing/wrong token -> 401
                resp = self.client.post("/api/v1/mis/procedure-event", json=payload)
                self.assertEqual(resp.status_code, 401, resp.text)
                resp = self.client.post(
                    "/api/v1/mis/procedure-event",
                    json=payload,
                    headers={"Authorization": "Bearer wrong-token"},
                )
                self.assertEqual(resp.status_code, 401, resp.text)
                # Correct token, but cabinet not mapped -> 404, not 401/500
                resp = self.client.post(
                    "/api/v1/mis/procedure-event",
                    json=payload,
                    headers={"Authorization": "Bearer secret-token"},
                )
                self.assertEqual(resp.status_code, 404, resp.text)
            finally:
                get_settings.cache_clear()

    def test_product_barcode_lookup_over_http(self) -> None:
        category = self.post("/api/v1/categories", {"name": "Штрихкод"})
        product = self.post(
            "/api/v1/products",
            {
                "name": "Тест штрихкод",
                "sku": "BC-TEST-001",
                "unit": "шт",
                "category_id": category["id"],
                "barcode": "4607001234567",
            },
        )
        # Found by exact barcode
        found = self.client.get(
            "/api/v1/products/by-barcode/4607001234567",
            headers=self.headers,
        )
        self.assertEqual(found.status_code, 200, found.text)
        self.assertEqual(found.json()["id"], product["id"])
        self.assertEqual(found.json()["name"], "Тест штрихкод")
        # Not found returns 404
        missing = self.client.get(
            "/api/v1/products/by-barcode/9999999999999",
            headers=self.headers,
        )
        self.assertEqual(missing.status_code, 404, missing.text)

    def test_reservation_use_flow_writes_off_reserved_stock_over_http(self) -> None:
        category = self.post("/api/v1/categories", {"name": "Резервы"})
        supplier = self.post("/api/v1/suppliers", {"name": "ТОО Резерв"})
        warehouse = self.post("/api/v1/warehouses", {"name": "Склад резервов"})
        product = self.post(
            "/api/v1/products",
            {
                "name": "Катетер резервный",
                "sku": "RES-HTTP",
                "unit": "шт",
                "category_id": category["id"],
            },
        )
        batch = self.post(
            "/api/v1/receipts",
            {
                "product_id": product["id"],
                "supplier_id": supplier["id"],
                "warehouse_id": warehouse["id"],
                "quantity": "10",
                "unit_price": "250",
                "lot": "RES-HTTP-1",
                "quarantine": False,
            },
        )
        reservation = self.post(
            "/api/v1/reservations",
            {
                "batch_id": batch["id"],
                "warehouse_id": warehouse["id"],
                "quantity": "4",
                "reserved_for": "Операционный день",
            },
        )

        used = self.post(
            f"/api/v1/reservations/{reservation['id']}/use",
            {"reason": "Выдача из резерва"},
        )
        balances_response = self.client.get(
            f"/api/v1/balances?product_id={product['id']}",
            headers=self.headers,
        )
        movements_response = self.client.get(
            f"/api/v1/stock-movements?batch_id={batch['id']}&warehouse_id={warehouse['id']}",
            headers=self.headers,
        )

        self.assertEqual(used["status"], "used")
        self.assertEqual(balances_response.status_code, 200, balances_response.text)
        balance = balances_response.json()["items"][0]
        self.assertEqual(balance["total_quantity"], "6")
        self.assertEqual(balance["reserved_quantity"], "0")
        self.assertEqual(balance["free_quantity"], "6")
        self.assertEqual(movements_response.status_code, 200, movements_response.text)
        write_offs = [
            movement
            for movement in movements_response.json()["items"]
            if movement["movement_type"] == "write_off"
        ]
        self.assertEqual(len(write_offs), 1)
        self.assertEqual(write_offs[0]["quantity"], "4")
        self.assertEqual(write_offs[0]["reason"], "Выдача из резерва")

    def test_transfer_document_flow_moves_balances_over_http(self) -> None:
        category = self.post("/api/v1/categories", {"name": "Расходники"})
        supplier = self.post("/api/v1/suppliers", {"name": "ТОО Медснаб"})
        source = self.post("/api/v1/warehouses", {"name": "Основной склад"})
        target = self.post("/api/v1/warehouses", {"name": "Кабинет 101"})
        product = self.post(
            "/api/v1/products",
            {
                "name": "Шприц",
                "sku": "SYR-001",
                "unit": "шт",
                "category_id": category["id"],
            },
        )
        batch = self.post(
            "/api/v1/receipts",
            {
                "product_id": product["id"],
                "supplier_id": supplier["id"],
                "warehouse_id": source["id"],
                "quantity": "10",
                "unit_price": "25",
                "lot": "TR-HTTP",
                "quarantine": False,
            },
        )
        document = self.post(
            "/api/v1/stock-documents/transfers",
            {
                "source_warehouse_id": source["id"],
                "lines": [
                    {
                        "batch_id": batch["id"],
                        "target_warehouse_id": target["id"],
                        "quantity": "4",
                        "reason": "Выдача в кабинет",
                    }
                ],
            },
        )

        posted = self.post(f"/api/v1/stock-documents/{document['id']}/post", {})
        balances_response = self.client.get(
            f"/api/v1/balances?product_id={product['id']}",
            headers=self.headers,
        )
        self.assertEqual(balances_response.status_code, 200, balances_response.text)
        balances = {
            item["warehouse_id"]: item for item in balances_response.json()["items"]
        }

        self.assertEqual(posted["status"], "posted")
        self.assertEqual(balances[source["id"]]["free_quantity"], "6")
        self.assertEqual(balances[target["id"]]["free_quantity"], "4")

        form_response = self.client.get(
            f"/api/v1/stock-documents/{document['id']}/transfer-print-form",
            headers=self.headers,
        )
        self.assertEqual(form_response.status_code, 200, form_response.text)
        form = form_response.json()

        self.assertEqual(form["document_id"], document["id"])
        self.assertEqual(form["source_warehouse_name"], "Основной склад")
        self.assertEqual(form["lines"][0]["target_warehouse_name"], "Кабинет 101")
        self.assertIn("Шприц", form["csv"])
        self.assertIn("Выдача в кабинет", form["csv"])

    def test_cancel_document_flow_does_not_change_balances_over_http(self) -> None:
        category = self.post("/api/v1/categories", {"name": "Перевязочные"})
        supplier = self.post("/api/v1/suppliers", {"name": "ТОО Чистота"})
        warehouse = self.post("/api/v1/warehouses", {"name": "Аптечный склад"})
        product = self.post(
            "/api/v1/products",
            {
                "name": "Бинт",
                "sku": "BND-001",
                "unit": "рулон",
                "category_id": category["id"],
            },
        )
        document = self.post(
            "/api/v1/stock-documents/receipts",
            {
                "supplier_id": supplier["id"],
                "warehouse_id": warehouse["id"],
                "lines": [
                    {
                        "product_id": product["id"],
                        "quantity": "5",
                        "unit_price": "120",
                        "lot": "CANCEL-HTTP",
                        "quarantine": False,
                    }
                ],
            },
        )

        cancelled = self.post(f"/api/v1/stock-documents/{document['id']}/cancel", {})
        balances_response = self.client.get(
            f"/api/v1/balances?product_id={product['id']}",
            headers=self.headers,
        )

        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(balances_response.status_code, 200, balances_response.text)
        self.assertEqual(balances_response.json()["total"], 0)

    def test_approve_document_flow_over_http(self) -> None:
        category = self.post("/api/v1/categories", {"name": "Approval"})
        supplier = self.post("/api/v1/suppliers", {"name": "ТОО Approval"})
        warehouse = self.post("/api/v1/warehouses", {"name": "Склад Approval"})
        product = self.post(
            "/api/v1/products",
            {
                "name": "Катетер",
                "sku": "APR-001",
                "unit": "шт",
                "category_id": category["id"],
            },
        )
        document = self.post(
            "/api/v1/stock-documents/receipts",
            {
                "supplier_id": supplier["id"],
                "warehouse_id": warehouse["id"],
                "lines": [
                    {
                        "product_id": product["id"],
                        "quantity": "7",
                        "unit_price": "120",
                        "lot": "APPROVE-HTTP",
                        "quarantine": False,
                    }
                ],
            },
        )

        approved = self.post(f"/api/v1/stock-documents/{document['id']}/approve", {})
        posted = self.post(f"/api/v1/stock-documents/{document['id']}/post", {})

        self.assertEqual(approved["status"], "approved")
        self.assertEqual(approved["approved_by"], "smoke-manager")
        self.assertIsNotNone(approved["approved_at"])
        self.assertEqual(posted["status"], "posted")
        self.assertEqual(posted["approved_by"], "smoke-manager")

    def test_recall_batch_flow_over_http(self) -> None:
        category = self.post("/api/v1/categories", {"name": "Recall"})
        supplier = self.post("/api/v1/suppliers", {"name": "ТОО Recall"})
        warehouse = self.post("/api/v1/warehouses", {"name": "Склад Recall"})
        product = self.post(
            "/api/v1/products",
            {
                "name": "Имплант",
                "sku": "RCL-001",
                "unit": "шт",
                "category_id": category["id"],
            },
        )
        batch = self.post(
            "/api/v1/receipts",
            {
                "product_id": product["id"],
                "supplier_id": supplier["id"],
                "warehouse_id": warehouse["id"],
                "quantity": "3",
                "unit_price": "5000",
                "lot": "RECALL-HTTP",
                "quarantine": False,
            },
        )

        result = self.post(
            f"/api/v1/batches/{batch['id']}/recall",
            {
                "reason": "Отзыв производителя",
                "source": "manufacturer",
                "reference": "RCL-HTTP-1",
            },
        )
        notifications = self.client.get(
            f"/api/v1/notifications?warehouse_id={warehouse['id']}",
            headers=self.headers,
        )
        recalls_response = self.client.get(
            "/api/v1/batch-recalls",
            headers=self.headers,
        )

        self.assertEqual(result["batch"]["status"], "blocked")
        self.assertEqual(result["recall"]["reference"], "RCL-HTTP-1")
        self.assertEqual(len(result["affected_warehouses"]), 1)
        self.assertEqual(notifications.status_code, 200, notifications.text)
        self.assertEqual(recalls_response.status_code, 200, recalls_response.text)
        recalls = recalls_response.json()
        self.assertEqual(recalls["total"], 1)
        self.assertEqual(recalls["items"][0]["batch_id"], batch["id"])
        self.assertEqual(recalls["items"][0]["product_name"], "Имплант")
        self.assertTrue(
            any(row["notification_type"] == "recall" for row in notifications.json()["items"])
        )

    def test_expiry_notifications_flow_over_http(self) -> None:
        category = self.post("/api/v1/categories", {"name": "Сроки"})
        supplier = self.post("/api/v1/suppliers", {"name": "ТОО Срочный поставщик"})
        warehouse = self.post("/api/v1/warehouses", {"name": "Склад сроков"})
        product = self.post(
            "/api/v1/products",
            {
                "name": "Тест-полоски",
                "sku": "EXP-HTTP",
                "unit": "уп",
                "category_id": category["id"],
            },
        )
        batch = self.post(
            "/api/v1/receipts",
            {
                "product_id": product["id"],
                "supplier_id": supplier["id"],
                "warehouse_id": warehouse["id"],
                "quantity": "8",
                "unit_price": "500",
                "lot": "EXP-HTTP-1",
                "expires_on": (datetime.now(UTC).date() + timedelta(days=9)).isoformat(),
                "quarantine": False,
            },
        )

        response = self.client.post(
            f"/api/v1/notifications/generate-expiry?warehouse_id={warehouse['id']}&days=60",
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200, response.text)
        notifications = response.json()

        self.assertEqual(len(notifications), 1)
        self.assertEqual(notifications[0]["notification_type"], "expiry")
        self.assertEqual(notifications[0]["batch_id"], batch["id"])
        self.assertEqual(notifications[0]["warehouse_id"], warehouse["id"])

    def test_sensor_warning_creates_notification_over_http(self) -> None:
        warehouse = self.post("/api/v1/warehouses", {"name": "Холодильная комната"})
        device = self.post(
            "/api/v1/sensor-devices",
            {
                "warehouse_id": warehouse["id"],
                "name": "Датчик холодильника",
                "serial_number": "USB-HTTP",
                "min_temperature_c": "2",
                "max_temperature_c": "8",
                "min_humidity_percent": "30",
                "max_humidity_percent": "70",
            },
        )

        reading = self.post(
            "/api/v1/sensor-readings",
            {
                "device_id": device["id"],
                "temperature_c": "11.5",
                "humidity_percent": "45",
                "raw_payload": "T=11.5 H=45",
            },
        )
        response = self.client.get(
            f"/api/v1/notifications?warehouse_id={warehouse['id']}",
            headers=self.headers,
        )

        self.assertEqual(reading["status"], "warning")
        self.assertEqual(response.status_code, 200, response.text)
        notifications = response.json()["items"]
        self.assertEqual(len(notifications), 1)
        self.assertEqual(notifications[0]["notification_type"], "sensor_warning")
        self.assertEqual(notifications[0]["device_id"], device["id"])
        self.assertEqual(notifications[0]["sensor_reading_id"], reading["id"])
        self.assertEqual(notifications[0]["warehouse_id"], warehouse["id"])

    def test_abc_xyz_analysis_flow_over_http(self) -> None:
        category = self.post("/api/v1/categories", {"name": "Аналитика"})
        supplier = self.post("/api/v1/suppliers", {"name": "ТОО Аналитик"})
        warehouse = self.post("/api/v1/warehouses", {"name": "Склад аналитики"})
        product = self.post(
            "/api/v1/products",
            {
                "name": "Катетер",
                "sku": "ANL-001",
                "unit": "шт",
                "category_id": category["id"],
                "reorder_point": "10",
                "safety_stock": "2",
            },
        )
        batch = self.post(
            "/api/v1/receipts",
            {
                "product_id": product["id"],
                "supplier_id": supplier["id"],
                "warehouse_id": warehouse["id"],
                "quantity": "12",
                "unit_price": "100",
                "lot": "ANL-HTTP",
                "quarantine": False,
            },
        )
        self.post(
            "/api/v1/write-offs",
            {
                "batch_id": batch["id"],
                "warehouse_id": warehouse["id"],
                "quantity": "5",
                "reason": "Расход для анализа",
            },
        )

        response = self.client.get(
            f"/api/v1/analytics/abc-xyz?warehouse_id={warehouse['id']}&days=90",
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200, response.text)
        analysis = response.json()
        rows = {row["product_id"]: row for row in analysis["items"]}

        self.assertEqual(analysis["warehouse_id"], warehouse["id"])
        self.assertEqual(rows[product["id"]]["abc_class"], "A")
        self.assertEqual(rows[product["id"]]["consumption_quantity"], "5")
        self.assertEqual(rows[product["id"]]["recommended_order_quantity"], "5")
        self.assertEqual(rows[product["id"]]["recommendation"], "Заказать в первую очередь")

    def test_purchase_request_generation_flow_over_http(self) -> None:
        category = self.post("/api/v1/categories", {"name": "Закупки"})
        supplier = self.post("/api/v1/suppliers", {"name": "ТОО Закуп"})
        warehouse = self.post("/api/v1/warehouses", {"name": "Склад закупок"})
        product = self.post(
            "/api/v1/products",
            {
                "name": "Перчатки",
                "sku": "PR-HTTP",
                "unit": "уп",
                "category_id": category["id"],
                "reorder_point": "10",
                "safety_stock": "2",
            },
        )
        self.post(
            "/api/v1/receipts",
            {
                "product_id": product["id"],
                "supplier_id": supplier["id"],
                "warehouse_id": warehouse["id"],
                "quantity": "6",
                "unit_price": "80",
                "lot": "PR-HTTP-1",
                "quarantine": False,
            },
        )

        response = self.client.post(
            f"/api/v1/purchase-requests/generate?warehouse_id={warehouse['id']}",
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200, response.text)
        generated = response.json()

        auto_response = self.client.post(
            f"/api/v1/purchase-requests/generate-auto?warehouse_id={warehouse['id']}",
            headers=self.headers,
        )
        self.assertEqual(auto_response.status_code, 200, auto_response.text)

        duplicate_response = self.client.post(
            f"/api/v1/purchase-requests/generate?warehouse_id={warehouse['id']}",
            headers=self.headers,
        )
        self.assertEqual(duplicate_response.status_code, 200, duplicate_response.text)
        manual_response = self.client.post(
            "/api/v1/purchase-requests",
            json={
                "warehouse_id": warehouse["id"],
                "product_id": product["id"],
                "quantity": "9",
                "reason": "Плановая закупка",
            },
            headers=self.headers,
        )
        self.assertEqual(manual_response.status_code, 201, manual_response.text)
        listed_response = self.client.get(
            f"/api/v1/purchase-requests?warehouse_id={warehouse['id']}",
            headers=self.headers,
        )
        self.assertEqual(listed_response.status_code, 200, listed_response.text)
        listed = listed_response.json()

        self.assertEqual(len(generated), 1)
        self.assertEqual(auto_response.json()[0]["id"], generated[0]["id"])
        self.assertEqual(duplicate_response.json()[0]["id"], generated[0]["id"])
        self.assertEqual(manual_response.json()["id"], generated[0]["id"])
        self.assertEqual(manual_response.json()["recommended_quantity"], "9")
        self.assertEqual(manual_response.json()["reason"], "Плановая закупка")
        self.assertEqual(len(listed), 1)
        self.assertEqual(generated[0]["product_id"], product["id"])
        self.assertEqual(generated[0]["status"], "draft")
        self.assertEqual(generated[0]["current_free_quantity"], "6")
        self.assertEqual(generated[0]["recommended_quantity"], "6")

    def test_repack_print_form_flow_over_http(self) -> None:
        category = self.post("/api/v1/categories", {"name": "Фасовка"})
        supplier = self.post("/api/v1/suppliers", {"name": "ТОО Фасовка"})
        warehouse = self.post("/api/v1/warehouses", {"name": "Склад фасовки"})
        source_product = self.post(
            "/api/v1/products",
            {
                "name": "Раствор 1 л",
                "sku": "RP-SRC",
                "unit": "бут",
                "category_id": category["id"],
            },
        )
        target_product = self.post(
            "/api/v1/products",
            {
                "name": "Раствор 100 мл",
                "sku": "RP-DST",
                "unit": "флакон",
                "category_id": category["id"],
            },
        )
        source_batch = self.post(
            "/api/v1/receipts",
            {
                "product_id": source_product["id"],
                "supplier_id": supplier["id"],
                "warehouse_id": warehouse["id"],
                "quantity": "10",
                "unit_price": "100",
                "lot": "RP-SRC-1",
                "quarantine": False,
            },
        )
        document_response = self.client.post(
            "/api/v1/stock-documents/repack",
            json={
                "warehouse_id": warehouse["id"],
                "lines": [
                    {
                        "batch_id": source_batch["id"],
                        "target_product_id": target_product["id"],
                        "quantity": "2",
                        "target_quantity": "20",
                        "conversion_factor": "10",
                        "loss_quantity": "0",
                        "target_lot": "RP-DST-1",
                        "reason": "Фасовка для отделения",
                    }
                ],
            },
            headers=self.headers,
        )
        self.assertEqual(document_response.status_code, 201, document_response.text)
        document = document_response.json()
        post_response = self.client.post(
            f"/api/v1/stock-documents/{document['id']}/post",
            json={"document_id": document["id"]},
            headers=self.headers,
        )
        self.assertEqual(post_response.status_code, 200, post_response.text)

        form_response = self.client.get(
            f"/api/v1/stock-documents/{document['id']}/repack-print-form",
            headers=self.headers,
        )
        self.assertEqual(form_response.status_code, 200, form_response.text)
        form = form_response.json()

        self.assertEqual(form["document_id"], document["id"])
        self.assertEqual(form["status"], "posted")
        self.assertEqual(form["warehouse_name"], "Склад фасовки")
        self.assertIn("Раствор 1 л", form["csv"])
        self.assertIn("RP-DST-1", form["csv"])

    def test_production_mode_rejects_header_only_auth_over_http(self) -> None:
        from app.api import dependencies
        from app.core.config import get_settings

        dependencies._database = None
        get_settings.cache_clear()

        with patch.dict(
            os.environ,
            {"SKLAD_DEV_AUTH_ENABLED": "false", "SKLAD_PUBLIC_ACCESS_ENABLED": "false"},
            clear=False,
        ):
            get_settings.cache_clear()
            response = self.client.get("/api/v1/balances", headers=self.headers)

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"]["code"], "unauthorized")
