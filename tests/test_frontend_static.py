from pathlib import Path
from unittest import TestCase
import json


ROOT = Path(__file__).resolve().parents[1]


class FrontendStaticTest(TestCase):
    def test_frontend_is_mounted_by_fastapi(self) -> None:
        main = (ROOT / "app" / "main.py").read_text()

        self.assertIn('app.mount("/app"', main)
        self.assertIn('app.mount("/sklad"', main)
        self.assertIn('app.include_router(router, prefix="/sklad")', main)
        self.assertIn("StaticFiles", main)

    def test_frontend_contains_operational_sklad_views(self) -> None:
        app = (ROOT / "frontend" / "app.js").read_text()

        for view in (
            "renderDashboard",
            "renderCatalog",
            "renderReceipts",
            "renderDocuments",
            "renderOperations",
            "renderRepacking",
            "renderReturns",
            "renderMovements",
            "renderReservations",
            "renderPurchaseRequests",
            "renderInventory",
            "renderConditions",
            "renderAnalytics",
            "renderNotifications",
            "renderAudit",
        ):
            with self.subTest(view=view):
                self.assertIn(view, app)

    def test_frontend_uses_backend_lists_and_selects(self) -> None:
        app = (ROOT / "frontend" / "app.js").read_text()
        css = (ROOT / "frontend" / "styles.css").read_text()

        for endpoint in (
            "/categories",
            "/suppliers",
            "/warehouses",
            "/product-units",
            "/products",
            "/batches",
            "/stock-documents",
            "/reservations",
            "/purchase-requests",
            "/inventory-sessions",
            "/sensor-devices",
            "/sensor-readings",
            "/stock-movements",
            "/batch-transformations",
            "/analytics/abc-xyz",
        ):
            with self.subTest(endpoint=endpoint):
                self.assertIn(endpoint, app)

        self.assertIn("optionsFrom", app)
        self.assertIn("pageItems", app)
        self.assertIn('type: "select"', app)
        for snippet in (
            "category-form",
            "supplier-form",
            "warehouse-form",
            "Новая категория",
            "Добавить категорию",
            "Новый поставщик",
            "Новый склад",
            "ID компании Tetis",
            "ID склада в Tetis",
            "Зона хранения",
            "Лимит вместимости",
            "Условия хранения",
            "Ответственный",
            "Серийный номер",
            "serial_number",
            "tetis_org_id: payload.tetis_org_id || null",
            "external_tetis_id: payload.external_tetis_id || null",
            "storage_zone: payload.storage_zone || null",
            "capacity_limit: payload.capacity_limit ? Number(payload.capacity_limit) : null",
            "storage_conditions: payload.storage_conditions || null",
            "responsible_person: payload.responsible_person || null",
            "catalog-overview",
            "catalog-guidance",
            "Заполните справочники по порядку",
            "Справочники готовы к работе",
            "quick-directory",
            "showCatalogEditModal",
            "catalogEditConfig",
            "data-edit-catalog",
            "data-edit-id",
            "Исправить",
            "data-delete-catalog",
            "data-delete-id",
            "function deleteCatalogEntry",
            "Скрыть запись",
            "Запись скрыта из справочника",
            "Справочник обновлен",
            ".compact-action",
            ".edit-modal",
            "Телефон",
            "phone: payload.phone || null",
            "Адрес",
            "Рейтинг",
            "Постоянный поставщик",
            "Контактное лицо",
            "Email",
            "Номер договора",
            "Договор действует до",
            "Условия оплаты",
            "Заметки",
            "function normalizeSupplierPayload",
            "address: payload.address || null",
            "rating: payload.rating ? Number(payload.rating) : null",
            "is_preferred: payload.is_preferred === true",
            "contact_person: payload.contact_person || null",
            "contract_expires_on: payload.contract_expires_on || null",
            "function showSupplierCard",
            "data-supplier-card",
            "Карточка",
            "Последние цены",
            "Точка заказа",
            "Страховой запас",
            "productUnits",
            "function productUnitOptions",
            'productUnitOptions("Выберите единицу")',
            "Штрихкод",
            "Сертификат",
            "Описание",
            "function normalizeProductPayload",
            "barcode: payload.barcode || null",
            "certificate_ref: payload.certificate_ref || null",
            "description: payload.description || null",
            'mutate("/categories", payload)',
            'mutate("/products", normalizeProductPayload(payload))',
            "removeResource",
            'mutate("/suppliers", normalizeSupplierPayload(payload))',
            'mutate("/warehouses"',
        ):
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, app + css)

    def test_frontend_supports_storage_condition_sensors(self) -> None:
        app = (ROOT / "frontend" / "app.js").read_text()
        css = (ROOT / "frontend" / "styles.css").read_text()

        for snippet in (
            "conditions",
            "Условия хранения",
            "sensorDevices",
            "sensorReadings",
            "renderConditions",
            "sensor-device-form",
            "sensor-reading-form",
            "/sensor-devices",
            "/sensor-readings",
            "conditionStatusSummary",
            "conditionChartPoints",
            "renderConditionChart",
            "latestConditionWarnings",
            "conditionBreachDetails",
            "conditionActionText",
            "Нужно проверить условия хранения",
            "График условий хранения",
            "Проверьте",
            "latestReadingForDevice",
            "Журнал температуры и влажности",
            "Внести показание",
            "Температура/влажность",
            "sklad-storage-conditions.csv",
            ".condition-alert",
            ".condition-warning-board",
            ".condition-warning-card",
            ".condition-chart",
            ".condition-chart-point",
            ".condition-chart-legend",
        ):
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, app + css)

    def test_frontend_supports_abc_xyz_matrix_and_history(self) -> None:
        app = (ROOT / "frontend" / "app.js").read_text()
        css = (ROOT / "frontend" / "styles.css").read_text()

        for snippet in (
            "abcXyzRuns",
            "abcXyzMatrixData",
            "abcXyzScatterPoints",
            "abcXyzRecommendation",
            "renderAbcXyzMatrix",
            "renderAbcXyzScatter",
            "Матрица ABC/XYZ",
            "Карта внимания ABC/XYZ",
            "История расчетов",
            "/analytics/abc-xyz/history",
            "/analytics/abc-xyz/runs",
            "save-abc-xyz-run",
            "sklad-abc-xyz-history.csv",
            ".abc-matrix",
            ".abc-cell",
            ".abc-cell.needs-order",
            ".abc-scatter",
            ".abc-scatter-point",
            ".abc-scatter-legend",
        ):
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, app + css)

    def test_frontend_supports_inventory_lines_and_returns(self) -> None:
        app = (ROOT / "frontend" / "app.js").read_text()
        css = (ROOT / "frontend" / "styles.css").read_text()

        for snippet in (
            "department-return-form",
            "supplier-return-form",
            "data-save-inventory-line",
            "inventorySessions",
            "function inventoryProgress",
            "function inventoryProgressText",
            "function inventorySummary",
            "function selectedInventorySession",
            "function inventoryCompletionPreview",
            "data-inventory-progress",
            "inventorySheet",
            "data-print-inventory",
            "data-print-inventory-reconciliation",
            "responsible_ids",
            "category_ids",
            "Выгрузить ведомость CSV",
            "Печать ведомости",
            "Сличительная ведомость",
            "Сличительная ведомость выгружена",
            "Проверить карантин",
            "Карантинные проверки",
            "data-quarantine-review",
            "data-quarantine-next-status",
            "/quarantine-reviews/${button.dataset.quarantineReview}",
            "/notifications/generate-quarantine",
            "Заполнено",
            "Недостачи",
            "Излишки",
            "Введите фактическое количество",
            ".inventory-progress",
            ".inventory-summary",
            "movements",
            "writeoff-form",
            'mutate("/write-offs"',
        ):
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, app + css)

    def test_frontend_exposes_labels_price_history_and_controlled_export(self) -> None:
        app = (ROOT / "frontend" / "app.js").read_text()

        for snippet in (
            "data-print-product-label",
            "/products/barcode-labels",
            "data-print-batch-price-label",
            "/price-label?symbology=ean13",
            "Ценник подготовлен",
            "data-export-price-history",
            "/price-history",
            "data-download-controlled-ledger",
            "/controlled-substances/ledger/export",
            "Журнал ПКУ выгружен",
        ):
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, app)

    def test_frontend_supports_multi_line_stock_documents(self) -> None:
        app = (ROOT / "frontend" / "app.js").read_text()

        for snippet in (
            "documentForms",
            "receiptDocumentLinesPayload",
            "writeoffDocumentLinesPayload",
            'data-doc-line-add="receipt"',
            'data-doc-line-add="writeoff"',
            "data-doc-line-remove",
            "data-doc-line-field",
            "receiptDocumentLinesTable",
            "writeoffDocumentLinesTable",
            "lines: receiptDocumentLinesPayload()",
            "lines: writeoffDocumentLinesPayload()",
            "data-download-transfer-form",
            "/transfer-print-form",
            "Печатная форма перемещения выгружена",
            "data-download-quarantine-protocol",
            "/quarantine-reviews/",
            "Протокол карантинной проверки выгружен",
        ):
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, app)

    def test_frontend_supports_repacking_workflow(self) -> None:
        app = (ROOT / "frontend" / "app.js").read_text()

        for snippet in (
            "repackings",
            "renderRepacking",
            "repacking-form",
            "Журнал фасовки",
            "/stock-documents/repack",
            "/batch-transformations",
            "normalizeRepackingPayload",
            "repackingPreview",
            "target_product_id",
            "target_quantity",
            "loss_quantity",
            "target_lot",
            "target_expires_on",
            "target_unit_price",
            "conversion_factor",
            "Цепочка фасовки",
            'data-export-report="repackings"',
            "data-download-repack-form",
            "/repack-print-form",
            "Печатная форма фасовки выгружена",
        ):
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, app)

    def test_frontend_has_safety_guards_for_dangerous_actions(self) -> None:
        app = (ROOT / "frontend" / "app.js").read_text()

        for snippet in (
            "confirmAction",
            "data-post-document",
            "data-approve-document",
            "data-cancel-document",
            "data-lock-warehouse",
            "/inventory-lock",
            "cancel-inventory",
            "/stock-documents/${button.dataset.cancelDocument}/cancel",
            "/stock-documents/${button.dataset.approveDocument}/approve",
            "/notifications/generate-expiry",
            "Остатки на складе не изменятся",
            "/returns/to-supplier",
            "/write-offs/fefo",
            "/transfers",
        ):
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, app)

    def test_frontend_uses_modal_confirmations_and_pending_state(self) -> None:
        app = (ROOT / "frontend" / "app.js").read_text()

        for snippet in (
            "function setPending",
            "function confirmAction",
            "new Promise",
            "modal-backdrop",
            "confirm-modal",
            'role="dialog"',
            "aria-modal",
            "await confirmAction",
            "node.dataset.pending",
            "aria-busy",
            "button.disabled",
            'tone === "danger" ? cancelButton : okButton',
        ):
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, app)

        self.assertNotIn("window.confirm", app)

    def test_frontend_shows_form_errors_near_the_form(self) -> None:
        app = (ROOT / "frontend" / "app.js").read_text()
        css = (ROOT / "frontend" / "styles.css").read_text()

        for snippet in (
            "function clearFormError",
            "function showFormError",
            ".form-error",
            'role", "alert"',
            'actions.insertAdjacentElement("beforebegin", item)',
            "showFormError(node, error.message)",
        ):
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, app + css)

    def test_frontend_uses_balance_aware_batches_and_realtime(self) -> None:
        app = (ROOT / "frontend" / "app.js").read_text()
        css = (ROOT / "frontend" / "styles.css").read_text()

        for snippet in (
            "function batchOptions",
            "function selectedBatchSummary",
            "function selectedBatchSummaryHtml",
            "function showBatchTraceability",
            "function renderBatchTraceability",
            "function downloadCsv",
            "function exportReport",
            "function updateBatchAwareForm",
            "function operationPreview",
            "function recallPreview",
            "data-batch-aware",
            "data-selected-batch-summary",
            "data-batch-detail",
            "data-export-report",
            "data-batch-warehouse-field",
            "bindBatchAwareForms",
            "/batches/${batchId}/traceability?limit=50",
            ".batch-summary",
            ".inventory-progress",
            ".trace-modal",
            ".trace-summary",
            ".compact-trace-table",
            "Открыть карточку партии",
            "Выгрузить CSV",
            "Где лежит партия",
            "Отзывы партии",
            "Последние движения",
            "На складе останется",
            "free_quantity",
            "batch_status",
            "new WebSocket",
            "/ws/balances",
            "stock.balance.updated",
            "stock.transfer.posted",
            "stock.return.posted",
            "batch.recalled",
            "batch.status.updated",
            "inventory.posted",
        ):
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, app + css)

    def test_frontend_supports_batch_recall_workflow(self) -> None:
        app = (ROOT / "frontend" / "app.js").read_text()

        for snippet in (
            "batch-recall-form",
            "Отзыв партии",
            "batchRecalls",
            "/batch-recalls",
            "Журнал отзывов партий",
            "sklad-batch-recalls.csv",
            'data-export-report="batchRecalls"',
            "Отозвать и заблокировать",
            "/batches/${batchId}/recall",
            "recallPreview",
            "reference: payload.reference || null",
            "Партия будет заблокирована",
        ):
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, app)

    def test_frontend_summarizes_visible_balances_for_non_it_users(self) -> None:
        app = (ROOT / "frontend" / "app.js").read_text()
        css = (ROOT / "frontend" / "styles.css").read_text()

        for snippet in (
            "function balanceSummary",
            'aria-label="Краткая сводка остатков"',
            "Позиции",
            "Товары",
            "Склады",
            "Партии с остатком",
            "Свободно к использованию",
            "Срок до 30 дней",
            "balanceSummary(rows)",
            ".balance-summary",
            "grid-template-columns: repeat(6, minmax(0, 1fr))",
        ):
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, app + css)

    def test_frontend_supports_bearer_auth_token(self) -> None:
        app = (ROOT / "frontend" / "app.js").read_text()
        html = (ROOT / "frontend" / "index.html").read_text()

        for snippet in (
            'id="auth-token"',
            "Authorization",
            "Bearer ${authToken}",
            "access_token",
            '\"auth-token\"',
        ):
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, app + html)

    def test_frontend_handles_auth_required_as_login_state(self) -> None:
        app = (ROOT / "frontend" / "app.js").read_text()

        for snippet in (
            "class AuthRequiredError extends Error",
            "response.status === 401",
            "throw new AuthRequiredError(message)",
            "if (error instanceof AuthRequiredError) throw error",
            "state.auth.blockedMessage",
            "Сервер требует вход",
            "if (!state.auth.blockedMessage) {\n    connectRealtime();",
        ):
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, app)

    def test_frontend_surfaces_optional_load_failures(self) -> None:
        app = (ROOT / "frontend" / "app.js").read_text()
        css = (ROOT / "frontend" / "styles.css").read_text()

        for snippet in (
            "loadWarnings",
            "loadOptional",
            "ApiError",
            "[401, 403, 404].includes(error.status)",
            "раздел не загрузился, обновите страницу",
            "escapeHtml(warning)",
            "warning-panel",
            "Документы",
            "Движения",
            "Журнал действий",
            "Карантинные проверки",
            "Заявки на закупку",
        ):
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, app)
        self.assertIn(".warning-panel", css)

    def test_frontend_keeps_optional_dashboard_endpoints_soft_fail(self) -> None:
        app = (ROOT / "frontend" / "app.js").read_text()

        for snippet in (
            'loadOptional("Бронирование", request(`/reservations',
            'loadOptional("Карантинные проверки", request(`/quarantine-reviews',
            'loadOptional("Заявки на закупку", request(`/purchase-requests',
            'loadOptional("Журнал действий", request(`/audit-log',
            'loadOptional("Документы", request(`/stock-documents',
            'loadOptional("Инвентаризация", request(`/inventory-sessions',
            'loadOptional("Движения", request(`/stock-movements',
            'loadOptional("Аналитика", request(`/analytics/abc-xyz',
            'request(`/notifications${query ? `${query}&limit=100` : "?limit=100"}`)',
        ):
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, app)

    def test_frontend_handles_non_json_api_and_realtime_payloads(self) -> None:
        app = (ROOT / "frontend" / "app.js").read_text()

        for snippet in (
            "function parseJson",
            "parseJson(text)",
            "body?.message",
            "response.statusText || `HTTP ${response.status}`",
            "parseJson(event.data, {})",
        ):
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, app)

    def test_frontend_has_operational_dashboard_controls(self) -> None:
        app = (ROOT / "frontend" / "app.js").read_text()
        html = (ROOT / "frontend" / "index.html").read_text()
        css = (ROOT / "frontend" / "styles.css").read_text()

        for snippet in (
            'id="global-search"',
            'aria-label="Глобальный поиск по складу"',
            'id="density-button"',
            'aria-pressed="false"',
            "state.ui.search",
            "filteredBalances",
            "filteredRows",
            "actionQueue",
            "renderActionQueue",
            "setupSteps",
            "renderSetupGuide",
            "receiptPrerequisites",
            "workflowNotice",
            "needsStockNotice",
            "needsWarehouseNotice",
            "needsProductNotice",
            "disabledSubmit",
            "submitHint",
            "form-hint",
            "Сначала примите товар на склад.",
            "Сначала создайте товар.",
            "Сначала добавьте склад.",
            "Первый запуск",
            "Что сделать, чтобы склад начал работать",
            "Примите первую партию",
            "Приход пока нельзя оформить",
            "Нет доступных остатков",
            "Склад еще не создан",
            "Товары еще не созданы",
            "control-strip",
            "setup-guide",
            "setup-step",
            "receipt-prerequisites",
            "workflow-notice",
            ".form-hint",
            "table-summary",
            "Найдено записей",
            "searchNotice",
            "searchEmptyText",
            "data-clear-search",
            "Показаны результаты по запросу",
            "Сбросить",
            "data-go-view",
            "applyDensity",
            ".search-banner",
        ):
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, app + html + css)

    def test_frontend_css_covers_accessibility_and_dense_tables(self) -> None:
        css = (ROOT / "frontend" / "styles.css").read_text()

        for snippet in (
            ":focus-visible",
            "position: sticky",
            "body.compact",
            ".search-input",
            ".search-banner",
            ".action-list",
            ".empty-state",
            ".modal-backdrop",
            ".confirm-modal",
            ".trace-modal",
            ".link-button",
            ".compact-trace-table",
            ".confirm-message",
            ".pending",
            "button[disabled]",
            ".helper-text",
            ".table-summary",
            ".row-actions",
            "@media (max-width: 620px)",
        ):
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, css)

    def test_frontend_escapes_user_controlled_text(self) -> None:
        app = (ROOT / "frontend" / "app.js").read_text()

        for snippet in (
            "function escapeHtml",
            "function escapeAttr",
            "escapeHtml(row[col.key] ??",
            "escapeHtml(label(item))",
            "rawNameById",
            "escapeHtml(row.title)",
            "escapeHtml(JSON.stringify(row.payload)",
        ):
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, app)

    def test_frontend_uses_plain_language_for_non_it_users(self) -> None:
        app = (ROOT / "frontend" / "app.js").read_text()
        html = (ROOT / "frontend" / "index.html").read_text()

        for snippet in (
            "Рабочее место склада",
            "Работаем как",
            "Настройки администратора",
            "Система доступна",
            "Нет связи с сервером",
            "Компактный вид",
            "Обычный вид",
            "Главная",
            "Товары и склады",
            "Списать / переместить",
            "Журнал действий",
            "Аналитика",
            "ABC/XYZ анализ и заказ",
            "Рекомендация",
            "humanStatus",
            "humanDocumentType",
            "humanNotificationType",
            "Проверить сроки годности",
            "Открыть карточку партии",
            "ПКУ / контролируемый товар",
            "Выгрузить CSV",
            "Где лежит партия",
            "Последние движения",
            "Сначала создайте товар",
            "Документов пока нет",
            "Брони пока нет",
            "Заявки на закупку",
            "Сессий пока нет",
        ):
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, app + html)

        visible_html = html.split("Настройки администратора", maxsplit=1)[0]
        self.assertNotIn("JWT", visible_html)
        self.assertNotIn("Bearer", visible_html)
        self.assertNotIn("API", visible_html)

    def test_frontend_preserves_controlled_writeoff_fields(self) -> None:
        app = (ROOT / "frontend" / "app.js").read_text()

        for snippet in (
            "function productForBatch",
            "function isControlledProduct",
            "function controlledWriteoffMetadataMissing",
            "function applyControlledWriteoffRequirements",
            "patient_id: line.patient_id || null",
            "doctor_id: line.doctor_id || null",
            "medical_record_no: line.medical_record_no || null",
            "second_approver_id: line.second_approver_id || null",
            "second_approval_note: line.second_approval_note || null",
            "Для ПКУ заполните пациента, врача, номер истории болезни и второго подтверждающего",
            "2-й подтверждающий",
            "Комментарий ПКУ",
            "showFormError(node",
            "trim()",
            "ПКУ / контролируемый товар",
            "is_controlled",
        ):
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, app)

    def test_frontend_blocks_controlled_document_posting_without_metadata(self) -> None:
        app = (ROOT / "frontend" / "app.js").read_text()
        css = (ROOT / "frontend" / "styles.css").read_text()

        for snippet in (
            "function controlledWriteoffDocumentIssues",
            "writeoffDocumentLinesTable",
            "data-doc-line-field",
            "data-post-document",
            'document.document_type !== "write_off"',
            'Object.prototype.hasOwnProperty.call(line, "patient_id")',
            "line.patient_id",
            "line.doctor_id",
            "line.medical_record_no",
            "line.second_approver_id",
            "Провести документ нельзя",
            "controlled-warning",
            ".controlled-required",
        ):
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, app + css)

    def test_frontend_has_role_aware_navigation_and_tablet_writeoff(self) -> None:
        app = (ROOT / "frontend" / "app.js").read_text()

        for snippet in (
            '["tablet-writeoff", `<svg',
            '"Списание"],',
            'const limitedRoleViews = new Set(["dashboard", "tablet-writeoff", "stock", "movements", "notifications", "support"])',
            'const limitedRoles = new Set(["nurse", "doctor", "other"])',
            "function visibleViews()",
            "function canAccessView(viewId)",
            "function ensureAccessibleView()",
            "function safeViewTarget(viewId)",
            'state.view = isLimitedRole() ? "tablet-writeoff" : "dashboard"',
            "const allowedIds = new Set(visibleViews().map",
            "return renderLimitedDashboard()",
            "function roleAccessNotice()",
            "Упрощенный режим",
            "Административные операции скрыты на фронте",
        ):
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, app)

    def test_frontend_has_tablet_writeoff_flow(self) -> None:
        app = (ROOT / "frontend" / "app.js").read_text()
        css = (ROOT / "frontend" / "styles.css").read_text()

        for snippet in (
            "function tabletWriteoffForm()",
            'form("tablet-writeoff-form"',
            'batchOptions("Выберите партию с остатком")',
            'batchWarehouseField: "warehouse_id"',
            'value: "Списание в отделении"',
            'value: currentRole() === "doctor" ? currentActorId() : ""',
            'bindSubmit("tablet-writeoff-form", (payload) => mutate("/write-offs", payload)',
            'applyControlledWriteoffRequirements(node, payload)',
            'operationPreview("writeoff", payload)',
            ".tablet-writeoff-panel",
            ".tablet-copy",
            ".tablet-writeoff-panel input",
            ".tablet-writeoff-panel .primary",
            "min-height: 48px",
        ):
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, app + css)

    def test_frontend_supports_purchase_requests_and_reservation_use(self) -> None:
        app = (ROOT / "frontend" / "app.js").read_text()

        for snippet in (
            '["purchase-requests", `<svg',
            '"Заявки"],',
            "purchaseRequests",
            "function renderPurchaseRequests",
            "function suggestedPurchaseRequests",
            "purchase-request-form",
            "data-action=\"generate-purchase-requests\"",
            "data-purchase-status",
            "data-purchase-next-status",
            "Сформировать автозаявки",
            'mutate("/purchase-requests", payload)',
            "/purchase-requests/${button.dataset.purchaseStatus}",
            "/purchase-requests/generate-auto",
            "loadOptional(\"Заявки на закупку\"",
            "data-use-reservation",
            "/reservations/${button.dataset.useReservation}/use",
            "Использовать резерв",
            "Заявок пока нет",
            "Автоматических рекомендаций пока нет",
        ):
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, app)

    def test_frontend_supports_tetis_sso_context(self) -> None:
        app = (ROOT / "frontend" / "app.js").read_text()
        html = (ROOT / "frontend" / "index.html").read_text()
        css = (ROOT / "frontend" / "styles.css").read_text()

        for snippet in (
            'window.localStorage',
            'window.sessionStorage',
            'storage.getItem("org-storage")',
            "org_id: orgId",
            'fetch("/api/v1/sklad/token"',
            'credentials: "include"',
            "state.auth.blockedMessage = \"\"",
            "renderAuthBlocked",
            "state.auth.source = \"demo\"",
            ".auth-blocked",
            'request("/me")',
            "Профиль доступа к складу не содержит роль",
            "const primaryRole = profile.roles[0]",
            "function hasPermission",
            'hasPermission("audit:read")',
            "function reconcileWarehouseScope",
            "function activeTetisOrgId",
            "warehouse.tetis_org_id",
            "orgWarehouses.map((warehouse) => warehouse.id).join",
            "const originalScoped = scopedWarehouseIds()",
            "reconcileWarehouseScope();",
            "const wf = warehouseFilterParam();",
            'document.body.classList.toggle("tetis-auth"',
            'id="auth-context"',
            'class="demo-auth-field"',
            "body.tetis-auth .demo-auth-field",
            "body.tetis-auth .advanced-settings",
            "managerOnlyViews",
        ):
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, app + html + css)

        self.assertNotIn('profile.roles?.[0] || "warehouse_manager"', app)
        self.assertNotIn("Администратор должен связать компанию Tetis со складами SKLAD", app)

    def test_frontend_declares_pwa_manifest_and_service_worker(self) -> None:
        html = (ROOT / "frontend" / "index.html").read_text()

        for snippet in (
            '<meta name="theme-color" content="#25636f" />',
            '<link rel="manifest" href="manifest.webmanifest" />',
            '"serviceWorker" in navigator',
            '.register("service-worker.js", { scope: "./" })',
            "registration.update()",
            "controllerchange",
        ):
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, html)

    def test_frontend_manifest_is_scoped_to_tablet_app_shell(self) -> None:
        manifest = json.loads((ROOT / "frontend" / "manifest.webmanifest").read_text())

        self.assertEqual(manifest["id"], ".")
        self.assertEqual(manifest["start_url"], ".")
        self.assertEqual(manifest["scope"], ".")
        self.assertEqual(manifest["display"], "standalone")
        self.assertEqual(manifest["orientation"], "landscape-primary")
        self.assertEqual(manifest["theme_color"], "#25636f")
        self.assertEqual(manifest["background_color"], "#f5f7f8")

    def test_frontend_service_worker_caches_only_app_shell_assets(self) -> None:
        worker = (ROOT / "frontend" / "service-worker.js").read_text()

        for snippet in (
            'const CACHE_NAME = "sklad-pwa-shell-v',
            "const APP_SCOPE = new URL(self.registration.scope).pathname",
            "`${APP_SCOPE}app.js?v=",
            "`${APP_SCOPE}styles.css`",
            "`${APP_SCOPE}manifest.webmanifest`",
            "`${APP_SCOPE}html5-qrcode.min.js`",
            'cache.addAll(APP_SHELL)',
            'event.request.mode === "navigate"',
            "caches.match(APP_SCOPE)",
            "url.pathname.startsWith(APP_SCOPE)",
        ):
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, worker)

    def test_qpartner_marketplace_actions_mark_source_channel(self) -> None:
        app = (ROOT / "frontend" / "app.js").read_text()

        for snippet in (
            'const body = { quantity: Number(fd.get("quantity")), source: "qpartner" };',
            'const body = { product_name: productName, quantity: Number(fd.get("quantity")), source: "qpartner" };',
            'body: JSON.stringify({ source: "qpartner" })',
            "function marketplaceInquirySourceBadge",
            "marketplaceInquirySourceBadge(inq.source)",
            "function marketplaceInquirySourceQuery",
            "function marketplaceInquiryStatusQuery",
            "function marketplaceInquiryStatusFilter",
            "function marketplaceInquiryFiltersActive",
            "function marketplaceInquiryFilterBar",
            "function myInquiriesPath",
            "function supplierInquiriesPath",
            "mp-inquiry-filter-reset",
            "mp-inquiry-empty-reset",
            "mp-inquiry-source-filter",
            "mp-inquiry-status-filter",
            "supplier-inquiry-filter-reset",
            "supplier-inquiry-empty-reset",
            "supplier-inquiry-source-filter",
            "supplier-inquiry-status-filter",
            "По выбранным фильтрам заявок нет",
            "По выбранным фильтрам входящих запросов нет",
            "state.ui.marketplaceInquirySourceFilter",
            "state.ui.marketplaceInquiryStatusFilter",
            "state.ui.supplierInquirySourceFilter",
            "state.ui.supplierInquiryStatusFilter",
            'label: "marqet.kz"',
            'label: "qpartner"',
        ):
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, app)
