const APP_BASE = window.location.pathname.startsWith("/sklad") ? "/sklad" : "";
const API = `${APP_BASE}/api/v1`;

const state = {
  view: "dashboard",
  realtime: "offline",
  loadWarnings: [],
  auth: {
    source: "demo",
    actor: null,
    blockedMessage: "",
    supplierId: null,
  },
  ui: {
    density: "comfortable",
    search: "",
    supplierMode: false,
    supplierTab: "offers",
    marketplaceType: null,
    marketplaceCategory: null,
  },
  data: {
    health: null,
    readiness: null,
    categories: [],
    suppliers: [],
    warehouses: [],
    productUnits: [],
    products: [],
    batches: [],
    batchRecalls: { items: [], total: 0 },
    balances: { items: [], total: 0 },
    reservations: [],
    quarantineReviews: { items: [], total: 0 },
    purchaseRequests: [],
    notifications: { items: [], total: 0 },
    audit: { items: [], total: 0 },
    documents: [],
    inventorySessions: [],
    movements: [],
    repackings: { items: [], total: 0 },
    analytics: { items: [], analysis_days: 90, warehouse_id: null, generated_at: null },
    abcXyzRuns: { items: [], total: 0 },
    sensorDevices: [],
    sensorReadings: { items: [], total: 0 },
    supplierApplication: null,
    supplierOpenPurchaseRequests: [],
    supplierOffers: [],
    supplierAdminOffers: [],
    supplierApplications: [],
    supplierCatalog: [],
    marketplace: { items: [], total: 0 },
  },
  documentForms: {
    receipt: {
      supplier_id: "",
      warehouse_id: "",
      lines: [{ product_id: "", quantity: "", unit_price: "0", lot: "", serial_number: "", expires_on: "" }],
    },
    writeoff: {
      warehouse_id: "",
      lines: [{ batch_id: "", quantity: "", reason: "Списание по документу", patient_id: "", doctor_id: "", medical_record_no: "", second_approver_id: "", second_approval_note: "" }],
    },
  },
};

let balanceSocket = null;
let realtimeRefreshTimer = null;

class AuthRequiredError extends Error {
  constructor(message) {
    super(message);
    this.name = "AuthRequiredError";
  }
}

class ApiError extends Error {
  constructor(message, status, code = "") {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

const views = [
  ["dashboard", "▦", "Главная"],
  ["tablet-writeoff", "−", "Списание"],
  ["catalog", "≡", "Товары и склады"],
  ["receipts", "+", "Приход товара"],
  ["documents", "▤", "Документы"],
  ["operations", "⇄", "Списать / переместить"],
  ["repacking", "⇆", "Фасовка"],
  ["returns", "↩", "Возвраты"],
  ["movements", "↕", "История склада"],
  ["reservations", "◇", "Бронирование"],
  ["purchase-requests", "⌑", "Заявки"],
  ["inventory", "□", "Инвентаризация"],
  ["conditions", "≋", "Условия хранения"],
  ["analytics", "◎", "Аналитика"],
  ["marketplace", "◈", "Маркетплейс"],
  ["notifications", "!", "Уведомления"],
  ["audit", "⌕", "Журнал действий"],
  ["supplier-portal", "◉", "Поставщик"],
];

const limitedRoleViews = new Set(["dashboard", "tablet-writeoff", "movements", "notifications"]);
const limitedRoles = new Set(["nurse", "doctor", "other"]);
const managerOnlyViews = new Set(["audit"]);
const supplierOnlyViews = new Set(["supplier-portal", "marketplace"]);

const el = (id) => document.getElementById(id);

function readTetisToken() {
  for (const storage of [window.localStorage, window.sessionStorage]) {
    try {
      const raw = storage.getItem("auth-storage");
      if (!raw) continue;
      const token = JSON.parse(raw)?.state?.token;
      if (typeof token === "string" && token.trim()) return token.trim();
    } catch {
      continue;
    }
  }
  return "";
}

function readTetisActiveOrgId() {
  for (const storage of [window.localStorage, window.sessionStorage]) {
    try {
      const raw = storage.getItem("org-storage");
      if (!raw) continue;
      const orgId = JSON.parse(raw)?.state?.activeOrgId;
      if (typeof orgId === "string" && orgId.trim()) return orgId.trim();
    } catch {
      continue;
    }
  }
  return "";
}

function activeTetisOrgId() {
  return readTetisActiveOrgId();
}

async function requestSkladTokenFromTetis() {
  if (!window.location.pathname.startsWith("/sklad")) return false;
  const tetisToken = readTetisToken();
  if (!tetisToken) {
    el("auth-token").value = "";
    state.auth.source = "demo";
    state.auth.blockedMessage = "";
    return false;
  }
  const orgId = readTetisActiveOrgId();
  const response = await fetch("/api/v1/sklad/token", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(tetisToken ? { Authorization: `Bearer ${tetisToken}` } : {}),
    },
    credentials: "include",
    body: JSON.stringify(orgId ? { org_id: orgId } : {}),
  });
  if (!response.ok) return false;
  const payload = await response.json();
  if (!payload?.access_token) return false;
  el("auth-token").value = payload.access_token;
  state.auth.source = "tetis";
  state.auth.blockedMessage = "";
  return true;
}

function applyActorProfile(profile) {
  if (!profile) return;
  if (!Array.isArray(profile.roles) || !profile.roles.length) {
    throw new Error("Профиль доступа к складу не содержит роль. Обратитесь к администратору Tetis.");
  }
  state.auth.actor = profile;
  el("actor-id").value = profile.actor_id || el("actor-id").value || "tetis-user";
  const primaryRole = profile.roles[0];
  el("actor-role").value = primaryRole;
  el("actor-warehouses").value = (profile.warehouse_ids || []).join(",");
  document.body.classList.toggle("tetis-auth", state.auth.source === "tetis");
  const context = el("auth-context");
  if (context) {
    const warehouses = profile.warehouse_ids?.length
      ? `Склады: ${profile.warehouse_ids.join(", ")}`
      : "Доступ ко всем складам";
    context.textContent = state.auth.source === "tetis"
      ? `Вход через Tetis: ${profile.actor_id}. ${warehouses}.`
      : "Демо-режим: роль и доступ задаются вручную.";
  }
  updateSupplierContext();
  state.auth.supplierId = profile.supplier_id ?? null;
  const canBeSupplier = state.auth.source === "demo" || ((profile.roles || []).includes("supplier") && profile.supplier_id != null);
  const supplierToggle = el("supplier-mode-toggle");
  if (supplierToggle) {
    supplierToggle.style.display = canBeSupplier ? "" : "none";
    if (!canBeSupplier) state.ui.supplierMode = false;
  }
  const becomeSupplierBtn = el("become-supplier-button");
  if (becomeSupplierBtn) {
    becomeSupplierBtn.style.display = (!canBeSupplier && state.auth.source === "tetis") ? "" : "none";
  }
}

async function toggleSupplierMode() {
  state.ui.supplierMode = !state.ui.supplierMode;
  if (state.ui.supplierMode) {
    state.view = "supplier-portal";
  }
  render();
}

function headers(extra = {}) {
  const authToken = el("auth-token").value.trim();
  const shouldSendAuthToken = state.auth.source === "tetis" && authToken;
  return {
    "Content-Type": "application/json",
    "X-Actor-Id": el("actor-id").value || "manager",
    "X-Actor-Roles": el("actor-role").value || "warehouse_manager",
    "X-Actor-Warehouse-Ids": el("actor-warehouses").value || "",
    ...(shouldSendAuthToken ? { Authorization: `Bearer ${authToken}` } : {}),
    ...extra,
  };
}

function warehouseFilterParam() {
  const role = el("actor-role").value;
  const warehouseId = el("warehouse-filter").value;
  if (warehouseId) return `warehouse_id=${encodeURIComponent(warehouseId)}`;
  if (role !== "warehouse_manager") {
    const firstScopedWarehouse = (el("actor-warehouses").value || "")
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean)[0];
    return firstScopedWarehouse ? `warehouse_id=${encodeURIComponent(firstScopedWarehouse)}` : "";
  }
  return "";
}

function scopedWarehouseIds() {
  return (el("actor-warehouses").value || "")
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);
}

function reconcileWarehouseScope() {
  const available = new Set(state.data.warehouses.map((warehouse) => String(warehouse.id)));
  const originalScoped = scopedWarehouseIds();
  const validScoped = originalScoped.filter((warehouseId) => available.has(String(warehouseId)));
  if (validScoped.length !== originalScoped.length) {
    el("actor-warehouses").value = validScoped.join(",");
  }
  updateWarehouseSelector();
  const selected = el("warehouse-filter").value;
  if (selected && !available.has(String(selected))) {
    el("warehouse-filter").value = "";
  }
  const orgId = activeTetisOrgId();
  const orgWarehouses = orgId
    ? state.data.warehouses.filter((warehouse) => String(warehouse.tetis_org_id || "") === String(orgId))
    : [];
  if (state.auth.source === "tetis" && originalScoped.length && !validScoped.length && orgWarehouses.length) {
    el("actor-warehouses").value = orgWarehouses.map((warehouse) => warehouse.id).join(",");
    updateWarehouseSelector();
    if (!el("warehouse-filter").value && orgWarehouses.length === 1) {
      el("warehouse-filter").value = String(orgWarehouses[0].id);
    }
    return;
  }
}

function currentRole() {
  return el("actor-role")?.value || "warehouse_manager";
}

function hasPermission(permission) {
  const permissions = state.auth.actor?.permissions || [];
  if (!permissions.length && state.auth.source !== "tetis") {
    return currentRole() === "warehouse_manager";
  }
  return permissions.includes(permission);
}

function hasSupplierAccess() {
  return hasPermission("supplier:profile:read") || Boolean(state.data.supplierApplication);
}

function currentActorId() {
  return el("actor-id")?.value || "";
}

function isLimitedRole() {
  return limitedRoles.has(currentRole());
}

function visibleViews() {
  const allowed = isLimitedRole() ? views.filter(([id]) => limitedRoleViews.has(id)) : views;
  return allowed.filter(([id]) => canAccessView(id));
}

function canAccessView(viewId) {
  if (managerOnlyViews.has(viewId) && !hasPermission("audit:read")) return false;
  if (supplierOnlyViews.has(viewId)) return true;
  if (!hasPermission("stock:read") && hasSupplierAccess()) return viewId === "supplier-portal";
  return !isLimitedRole() || limitedRoleViews.has(viewId);
}

function ensureAccessibleView() {
  if (canAccessView(state.view) && renderers[state.view]) return;
  if (!hasPermission("stock:read") && hasSupplierAccess()) {
    state.view = "supplier-portal";
    return;
  }
  state.view = isLimitedRole() ? "tablet-writeoff" : "dashboard";
}

function safeViewTarget(viewId) {
  if (canAccessView(viewId)) return viewId;
  return isLimitedRole() ? "tablet-writeoff" : viewId;
}

function roleAccessNotice() {
  if (!isLimitedRole()) return "";
  return `
    <div class="role-notice">
      <strong>Упрощенный режим</strong>
      <span>Для этой роли в меню оставлены списание, остатки, история и уведомления. Административные операции скрыты на фронте.</span>
    </div>
  `;
}

function supplierApplicationStatusText(application = state.data.supplierApplication) {
  if (!application) return "Профиль поставщика еще не подключен.";
  if (application.status === "approved") return `Поставщик активен: ${application.supplier_name || application.name}.`;
  if (application.status === "pending") return "Заявка поставщика отправлена и ожидает проверки на Tetis.";
  if (application.status === "needs_changes") return `Заявка требует правок${application.review_reason ? `: ${application.review_reason}` : "."}`;
  if (application.status === "rejected") return `Заявка отклонена${application.review_reason ? `: ${application.review_reason}` : "."}`;
  if (application.status === "suspended") return `Профиль поставщика приостановлен${application.review_reason ? `: ${application.review_reason}` : "."}`;
  return `Статус поставщика: ${humanStatus(application.status)}.`;
}

function updateSupplierContext() {
  const node = el("supplier-context");
  if (!node) return;
  const application = state.data.supplierApplication;
  const canApply = !application || ["rejected", "needs_changes"].includes(application.status);
  node.innerHTML = `
    <div class="supplier-context-card">
      <span>${escapeHtml(supplierApplicationStatusText(application))}</span>
      <div class="row-actions">
        ${application?.status === "approved" ? '<button class="secondary compact-action" type="button" data-go-view="supplier-portal">Кабинет поставщика</button>' : ""}
        ${canApply ? '<button class="secondary compact-action" type="button" data-go-view="supplier-portal">Стать поставщиком</button>' : ""}
      </div>
    </div>
  `;
  node.querySelectorAll("[data-go-view]").forEach((button) => {
    button.addEventListener("click", () => {
      state.view = safeViewTarget(button.dataset.goView);
      render();
    });
  });
}

async function request(path, options = {}) {
  const response = await fetch(`${API}${path}`, {
    ...options,
    headers: headers(options.headers || {}),
  });
  const text = await response.text();
  const body = parseJson(text);
  if (!response.ok) {
    const message = body?.detail?.message || body?.detail || body?.message || response.statusText || `HTTP ${response.status}`;
    if (response.status === 401) {
      throw new AuthRequiredError(message);
    }
    throw new ApiError(message, response.status, body?.detail?.code || body?.code || "");
  }
  return body;
}

function parseJson(text, fallback = null) {
  if (!text) return fallback;
  try {
    return JSON.parse(text);
  } catch {
    return fallback;
  }
}

function escapeHtml(value) {
  return String(value ?? "—")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function escapeAttr(value) {
  return escapeHtml(value);
}

function csvCell(value) {
  const text = String(value ?? "").replaceAll('"', '""');
  return `"${text}"`;
}

function downloadCsv(filename, columns, rows) {
  const header = columns.map((column) => csvCell(column.label)).join(",");
  const body = rows.map((row) => columns.map((column) => {
    const value = column.value ? column.value(row) : row[column.key];
    return csvCell(value);
  }).join(","));
  const blob = new Blob([[header, ...body].join("\n")], { type: "text/csv;charset=utf-8" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  URL.revokeObjectURL(link.href);
  link.remove();
}

function downloadText(filename, text, type = "text/plain;charset=utf-8") {
  const blob = new Blob([text], { type });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  URL.revokeObjectURL(link.href);
  link.remove();
}

async function mutate(path, payload, method = "POST") {
  return request(path, {
    method,
    headers: { "Idempotency-Key": crypto.randomUUID() },
    body: JSON.stringify(payload),
  });
}

async function removeResource(path) {
  return request(path, {
    method: "DELETE",
    headers: { "Idempotency-Key": crypto.randomUUID() },
  });
}

function showAlert(message, type = "success") {
  const item = document.createElement("div");
  item.className = `alert ${type}`;
  item.textContent = message;
  el("alerts").replaceChildren(item);
  window.setTimeout(() => item.remove(), 4200);
}

function clearFormError(formElement) {
  formElement.querySelector(".form-error")?.remove();
}

function showFormError(formElement, message) {
  clearFormError(formElement);
  const item = document.createElement("div");
  item.className = "form-error full";
  item.setAttribute("role", "alert");
  item.textContent = message;
  const actions = formElement.querySelector(".actions");
  if (actions) {
    actions.insertAdjacentElement("beforebegin", item);
    return;
  }
  formElement.appendChild(item);
}

function money(value) {
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

function qty(value) {
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

function dateText(value) {
  if (!value) return "—";
  return new Date(value).toLocaleString("ru-RU");
}

function badge(value) {
  const text = String(value ?? "—");
  let cls = "badge";
  if (["available", "posted", "active", "ok", "succeeded"].includes(text)) cls += " ok";
  if (["quarantine", "draft", "approved", "processing", "warning"].includes(text)) cls += " warn";
  if (["blocked", "cancelled", "failed", "released"].includes(text)) cls += " bad";
  return `<span class="${cls}">${escapeHtml(humanStatus(text))}</span>`;
}

function humanStatus(value) {
  return ({
    active: "Активно",
    approved: "Допущено",
    available: "Можно использовать",
    blocked: "Заблокировано",
    cancelled: "Отменено",
    draft: "Черновик",
    failed: "Ошибка",
    in_review: "На проверке",
    locked: "Заблокировано",
    ok: "В порядке",
    open: "Открыто",
    posted: "Проведен",
    processing: "В обработке",
    quarantine: "Карантин",
    pending: "Ожидает проверки",
    read: "Прочитано",
    received: "Получено",
    repack: "Фасовка",
    repack_in: "Результат фасовки",
    repack_out: "Исходная партия",
    receipt: "Приход",
    requested: "Запрошено",
    rejected: "Забраковано",
    needs_changes: "Нужны правки",
    released: "Снято",
    return_from_department: "Возврат от отделения",
    return_to_supplier: "Возврат поставщику",
    sent: "Отправлено",
    submitted: "Отправлено",
    succeeded: "Выполнено",
    suspended: "Приостановлено",
    transfer: "Перемещение",
    unread: "Новое",
    used: "Использовано",
    warning: "Внимание",
    write_off: "Списание",
  })[String(value)] || String(value ?? "—");
}

function humanDocumentType(value) {
  return ({
    receipt: "Приход",
    write_off: "Списание",
    transfer: "Перемещение",
    repack: "Фасовка / переупаковка",
    return_from_department: "Возврат от отделения",
    return_to_supplier: "Возврат поставщику",
  })[String(value)] || humanStatus(value);
}

function humanNotificationType(value) {
  return ({
    low_stock: "Мало остатка",
    expiry: "Срок годности",
    inventory: "Инвентаризация",
    quarantine: "Карантин",
    sensor_warning: "Условия хранения",
    stock: "Склад",
  })[String(value)] || humanStatus(value);
}

function analyticsClassBadge(value, kind) {
  const text = String(value || "—");
  const cls = kind === "abc" && text === "A" ? "badge ok"
    : kind === "abc" && text === "B" ? "badge warn"
    : kind === "xyz" && text === "Z" ? "badge bad"
    : "badge";
  return `<span class="${cls}">${escapeHtml(text)}</span>`;
}

function activeSearchQuery() {
  return state.ui.search.trim();
}

function searchEmptyText(defaultText) {
  const query = activeSearchQuery();
  if (!query) return defaultText;
  return `По запросу “${query}” ничего не найдено. Сбросьте поиск или измените текст.`;
}

function searchNotice() {
  const query = activeSearchQuery();
  if (!query) return "";
  return `
    <div class="search-banner">
      <span>Показаны результаты по запросу: <strong>${escapeHtml(query)}</strong></span>
      <button class="secondary" type="button" data-clear-search>Сбросить</button>
    </div>
  `;
}

function table(columns, rows, empty = "Данных пока нет") {
  if (!rows || rows.length === 0) return `<div class="empty">${escapeHtml(searchEmptyText(empty))}</div>`;
  return `
    <div class="table-summary">
      <span>Найдено записей: ${escapeHtml(rows.length)}</span>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr>${columns.map((col) => `<th>${escapeHtml(col.label)}</th>`).join("")}</tr></thead>
        <tbody>
          ${rows.map((row) => `
            <tr>
              ${columns.map((col) => `<td>${col.render ? col.render(row) : escapeHtml(row[col.key] ?? "—")}</td>`).join("")}
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function batchButton(batchId, label = null) {
  if (!batchId) return "—";
  return `<button class="link-button" type="button" data-batch-detail="${escapeAttr(batchId)}">${label || `#${escapeHtml(batchId)}`}</button>`;
}

function extraFieldAttrs(field) {
  return [
    field.batchWarehouseField ? `data-batch-warehouse-field="${escapeAttr(field.batchWarehouseField)}"` : "",
  ].filter(Boolean).join(" ");
}

function form(id, fields, buttonText, options = {}) {
  const disabled = Boolean(options.disabledSubmit);
  return `
    <form id="${escapeAttr(id)}" class="form-grid" ${options.batchAware ? "data-batch-aware=\"true\"" : ""}>
      ${fields.map((field) => field.type === "select" ? `
        <label class="${field.full ? "full" : ""}">${escapeHtml(field.label)}
          <select name="${escapeAttr(field.name)}" ${field.required ? "required" : ""} ${extraFieldAttrs(field)}>
            ${(field.options || []).map((option) => `
              <option value="${escapeAttr(option.value)}" ${String(option.value) === String(field.value ?? "") ? "selected" : ""}>${option.label}</option>
            `).join("")}
          </select>
        </label>
      ` : field.type === "textarea" ? `
        <label class="${field.full ? "full" : ""}">${escapeHtml(field.label)}
          <textarea name="${escapeAttr(field.name)}" ${field.required ? "required" : ""}>${escapeHtml(field.value || "")}</textarea>
        </label>
      ` : `
        <label class="${field.full ? "full" : ""}">${escapeHtml(field.label)}
          <input name="${escapeAttr(field.name)}" type="${escapeAttr(field.type || "text")}" value="${escapeAttr(field.value || "")}" ${field.required ? "required" : ""} ${field.step ? `step="${escapeAttr(field.step)}"` : ""} ${field.min ? `min="${escapeAttr(field.min)}"` : ""} ${extraFieldAttrs(field)} />
        </label>
      `).join("")}
      ${options.batchAware ? '<div class="batch-summary full" data-selected-batch-summary>Выберите партию, и здесь появится доступный остаток и склад.</div>' : ""}
      ${options.submitHint ? `<div class="form-hint full ${disabled ? "blocked" : ""}">${escapeHtml(options.submitHint)}</div>` : ""}
      <div class="actions full"><button class="primary" type="submit" ${disabled ? "disabled" : ""}>${escapeHtml(buttonText)}</button></div>
    </form>
  `;
}

function optionsFrom(collection, placeholder, label = (item) => item.name) {
  return [
    { value: "", label: escapeHtml(placeholder) },
    ...state.data[collection].map((item) => ({ value: item.id, label: `${escapeHtml(label(item))} (#${escapeHtml(item.id)})` })),
  ];
}

function staticOptions(items, placeholder) {
  return [{ value: "", label: escapeHtml(placeholder) }, ...items.map(([value, label]) => ({ value, label: escapeHtml(label) }))];
}

function productUnitOptions(placeholder = "Выберите единицу") {
  const units = state.data.productUnits.length
    ? state.data.productUnits
    : ["шт", "уп", "рулон", "флакон", "бут", "ампула"];
  return staticOptions(units.map((unit) => [unit, unit]), placeholder);
}

function pageItems(payload) {
  return Array.isArray(payload) ? payload : (payload?.items || []);
}

function searchText(...parts) {
  return parts
    .filter((part) => part !== null && part !== undefined)
    .join(" ")
    .toLowerCase();
}

function matchesSearch(row, ...parts) {
  const query = state.ui.search.trim().toLowerCase();
  if (!query) return true;
  return searchText(...parts).includes(query);
}

function filteredBalances(rows = state.data.balances.items) {
  return rows.filter((row) => matchesSearch(
    row,
    row.batch_id,
    row.batch_status,
    row.expires_on,
    rawNameById("products", row.product_id),
    rawNameById("warehouses", row.warehouse_id),
  ));
}

function filteredRows(rows, selector) {
  return rows.filter((row) => {
    const parts = selector(row);
    return matchesSearch(row, ...(Array.isArray(parts) ? parts : [parts]));
  });
}

const reportConfigs = {
  balances: {
    filename: "sklad-balances.csv",
    columns: [
      { label: "Товар", value: (row) => rawNameById("products", row.product_id) },
      { label: "Партия", key: "batch_id" },
      { label: "Склад", value: (row) => rawNameById("warehouses", row.warehouse_id) },
      { label: "Всего", key: "total_quantity" },
      { label: "Резерв", key: "reserved_quantity" },
      { label: "Свободно", key: "free_quantity" },
      { label: "Статус партии", value: (row) => humanStatus(row.batch_status) },
      { label: "Годен до", key: "expires_on" },
    ],
    rows: () => filteredBalances(state.data.balances.items),
  },
  movements: {
    filename: "sklad-movements.csv",
    columns: [
      { label: "Номер", key: "id" },
      { label: "Действие", value: (row) => humanStatus(row.movement_type) },
      { label: "Партия", value: (row) => rawBatchLabel(row.batch_id) },
      { label: "Склад", value: (row) => rawNameById("warehouses", row.warehouse_id) },
      { label: "Количество", key: "quantity" },
      { label: "Причина", key: "reason" },
      { label: "Время", value: (row) => dateText(row.created_at) },
    ],
    rows: () => filteredRows(state.data.movements, (row) => [
      row.id,
      row.movement_type,
      rawBatchLabel(row.batch_id),
      rawNameById("warehouses", row.warehouse_id),
      row.quantity,
      row.reason,
      row.created_at,
    ]),
  },
  documents: {
    filename: "sklad-documents.csv",
    columns: [
      { label: "Номер", key: "id" },
      { label: "Тип", value: (row) => humanDocumentType(row.document_type) },
      { label: "Статус", value: (row) => humanStatus(row.status) },
      { label: "Склад", value: (row) => rawNameById("warehouses", row.warehouse_id) },
      { label: "Строк", value: (row) => row.lines?.length || 0 },
      { label: "Создал", key: "created_by" },
      { label: "Создан", value: (row) => dateText(row.created_at) },
      { label: "Утвердил", key: "approved_by" },
      { label: "Утвержден", value: (row) => dateText(row.approved_at) },
      { label: "Проведен", value: (row) => dateText(row.posted_at) },
    ],
    rows: () => filteredRows(state.data.documents, (row) => [
      row.id,
      row.document_type,
      row.status,
      rawNameById("warehouses", row.warehouse_id),
      row.created_by,
      row.created_at,
      row.approved_by,
      row.approved_at,
      row.posted_at,
    ]),
  },
  analytics: {
    filename: "sklad-abc-xyz.csv",
    columns: [
      { label: "Товар", key: "product_name" },
      { label: "Код товара", key: "sku" },
      { label: "ABC", key: "abc_class" },
      { label: "XYZ", key: "xyz_class" },
      { label: "Расход", key: "consumption_quantity" },
      { label: "Стоимость расхода", key: "consumption_value" },
      { label: "Свободно", key: "current_free_quantity" },
      { label: "Точка заказа", key: "reorder_point" },
      { label: "Страховой запас", key: "safety_stock" },
      { label: "Заказать", key: "recommended_order_quantity" },
      { label: "Рекомендация", key: "recommendation" },
    ],
    rows: () => filteredRows(state.data.analytics.items || [], (row) => [
      row.product_name,
      row.sku,
      row.abc_class,
      row.xyz_class,
      row.recommendation,
      row.recommended_order_quantity,
    ]),
  },
  abcXyzRuns: {
    filename: "sklad-abc-xyz-history.csv",
    columns: [
      { label: "Номер", key: "id" },
      { label: "Склад", value: (row) => row.warehouse_id ? rawNameById("warehouses", row.warehouse_id) : "Все склады" },
      { label: "Дней анализа", key: "analysis_days" },
      { label: "Период с", value: (row) => dateText(row.period_start) },
      { label: "Период по", value: (row) => dateText(row.period_end) },
      { label: "Источник", key: "source" },
      { label: "Статус", value: (row) => humanStatus(row.status) },
      { label: "Позиций", key: "items_count" },
      { label: "Создан", value: (row) => dateText(row.generated_at) },
    ],
    rows: () => filteredRows(state.data.abcXyzRuns.items || [], (row) => [
      row.id,
      row.warehouse_id,
      row.analysis_days,
      row.source,
      row.status,
      row.generated_at,
    ]),
  },
  purchaseRequests: {
    filename: "sklad-purchase-requests.csv",
    columns: [
      { label: "Номер", key: "id" },
      { label: "Товар", value: (row) => rawNameById("products", row.product_id) },
      { label: "Склад", value: (row) => row.warehouse_id ? rawNameById("warehouses", row.warehouse_id) : "" },
      { label: "Количество", key: "quantity" },
      { label: "Статус", value: (row) => humanStatus(row.status) },
      { label: "Причина", key: "reason" },
      { label: "Создано", value: (row) => dateText(row.created_at) },
    ],
    rows: () => filteredRows(state.data.purchaseRequests, (row) => [
      row.id,
      rawNameById("products", row.product_id),
      rawNameById("warehouses", row.warehouse_id),
      row.quantity,
      row.status,
      row.reason,
      row.created_at,
    ]),
  },
  batchRecalls: {
    filename: "sklad-batch-recalls.csv",
    columns: [
      { label: "Номер", key: "id" },
      { label: "Товар", key: "product_name" },
      { label: "Партия", key: "lot" },
      { label: "Источник", key: "source" },
      { label: "Основание", key: "reference" },
      { label: "Причина", key: "reason" },
      { label: "Создал", key: "created_by" },
      { label: "Создано", value: (row) => dateText(row.created_at) },
    ],
    rows: () => filteredRows(state.data.batchRecalls.items || [], (row) => [
      row.id,
      row.product_name,
      row.lot,
      row.source,
      row.reference,
      row.reason,
      row.created_by,
      row.created_at,
    ]),
  },
  audit: {
    filename: "sklad-audit-log.csv",
    columns: [
      { label: "Время", value: (row) => dateText(row.created_at) },
      { label: "Пользователь", key: "actor_id" },
      { label: "Действие", key: "action" },
      { label: "Сущность", value: (row) => `${row.entity_type} #${row.entity_id}` },
      { label: "Склад", value: (row) => row.warehouse_id || "" },
      { label: "Данные", value: (row) => JSON.stringify(row.payload || {}) },
    ],
    rows: () => filteredRows(state.data.audit.items || [], (row) => [
      row.created_at,
      row.actor_id,
      row.action,
      row.entity_type,
      row.entity_id,
      row.warehouse_id,
      JSON.stringify(row.payload),
    ]),
  },
  sensorReadings: {
    filename: "sklad-storage-conditions.csv",
    columns: [
      { label: "Время", value: (row) => dateText(row.recorded_at) },
      { label: "Склад", value: (row) => row.warehouse_name || rawNameById("warehouses", row.warehouse_id) },
      { label: "Датчик", value: (row) => row.device_name || `#${row.device_id}` },
      { label: "Температура", key: "temperature_c" },
      { label: "Влажность", key: "humidity_percent" },
      { label: "Статус", value: (row) => humanStatus(row.status) },
      { label: "Источник", key: "raw_payload" },
    ],
    rows: () => filteredRows(state.data.sensorReadings.items || [], (row) => [
      row.recorded_at,
      row.warehouse_name,
      row.device_name,
      row.temperature_c,
      row.humidity_percent,
      row.status,
      row.raw_payload,
    ]),
  },
  repackings: {
    filename: "sklad-repackings.csv",
    columns: [
      { label: "Номер", key: "id" },
      { label: "Документ", key: "document_id" },
      { label: "Исходная партия", value: (row) => rawBatchLabel(row.source_batch_id) },
      { label: "Результат", value: (row) => rawBatchLabel(row.target_batch_id) },
      { label: "Склад", value: (row) => rawNameById("warehouses", row.warehouse_id) },
      { label: "Исходное количество", key: "source_quantity" },
      { label: "Получено", key: "target_quantity" },
      { label: "Коэффициент", key: "conversion_factor" },
      { label: "Потери", key: "loss_quantity" },
      { label: "Причина", key: "reason" },
      { label: "Создал", key: "created_by" },
      { label: "Создано", value: (row) => dateText(row.created_at) },
    ],
    rows: () => filteredRows(pageItems(state.data.repackings), (row) => [
      row.id,
      row.document_id,
      rawBatchLabel(row.source_batch_id),
      rawBatchLabel(row.target_batch_id),
      rawNameById("warehouses", row.warehouse_id),
      row.source_quantity,
      row.target_quantity,
      row.conversion_factor,
      row.loss_quantity,
      row.reason,
      row.created_by,
      row.created_at,
    ]),
  },
  inventorySheet: {
    filename: "sklad-inventory-sheet.csv",
    columns: [
      { label: "Сессия", value: (row) => row.session_id },
      { label: "Склад", value: (row) => rawNameById("warehouses", row.warehouse_id) },
      { label: "Товар", value: (row) => rawNameById("products", row.product_id) },
      { label: "Партия", value: (row) => rawBatchLabel(row.batch_id) },
      { label: "Ожидалось", key: "expected_quantity" },
      { label: "Факт", value: (row) => row.actual_quantity ?? "" },
      { label: "Расхождение", value: (row) => row.difference_quantity ?? "" },
    ],
    rows: () => {
      const session = selectedInventorySession();
      return (session?.lines || []).map((line) => ({
        ...line,
        session_id: session.id,
        warehouse_id: session.warehouse_id,
      }));
    },
  },
};

function exportReport(reportName) {
  const config = reportConfigs[reportName];
  if (!config) return;
  const rows = config.rows();
  if (!rows.length) {
    showAlert("В отчете нет строк для выгрузки", "error");
    return;
  }
  downloadCsv(config.filename, config.columns, rows);
  showAlert("Отчет выгружен");
}

async function loadOptional(label, requestPromise, fallback) {
  try {
    return await requestPromise;
  } catch (error) {
    if (error instanceof AuthRequiredError) throw error;
    if (error instanceof ApiError && [401, 403, 404].includes(error.status)) {
      return fallback;
    }
    state.loadWarnings.push(`${label}: раздел не загрузился, обновите страницу`);
    return fallback;
  }
}

function batchOptions(placeholder, { onlyAvailable = true } = {}) {
  const seen = new Set();
  const options = state.data.balances.items
    .filter((item) => Number(item.free_quantity || 0) > 0)
    .filter((item) => !onlyAvailable || item.batch_status === "available")
    .filter((item) => {
      const key = `${item.batch_id}:${item.warehouse_id}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .map((item) => {
      const batch = state.data.batches.find((entry) => Number(entry.id) === Number(item.batch_id));
      const lot = batch?.lot || item.lot || "—";
      const expires = item.expires_on ? ` · до ${item.expires_on}` : "";
      return {
        value: item.batch_id,
        label: escapeHtml(`${rawNameById("products", item.product_id)} · серия ${lot} · ${rawNameById("warehouses", item.warehouse_id)} · свободно ${item.free_quantity}${expires} · ${humanStatus(item.batch_status)}`),
      };
    });
  return [{ value: "", label: escapeHtml(placeholder) }, ...options];
}

function batchById(batchId) {
  return state.data.batches.find((entry) => Number(entry.id) === Number(batchId));
}

function productForBatch(batchId) {
  const batch = batchById(batchId);
  if (!batch) return null;
  return state.data.products.find((product) => Number(product.id) === Number(batch.product_id)) || null;
}

function isControlledProduct(productId) {
  const product = state.data.products.find((entry) => Number(entry.id) === Number(productId));
  return Boolean(product?.is_controlled);
}

function controlledWriteoffMetadataMissing(payload) {
  const controlled = payload.batch_id
    ? Boolean(productForBatch(payload.batch_id)?.is_controlled)
    : isControlledProduct(payload.product_id);
  if (!controlled) return [];
  return ["patient_id", "doctor_id", "medical_record_no", "second_approver_id"].filter((field) => !String(payload[field] || "").trim());
}

function controlledWriteoffMessage() {
  return "Для ПКУ заполните пациента, врача, номер истории болезни и второго подтверждающего.";
}

function applyControlledWriteoffRequirements(formElement, payload = null) {
  const data = payload || collect(formElement);
  const missing = controlledWriteoffMetadataMissing(data);
  const controlled = missing.length > 0 || (data.batch_id
    ? Boolean(productForBatch(data.batch_id)?.is_controlled)
    : isControlledProduct(data.product_id));
  ["patient_id", "doctor_id", "medical_record_no", "second_approver_id"].forEach((field) => {
    const input = formElement.elements[field];
    if (!input) return;
    input.required = controlled;
    input.closest("label")?.classList.toggle("controlled-required", controlled);
  });
  return missing;
}

function balanceForBatch(batchId, warehouseId = null) {
  return state.data.balances.items.find((item) => {
    if (Number(item.batch_id) !== Number(batchId)) return false;
    if (warehouseId && Number(item.warehouse_id) !== Number(warehouseId)) return false;
    return Number(item.free_quantity || 0) > 0;
  });
}

function selectedBatchSummary(batchId, warehouseId = null) {
  const batch = batchById(batchId);
  const balance = balanceForBatch(batchId, warehouseId);
  if (!batch || !balance) return null;
  return {
    batch,
    balance,
    productName: rawNameById("products", batch.product_id),
    warehouseName: rawNameById("warehouses", balance.warehouse_id),
    supplierName: rawNameById("suppliers", batch.supplier_id),
  };
}

function selectedBatchSummaryHtml(batchId, warehouseId = null) {
  const summary = selectedBatchSummary(batchId, warehouseId);
  if (!batchId) return "Выберите партию, и здесь появится доступный остаток и склад.";
  if (!summary) return "По выбранной партии нет свободного остатка на выбранном складе.";
  return [
    `<strong>${escapeHtml(summary.productName)}</strong>`,
    `серия ${escapeHtml(summary.batch.lot)}`,
    `склад: ${escapeHtml(summary.warehouseName)}`,
    `свободно: ${escapeHtml(summary.balance.free_quantity)}`,
    `годен до: ${escapeHtml(summary.batch.expires_on || "не указан")}`,
    `поставщик: ${escapeHtml(summary.supplierName)}`,
    batchButton(batchId, "Открыть карточку партии"),
  ].join(" · ");
}

function operationPreview(kind, payload) {
  const warehouseId = payload.warehouse_id || payload.source_warehouse_id;
  const summary = selectedBatchSummary(payload.batch_id, warehouseId);
  const quantity = Number(payload.quantity || 0);
  const free = Number(summary?.balance?.free_quantity || 0);
  const remaining = Number.isFinite(quantity) ? Math.max(0, free - quantity) : free;
  if (!summary) return `Партия #${payload.batch_id}: проверьте выбранный склад и количество.`;
  if (kind === "transfer" || kind === "department-return") {
    const sourceName = rawNameById("warehouses", payload.source_warehouse_id);
    const targetName = rawNameById("warehouses", payload.target_warehouse_id);
    return `${summary.productName}, серия ${summary.batch.lot}: ${payload.quantity} уйдет со склада “${sourceName}” на склад “${targetName}”. На источнике останется ${remaining}.`;
  }
  if (kind === "supplier-return") {
    return `${summary.productName}, серия ${summary.batch.lot}: ${payload.quantity} будет возвращено поставщику “${rawNameById("suppliers", payload.supplier_id)}”. На складе останется ${remaining}.`;
  }
  return `${summary.productName}, серия ${summary.batch.lot}: будет списано ${payload.quantity}. На складе “${summary.warehouseName}” останется ${remaining}.`;
}

function normalizeRepackingPayload(payload) {
  const sourceQuantity = Number(payload.quantity || 0);
  const targetQuantity = Number(payload.target_quantity || 0);
  const lossQuantity = Number(payload.loss_quantity || 0);
  const usableSource = Math.max(0, sourceQuantity - lossQuantity);
  const conversionFactor = usableSource > 0 && targetQuantity > 0
    ? (targetQuantity / usableSource).toFixed(6)
    : payload.conversion_factor || "1";
  return {
    warehouse_id: payload.warehouse_id,
    lines: [{
      batch_id: payload.batch_id,
      target_product_id: payload.target_product_id,
      quantity: payload.quantity,
      target_quantity: payload.target_quantity,
      conversion_factor: conversionFactor,
      loss_quantity: payload.loss_quantity || "0",
      target_lot: payload.target_lot,
      target_expires_on: payload.target_expires_on || null,
      target_unit_price: payload.target_unit_price || null,
      quarantine: Boolean(payload.quarantine),
      reason: payload.reason || "Фасовка / переупаковка",
    }],
  };
}

function repackingPreview(payload) {
  const summary = selectedBatchSummary(payload.batch_id, payload.warehouse_id);
  const sourceQuantity = Number(payload.quantity || 0);
  const targetQuantity = Number(payload.target_quantity || 0);
  const lossQuantity = Number(payload.loss_quantity || 0);
  const free = Number(summary?.balance?.free_quantity || 0);
  const remaining = Number.isFinite(sourceQuantity) ? Math.max(0, free - sourceQuantity) : free;
  const targetName = rawNameById("products", payload.target_product_id);
  if (!summary) return `Партия #${payload.batch_id}: проверьте выбранный склад и доступный остаток.`;
  return `${summary.productName}, серия ${summary.batch.lot}: ${payload.quantity} уйдет в фасовку, получится ${payload.target_quantity} “${targetName}”, потери ${lossQuantity || 0}. На складе останется ${remaining}.`;
}

function recallPreview(payload) {
  const summary = selectedBatchSummary(payload.batch_id, payload.warehouse_id);
  if (!summary) return `Партия #${payload.batch_id}: проверьте выбранный склад и остаток.`;
  return `${summary.productName}, серия ${summary.batch.lot}: партия будет заблокирована на всех складах с остатком. Причина: ${payload.reason || "не указана"}.`;
}

function inventoryProgress(session) {
  const lines = session?.lines || [];
  const filled = lines.filter((line) => line.actual_quantity !== null && line.actual_quantity !== undefined && line.actual_quantity !== "").length;
  return {
    total: lines.length,
    filled,
    missing: Math.max(0, lines.length - filled),
  };
}

function inventorySummary(session) {
  if (session?.summary) return session.summary;
  const lines = session?.lines || [];
  return lines.reduce((summary, line) => {
    const expected = Number(line.expected_quantity || 0);
    const actualRaw = line.actual_quantity;
    const filled = actualRaw !== null && actualRaw !== undefined && actualRaw !== "";
    const actual = filled ? Number(actualRaw || 0) : 0;
    const difference = filled ? Number(line.difference_quantity ?? actual - expected) : 0;
    summary.total_lines += 1;
    summary.total_expected_quantity += expected;
    if (!filled) {
      summary.missing_lines += 1;
      return summary;
    }
    summary.filled_lines += 1;
    summary.total_actual_quantity += actual;
    if (difference > 0) {
      summary.surplus_lines += 1;
      summary.total_surplus_quantity += difference;
    } else if (difference < 0) {
      summary.shortage_lines += 1;
      summary.total_shortage_quantity += Math.abs(difference);
    } else {
      summary.matched_lines += 1;
    }
    return summary;
  }, {
    total_lines: 0,
    filled_lines: 0,
    missing_lines: 0,
    surplus_lines: 0,
    shortage_lines: 0,
    matched_lines: 0,
    total_expected_quantity: 0,
    total_actual_quantity: 0,
    total_surplus_quantity: 0,
    total_shortage_quantity: 0,
  });
}

function selectedInventorySession() {
  return state.data.inventorySessions.find((session) => session.status === "in_progress")
    || state.data.inventorySessions[0];
}

function inventorySummaryHtml(session) {
  const summary = inventorySummary(session);
  const items = [
    ["Строк", summary.total_lines],
    ["Заполнено", `${summary.filled_lines}/${summary.total_lines}`],
    ["Недостачи", `${summary.shortage_lines} · ${qty(summary.total_shortage_quantity)}`],
    ["Излишки", `${summary.surplus_lines} · ${qty(summary.total_surplus_quantity)}`],
    ["Без расхождений", summary.matched_lines],
  ];
  return `<div class="inventory-summary">${items.map(([label, value]) => `
    <div><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>
  `).join("")}</div>`;
}

function inventoryProgressText(session) {
  if (!session) return "Выберите проверку склада.";
  const progress = inventoryProgress(session);
  if (!progress.total) return "В проверке нет строк. Проверьте остатки выбранного склада.";
  if (progress.missing > 0) {
    return `Заполнено ${progress.filled} из ${progress.total}. Осталось внести факт по ${progress.missing} строкам.`;
  }
  return `Все ${progress.total} строк заполнены. Можно завершать проверку.`;
}

function inventoryCompletionPreview(sessionId) {
  const session = state.data.inventorySessions.find((item) => Number(item.id) === Number(sessionId));
  if (!session) return `Провести инвентаризацию #${sessionId}?`;
  const progress = inventoryProgress(session);
  if (progress.missing > 0) {
    return `В проверке #${session.id} еще не заполнено ${progress.missing} строк. Система не проведет инвентаризацию, пока все факты не внесены.`;
  }
  return `Провести инвентаризацию #${session.id}? Будут применены расхождения по ${progress.total} строкам.`;
}

function setPending(control, pending, pendingText = "Выполняется...") {
  if (!control) return;
  if (pending) {
    control.dataset.originalText = control.textContent;
    control.textContent = pendingText;
    control.disabled = true;
    control.classList.add("pending");
    control.setAttribute("aria-busy", "true");
    return;
  }
  control.textContent = control.dataset.originalText || control.textContent;
  delete control.dataset.originalText;
  control.disabled = false;
  control.classList.remove("pending");
  control.removeAttribute("aria-busy");
}

function confirmAction(message, { title = "Подтвердите действие", confirmText = "Да, выполнить", cancelText = "Отмена", tone = "danger" } = {}) {
  return new Promise((resolve) => {
    const backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop";
    backdrop.innerHTML = `
      <section class="confirm-modal ${escapeAttr(tone)}" role="dialog" aria-modal="true" aria-labelledby="confirm-title">
        <header>
          <h2 id="confirm-title">${escapeHtml(title)}</h2>
        </header>
        <p class="confirm-message">${escapeHtml(message)}</p>
        <footer>
          <button class="secondary" type="button" data-confirm-cancel>${escapeHtml(cancelText)}</button>
          <button class="${tone === "danger" ? "danger" : "primary"}" type="button" data-confirm-ok>${escapeHtml(confirmText)}</button>
        </footer>
      </section>
    `;
    document.body.appendChild(backdrop);

    const cancelButton = backdrop.querySelector("[data-confirm-cancel]");
    const okButton = backdrop.querySelector("[data-confirm-ok]");
    const previousFocus = document.activeElement;

    const close = (answer) => {
      backdrop.remove();
      document.removeEventListener("keydown", onKeydown);
      if (previousFocus && typeof previousFocus.focus === "function") previousFocus.focus();
      resolve(answer);
    };
    const onKeydown = (event) => {
      if (event.key === "Escape") close(false);
    };

    cancelButton.addEventListener("click", () => close(false));
    okButton.addEventListener("click", () => close(true));
    backdrop.addEventListener("click", (event) => {
      if (event.target === backdrop) close(false);
    });
    document.addEventListener("keydown", onKeydown);
    (tone === "danger" ? cancelButton : okButton).focus();
  });
}

function catalogKindLabel(kind) {
  return ({
    category: "категорию",
    product: "товар",
    supplier: "поставщика",
    warehouse: "склад",
  })[kind] || "запись";
}

function catalogEditConfig(kind, row) {
  const configs = {
    category: {
      endpoint: `/categories/${row.id}`,
      fields: [
        { label: "Название категории", name: "name", value: row.name, required: true },
      ],
      normalize: (payload) => payload,
    },
    supplier: {
      endpoint: `/suppliers/${row.id}`,
      fields: [
        { label: "Название поставщика", name: "name", value: row.name, required: true },
        { label: "БИН", name: "bin", value: row.bin || "" },
        { label: "Телефон", name: "phone", type: "tel", value: row.phone || "" },
        { label: "Адрес", name: "address", value: row.address || "" },
        { label: "Рейтинг", name: "rating", type: "number", min: "1", max: "5", step: "1", value: row.rating || "" },
        { label: "Постоянный поставщик", name: "is_preferred", type: "select", options: staticOptions([["false", "Нет"], ["true", "Да"]], "Выберите значение"), value: row.is_preferred ? "true" : "false" },
        { label: "Контактное лицо", name: "contact_person", value: row.contact_person || "" },
        { label: "Email", name: "email", type: "email", value: row.email || "" },
        { label: "Номер договора", name: "contract_number", value: row.contract_number || "" },
        { label: "Договор действует до", name: "contract_expires_on", type: "date", value: row.contract_expires_on || "" },
        { label: "Условия оплаты", name: "payment_terms", value: row.payment_terms || "" },
        { label: "Заметки", name: "notes", type: "textarea", full: true, value: row.notes || "" },
      ],
      normalize: normalizeSupplierPayload,
    },
    warehouse: {
      endpoint: `/warehouses/${row.id}`,
      fields: [
        { label: "Название склада или кабинета", name: "name", value: row.name, required: true },
        { label: "Отделение", name: "department", value: row.department || "" },
        { label: "ID компании Tetis", name: "tetis_org_id", value: row.tetis_org_id || "" },
        { label: "ID склада в Tetis", name: "external_tetis_id", value: row.external_tetis_id || "" },
        { label: "Зона хранения", name: "storage_zone", value: row.storage_zone || "" },
        { label: "Лимит вместимости", name: "capacity_limit", type: "number", step: "0.001", min: "0", value: row.capacity_limit || "" },
        { label: "Условия хранения", name: "storage_conditions", value: row.storage_conditions || "" },
        { label: "Ответственный", name: "responsible_person", value: row.responsible_person || "" },
      ],
      normalize: (payload) => ({
        ...payload,
        department: payload.department || null,
        tetis_org_id: payload.tetis_org_id || null,
        external_tetis_id: payload.external_tetis_id || null,
        storage_zone: payload.storage_zone || null,
        capacity_limit: payload.capacity_limit ? Number(payload.capacity_limit) : null,
        storage_conditions: payload.storage_conditions || null,
        responsible_person: payload.responsible_person || null,
      }),
    },
    product: {
      endpoint: `/products/${row.id}`,
      fields: [
        { label: "Название", name: "name", value: row.name, required: true },
        { label: "Код товара", name: "sku", value: row.sku, required: true },
        { label: "Ед. изм.", name: "unit", type: "select", options: productUnitOptions("Выберите единицу"), value: row.unit, required: true },
        { label: "Категория", name: "category_id", type: "select", options: optionsFrom("categories", "Выберите категорию"), value: row.category_id, required: true },
        { label: "Точка заказа", name: "reorder_point", type: "number", step: "0.001", min: "0", value: row.reorder_point || "0" },
        { label: "Страховой запас", name: "safety_stock", type: "number", step: "0.001", min: "0", value: row.safety_stock || "0" },
        { label: "ПКУ / контролируемый товар", name: "is_controlled", type: "select", options: staticOptions([["false", "Нет"], ["true", "Да"]], "Выберите значение"), value: row.is_controlled ? "true" : "false" },
        { label: "Штрихкод", name: "barcode", value: row.barcode || "" },
        { label: "Сертификат", name: "certificate_ref", value: row.certificate_ref || "" },
        { label: "Описание", name: "description", type: "textarea", full: true, value: row.description || "" },
      ],
      normalize: normalizeProductPayload,
    },
  };
  return configs[kind] || null;
}

function normalizeProductPayload(payload) {
  return {
    ...payload,
    reorder_point: payload.reorder_point || "0",
    safety_stock: payload.safety_stock || "0",
    is_controlled: payload.is_controlled === true || payload.is_controlled === "true",
    barcode: payload.barcode || null,
    description: payload.description || null,
    certificate_ref: payload.certificate_ref || null,
  };
}

function normalizeSupplierPayload(payload) {
  return {
    ...payload,
    bin: payload.bin || null,
    phone: payload.phone || null,
    address: payload.address || null,
    rating: payload.rating ? Number(payload.rating) : null,
    is_preferred: payload.is_preferred === true || payload.is_preferred === "true",
    contact_person: payload.contact_person || null,
    email: payload.email || null,
    contract_number: payload.contract_number || null,
    contract_expires_on: payload.contract_expires_on || null,
    payment_terms: payload.payment_terms || null,
    notes: payload.notes || null,
  };
}

async function showSupplierCard(id) {
  const supplier = state.data.suppliers.find((item) => Number(item.id) === Number(id));
  if (!supplier) {
    showAlert("Поставщик не найден. Обновите страницу и попробуйте еще раз.", "error");
    return;
  }
  const priceHistory = await loadOptional(
    "История цен поставщика",
    request(`/suppliers/${id}/price-history?limit=5`),
    { items: [], total: 0 },
  );
  const backdrop = document.createElement("div");
  backdrop.className = "modal-backdrop";
  backdrop.innerHTML = `
    <section class="confirm-modal trace-modal" role="dialog" aria-modal="true" aria-labelledby="supplier-card-title">
      <header>
        <h2 id="supplier-card-title">${escapeHtml(supplier.name)}</h2>
        <button class="icon-button" type="button" data-supplier-card-close title="Закрыть">×</button>
      </header>
      <div class="trace-body">
        <div class="trace-summary">
          <div><span>БИН</span><strong>${escapeHtml(supplier.bin || "не указан")}</strong></div>
          <div><span>Телефон</span><strong>${escapeHtml(supplier.phone || "не указан")}</strong></div>
          <div><span>Email</span><strong>${escapeHtml(supplier.email || "не указан")}</strong></div>
          <div><span>Контакт</span><strong>${escapeHtml(supplier.contact_person || "не указан")}</strong></div>
          <div><span>Рейтинг</span><strong>${supplier.rating ? `${escapeHtml(supplier.rating)}/5` : "не указан"}</strong></div>
          <div><span>Статус</span>${supplier.is_preferred ? badge("постоянный") : badge("обычный")}</div>
        </div>
        <div class="trace-section">
          <h3>Договор и условия</h3>
          ${compactTraceTable([
            { label: "Адрес", render: () => escapeHtml(supplier.address || "—") },
            { label: "Договор", render: () => escapeHtml(supplier.contract_number || "—") },
            { label: "Действует до", render: () => escapeHtml(supplier.contract_expires_on || "—") },
            { label: "Оплата", render: () => escapeHtml(supplier.payment_terms || "—") },
          ], [supplier], "Реквизиты договора пока не заполнены.")}
        </div>
        <div class="trace-section">
          <h3>Последние цены</h3>
          ${compactTraceTable([
            { label: "Дата", render: (row) => dateText(row.recorded_at) },
            { label: "Товар", key: "product_name" },
            { label: "SKU", key: "sku" },
            { label: "Партия", render: (row) => escapeHtml(row.lot || "—") },
            { label: "Цена", key: "unit_price" },
          ], priceHistory.items || [], "Истории цен по поставщику пока нет.")}
        </div>
        <div class="trace-section">
          <h3>Заметки</h3>
          <p class="confirm-message">${escapeHtml(supplier.notes || "Заметок пока нет.")}</p>
        </div>
      </div>
      <footer>
        <button class="secondary" type="button" data-supplier-card-close>Закрыть</button>
      </footer>
    </section>
  `;
  document.body.appendChild(backdrop);
  const previousFocus = document.activeElement;
  const close = () => {
    backdrop.remove();
    document.removeEventListener("keydown", onKeydown);
    if (previousFocus && typeof previousFocus.focus === "function") previousFocus.focus();
  };
  const onKeydown = (event) => {
    if (event.key === "Escape") close();
  };
  document.addEventListener("keydown", onKeydown);
  backdrop.addEventListener("click", (event) => {
    if (event.target === backdrop) close();
  });
  backdrop.querySelectorAll("[data-supplier-card-close]").forEach((button) => button.addEventListener("click", close));
  backdrop.querySelector("[data-supplier-card-close]")?.focus();
}

function showCatalogEditModal(kind, id) {
  const collections = {
    category: "categories",
    product: "products",
    supplier: "suppliers",
    warehouse: "warehouses",
  };
  const collection = collections[kind];
  const row = state.data[collection]?.find((item) => Number(item.id) === Number(id));
  const config = row ? catalogEditConfig(kind, row) : null;
  if (!config) {
    showAlert("Запись не найдена. Обновите страницу и попробуйте еще раз.", "error");
    return;
  }

  const backdrop = document.createElement("div");
  backdrop.className = "modal-backdrop";
  backdrop.innerHTML = `
    <section class="confirm-modal edit-modal" role="dialog" aria-modal="true" aria-labelledby="catalog-edit-title">
      <header>
        <h2 id="catalog-edit-title">Исправить ${escapeHtml(catalogKindLabel(kind))}</h2>
      </header>
      <p class="confirm-message">Изменения сохранятся в справочнике и будут видны в новых и старых документах.</p>
      ${form("catalog-edit-form", config.fields, "Сохранить изменения")}
      <footer>
        <button class="secondary" type="button" data-catalog-edit-close>Отмена</button>
      </footer>
    </section>
  `;
  document.body.appendChild(backdrop);
  const previousFocus = document.activeElement;
  const formElement = backdrop.querySelector("#catalog-edit-form");
  const close = () => {
    backdrop.remove();
    document.removeEventListener("keydown", onKeydown);
    if (previousFocus && typeof previousFocus.focus === "function") previousFocus.focus();
  };
  const onKeydown = (event) => {
    if (event.key === "Escape") close();
  };
  document.addEventListener("keydown", onKeydown);
  backdrop.addEventListener("click", (event) => {
    if (event.target === backdrop) close();
  });
  backdrop.querySelector("[data-catalog-edit-close]").addEventListener("click", close);
  formElement.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (formElement.dataset.pending === "true") return;
    const submitButton = formElement.querySelector('button[type="submit"]');
    try {
      clearFormError(formElement);
      formElement.dataset.pending = "true";
      setPending(submitButton, true, "Сохраняем");
      await mutate(config.endpoint, config.normalize(collect(formElement)), "PATCH");
      showAlert("Справочник обновлен");
      close();
      await loadAll();
    } catch (error) {
      showFormError(formElement, error.message);
      showAlert(error.message, "error");
    } finally {
      delete formElement.dataset.pending;
      setPending(submitButton, false);
    }
  });
  formElement.querySelector("input, select, textarea")?.focus();
}

async function deleteCatalogEntry(kind, id, button) {
  const collections = {
    category: "categories",
    product: "products",
  };
  const endpoints = {
    category: `/categories/${id}`,
    product: `/products/${id}`,
  };
  const row = state.data[collections[kind]]?.find((item) => Number(item.id) === Number(id));
  if (!row || !endpoints[kind]) {
    showAlert("Запись не найдена. Обновите страницу и попробуйте еще раз.", "error");
    return;
  }
  const label = kind === "category" ? "категорию" : "товар";
  const ok = await confirmAction(
    `Скрыть ${label} «${row.name}»? Новые операции больше не будут предлагать эту запись, но история документов сохранится.`,
    { title: "Скрыть запись", confirmText: "Скрыть", tone: "danger" },
  );
  if (!ok) return;
  try {
    setPending(button, true, "Скрываем");
    await removeResource(endpoints[kind]);
    showAlert("Запись скрыта из справочника");
    await loadAll();
  } catch (error) {
    showAlert(error.message, "error");
  } finally {
    setPending(button, false);
  }
}

function daysUntil(value) {
  if (!value) return null;
  const end = new Date(`${value}T00:00:00`);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.ceil((end - today) / 86400000);
}

function productFreeQuantity(productId) {
  return state.data.balances.items
    .filter((row) => Number(row.product_id) === Number(productId))
    .reduce((sum, row) => sum + Number(row.free_quantity || 0), 0);
}

function lowStockProducts() {
  return state.data.products.filter((product) => {
    const reorderPoint = Number(product.reorder_point || 0);
    return reorderPoint > 0 && productFreeQuantity(product.id) < reorderPoint;
  });
}

function expiringBalances(days = 30) {
  return state.data.balances.items.filter((row) => {
    const left = daysUntil(row.expires_on);
    return left !== null && left >= 0 && left <= days;
  });
}

function deviceById(deviceId) {
  return state.data.sensorDevices.find((device) => Number(device.id) === Number(deviceId)) || null;
}

function conditionRangeText(min, max, unit) {
  if (min !== null && min !== undefined && max !== null && max !== undefined) return `${min}…${max} ${unit}`;
  if (min !== null && min !== undefined) return `от ${min} ${unit}`;
  if (max !== null && max !== undefined) return `до ${max} ${unit}`;
  return `норма не задана`;
}

function conditionBreachDetails(reading, device = deviceById(reading.device_id)) {
  const details = [];
  if (!device) return details;
  const temperature = Number(reading.temperature_c);
  if (reading.temperature_c !== null && reading.temperature_c !== undefined && !Number.isNaN(temperature)) {
    const min = device.min_temperature_c === null || device.min_temperature_c === undefined ? null : Number(device.min_temperature_c);
    const max = device.max_temperature_c === null || device.max_temperature_c === undefined ? null : Number(device.max_temperature_c);
    const range = conditionRangeText(device.min_temperature_c, device.max_temperature_c, "°C");
    if (min !== null && temperature < min) details.push(`Температура ниже нормы: ${reading.temperature_c} °C, норма ${range}`);
    if (max !== null && temperature > max) details.push(`Температура выше нормы: ${reading.temperature_c} °C, норма ${range}`);
  }
  const humidity = Number(reading.humidity_percent);
  if (reading.humidity_percent !== null && reading.humidity_percent !== undefined && !Number.isNaN(humidity)) {
    const min = device.min_humidity_percent === null || device.min_humidity_percent === undefined ? null : Number(device.min_humidity_percent);
    const max = device.max_humidity_percent === null || device.max_humidity_percent === undefined ? null : Number(device.max_humidity_percent);
    const range = conditionRangeText(device.min_humidity_percent, device.max_humidity_percent, "%");
    if (min !== null && humidity < min) details.push(`Влажность ниже нормы: ${reading.humidity_percent} %, норма ${range}`);
    if (max !== null && humidity > max) details.push(`Влажность выше нормы: ${reading.humidity_percent} %, норма ${range}`);
  }
  return details;
}

function latestConditionWarnings() {
  const latestByDevice = new Map();
  [...(state.data.sensorReadings.items || [])]
    .sort((a, b) => new Date(b.recorded_at || 0) - new Date(a.recorded_at || 0) || Number(b.id || 0) - Number(a.id || 0))
    .forEach((reading) => {
      if (!latestByDevice.has(reading.device_id)) latestByDevice.set(reading.device_id, reading);
    });
  return [...latestByDevice.values()].filter((reading) => reading.status === "warning");
}

function conditionActionText(reading) {
  const details = conditionBreachDetails(reading);
  const temperatureProblem = details.some((item) => item.includes("Температура"));
  if (temperatureProblem) return "Проверьте дверь, питание холодильника и перенесите чувствительные партии при необходимости.";
  return "Проверьте вентиляцию, упаковку и состояние помещения.";
}

function actionQueue() {
  return [
    ...latestConditionWarnings()
      .slice(0, 3)
      .map((reading) => ({
        severity: "bad",
        title: `Проверьте склад: ${reading.device_name || `датчик #${reading.device_id}`}`,
        meta: `${conditionBreachDetails(reading).join(" · ") || "Показание вне нормы"} · ${rawNameById("warehouses", reading.warehouse_id)}`,
        view: "conditions",
      })),
    ...state.data.warehouses
      .filter((warehouse) => warehouse.inventory_lock)
      .map((warehouse) => ({
        severity: "bad",
        title: `Склад заблокирован: ${warehouse.name}`,
        meta: "Движения остановлены до завершения инвентаризации",
        view: "inventory",
      })),
    ...state.data.documents
      .filter((document) => document.status === "draft")
      .map((document) => ({
        severity: "warn",
        title: `Черновик документа #${document.id}`,
        meta: `${humanDocumentType(document.document_type)} · ${rawNameById("warehouses", document.warehouse_id)} · строк: ${document.lines?.length || 0}`,
        view: "documents",
      })),
    ...lowStockProducts().map((product) => ({
      severity: "warn",
      title: `Ниже точки заказа: ${product.name}`,
      meta: `Свободно ${productFreeQuantity(product.id).toFixed(3)} · точка ${product.reorder_point}`,
      view: "purchase-requests",
    })),
    ...state.data.purchaseRequests
      .filter((request) => ["draft", "requested", "open"].includes(String(request.status || "open")))
      .map((request) => ({
        severity: "warn",
        title: `Заявка на закупку #${request.id}`,
        meta: `${rawNameById("products", request.product_id)} · нужно ${request.quantity || "—"}`,
        view: "purchase-requests",
      })),
    ...state.data.batches
      .filter((batch) => ["quarantine", "blocked"].includes(batch.status))
      .map((batch) => ({
        severity: batch.status === "blocked" ? "bad" : "warn",
        title: `${batch.status === "blocked" ? "Заблокирована" : "Карантин"} партия #${batch.id}`,
        meta: `${rawNameById("products", batch.product_id)} · серия ${batch.lot}`,
        view: "operations",
      })),
    ...expiringBalances(30).map((balance) => ({
      severity: "warn",
      title: `Срок годности до ${balance.expires_on}`,
      meta: `${rawNameById("products", balance.product_id)} · партия #${balance.batch_id} · ${rawNameById("warehouses", balance.warehouse_id)}`,
      view: "receipts",
    })),
  ].slice(0, 12);
}

function collect(formElement) {
  const data = new FormData(formElement);
  const result = {};
  for (const [key, value] of data.entries()) {
    if (value === "") continue;
    if (key.endsWith("_id") || ["batch_id", "product_id", "supplier_id", "warehouse_id", "source_warehouse_id", "target_warehouse_id"].includes(key)) {
      result[key] = Number(value);
    } else if (["quantity", "target_quantity", "conversion_factor", "loss_quantity", "unit_price", "target_unit_price", "reorder_point", "safety_stock", "actual_quantity", "temperature_c", "humidity_percent", "min_temperature_c", "max_temperature_c", "min_humidity_percent", "max_humidity_percent"].includes(key)) {
      result[key] = String(value);
    } else if (key === "quarantine" || key === "is_controlled") {
      result[key] = value === "true";
    } else {
      result[key] = value;
    }
  }
  return result;
}

function newReceiptDocumentLine() {
  return { product_id: "", quantity: "", unit_price: "0", lot: "", serial_number: "", expires_on: "" };
}

function newWriteoffDocumentLine() {
  return { batch_id: "", quantity: "", reason: "Списание по документу", patient_id: "", doctor_id: "", medical_record_no: "", second_approver_id: "", second_approval_note: "" };
}

function compactLine(line) {
  return Object.fromEntries(Object.entries(line).filter(([, value]) => value !== "" && value !== null && value !== undefined));
}

function receiptDocumentLinesPayload() {
  return state.documentForms.receipt.lines.map((line) => ({
    ...compactLine(line),
    product_id: Number(line.product_id),
    quantity: String(line.quantity),
    unit_price: String(line.unit_price || "0"),
    expires_on: line.expires_on || null,
    quarantine: true,
  }));
}

function writeoffDocumentLinesPayload() {
  return state.documentForms.writeoff.lines.map((line) => ({
    ...compactLine(line),
    batch_id: Number(line.batch_id),
    quantity: String(line.quantity),
    reason: line.reason,
    patient_id: line.patient_id || null,
    doctor_id: line.doctor_id || null,
    medical_record_no: line.medical_record_no || null,
    second_approver_id: line.second_approver_id || null,
    second_approval_note: line.second_approval_note || null,
  }));
}

function controlledWriteoffDocumentIssues(document) {
  if (!document || document.document_type !== "write_off") return [];
  return (document.lines || []).filter((line) => {
    if (!Object.prototype.hasOwnProperty.call(line, "patient_id")) return false;
    const missing = controlledWriteoffMetadataMissing({
      batch_id: line.batch_id,
      patient_id: line.patient_id,
      doctor_id: line.doctor_id,
      medical_record_no: line.medical_record_no,
      second_approver_id: line.second_approver_id,
    });
    return missing.length > 0;
  });
}

function resetDocumentLines(kind) {
  if (kind === "receipt") {
    state.documentForms.receipt.lines = [newReceiptDocumentLine()];
  }
  if (kind === "writeoff") {
    state.documentForms.writeoff.lines = [newWriteoffDocumentLine()];
  }
}

function renderNav() {
  ensureAccessibleView();
  el("nav").innerHTML = visibleViews().map(([id, icon, label]) => `
    <button class="${state.view === id ? "active" : ""}" data-view="${id}">
      <span>${icon}</span><span>${label}</span>
    </button>
  `).join("");
  el("nav").querySelectorAll("button").forEach((button) => {
    button.addEventListener("click", () => {
      state.view = button.dataset.view;
      render();
    });
  });
}

function updateWarehouseSelector() {
  const node = el("warehouse-filter");
  if (!node) return;
  const selected = node.value;
  const scoped = new Set((state.auth.actor?.warehouse_ids || []).map(String));
  const warehouses = scoped.size
    ? state.data.warehouses.filter((warehouse) => scoped.has(String(warehouse.id)))
    : state.data.warehouses;
  node.innerHTML = [
    `<option value="">Все доступные склады</option>`,
    ...warehouses.map((warehouse) => (
      `<option value="${escapeAttr(warehouse.id)}">${escapeHtml(warehouse.name)} (#${escapeHtml(warehouse.id)})</option>`
    )),
  ].join("");
  if ([...node.options].some((option) => option.value === selected)) {
    node.value = selected;
  } else if (warehouses.length === 1) {
    node.value = String(warehouses[0].id);
  }
}

function setupSteps() {
  return [
    {
      key: "categories",
      title: "Добавьте категорию",
      meta: "Например: медикаменты, расходники, оборудование.",
      done: state.data.categories.length > 0,
      view: "catalog",
    },
    {
      key: "products",
      title: "Создайте товар",
      meta: "Укажите название, код, единицу измерения и категорию.",
      done: state.data.products.length > 0,
      view: "catalog",
    },
    {
      key: "suppliers",
      title: "Добавьте поставщика",
      meta: "Поставщик нужен для прихода партии на склад.",
      done: state.data.suppliers.length > 0,
      view: "catalog",
    },
    {
      key: "warehouses",
      title: "Добавьте склад",
      meta: "Это может быть основной склад, отделение или кабинет.",
      done: state.data.warehouses.length > 0,
      view: "catalog",
    },
    {
      key: "receipts",
      title: "Примите первую партию",
      meta: "После прихода товар появится в остатках и станет доступен для операций.",
      done: state.data.balances.items.length > 0,
      view: "receipts",
    },
  ];
}

function renderSetupGuide() {
  const steps = setupSteps();
  if (steps.every((step) => step.done)) return "";
  const nextStep = steps.find((step) => !step.done);
  return `
    <div class="panel span-12 setup-guide">
      <div class="setup-head">
        <div>
          <span class="eyebrow">Первый запуск</span>
          <h2>Что сделать, чтобы склад начал работать</h2>
        </div>
        ${nextStep ? `<button class="primary" type="button" data-go-view="${escapeAttr(nextStep.view)}">${escapeHtml(nextStep.title)}</button>` : ""}
      </div>
      <div class="setup-steps">
        ${steps.map((step, index) => `
          <button class="setup-step ${step.done ? "done" : ""}" type="button" data-go-view="${escapeAttr(step.view)}">
            <span>${step.done ? "✓" : index + 1}</span>
            <strong>${escapeHtml(step.title)}</strong>
            <small>${escapeHtml(step.meta)}</small>
          </button>
        `).join("")}
      </div>
    </div>
  `;
}

function receiptPrerequisites() {
  const missing = [];
  if (!state.data.categories.length) missing.push("категорию");
  if (!state.data.products.length) missing.push("товар");
  if (!state.data.suppliers.length) missing.push("поставщика");
  if (!state.data.warehouses.length) missing.push("склад");
  if (!missing.length) return "";
  return `
    <div class="panel span-12 warning-panel receipt-prerequisites">
      <strong>Приход пока нельзя оформить</strong>
      <span>Сначала добавьте: ${escapeHtml(missing.join(", "))}.</span>
      <button class="secondary" type="button" data-go-view="catalog">Перейти в товары и склады</button>
    </div>
  `;
}

function workflowNotice(title, text, view, buttonText) {
  return `
    <div class="panel span-12 warning-panel workflow-notice">
      <div>
        <strong>${escapeHtml(title)}</strong>
        <span>${escapeHtml(text)}</span>
      </div>
      <button class="secondary" type="button" data-go-view="${escapeAttr(view)}">${escapeHtml(buttonText)}</button>
    </div>
  `;
}

function needsStockNotice(actionText = "Продолжить") {
  if (state.data.balances.items.length > 0) return "";
  return workflowNotice(
    "Нет доступных остатков",
    "Сначала примите товар на склад. После этого здесь появятся партии для выбора.",
    "receipts",
    actionText,
  );
}

function needsWarehouseNotice(actionText = "Добавить склад") {
  if (state.data.warehouses.length > 0) return "";
  return workflowNotice(
    "Склад еще не создан",
    "Для этой операции нужен хотя бы один склад или кабинет.",
    "catalog",
    actionText,
  );
}

function needsProductNotice(actionText = "Создать товар") {
  if (state.data.products.length > 0) return "";
  return workflowNotice(
    "Товары еще не созданы",
    "Сначала добавьте категорию и товар, чтобы можно было оформить заявку или приход.",
    "catalog",
    actionText,
  );
}

function renderDashboard() {
  if (isLimitedRole()) return renderLimitedDashboard();
  const balances = state.data.balances.items;
  const free = balances.reduce((sum, item) => sum + Number(item.free_quantity || 0), 0);
  const reserved = balances.reduce((sum, item) => sum + Number(item.reserved_quantity || 0), 0);
  const quarantine = state.data.batches.filter((batch) => batch.status === "quarantine").length;
  const activeInventory = state.data.inventorySessions.filter((session) => session.status === "in_progress").length;
  const purchaseAttention = state.data.purchaseRequests.length
    + state.data.analytics.items.filter((row) => Number(row.recommended_order_quantity || 0) > 0).length;
  const conditionWarnings = state.data.sensorReadings.items.filter((row) => row.status === "warning").length;
  const queue = actionQueue();
  return `
    <div class="grid">
      ${state.loadWarnings.length ? `<div class="panel span-12 warning-panel">${state.loadWarnings.map((warning) => `<div>${escapeHtml(warning)}</div>`).join("")}</div>` : ""}
      ${renderSetupGuide()}
      <div class="panel span-3 metric"><span>Свободный остаток</span><strong>${free.toFixed(3)}</strong></div>
      <div class="panel span-3 metric"><span>В резерве</span><strong>${reserved.toFixed(3)}</strong></div>
      <div class="panel span-3 metric"><span>Партии в карантине</span><strong>${quarantine}</strong></div>
      <div class="panel span-3 metric"><span>Уведомления</span><strong>${state.data.notifications.total || 0}</strong></div>
      <div class="panel span-12 control-strip">
        ${controlItem("Мало на складе", lowStockProducts().length, "catalog")}
        ${controlItem("Срок до 30 дней", expiringBalances(30).length, "receipts")}
        ${controlItem("Документы ждут", state.data.documents.filter((row) => row.status === "draft").length, "documents")}
        ${controlItem("Заказать", purchaseAttention, "purchase-requests")}
        ${controlItem("Идет проверка", activeInventory, "inventory")}
        ${controlItem("Температура/влажность", conditionWarnings, "conditions")}
      </div>
      <div class="table-panel span-8">
        <div class="toolbar"><h2>Остатки по партиям</h2><span class="status-dot ${state.realtime === "online" ? "ok" : ""}">Автообновление: ${state.realtime === "online" ? "включено" : "нет связи"}</span><div class="row-actions"><button class="secondary" data-export-report="balances">Выгрузить CSV</button><button class="secondary" data-action="reload">Обновить</button></div></div>
        ${balancesTable(filteredBalances(balances), "Остатков пока нет. Добавьте приход товара или выберите другой склад.")}
      </div>
      <div class="table-panel span-4">
        <h2>Очередь действий</h2>
        ${renderActionQueue(queue)}
      </div>
      <div class="table-panel span-12">
        <h2>Последние уведомления</h2>
        ${table([
          { label: "Событие", render: (row) => humanNotificationType(row.notification_type) },
          { label: "Сообщение", render: (row) => `${escapeHtml(row.title)}<br><span class="badge ${row.is_read ? "" : "warn"}">${row.is_read ? "прочитано" : "новое"}</span>` },
          { label: "Склад", render: (row) => row.warehouse_id ? nameById("warehouses", row.warehouse_id) : "—" },
          { label: "Создано", render: (row) => dateText(row.created_at) },
        ], state.data.notifications.items.slice(0, 8))}
      </div>
    </div>
  `;
}

function controlItem(label, value, view) {
  const tone = Number(value) > 0 ? "warn" : "ok";
  return `<button class="control-item ${tone}" data-go-view="${escapeAttr(safeViewTarget(view))}"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></button>`;
}

function renderActionQueue(items) {
  if (!items.length) return `<div class="empty-state"><strong>Критичных действий нет</strong><span>Складские риски появятся здесь автоматически</span></div>`;
  return `<div class="action-list">${items.map((item) => `
    <button class="action-item ${escapeAttr(item.severity)}" data-go-view="${escapeAttr(safeViewTarget(item.view))}">
      <strong>${escapeHtml(item.title)}</strong>
      <span>${escapeHtml(item.meta)}</span>
    </button>
  `).join("")}</div>`;
}

function renderLimitedDashboard() {
  const balances = state.data.balances.items;
  const free = balances.reduce((sum, item) => sum + Number(item.free_quantity || 0), 0);
  const expiring = expiringBalances(30).length;
  return `
    <div class="grid">
      ${roleAccessNotice()}
      ${state.loadWarnings.length ? `<div class="panel span-12 warning-panel">${state.loadWarnings.map((warning) => `<div>${escapeHtml(warning)}</div>`).join("")}</div>` : ""}
      <div class="panel span-4 metric"><span>Свободный остаток</span><strong>${free.toFixed(3)}</strong></div>
      <div class="panel span-4 metric"><span>Срок до 30 дней</span><strong>${expiring}</strong></div>
      <div class="panel span-4 metric"><span>Уведомления</span><strong>${state.data.notifications.total || 0}</strong></div>
      <div class="tablet-writeoff-panel span-12">
        <div class="tablet-copy">
          <span class="eyebrow">Планшетный режим</span>
          <h2>Списать партию</h2>
        </div>
        ${tabletWriteoffForm()}
      </div>
      <div class="table-panel span-12">
        <div class="toolbar"><h2>Доступные остатки</h2><button class="secondary" data-action="reload">Обновить</button></div>
        ${balancesTable(filteredBalances(balances), "Остатков пока нет. Проверьте выбранный склад или обратитесь к заведующему складом.")}
      </div>
    </div>
  `;
}

function balanceSummary(rows) {
  if (!rows.length) return "";
  const productCount = new Set(rows.map((row) => row.product_id)).size;
  const warehouseCount = new Set(rows.map((row) => row.warehouse_id)).size;
  const availableBatchCount = new Set(rows
    .filter((row) => Number(row.free_quantity || 0) > 0)
    .map((row) => row.batch_id)).size;
  const free = rows.reduce((sum, row) => sum + Number(row.free_quantity || 0), 0);
  const expiring = rows.filter((row) => {
    const left = daysUntil(row.expires_on);
    return left !== null && left >= 0 && left <= 30;
  }).length;
  return `
    <div class="balance-summary" aria-label="Краткая сводка остатков">
      <div><span>Позиции</span><strong>${escapeHtml(rows.length)}</strong></div>
      <div><span>Товары</span><strong>${escapeHtml(productCount)}</strong></div>
      <div><span>Склады</span><strong>${escapeHtml(warehouseCount)}</strong></div>
      <div><span>Партии с остатком</span><strong>${escapeHtml(availableBatchCount)}</strong></div>
      <div><span>Свободно к использованию</span><strong>${escapeHtml(free.toFixed(3))}</strong></div>
      <div><span>Срок до 30 дней</span><strong>${escapeHtml(expiring)}</strong></div>
    </div>
  `;
}

function balancesTable(rows, empty = "Данных пока нет") {
  return `${balanceSummary(rows)}${table([
    { label: "Товар", render: (row) => nameById("products", row.product_id) },
    { label: "Партия", render: (row) => batchButton(row.batch_id) },
    { label: "Склад", render: (row) => nameById("warehouses", row.warehouse_id) },
    { label: "Всего", key: "total_quantity" },
    { label: "Резерв", key: "reserved_quantity" },
    { label: "Свободно", key: "free_quantity" },
    { label: "Статус", render: (row) => badge(row.batch_status) },
    { label: "Годен до", render: (row) => row.expires_on || "—" },
  ], rows, searchEmptyText(empty))}`;
}

function nameById(collection, id) {
  return escapeHtml(rawNameById(collection, id));
}

function rawNameById(collection, id) {
  const item = state.data[collection].find((entry) => Number(entry.id) === Number(id));
  return item ? `${item.name} (#${id})` : `#${id}`;
}

function rawBatchLabel(batchId) {
  if (!batchId) return "—";
  const batch = state.data.batches.find((entry) => Number(entry.id) === Number(batchId));
  if (!batch) return `#${batchId}`;
  return `${rawNameById("products", batch.product_id)} · серия ${batch.lot} (#${batch.id})`;
}

function batchLabel(batchId) {
  if (!batchId) return "—";
  const batch = state.data.batches.find((entry) => Number(entry.id) === Number(batchId));
  if (!batch) return `#${batchId}`;
  return `${nameById("products", batch.product_id)} · серия ${escapeHtml(batch.lot)} (#${escapeHtml(batch.id)})`;
}

function batchDetailLabel(batchId) {
  return batchButton(batchId, batchLabel(batchId));
}

function documentTitle(document) {
  return `${humanDocumentType(document.document_type)} #${document.id} · ${humanStatus(document.status)}`;
}

function compactTraceTable(columns, rows, empty) {
  return table(columns, rows, empty).replaceAll("table-wrap", "table-wrap compact-trace-table");
}

function traceabilitySummary(detail) {
  const free = (detail.balances || []).reduce((sum, row) => sum + Number(row.free_quantity || 0), 0);
  const reserved = (detail.balances || []).reduce((sum, row) => sum + Number(row.reserved_quantity || 0), 0);
  const movements = detail.movements || [];
  return {
    free,
    reserved,
    movements: movements.length,
    documents: (detail.documents || []).length,
    transformations: (detail.transformations || []).length,
    recalls: (detail.recalls || []).length,
  };
}

function renderBatchTraceability(detail) {
  const batch = detail.batch;
  const summary = traceabilitySummary(detail);
  return `
    <section class="confirm-modal trace-modal" role="dialog" aria-modal="true" aria-labelledby="batch-trace-title">
      <header>
        <div>
          <h2 id="batch-trace-title">${escapeHtml(rawNameById("products", batch.product_id))}</h2>
          <span class="helper-text">Партия #${escapeHtml(batch.id)} · серия ${escapeHtml(batch.lot)}${batch.serial_number ? ` · серийный ${escapeHtml(batch.serial_number)}` : ""}</span>
        </div>
        <button class="icon-button" type="button" data-trace-close title="Закрыть">×</button>
      </header>
      <div class="trace-body">
        <div class="trace-summary">
          <div><span>Поставщик</span><strong>${nameById("suppliers", batch.supplier_id)}</strong></div>
          <div><span>Статус</span>${badge(batch.status)}</div>
          <div><span>Серийный номер</span><strong>${escapeHtml(batch.serial_number || "не указан")}</strong></div>
          <div><span>Годен до</span><strong>${escapeHtml(batch.expires_on || "не указан")}</strong></div>
          <div><span>Свободно</span><strong>${summary.free.toFixed(3)}</strong></div>
          <div><span>В резерве</span><strong>${summary.reserved.toFixed(3)}</strong></div>
          <div><span>Движений</span><strong>${summary.movements}</strong></div>
          <div><span>Фасовок</span><strong>${summary.transformations}</strong></div>
          <div><span>Отзывов</span><strong>${summary.recalls}</strong></div>
        </div>
        <div class="trace-section">
          <h3>Где лежит партия</h3>
          ${compactTraceTable([
            { label: "Склад", render: (row) => nameById("warehouses", row.warehouse_id) },
            { label: "Всего", key: "total_quantity" },
            { label: "Резерв", key: "reserved_quantity" },
            { label: "Свободно", key: "free_quantity" },
            { label: "Статус", render: (row) => badge(row.batch_status) },
          ], detail.balances || [], "По партии нет остатков на складах.")}
        </div>
        <div class="trace-section">
          <h3>Последние движения</h3>
          ${compactTraceTable([
            { label: "Время", render: (row) => dateText(row.created_at) },
            { label: "Действие", render: (row) => badge(row.movement_type) },
            { label: "Склад", render: (row) => nameById("warehouses", row.warehouse_id) },
            { label: "Количество", key: "quantity" },
            { label: "Причина", key: "reason" },
          ], detail.movements || [], "Движений по партии пока нет.")}
        </div>
        <div class="trace-section">
          <h3>Цепочка фасовки</h3>
          ${compactTraceTable([
            { label: "Время", render: (row) => dateText(row.created_at) },
            { label: "Исходная партия", render: (row) => batchDetailLabel(row.source_batch_id) },
            { label: "Полученная партия", render: (row) => batchDetailLabel(row.target_batch_id) },
            { label: "Взяли", key: "source_quantity" },
            { label: "Получили", key: "target_quantity" },
            { label: "Потери", key: "loss_quantity" },
            { label: "Причина", key: "reason" },
          ], detail.transformations || [], "Эта партия пока не участвовала в фасовке.")}
        </div>
        <div class="trace-section">
          <h3>Отзывы партии</h3>
          ${compactTraceTable([
            { label: "Время", render: (row) => dateText(row.created_at) },
            { label: "Причина", key: "reason" },
            { label: "Источник", key: "source" },
            { label: "Основание", render: (row) => escapeHtml(row.reference || "—") },
            { label: "Создал", key: "created_by" },
          ], detail.recalls || [], "Отзывов по партии нет.")}
        </div>
        <div class="trace-section">
          <h3>Документы</h3>
          ${compactTraceTable([
            { label: "Документ", render: (row) => escapeHtml(documentTitle(row)) },
            { label: "Склад", render: (row) => nameById("warehouses", row.warehouse_id) },
            { label: "Создал", key: "created_by" },
            { label: "Утвердил", render: (row) => escapeHtml(row.approved_by || "—") },
            { label: "Создан", render: (row) => dateText(row.created_at) },
            { label: "Утвержден", render: (row) => dateText(row.approved_at) },
            { label: "Проведен", render: (row) => dateText(row.posted_at) },
          ], detail.documents || [], "Документов по партии пока нет.")}
        </div>
      </div>
      <footer>
        <button class="secondary" type="button" data-trace-close>Закрыть</button>
      </footer>
    </section>
  `;
}

async function showBatchTraceability(batchId) {
  const backdrop = document.createElement("div");
  backdrop.className = "modal-backdrop";
  backdrop.innerHTML = `
    <section class="confirm-modal trace-modal" role="dialog" aria-modal="true" aria-labelledby="batch-trace-title">
      <header>
        <h2 id="batch-trace-title">Загружаем партию #${escapeHtml(batchId)}</h2>
      </header>
      <p class="confirm-message">Собираем остатки, движения и документы партии.</p>
    </section>
  `;
  document.body.appendChild(backdrop);
  const previousFocus = document.activeElement;
  const close = () => {
    backdrop.remove();
    document.removeEventListener("keydown", onKeydown);
    if (previousFocus && typeof previousFocus.focus === "function") previousFocus.focus();
  };
  const onKeydown = (event) => {
    if (event.key === "Escape") close();
  };
  document.addEventListener("keydown", onKeydown);
  backdrop.addEventListener("click", (event) => {
    if (event.target === backdrop) close();
  });
  try {
    const detail = await request(`/batches/${batchId}/traceability?limit=50`);
    backdrop.innerHTML = renderBatchTraceability(detail);
    backdrop.querySelectorAll("[data-trace-close]").forEach((button) => {
      button.addEventListener("click", close);
    });
    backdrop.querySelector("[data-trace-close]")?.focus();
  } catch (error) {
    backdrop.innerHTML = `
      <section class="confirm-modal danger" role="dialog" aria-modal="true" aria-labelledby="batch-trace-title">
        <header><h2 id="batch-trace-title">Не удалось открыть партию</h2></header>
        <p class="confirm-message">${escapeHtml(error.message)}</p>
        <footer><button class="secondary" type="button" data-trace-close>Закрыть</button></footer>
      </section>
    `;
    backdrop.querySelector("[data-trace-close]").addEventListener("click", close);
  }
}

function renderCatalog() {
  const directoryRows = [
    ...state.data.warehouses.map((row) => ({ ...row, kind: "Склад", catalogKind: "warehouse" })),
    ...state.data.suppliers.map((row) => ({ ...row, kind: "Поставщик", catalogKind: "supplier" })),
    ...state.data.categories.map((row) => ({ ...row, kind: "Категория", catalogKind: "category" })),
  ];
  const catalogStats = [
    ["Категории", state.data.categories.length],
    ["Товары", state.data.products.length],
    ["Поставщики", state.data.suppliers.length],
    ["Склады", state.data.warehouses.length],
  ];
  const catalogReady = state.data.categories.length
    && state.data.products.length
    && state.data.suppliers.length
    && state.data.warehouses.length;
  return `
    <div class="grid">
      <div class="panel span-12 catalog-overview">
        ${catalogStats.map(([label, value]) => `
          <div>
            <span>${escapeHtml(label)}</span>
            <strong>${escapeHtml(value)}</strong>
          </div>
        `).join("")}
      </div>
      <div class="panel span-12 catalog-guidance ${catalogReady ? "ok" : "warn"}">
        <strong>${catalogReady ? "Справочники готовы к работе" : "Заполните справочники по порядку"}</strong>
        <span>${catalogReady
          ? "Можно оформлять приход, списание, перемещение, заявки и инвентаризацию."
          : "Сначала добавьте категорию справа, затем создайте товар слева. После этого добавьте поставщика и склад."}</span>
      </div>
      <div class="form-panel span-7"><h2>Новый товар</h2>${form("product-form", [
        { label: "Название", name: "name", required: true },
        { label: "Код товара", name: "sku", required: true },
        { label: "Ед. изм.", name: "unit", type: "select", options: productUnitOptions("Выберите единицу"), value: "шт", required: true },
        { label: "Категория", name: "category_id", type: "select", options: optionsFrom("categories", "Выберите категорию"), required: true },
        { label: "Точка заказа", name: "reorder_point", type: "number", step: "0.001", min: "0", value: "0" },
        { label: "Страховой запас", name: "safety_stock", type: "number", step: "0.001", min: "0", value: "0" },
        { label: "ПКУ / контролируемый товар", name: "is_controlled", type: "select", options: staticOptions([["false", "Нет"], ["true", "Да"]], "Выберите значение"), value: "false" },
        { label: "Штрихкод", name: "barcode" },
        { label: "Сертификат", name: "certificate_ref" },
        { label: "Описание", name: "description", type: "textarea", full: true },
      ], "Создать товар", {
        disabledSubmit: state.data.categories.length === 0,
        submitHint: state.data.categories.length === 0 ? "Сначала добавьте категорию справа." : "",
      })}</div>
      <div class="span-5 quick-directory">
        <div class="form-panel"><h2>Новая категория</h2>${form("category-form", [
          { label: "Название категории", name: "name", required: true },
        ], "Добавить категорию")}</div>
        <div class="form-panel"><h2>Новый поставщик</h2>${form("supplier-form", [
          { label: "Название поставщика", name: "name", required: true },
          { label: "БИН", name: "bin" },
          { label: "Телефон", name: "phone", type: "tel" },
          { label: "Адрес", name: "address" },
          { label: "Рейтинг", name: "rating", type: "number", min: "1", max: "5", step: "1" },
          { label: "Постоянный поставщик", name: "is_preferred", type: "select", options: staticOptions([["false", "Нет"], ["true", "Да"]], "Выберите значение"), value: "false" },
          { label: "Контактное лицо", name: "contact_person" },
          { label: "Email", name: "email", type: "email" },
          { label: "Номер договора", name: "contract_number" },
          { label: "Договор действует до", name: "contract_expires_on", type: "date" },
          { label: "Условия оплаты", name: "payment_terms" },
          { label: "Заметки", name: "notes", type: "textarea", full: true },
        ], "Добавить поставщика")}</div>
        <div class="form-panel"><h2>Новый склад</h2>${form("warehouse-form", [
          { label: "Название склада или кабинета", name: "name", required: true },
          { label: "Отделение", name: "department" },
          { label: "ID компании Tetis", name: "tetis_org_id" },
          { label: "ID склада в Tetis", name: "external_tetis_id" },
          { label: "Зона хранения", name: "storage_zone" },
          { label: "Лимит вместимости", name: "capacity_limit", type: "number", step: "0.001", min: "0" },
          { label: "Условия хранения", name: "storage_conditions" },
          { label: "Ответственный", name: "responsible_person" },
        ], "Добавить склад")}</div>
      </div>
      <div class="table-panel span-7"><h2>Товары</h2>${table([
        { label: "Номер", key: "id" }, { label: "Название", key: "name" }, { label: "Код товара", key: "sku" },
        { label: "Ед.", key: "unit" },
        { label: "Категория", render: (row) => nameById("categories", row.category_id) },
        { label: "Штрихкод", render: (row) => escapeHtml(row.barcode || "—") },
        { label: "Сертификат", render: (row) => escapeHtml(row.certificate_ref || "—") },
        { label: "Точка заказа", render: (row) => qty(row.reorder_point) },
        { label: "Страховой запас", render: (row) => qty(row.safety_stock) },
        { label: "ПКУ", render: (row) => row.is_controlled ? badge("да") : "нет" },
        { label: "", render: (row) => `<button class="secondary compact-action" type="button" data-print-product-label="${escapeAttr(row.id)}">Этикетка</button>` },
        { label: "", render: (row) => `<button class="secondary compact-action" type="button" data-edit-catalog="product" data-edit-id="${escapeAttr(row.id)}">Исправить</button>` },
        { label: "", render: (row) => `<button class="danger compact-action" type="button" data-delete-catalog="product" data-delete-id="${escapeAttr(row.id)}">Скрыть</button>` },
      ], filteredRows(state.data.products, (row) => [row.id, row.name, row.sku, row.unit, row.barcode, row.certificate_ref, row.description, rawNameById("categories", row.category_id)]), "Товаров пока нет. Создайте категорию и новый товар в форме слева.")}</div>
      <div class="table-panel span-5"><h2>Справочник</h2>${table([
        { label: "Тип", render: (row) => row.kind },
        { label: "Номер", key: "id" },
        { label: "Название", key: "name" },
        { label: "Детали", render: (row) => escapeHtml([row.department, row.storage_zone ? `Зона: ${row.storage_zone}` : "", row.capacity_limit ? `Лимит: ${row.capacity_limit}` : "", row.storage_conditions, row.responsible_person ? `Ответственный: ${row.responsible_person}` : "", row.bin, row.phone, row.email, row.contact_person, row.address, row.contract_number ? `Договор: ${row.contract_number}` : "", row.contract_expires_on ? `до ${row.contract_expires_on}` : "", row.rating ? `Рейтинг: ${row.rating}/5` : "", row.is_preferred ? "Постоянный" : "", row.tetis_org_id ? `Tetis: ${row.tetis_org_id}` : "", row.external_tetis_id ? `Склад Tetis: ${row.external_tetis_id}` : ""].filter(Boolean).join(" · ") || "—") },
        { label: "Статус", render: (row) => row.kind === "Склад" ? badge(row.inventory_lock ? "locked" : "open") : "—" },
        { label: "", render: (row) => row.kind === "Склад"
          ? `<button class="${row.inventory_lock ? "secondary" : "danger"}" data-lock-warehouse="${row.id}" data-lock-value="${row.inventory_lock ? "false" : "true"}">${row.inventory_lock ? "Разблокировать" : "Заблокировать"}</button>`
          : "" },
        { label: "", render: (row) => row.catalogKind === "supplier" ? `<button class="secondary compact-action" type="button" data-supplier-card="${escapeAttr(row.id)}">Карточка</button>` : "" },
        { label: "", render: (row) => row.catalogKind === "supplier" ? `<button class="secondary compact-action" type="button" data-export-price-history="${escapeAttr(row.id)}">История цен</button>` : "" },
        { label: "", render: (row) => `<button class="secondary compact-action" type="button" data-edit-catalog="${escapeAttr(row.catalogKind)}" data-edit-id="${escapeAttr(row.id)}">Исправить</button>` },
        { label: "", render: (row) => row.catalogKind === "category" ? `<button class="danger compact-action" type="button" data-delete-catalog="category" data-delete-id="${escapeAttr(row.id)}">Скрыть</button>` : "" },
      ], filteredRows(directoryRows, (row) => [row.kind, row.id, row.name, row.department, row.storage_zone, row.storage_conditions, row.responsible_person, row.bin, row.phone, row.email, row.contact_person, row.contract_number, row.notes]), "Справочник пуст. Добавьте категорию, поставщика или склад в формах выше.")}</div>
    </div>
  `;
}

function renderReceipts() {
  return `
    <div class="grid">
      ${receiptPrerequisites()}
      <div class="form-panel span-5"><h2>Приемка сразу в остатки</h2>${form("receipt-form", [
        { label: "Товар", name: "product_id", type: "select", options: optionsFrom("products", "Выберите товар"), required: true },
        { label: "Поставщик", name: "supplier_id", type: "select", options: optionsFrom("suppliers", "Выберите поставщика"), required: true },
        { label: "Склад", name: "warehouse_id", type: "select", options: optionsFrom("warehouses", "Выберите склад"), required: true },
        { label: "Количество", name: "quantity", type: "number", step: "0.001", required: true },
        { label: "Цена", name: "unit_price", type: "number", step: "0.01", value: "0" },
        { label: "Серия партии", name: "lot", required: true },
        { label: "Серийный номер", name: "serial_number" },
        { label: "Срок годности", name: "expires_on", type: "date" },
      ], "Принять товар", {
        disabledSubmit: Boolean(receiptPrerequisites()),
        submitHint: receiptPrerequisites() ? "Заполните справочники выше, затем приход станет доступен." : "",
      })}</div>
      <div class="table-panel span-7"><h2>Партии</h2>${table([
        { label: "Номер", key: "id" },
        { label: "Товар", render: (row) => nameById("products", row.product_id) },
        { label: "Поставщик", render: (row) => nameById("suppliers", row.supplier_id) },
        { label: "Серия", key: "lot" },
        { label: "Серийный", render: (row) => escapeHtml(row.serial_number || "—") },
        { label: "Цена", render: (row) => money(row.unit_price) },
        { label: "Годен до", key: "expires_on" },
        { label: "Статус", render: (row) => badge(row.status) },
        { label: "", render: (row) => `<button class="secondary compact-action" type="button" data-print-batch-price-label="${escapeAttr(row.id)}">Ценник</button>` },
        { label: "", render: (row) => batchButton(row.id, "Открыть") },
      ], filteredRows(state.data.batches, (row) => [row.id, rawNameById("products", row.product_id), rawNameById("suppliers", row.supplier_id), row.lot, row.serial_number, row.expires_on, row.status]), "Партий пока нет. Сначала создайте товар, поставщика и примите товар на склад.")}</div>
    </div>
  `;
}

function renderDocuments() {
  return `
    <div class="grid">
      ${!state.data.products.length || !state.data.suppliers.length || !state.data.warehouses.length
        ? workflowNotice("Не хватает справочников", "Для документов нужны товар, поставщик и склад.", "catalog", "Заполнить справочники")
        : ""}
      <div class="form-panel span-6"><h2>Черновик приходного документа</h2>${receiptDocumentForm()}</div>
      <div class="form-panel span-6"><h2>Черновик документа списания</h2>${writeoffDocumentForm()}</div>
      <div class="table-panel span-12"><div class="toolbar"><h2>Складские документы</h2><button class="secondary" data-export-report="documents">Выгрузить CSV</button></div>${table([
        { label: "Номер", key: "id" },
        { label: "Тип", render: (row) => humanDocumentType(row.document_type) },
        { label: "Статус", render: (row) => badge(row.status) },
        { label: "Склад", render: (row) => nameById("warehouses", row.warehouse_id) },
        { label: "Строк", render: (row) => row.lines?.length || 0 },
        { label: "Создал", key: "created_by" },
        { label: "Утвердил", render: (row) => escapeHtml(row.approved_by || "—") },
        { label: "Создан", render: (row) => dateText(row.created_at) },
        { label: "", render: (row) => row.document_type === "transfer" ? `<button class="secondary compact-action" data-download-transfer-form="${escapeAttr(row.id)}">Печатная форма</button>` : "" },
        { label: "", render: (row) => ["draft", "approved"].includes(String(row.status)) ? `<div class="row-actions">${row.status === "draft" ? `<button class="secondary" data-approve-document="${row.id}">Утвердить</button>` : `<button class="secondary" data-post-document="${row.id}">Провести и изменить остатки</button>`}<button class="danger" data-cancel-document="${row.id}">Отменить</button></div>` : "" },
      ], filteredRows(state.data.documents, (row) => [row.id, row.document_type, row.status, rawNameById("warehouses", row.warehouse_id), row.created_by, row.approved_by, row.created_at]), "Документов пока нет. Создайте черновик прихода или списания выше.")}</div>
    </div>
  `;
}

function receiptDocumentForm() {
  const unavailable = !state.data.products.length || !state.data.suppliers.length || !state.data.warehouses.length;
  return `
    <form id="receipt-doc-form" class="form-grid">
      <label>Поставщик
        <select name="supplier_id" required data-doc-header-field="supplier_id" data-doc-line-kind="receipt">
          ${optionsFrom("suppliers", "Выберите поставщика").map((option) => `<option value="${escapeAttr(option.value)}" ${String(option.value) === String(state.documentForms.receipt.supplier_id) ? "selected" : ""}>${option.label}</option>`).join("")}
        </select>
      </label>
      <label>Склад
        <select name="warehouse_id" required data-doc-header-field="warehouse_id" data-doc-line-kind="receipt">
          ${optionsFrom("warehouses", "Выберите склад").map((option) => `<option value="${escapeAttr(option.value)}" ${String(option.value) === String(state.documentForms.receipt.warehouse_id) ? "selected" : ""}>${option.label}</option>`).join("")}
        </select>
      </label>
      <div class="full">
        <div class="toolbar">
          <h3>Строки прихода</h3>
          <button class="secondary" type="button" data-doc-line-add="receipt">Добавить строку</button>
        </div>
        ${receiptDocumentLinesTable()}
      </div>
      ${unavailable ? '<div class="form-hint blocked full">Сначала добавьте товар, поставщика и склад.</div>' : ""}
      <div class="actions full"><button class="primary" type="submit" ${unavailable ? "disabled" : ""}>Создать черновик прихода</button></div>
    </form>
  `;
}

function writeoffDocumentForm() {
  const unavailable = state.data.balances.items.length === 0;
  return `
    <form id="writeoff-doc-form" class="form-grid">
      <label class="full">Склад
        <select name="warehouse_id" required data-doc-header-field="warehouse_id" data-doc-line-kind="writeoff">
          ${optionsFrom("warehouses", "Выберите склад").map((option) => `<option value="${escapeAttr(option.value)}" ${String(option.value) === String(state.documentForms.writeoff.warehouse_id) ? "selected" : ""}>${option.label}</option>`).join("")}
        </select>
      </label>
      <div class="full">
        <div class="toolbar">
          <h3>Строки списания</h3>
          <button class="secondary" type="button" data-doc-line-add="writeoff">Добавить строку</button>
        </div>
        ${writeoffDocumentLinesTable()}
      </div>
      ${unavailable ? '<div class="form-hint blocked full">Сначала примите товар на склад.</div>' : ""}
      <div class="actions full"><button class="primary" type="submit" ${unavailable ? "disabled" : ""}>Создать черновик списания</button></div>
    </form>
  `;
}

function docLineAttrs(kind, index, field) {
  return `data-doc-line-field="${field}" data-doc-line-kind="${kind}" data-doc-line-index="${index}"`;
}

function receiptDocumentLinesTable() {
  return `
    <div class="table-wrap">
      <table>
        <thead><tr><th>Товар</th><th>Количество</th><th>Цена</th><th>Серия партии</th><th>Серийный номер</th><th>Срок годности</th><th></th></tr></thead>
        <tbody>
          ${state.documentForms.receipt.lines.map((line, index) => `
            <tr>
              <td><select required ${docLineAttrs("receipt", index, "product_id")}>
                ${optionsFrom("products", "Выберите товар").map((option) => `<option value="${escapeAttr(option.value)}" ${String(option.value) === String(line.product_id) ? "selected" : ""}>${option.label}</option>`).join("")}
              </select></td>
              <td><input required type="number" step="0.001" value="${escapeAttr(line.quantity)}" ${docLineAttrs("receipt", index, "quantity")} /></td>
              <td><input required type="number" step="0.01" value="${escapeAttr(line.unit_price)}" ${docLineAttrs("receipt", index, "unit_price")} /></td>
              <td><input required value="${escapeAttr(line.lot)}" ${docLineAttrs("receipt", index, "lot")} /></td>
              <td><input value="${escapeAttr(line.serial_number)}" ${docLineAttrs("receipt", index, "serial_number")} /></td>
              <td><input type="date" value="${escapeAttr(line.expires_on)}" ${docLineAttrs("receipt", index, "expires_on")} /></td>
              <td><button class="danger" type="button" data-doc-line-remove="receipt" data-doc-line-index="${index}" ${state.documentForms.receipt.lines.length === 1 ? "disabled" : ""}>Удалить</button></td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function writeoffDocumentLinesTable() {
  return `
    <div class="table-wrap">
      <table>
        <thead><tr><th>Партия</th><th>Количество</th><th>Причина</th><th>Пациент</th><th>Врач</th><th>История болезни</th><th>2-й подтверждающий</th><th>Комментарий ПКУ</th><th></th></tr></thead>
        <tbody>
          ${state.documentForms.writeoff.lines.map((line, index) => `
            <tr class="${controlledWriteoffMetadataMissing(line).length ? "controlled-warning" : ""}">
              <td><select required ${docLineAttrs("writeoff", index, "batch_id")}>
                ${batchOptions("Выберите партию с остатком").map((option) => `<option value="${escapeAttr(option.value)}" ${String(option.value) === String(line.batch_id) ? "selected" : ""}>${option.label}</option>`).join("")}
              </select></td>
              <td><input required type="number" step="0.001" value="${escapeAttr(line.quantity)}" ${docLineAttrs("writeoff", index, "quantity")} /></td>
              <td><input required value="${escapeAttr(line.reason)}" ${docLineAttrs("writeoff", index, "reason")} /></td>
              <td><input value="${escapeAttr(line.patient_id)}" ${docLineAttrs("writeoff", index, "patient_id")} /></td>
              <td><input value="${escapeAttr(line.doctor_id)}" ${docLineAttrs("writeoff", index, "doctor_id")} /></td>
              <td><input value="${escapeAttr(line.medical_record_no)}" ${docLineAttrs("writeoff", index, "medical_record_no")} /></td>
              <td><input value="${escapeAttr(line.second_approver_id)}" ${docLineAttrs("writeoff", index, "second_approver_id")} /></td>
              <td><input value="${escapeAttr(line.second_approval_note)}" ${docLineAttrs("writeoff", index, "second_approval_note")} /></td>
              <td><button class="danger" type="button" data-doc-line-remove="writeoff" data-doc-line-index="${index}" ${state.documentForms.writeoff.lines.length === 1 ? "disabled" : ""}>Удалить</button></td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function tabletWriteoffForm() {
  const stockUnavailable = state.data.balances.items.length === 0;
  return form("tablet-writeoff-form", [
    { label: "Партия", name: "batch_id", type: "select", options: batchOptions("Выберите партию с остатком"), required: true, full: true },
    { label: "Склад", name: "warehouse_id", type: "select", options: optionsFrom("warehouses", "Автоматически по партии"), required: true, batchWarehouseField: "warehouse_id" },
    { label: "Количество", name: "quantity", type: "number", step: "0.001", required: true },
    { label: "Причина", name: "reason", value: "Списание в отделении", required: true, full: true },
    { label: "Пациент", name: "patient_id" },
    { label: "История болезни", name: "medical_record_no" },
    { label: "Врач", name: "doctor_id", value: currentRole() === "doctor" ? currentActorId() : "" },
    { label: "2-й подтверждающий", name: "second_approver_id" },
    { label: "Комментарий ПКУ", name: "second_approval_note" },
  ], "Списать", {
    batchAware: true,
    disabledSubmit: stockUnavailable,
    submitHint: stockUnavailable ? "Сначала примите товар на склад." : "",
  });
}

function renderTabletWriteoff() {
  return `
    <div class="grid tablet-view">
      ${roleAccessNotice()}
      <div class="tablet-writeoff-panel span-7">
        <div class="tablet-copy">
          <span class="eyebrow">Планшетное списание</span>
          <h2>Минимальная форма списания партии</h2>
        </div>
        ${tabletWriteoffForm()}
      </div>
      <div class="table-panel span-5">
        <div class="toolbar">
          <h2>Остатки</h2>
          <button class="secondary" data-action="reload">Обновить</button>
        </div>
        ${balancesTable(filteredBalances(state.data.balances.items), "Остатков пока нет. Проверьте склад в верхней панели.")}
      </div>
      <div class="table-panel span-12">
        <h2>Недавние списания</h2>
        ${table([
          { label: "Партия", render: (row) => batchDetailLabel(row.batch_id) },
          { label: "Склад", render: (row) => nameById("warehouses", row.warehouse_id) },
          { label: "Количество", key: "quantity" },
          { label: "Причина", key: "reason" },
          { label: "Пациент", render: (row) => escapeHtml(row.patient_id || "—") },
          { label: "Время", render: (row) => dateText(row.created_at) },
        ], filteredRows(state.data.movements.filter((row) => row.movement_type === "write_off").slice(0, 12), (row) => [row.batch_id, rawNameById("warehouses", row.warehouse_id), row.quantity, row.reason, row.patient_id, row.created_at]), "Списаний пока нет.")}
      </div>
    </div>
  `;
}

function renderOperations() {
  const stockUnavailable = state.data.balances.items.length === 0;
  const quarantineReviews = pageItems(state.data.quarantineReviews);
  return `
    <div class="grid">
      ${needsStockNotice("Перейти к приходу")}
      <div class="form-panel span-3"><h2>Списание по ближайшему сроку</h2>${form("fefo-form", [
        { label: "Товар", name: "product_id", type: "select", options: optionsFrom("products", "Выберите товар"), required: true },
        { label: "Склад", name: "warehouse_id", type: "select", options: optionsFrom("warehouses", "Выберите склад"), required: true },
        { label: "Количество", name: "quantity", type: "number", step: "0.001", required: true },
        { label: "Причина", name: "reason", value: "Списание по требованию", required: true },
        { label: "Пациент", name: "patient_id" },
        { label: "Врач", name: "doctor_id" },
        { label: "История болезни", name: "medical_record_no" },
        { label: "2-й подтверждающий", name: "second_approver_id" },
        { label: "Комментарий ПКУ", name: "second_approval_note" },
      ], "Списать по сроку годности", {
        disabledSubmit: stockUnavailable,
        submitHint: stockUnavailable ? "Сначала примите товар на склад." : "",
      })}</div>
      <div class="form-panel span-3"><h2>Списание партии</h2>${form("writeoff-form", [
        { label: "Партия", name: "batch_id", type: "select", options: batchOptions("Выберите партию с остатком"), required: true },
        { label: "Склад", name: "warehouse_id", type: "select", options: optionsFrom("warehouses", "Выберите склад"), required: true, batchWarehouseField: "warehouse_id" },
        { label: "Количество", name: "quantity", type: "number", step: "0.001", required: true },
        { label: "Причина", name: "reason", value: "Списание конкретной партии", required: true },
        { label: "Пациент", name: "patient_id" },
        { label: "Врач", name: "doctor_id" },
        { label: "История болезни", name: "medical_record_no" },
        { label: "2-й подтверждающий", name: "second_approver_id" },
        { label: "Комментарий ПКУ", name: "second_approval_note" },
      ], "Списать партию", {
        batchAware: true,
        disabledSubmit: stockUnavailable,
        submitHint: stockUnavailable ? "Сначала примите товар на склад." : "",
      })}</div>
      <div class="form-panel span-3"><h2>Перемещение</h2>${form("transfer-form", [
        { label: "Партия", name: "batch_id", type: "select", options: batchOptions("Выберите партию с остатком"), required: true },
        { label: "Склад-источник", name: "source_warehouse_id", type: "select", options: optionsFrom("warehouses", "Выберите склад"), required: true, batchWarehouseField: "source_warehouse_id" },
        { label: "Склад-получатель", name: "target_warehouse_id", type: "select", options: optionsFrom("warehouses", "Выберите склад"), required: true },
        { label: "Количество", name: "quantity", type: "number", step: "0.001", required: true },
        { label: "Причина", name: "reason", value: "Внутреннее перемещение", required: true },
      ], "Переместить", {
        batchAware: true,
        disabledSubmit: stockUnavailable,
        submitHint: stockUnavailable ? "Сначала примите товар на склад." : "",
      })}</div>
      <div class="form-panel span-3"><h2>Статус партии</h2>${form("batch-status-form", [
        { label: "Партия", name: "batch_id", type: "select", options: optionsFrom("batches", "Выберите партию", (batch) => `${rawNameById("products", batch.product_id)} · серия ${batch.lot}`), required: true },
        { label: "Статус", name: "status", type: "select", options: staticOptions([["available", "Допущен"], ["quarantine", "Карантин"], ["blocked", "Заблокирован"]], "Выберите статус"), value: "available", required: true },
        { label: "Причина", name: "reason" },
      ], "Обновить статус", {
        disabledSubmit: state.data.batches.length === 0,
        submitHint: state.data.batches.length === 0 ? "Сначала примите партию на склад." : "",
      })}</div>
      <div class="form-panel span-3"><h2>Отзыв партии</h2>${form("batch-recall-form", [
        { label: "Партия", name: "batch_id", type: "select", options: batchOptions("Выберите партию с остатком", { onlyAvailable: false }), required: true },
        { label: "Склад для проверки", name: "warehouse_id", type: "select", options: optionsFrom("warehouses", "Автоматически по партии"), required: true, batchWarehouseField: "warehouse_id" },
        { label: "Источник", name: "source", value: "Поставщик / производитель" },
        { label: "Документ-основание", name: "reference" },
        { label: "Причина отзыва", name: "reason", type: "textarea", required: true, full: true },
      ], "Отозвать и заблокировать", {
        batchAware: true,
        disabledSubmit: stockUnavailable,
        submitHint: stockUnavailable ? "Нет партий с остатком для отзыва." : "Партия будет заблокирована, а склады получат уведомления.",
      })}</div>
      <div class="table-panel span-12">
        <div class="toolbar">
          <div>
            <h2>Карантинные проверки</h2>
            <span class="helper-text">Партия из карантина станет доступной только после решения проверки.</span>
          </div>
          <button class="secondary" data-action="reload">Обновить</button>
        </div>
        ${table([
          { label: "Партия", render: (row) => `${batchButton(row.batch_id)}<br><span class="badge">${escapeHtml(row.lot)}</span>` },
          { label: "Товар", render: (row) => escapeHtml(row.product_name) },
          { label: "Статус", render: (row) => badge(row.status) },
          { label: "Ответственный", render: (row) => escapeHtml(row.responsible_id || "Не назначен") },
          { label: "Срок", render: (row) => row.due_at ? dateText(row.due_at) : "—" },
          { label: "Решение", render: (row) => escapeHtml(row.decision_reason || "—") },
          { label: "", render: (row) => `<button class="secondary compact-action" data-download-quarantine-protocol="${escapeAttr(row.id)}">Протокол</button>` },
          { label: "", render: (row) => ["pending", "in_review"].includes(String(row.status)) ? `
            <div class="row-actions">
              <button class="secondary" data-quarantine-review="${row.id}" data-quarantine-next-status="in_review">Начать проверку</button>
              <button class="primary" data-quarantine-review="${row.id}" data-quarantine-next-status="approved">Допустить</button>
              <button class="danger" data-quarantine-review="${row.id}" data-quarantine-next-status="rejected">Забраковать</button>
            </div>
          ` : "" },
        ], filteredRows(quarantineReviews, (row) => [row.batch_id, row.product_name, row.lot, row.status, row.responsible_id, row.decision_reason]), "Карантинных проверок пока нет. Новые партии в карантине появятся здесь автоматически.")}
      </div>
      <div class="table-panel span-12"><h2>Текущие остатки</h2>${balancesTable(filteredBalances(state.data.balances.items), "Остатков пока нет. Примите товар на склад или проверьте выбранный фильтр склада.")}</div>
    </div>
  `;
}

function renderRepacking() {
  const stockUnavailable = state.data.balances.items.length === 0;
  const rows = pageItems(state.data.repackings);
  return `
    <div class="grid">
      ${needsStockNotice("Принять товар")}
      <div class="form-panel span-4">
        <h2>Фасовка партии</h2>
        ${form("repacking-form", [
          { label: "Исходная партия", name: "batch_id", type: "select", options: batchOptions("Выберите партию с остатком"), required: true },
          { label: "Склад", name: "warehouse_id", type: "select", options: optionsFrom("warehouses", "Склад партии"), required: true, batchWarehouseField: "warehouse_id" },
          { label: "Что получится", name: "target_product_id", type: "select", options: optionsFrom("products", "Выберите товар результата"), required: true },
          { label: "Сколько взять", name: "quantity", type: "number", step: "0.001", required: true },
          { label: "Сколько получится", name: "target_quantity", type: "number", step: "0.001", required: true },
          { label: "Потери", name: "loss_quantity", type: "number", step: "0.001", value: "0" },
          { label: "Новая серия / лот", name: "target_lot", required: true },
          { label: "Годен до", name: "target_expires_on", type: "date" },
          { label: "Цена результата", name: "target_unit_price", type: "number", step: "0.0001" },
          { label: "Статус результата", name: "quarantine", type: "select", options: staticOptions([["false", "Сразу доступен"], ["true", "Через карантин"]], "Выберите статус"), value: "false" },
          { label: "Причина", name: "reason", value: "Фасовка / переупаковка", required: true, full: true },
        ], "Создать черновик фасовки", {
          batchAware: true,
          disabledSubmit: stockUnavailable,
          submitHint: stockUnavailable ? "Сначала примите товар на склад." : "После создания черновик нужно провести в разделе документов.",
        })}
      </div>
      <div class="table-panel span-8">
        <div class="toolbar">
          <div>
            <h2>Журнал фасовки</h2>
            <span class="helper-text">Здесь видно, какая партия стала источником и какая появилась после фасовки.</span>
          </div>
          <button class="secondary" data-export-report="repackings">Выгрузить CSV</button>
        </div>
        ${table([
          { label: "Номер", key: "id" },
          { label: "Исходная партия", render: (row) => batchDetailLabel(row.source_batch_id) },
          { label: "Полученная партия", render: (row) => batchDetailLabel(row.target_batch_id) },
          { label: "Склад", render: (row) => nameById("warehouses", row.warehouse_id) },
          { label: "Взяли", key: "source_quantity" },
          { label: "Получили", key: "target_quantity" },
          { label: "Потери", key: "loss_quantity" },
          { label: "Коэф.", key: "conversion_factor" },
          { label: "Время", render: (row) => dateText(row.created_at) },
          { label: "", render: (row) => row.document_id ? `<button class="secondary compact-action" data-download-repack-form="${escapeAttr(row.document_id)}">Печатная форма</button>` : "" },
        ], filteredRows(rows, (row) => [
          row.id,
          row.document_id,
          row.source_batch_id,
          row.target_batch_id,
          row.source_product_name,
          row.target_product_name,
          row.source_lot,
          row.target_lot,
          rawNameById("warehouses", row.warehouse_id),
          row.reason,
          row.created_at,
        ]), "Фасовок пока нет. Создайте черновик и проведите его в документах.")}
      </div>
      <div class="table-panel span-12"><h2>Остатки после операций</h2>${balancesTable(filteredBalances(state.data.balances.items), "Остатков пока нет. Примите товар на склад или проверьте выбранный фильтр склада.")}</div>
    </div>
  `;
}

function renderReturns() {
  const stockUnavailable = state.data.balances.items.length === 0;
  return `
    <div class="grid">
      ${needsStockNotice("Принять товар")}
      <div class="form-panel span-6"><h2>Возврат от отделения</h2>${form("department-return-form", [
        { label: "Партия", name: "batch_id", type: "select", options: batchOptions("Выберите партию с остатком"), required: true },
        { label: "Откуда", name: "source_warehouse_id", type: "select", options: optionsFrom("warehouses", "Кабинет / отделение"), required: true, batchWarehouseField: "source_warehouse_id" },
        { label: "Куда", name: "target_warehouse_id", type: "select", options: optionsFrom("warehouses", "Основной склад"), required: true },
        { label: "Количество", name: "quantity", type: "number", step: "0.001", required: true },
        { label: "Причина", name: "reason", value: "Возврат неиспользованных материалов", required: true },
      ], "Оформить возврат", {
        batchAware: true,
        disabledSubmit: stockUnavailable,
        submitHint: stockUnavailable ? "Сначала примите товар на склад." : "",
      })}</div>
      <div class="form-panel span-6"><h2>Возврат поставщику</h2>${form("supplier-return-form", [
        { label: "Партия", name: "batch_id", type: "select", options: batchOptions("Выберите партию с остатком", { onlyAvailable: false }), required: true },
        { label: "Склад", name: "warehouse_id", type: "select", options: optionsFrom("warehouses", "Выберите склад"), required: true, batchWarehouseField: "warehouse_id" },
        { label: "Поставщик", name: "supplier_id", type: "select", options: optionsFrom("suppliers", "Выберите поставщика"), required: true },
        { label: "Количество", name: "quantity", type: "number", step: "0.001", required: true },
        { label: "Причина", name: "reason", value: "Брак / несоответствие поставке", required: true },
      ], "Вернуть поставщику", {
        batchAware: true,
        disabledSubmit: stockUnavailable,
        submitHint: stockUnavailable ? "Сначала примите товар на склад." : "",
      })}</div>
      <div class="table-panel span-12"><h2>Партии для возврата</h2>${table([
        { label: "Номер", key: "id" },
        { label: "Товар", render: (row) => nameById("products", row.product_id) },
        { label: "Поставщик", render: (row) => nameById("suppliers", row.supplier_id) },
        { label: "Серия", key: "lot" },
        { label: "Годен до", key: "expires_on" },
        { label: "Статус", render: (row) => badge(row.status) },
        { label: "", render: (row) => batchButton(row.id, "Открыть") },
      ], filteredRows(state.data.batches, (row) => [row.id, rawNameById("products", row.product_id), rawNameById("suppliers", row.supplier_id), row.lot, row.expires_on, row.status]), "Партий для возврата пока нет. Сначала примите товар на склад.")}</div>
      <div class="table-panel span-12">
        <div class="toolbar">
          <h2>Журнал отзывов партий</h2>
          <button class="secondary" data-export-report="batchRecalls">Выгрузить CSV</button>
        </div>
        ${table([
          { label: "Номер", key: "id" },
          { label: "Товар", render: (row) => escapeHtml(row.product_name || "—") },
          { label: "Партия", render: (row) => row.batch_id ? batchButton(row.batch_id, row.lot || `#${row.batch_id}`) : "—" },
          { label: "Источник", key: "source" },
          { label: "Основание", render: (row) => escapeHtml(row.reference || "—") },
          { label: "Причина", key: "reason" },
          { label: "Создал", key: "created_by" },
          { label: "Создано", render: (row) => dateText(row.created_at) },
        ], filteredRows(state.data.batchRecalls.items || [], (row) => [row.id, row.product_name, row.lot, row.source, row.reference, row.reason, row.created_by, row.created_at]), "Отзывов партий пока нет. Если производитель отзывает серию, оформите отзыв в разделе списания и перемещения.")}
      </div>
    </div>
  `;
}

function renderMovements() {
  return `
    <div class="grid">
      <div class="panel span-3 metric"><span>Всего движений</span><strong>${state.data.movements.length}</strong></div>
      <div class="panel span-3 metric"><span>Поступления</span><strong>${state.data.movements.filter((row) => row.movement_type === "receipt").length}</strong></div>
      <div class="panel span-3 metric"><span>Списания</span><strong>${state.data.movements.filter((row) => row.movement_type === "write_off").length}</strong></div>
      <div class="panel span-3 metric"><span>Возвраты поставщику</span><strong>${state.data.movements.filter((row) => row.movement_type === "return_to_supplier").length}</strong></div>
      <div class="table-panel span-12"><div class="toolbar"><h2>История движения ТМЦ</h2><div class="row-actions"><button class="secondary" data-download-controlled-ledger>Экспорт ПКУ</button><button class="secondary" data-export-report="movements">Выгрузить CSV</button></div></div>${table([
        { label: "Номер", key: "id" },
        { label: "Действие", render: (row) => badge(row.movement_type) },
        { label: "Партия", render: (row) => batchDetailLabel(row.batch_id) },
        { label: "Склад", render: (row) => nameById("warehouses", row.warehouse_id) },
        { label: "Количество", key: "quantity" },
        { label: "Причина", key: "reason" },
        { label: "Пациент", render: (row) => escapeHtml(row.patient_id || "—") },
        { label: "Время", render: (row) => dateText(row.created_at) },
      ], filteredRows(state.data.movements, (row) => [row.id, row.movement_type, batchLabel(row.batch_id), rawNameById("warehouses", row.warehouse_id), row.quantity, row.reason, row.patient_id, row.created_at]))}</div>
    </div>
  `;
}

function renderReservations() {
  const stockUnavailable = state.data.balances.items.length === 0;
  return `
    <div class="grid">
      ${needsStockNotice("Принять товар")}
      <div class="form-panel span-4"><h2>Новый резерв</h2>${form("reservation-form", [
        { label: "Партия", name: "batch_id", type: "select", options: batchOptions("Выберите партию с остатком"), required: true },
        { label: "Склад", name: "warehouse_id", type: "select", options: optionsFrom("warehouses", "Выберите склад"), required: true },
        { label: "Количество", name: "quantity", type: "number", step: "0.001", required: true },
        { label: "Для кого", name: "reserved_for", required: true },
        { label: "Истекает", name: "expires_at", type: "datetime-local" },
      ], "Зарезервировать", {
        disabledSubmit: stockUnavailable,
        submitHint: stockUnavailable ? "Сначала примите товар на склад." : "",
      })}</div>
      <div class="table-panel span-8"><div class="toolbar"><h2>Бронирование товаров</h2><button class="secondary" data-action="expire-reservations">Снять просроченную бронь</button></div>${table([
        { label: "Номер", key: "id" },
        { label: "Партия", render: (row) => batchButton(row.batch_id) },
        { label: "Склад", render: (row) => nameById("warehouses", row.warehouse_id) },
        { label: "Кол-во", key: "quantity" },
        { label: "Для", key: "reserved_for" },
        { label: "Статус", render: (row) => badge(row.status) },
        { label: "Истекает", render: (row) => dateText(row.expires_at) },
        { label: "", render: (row) => `
          <div class="row-actions">
            <button class="primary" data-use-reservation="${row.id}" ${["used", "released", "cancelled"].includes(String(row.status)) ? "disabled" : ""}>Использовать резерв</button>
            <button class="secondary" data-release="${row.id}" ${["used", "released", "cancelled"].includes(String(row.status)) ? "disabled" : ""}>Снять бронь</button>
          </div>
        ` },
      ], filteredRows(state.data.reservations, (row) => [row.id, row.batch_id, rawNameById("warehouses", row.warehouse_id), row.quantity, row.reserved_for, row.status, row.expires_at]), "Брони пока нет. Выберите партию с остатком и создайте резерв слева.")}</div>
    </div>
  `;
}

function suggestedPurchaseRequests() {
  return state.data.analytics.items
    .filter((row) => Number(row.recommended_order_quantity || 0) > 0)
    .map((row) => ({
      product_id: row.product_id,
      product_name: row.product_name,
      sku: row.sku,
      warehouse_id: row.warehouse_id || state.data.analytics.warehouse_id,
      quantity: row.recommended_order_quantity,
      reason: row.recommendation || "Ниже точки заказа",
      source: "analytics",
    }));
}

function renderPurchaseRequests() {
  const productUnavailable = state.data.products.length === 0;
  const suggestions = suggestedPurchaseRequests();
  const adminOffers = filteredRows(state.data.supplierAdminOffers, (row) => [
    row.id,
    row.supplier_name,
    row.product_name,
    row.sku,
    row.status,
    row.unit_price,
    row.quantity,
    row.review_reason,
  ]);
  const requests = filteredRows(state.data.purchaseRequests, (row) => [
    row.id,
    rawNameById("products", row.product_id),
    rawNameById("warehouses", row.warehouse_id),
    row.recommended_quantity,
    row.status,
    row.reason,
    row.created_at,
  ]);
  return `
    <div class="grid">
      ${needsProductNotice("Создать товар")}
      <div class="form-panel span-4"><h2>Новая заявка</h2>${form("purchase-request-form", [
        { label: "Товар", name: "product_id", type: "select", options: optionsFrom("products", "Выберите товар"), required: true },
        { label: "Склад", name: "warehouse_id", type: "select", options: optionsFrom("warehouses", "Для какого склада") },
        { label: "Количество", name: "quantity", type: "number", step: "0.001", required: true },
        { label: "Причина", name: "reason", value: "Пополнение склада", full: true },
      ], "Создать заявку", {
        disabledSubmit: productUnavailable,
        submitHint: productUnavailable ? "Сначала создайте товар." : "",
      })}</div>
      <div class="panel span-3 metric"><span>Открытые заявки</span><strong>${state.data.purchaseRequests.filter((row) => ["draft", "requested", "open"].includes(String(row.status || "open"))).length}</strong></div>
      <div class="panel span-3 metric"><span>КП на рассмотрении</span><strong>${state.data.supplierAdminOffers.filter((row) => row.status === "submitted").length}</strong></div>
      <div class="panel span-3 metric"><span>Автозаявки к созданию</span><strong>${suggestions.length}</strong></div>
      <div class="panel span-3 metric"><span>Заявки поставщиков</span><strong>${state.data.supplierApplications.filter((row) => row.status === "pending").length}</strong></div>
      <div class="table-panel span-12">
        <div class="toolbar">
          <div>
            <h2>Заявки на закупку</h2>
            <span class="helper-text">Если модуль закупок еще не включен на сервере, эта панель останется пустой и покажет предупреждение на главной.</span>
          </div>
          <div class="row-actions">
            <button class="secondary" data-export-report="purchaseRequests">Выгрузить CSV</button>
            <button class="primary" data-action="generate-purchase-requests">Сформировать автозаявки</button>
            <button class="secondary" data-action="reload">Обновить</button>
          </div>
        </div>
        ${table([
          { label: "Номер", key: "id" },
          { label: "Товар", render: (row) => nameById("products", row.product_id) },
          { label: "Склад", render: (row) => row.warehouse_id ? nameById("warehouses", row.warehouse_id) : "—" },
          { label: "Количество", render: (row) => escapeHtml(row.recommended_quantity || row.quantity || row.recommended_order_quantity || "—") },
          { label: "Статус", render: (row) => badge(row.status || "open") },
          { label: "Причина", render: (row) => escapeHtml(row.reason || row.recommendation || "—") },
          { label: "Создано", render: (row) => dateText(row.created_at) },
          { label: "", render: (row) => row.status === "draft" ? `<div class="row-actions"><button class="primary" data-purchase-status="${row.id}" data-purchase-next-status="ordered">Заказано</button><button class="secondary" data-purchase-status="${row.id}" data-purchase-next-status="cancelled">Отменить</button></div>` : "" },
        ], requests, "Заявок пока нет. Нажмите «Сформировать автозаявки» или создайте заявку вручную слева.")}
      </div>
      <div class="table-panel span-12">
        <div class="toolbar">
          <div>
            <h2>Предложения поставщиков</h2>
            <span class="helper-text">Принятие КП переводит заявку в статус «Заказано» и закрывает остальные предложения по этой заявке.</span>
          </div>
          <button class="secondary" data-action="reload">Обновить</button>
        </div>
        ${table([
          { label: "КП", render: (row) => `#${escapeHtml(row.id)}` },
          { label: "Заявка", render: (row) => `#${escapeHtml(row.purchase_request_id)}` },
          { label: "Поставщик", render: (row) => escapeHtml(row.supplier_name || "—") },
          { label: "Товар", render: (row) => escapeHtml(row.product_name || "—") },
          { label: "Цена", key: "unit_price" },
          { label: "Количество", key: "quantity" },
          { label: "Поставка", render: (row) => escapeHtml(row.delivery_date || "—") },
          { label: "Статус", render: (row) => badge(row.status) },
          { label: "Комментарий", render: (row) => escapeHtml(row.comment || row.review_reason || "—") },
          { label: "", render: (row) => row.status === "submitted" ? `<div class="row-actions"><button class="primary" data-review-offer="${escapeAttr(row.id)}" data-offer-next-status="accepted">Принять</button><button class="secondary" data-review-offer="${escapeAttr(row.id)}" data-offer-next-status="rejected">Отклонить</button></div>` : "" },
        ], adminOffers, "Коммерческих предложений пока нет.")}
      </div>
      ${state.data.supplierApplications.length > 0 || hasPermission("admin:users") ? `
      <div class="table-panel span-12">
        <div class="toolbar">
          <div>
            <h2>Заявки поставщиков</h2>
            <span class="helper-text">Заявки на регистрацию поставщика. После одобрения поставщик сможет видеть открытые заявки на закупку и отправлять коммерческие предложения.</span>
          </div>
          <button class="secondary" data-action="reload">Обновить</button>
        </div>
        ${table([
          { label: "Компания", render: (row) => escapeHtml(row.name) },
          { label: "БИН", render: (row) => escapeHtml(row.bin || "—") },
          { label: "Email", render: (row) => escapeHtml(row.email || "—") },
          { label: "Телефон", render: (row) => escapeHtml(row.phone || "—") },
          { label: "Контакт", render: (row) => escapeHtml(row.contact_person || "—") },
          { label: "Статус", render: (row) => badge(row.status) },
          { label: "Подана", render: (row) => dateText(row.submitted_at) },
          { label: "Комментарий", render: (row) => escapeHtml(row.review_reason || "—") },
          { label: "", render: (row) => ["pending", "needs_changes"].includes(row.status) ? `
            <div class="row-actions">
              <button class="primary compact-action" data-review-application="${escapeAttr(row.id)}" data-application-next-status="approved">Одобрить</button>
              <button class="secondary compact-action" data-review-application="${escapeAttr(row.id)}" data-application-next-status="needs_changes">Правки</button>
              <button class="danger compact-action" data-review-application="${escapeAttr(row.id)}" data-application-next-status="rejected">Отклонить</button>
            </div>
          ` : (row.status === "approved" ? `<button class="secondary compact-action" data-review-application="${escapeAttr(row.id)}" data-application-next-status="suspended">Приостановить</button>` : "") },
        ], filteredRows(state.data.supplierApplications, (row) => [row.name, row.bin, row.email, row.phone, row.status]), "Заявок поставщиков пока нет.")}
      </div>
      ` : ""}
      <div class="table-panel span-12">
        <h2>Рекомендации к закупке</h2>
        ${table([
          { label: "Товар", render: (row) => `${escapeHtml(row.product_name || rawNameById("products", row.product_id))}<br><span class="badge">${escapeHtml(row.sku || "без кода")}</span>` },
          { label: "Склад", render: (row) => row.warehouse_id ? nameById("warehouses", row.warehouse_id) : "—" },
          { label: "Количество", key: "quantity" },
          { label: "Основание", key: "reason" },
        ], filteredRows(suggestions, (row) => [row.product_name, row.sku, rawNameById("warehouses", row.warehouse_id), row.quantity, row.reason]), "Автоматических рекомендаций пока нет. Они появятся после ABC/XYZ анализа и настроенных точек заказа.")}
      </div>
    </div>
  `;
}

function renderInventory() {
  const warehouseUnavailable = state.data.warehouses.length === 0;
  const selectedSession = selectedInventorySession();
  const progress = inventoryProgress(selectedSession);
  const progressTone = selectedSession && progress.missing === 0 && progress.total > 0 ? "ok" : "warn";
  return `
    <div class="grid">
      ${needsWarehouseNotice("Добавить склад")}
      <div class="form-panel span-4"><h2>Создать инвентаризацию</h2>${form("inventory-form", [
        { label: "Склад", name: "warehouse_id", type: "select", options: optionsFrom("warehouses", "Выберите склад"), required: true },
        { label: "Категория", name: "category_id", type: "select", options: optionsFrom("categories", "Все категории") },
        { label: "Ответственные", name: "responsible_ids", placeholder: "manager, nurse-1" },
      ], "Начать", {
        disabledSubmit: warehouseUnavailable,
        submitHint: warehouseUnavailable ? "Сначала добавьте склад." : "",
      })}</div>
      <div class="form-panel span-4"><h2>Завершение</h2>${form("inventory-action-form", [
        { label: "Проверка", name: "session_id", type: "select", options: optionsFrom("inventorySessions", "Выберите проверку", (session) => `${rawNameById("warehouses", session.warehouse_id)} · ${humanStatus(session.status)}`), required: true },
      ], "Завершить проверку")}
        <div class="inventory-progress ${progressTone}" data-inventory-progress>${escapeHtml(inventoryProgressText(selectedSession))}</div>
        <div class="actions"><button class="danger" data-action="cancel-inventory">Отменить инвентаризацию</button></div>
      </div>
      <div class="panel span-4 metric"><span>Активная сессия</span><strong>${selectedSession ? `#${selectedSession.id}` : "—"}</strong></div>
      <div class="panel span-12">
        <div class="toolbar">
          <h2>Сводка выбранной проверки</h2>
          <div class="row-actions">
            <button class="secondary" data-export-report="inventorySheet" ${selectedSession ? "" : "disabled"}>Выгрузить ведомость CSV</button>
            <button class="secondary" data-print-inventory ${selectedSession ? "" : "disabled"}>Печать ведомости</button>
            <button class="secondary" data-print-inventory-reconciliation ${selectedSession ? "" : "disabled"}>Сличительная ведомость</button>
          </div>
        </div>
        ${selectedSession ? inventorySummaryHtml(selectedSession) : '<div class="empty">Выберите или создайте инвентаризацию, чтобы увидеть сводку.</div>'}
      </div>
      <div class="table-panel span-12"><h2>Проверки склада</h2>${table([
        { label: "Номер", key: "id" },
        { label: "Склад", render: (row) => nameById("warehouses", row.warehouse_id) },
        { label: "Статус", render: (row) => badge(row.status) },
        { label: "Строк", render: (row) => row.lines?.length || 0 },
        { label: "Заполнено", render: (row) => {
          const rowProgress = inventoryProgress(row);
          return `${rowProgress.filled}/${rowProgress.total}`;
        } },
        { label: "Начал", key: "started_by" },
        { label: "Начата", render: (row) => dateText(row.started_at) },
        { label: "Проведена", render: (row) => dateText(row.posted_at) },
      ], filteredRows(state.data.inventorySessions, (row) => [row.id, rawNameById("warehouses", row.warehouse_id), row.status, row.started_by, row.started_at, row.posted_at]), "Проверок склада пока нет. Выберите склад и начните инвентаризацию.")}</div>
      <div class="table-panel span-12"><h2>Товары в выбранной проверке</h2>${selectedSession ? table([
        { label: "Номер строки", key: "id" },
        { label: "Товар", render: (row) => nameById("products", row.product_id) },
        { label: "Партия", render: (row) => batchDetailLabel(row.batch_id) },
        { label: "Ожидалось", key: "expected_quantity" },
        { label: "Факт", render: (row) => `<input class="inline-input" type="number" step="0.001" value="${escapeAttr(row.actual_quantity ?? "")}" data-actual-line="${escapeAttr(row.id)}" />` },
        { label: "Разница", render: (row) => escapeHtml(row.difference_quantity ?? "—") },
        { label: "Готовность", render: (row) => row.actual_quantity === null || row.actual_quantity === undefined || row.actual_quantity === "" ? badge("draft") : badge("ok") },
        { label: "", render: (row) => `<button class="secondary" data-save-inventory-line="${escapeAttr(row.id)}" data-session="${escapeAttr(selectedSession.id)}">Сохранить</button>` },
      ], filteredRows(selectedSession.lines || [], (row) => [row.id, rawNameById("products", row.product_id), batchLabel(row.batch_id), row.expected_quantity, row.actual_quantity, row.difference_quantity]), "В выбранной проверке нет строк. Проверьте, есть ли остатки на складе.") : '<div class="empty">Сессий пока нет. Сначала начните инвентаризацию склада.</div>'}</div>
      <div class="table-panel span-12"><h2>Остатки для сверки</h2>${balancesTable(filteredBalances(state.data.balances.items), "Остатков для сверки пока нет. Примите товар на склад перед инвентаризацией.")}</div>
    </div>
  `;
}

function renderNotifications() {
  return `
    <div class="table-panel">
      <div class="toolbar">
        <h2>Уведомления</h2>
        <div class="row-actions">
          <button class="secondary" data-action="generate-low-stock">Проверить малые остатки</button>
          <button class="secondary" data-action="generate-expiry">Проверить сроки годности</button>
          <button class="secondary" data-action="generate-quarantine">Проверить карантин</button>
        </div>
      </div>
      ${table([
        { label: "Номер", key: "id" },
        { label: "Событие", render: (row) => humanNotificationType(row.notification_type) },
        { label: "Партия", render: (row) => row.batch_id ? batchDetailLabel(row.batch_id) : "—" },
        { label: "Склад", render: (row) => row.warehouse_id ? nameById("warehouses", row.warehouse_id) : "—" },
        { label: "Заголовок", key: "title" },
        { label: "Сообщение", key: "message" },
        { label: "Статус", render: (row) => badge(row.is_read ? "read" : "unread") },
        { label: "", render: (row) => `<button class="secondary" data-read="${row.id}">Прочитано</button>` },
      ], filteredRows(state.data.notifications.items, (row) => [row.id, row.notification_type, batchLabel(row.batch_id), rawNameById("warehouses", row.warehouse_id), row.title, row.message, row.is_read ? "read" : "unread"]))}
    </div>
  `;
}

function abcXyzMatrixData(items) {
  const matrix = {};
  ["A", "B", "C"].forEach((abcClass) => {
    ["X", "Y", "Z"].forEach((xyzClass) => {
      matrix[`${abcClass}${xyzClass}`] = {
        abcClass,
        xyzClass,
        items: [],
        recommended: 0,
        free: 0,
      };
    });
  });
  items.forEach((item) => {
    const key = `${item.abc_class}${item.xyz_class}`;
    if (!matrix[key]) return;
    matrix[key].items.push(item);
    matrix[key].recommended += Number(item.recommended_order_quantity || 0);
    matrix[key].free += Number(item.current_free_quantity || 0);
  });
  return matrix;
}

function abcXyzRecommendation(abcClass, xyzClass) {
  const recommendations = {
    AX: "Критичный стабильный расход: держать страховой запас и контролировать ежедневно.",
    AY: "Критичный переменный расход: проверять сезонность и согласовывать точку заказа.",
    AZ: "Критичный нерегулярный расход: закупать осторожно, проверять потребность перед заказом.",
    BX: "Средний стабильный расход: пополнять по точке заказа.",
    BY: "Средний переменный расход: смотреть динамику и не держать лишний запас.",
    BZ: "Средний нерегулярный расход: заказывать по подтвержденной потребности.",
    CX: "Низкий стабильный расход: поддерживать минимальный запас.",
    CY: "Низкий переменный расход: держать небольшой запас, пересматривать редко.",
    CZ: "Низкий нерегулярный расход: не закупать без заявки отделения.",
  };
  return recommendations[`${abcClass}${xyzClass}`] || "Проверьте расход и остатки перед заказом.";
}

function renderAbcXyzMatrix(items) {
  if (!items.length) return `<div class="empty">Матрица появится после приемки и расхода товаров.</div>`;
  const matrix = abcXyzMatrixData(items);
  return `
    <div class="abc-matrix" role="table" aria-label="Матрица ABC XYZ">
      <div class="abc-matrix-corner">ABC / XYZ</div>
      ${["X", "Y", "Z"].map((xyzClass) => `<div class="abc-matrix-head">XYZ ${xyzClass}</div>`).join("")}
      ${["A", "B", "C"].map((abcClass) => `
        <div class="abc-matrix-head">ABC ${abcClass}</div>
        ${["X", "Y", "Z"].map((xyzClass) => {
          const cell = matrix[`${abcClass}${xyzClass}`];
          const attention = cell.items.filter((item) => Number(item.recommended_order_quantity || 0) > 0).length;
          return `
            <div class="abc-cell ${attention ? "needs-order" : ""}">
              <div class="abc-cell-title">
                <strong>${abcClass}${xyzClass}</strong>
                <span>${escapeHtml(cell.items.length)} поз.</span>
              </div>
              <div class="abc-cell-metrics">
                <span>Свободно: ${escapeHtml(cell.free.toFixed(3))}</span>
                <span>Заказать: ${escapeHtml(cell.recommended.toFixed(3))}</span>
              </div>
              <p>${escapeHtml(abcXyzRecommendation(abcClass, xyzClass))}</p>
            </div>
          `;
        }).join("")}
      `).join("")}
    </div>
  `;
}

function abcXyzScatterPoints(items) {
  const values = items.map((item) => ({
    item,
    consumptionValue: Number(item.consumption_value || 0),
    freeQuantity: Number(item.current_free_quantity || 0),
    recommendedOrder: Number(item.recommended_order_quantity || 0),
  }));
  const maxValue = Math.max(1, ...values.map((point) => point.consumptionValue));
  const maxFree = Math.max(1, ...values.map((point) => point.freeQuantity));
  return values.map((point) => ({
    ...point,
    left: 8 + (point.consumptionValue / maxValue) * 84,
    top: 92 - (point.freeQuantity / maxFree) * 84,
  }));
}

function renderAbcXyzScatter(items) {
  if (!items.length) return `<div class="empty">Карта внимания появится после анализа расхода.</div>`;
  const points = abcXyzScatterPoints(items);
  return `
    <div class="abc-scatter" role="img" aria-label="Карта ABC XYZ по стоимости расхода и свободному остатку">
      <div class="abc-scatter-axis x">Стоимость расхода</div>
      <div class="abc-scatter-axis y">Свободный остаток</div>
      ${points.map((point) => {
        const item = point.item;
        const classes = [
          "abc-scatter-point",
          `abc-${String(item.abc_class || "c").toLowerCase()}`,
          `xyz-${String(item.xyz_class || "z").toLowerCase()}`,
          point.recommendedOrder > 0 ? "needs-order" : "",
        ].filter(Boolean).join(" ");
        const title = `${item.product_name} · ABC ${item.abc_class}/XYZ ${item.xyz_class} · расход ${item.consumption_value} · свободно ${item.current_free_quantity}`;
        return `
          <button
            class="${classes}"
            type="button"
            style="left: ${point.left.toFixed(2)}%; top: ${point.top.toFixed(2)}%;"
            title="${escapeAttr(title)}"
            aria-label="${escapeAttr(title)}"
          >
            <span>${escapeHtml(item.abc_class)}${escapeHtml(item.xyz_class)}</span>
          </button>
        `;
      }).join("")}
    </div>
    <div class="abc-scatter-legend">
      <span><i class="abc-a"></i> A: критично по стоимости</span>
      <span><i class="abc-b"></i> B: средняя важность</span>
      <span><i class="abc-c"></i> C: низкая стоимость</span>
      <span><i class="needs-order"></i> нужен заказ</span>
    </div>
  `;
}

function latestReadingForDevice(deviceId) {
  return state.data.sensorReadings.items.find((reading) => Number(reading.device_id) === Number(deviceId)) || null;
}

function conditionStatusSummary() {
  const readings = state.data.sensorReadings.items || [];
  const latestByDevice = new Map();
  readings.forEach((reading) => {
    if (!latestByDevice.has(reading.device_id)) latestByDevice.set(reading.device_id, reading);
  });
  const latest = [...latestByDevice.values()];
  return {
    devices: state.data.sensorDevices.length,
    readings: readings.length,
    warnings: latest.filter((reading) => reading.status === "warning").length,
    ok: latest.filter((reading) => reading.status === "ok").length,
  };
}

function renderConditionWarningBoard(warnings) {
  if (!warnings.length) return "";
  return `
    <div class="condition-warning-board span-12">
      <div class="toolbar">
        <h2>Нужно проверить условия хранения</h2>
        <button class="secondary" data-action="reload">Обновить</button>
      </div>
      <div class="condition-warning-grid">
        ${warnings.slice(0, 5).map((reading) => {
          const details = conditionBreachDetails(reading);
          return `
            <div class="condition-warning-card bad">
              <div>
                <strong>${escapeHtml(reading.device_name || `Датчик #${reading.device_id}`)}</strong>
                <span>${reading.warehouse_name ? escapeHtml(reading.warehouse_name) : nameById("warehouses", reading.warehouse_id)}</span>
              </div>
              <div class="condition-reading">
                <span>${reading.temperature_c === null || reading.temperature_c === undefined ? "—" : `${escapeHtml(reading.temperature_c)} °C`}</span>
                <span>${reading.humidity_percent === null || reading.humidity_percent === undefined ? "—" : `${escapeHtml(reading.humidity_percent)} %`}</span>
                <small>${dateText(reading.recorded_at)}</small>
              </div>
              <ul class="condition-breach-list">
                ${(details.length ? details : ["Показание вне нормы"]).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}
              </ul>
              <p class="condition-action">${escapeHtml(conditionActionText(reading))}</p>
            </div>
          `;
        }).join("")}
      </div>
    </div>
  `;
}

function conditionChartPoints(readings, field) {
  const values = readings
    .map((reading) => ({
      reading,
      value: reading[field] === null || reading[field] === undefined ? null : Number(reading[field]),
    }))
    .filter((point) => point.value !== null && !Number.isNaN(point.value));
  if (!values.length) return [];
  const rawMin = Math.min(...values.map((point) => point.value));
  const rawMax = Math.max(...values.map((point) => point.value));
  const min = rawMin === rawMax ? rawMin - 1 : rawMin;
  const max = rawMin === rawMax ? rawMax + 1 : rawMax;
  return values.map((point, index) => ({
    ...point,
    left: values.length === 1 ? 50 : (index / (values.length - 1)) * 100,
    top: 90 - ((point.value - min) / (max - min)) * 80,
  }));
}

function renderConditionChart() {
  const readings = [...(state.data.sensorReadings.items || [])]
    .sort((left, right) => String(left.recorded_at || "").localeCompare(String(right.recorded_at || "")))
    .slice(-20);
  if (!readings.length) return '<div class="empty">График появится после первых показаний датчика.</div>';
  const temperaturePoints = conditionChartPoints(readings, "temperature_c");
  const humidityPoints = conditionChartPoints(readings, "humidity_percent");
  return `
    <div class="condition-chart" role="img" aria-label="График температуры и влажности">
      ${temperaturePoints.map((point) => `
        <span
          class="condition-chart-point temperature"
          style="left: ${point.left.toFixed(2)}%; top: ${point.top.toFixed(2)}%;"
          title="${escapeAttr(`${point.value} °C · ${dateText(point.reading.recorded_at)}`)}"
        ></span>
      `).join("")}
      ${humidityPoints.map((point) => `
        <span
          class="condition-chart-point humidity"
          style="left: ${point.left.toFixed(2)}%; top: ${point.top.toFixed(2)}%;"
          title="${escapeAttr(`${point.value} % · ${dateText(point.reading.recorded_at)}`)}"
        ></span>
      `).join("")}
      <div class="condition-chart-axis x">Последние 20 показаний</div>
      <div class="condition-chart-axis y">Значение</div>
    </div>
    <div class="condition-chart-legend">
      <span><i class="temperature"></i> Температура</span>
      <span><i class="humidity"></i> Влажность</span>
    </div>
  `;
}

function renderConditions() {
  const summary = conditionStatusSummary();
  const warnings = latestConditionWarnings();
  const devices = filteredRows(state.data.sensorDevices, (row) => [
    row.id,
    row.name,
    row.serial_number,
    row.sensor_type,
    rawNameById("warehouses", row.warehouse_id),
  ]);
  const readings = filteredRows(state.data.sensorReadings.items || [], (row) => [
    row.id,
    row.device_name,
    row.warehouse_name,
    row.temperature_c,
    row.humidity_percent,
    row.status,
    row.raw_payload,
    row.recorded_at,
  ]);
  const warehouseUnavailable = state.data.warehouses.length === 0;
  const deviceUnavailable = state.data.sensorDevices.length === 0;
  return `
    <div class="grid">
      ${needsWarehouseNotice("Добавить склад")}
      <div class="panel span-3 metric"><span>Датчики</span><strong>${summary.devices}</strong></div>
      <div class="panel span-3 metric"><span>Показаний</span><strong>${summary.readings}</strong></div>
      <div class="panel span-3 metric"><span>В норме</span><strong>${summary.ok}</strong></div>
      <div class="panel span-3 metric ${summary.warnings ? "condition-alert" : ""}"><span>Требуют внимания</span><strong>${summary.warnings}</strong></div>
      ${renderConditionWarningBoard(warnings)}
      <div class="panel span-12">
        <div class="toolbar">
          <div>
            <h2>График условий хранения</h2>
            <span class="helper-text">Последние показания помогают быстро увидеть скачки температуры и влажности.</span>
          </div>
          <button class="secondary" data-action="reload">Обновить</button>
        </div>
        ${renderConditionChart()}
      </div>

      <div class="form-panel span-5">
        <h2>Новый датчик</h2>
        ${form("sensor-device-form", [
          { label: "Склад или кабинет", name: "warehouse_id", type: "select", options: optionsFrom("warehouses", "Выберите склад"), required: true },
          { label: "Название", name: "name", value: "Датчик температуры и влажности", required: true },
          { label: "Серийный номер", name: "serial_number", value: "" },
          { label: "Тип", name: "sensor_type", value: "temperature_humidity", required: true },
          { label: "Мин. температура °C", name: "min_temperature_c", type: "number", step: "0.1", value: "2" },
          { label: "Макс. температура °C", name: "max_temperature_c", type: "number", step: "0.1", value: "8" },
          { label: "Мин. влажность %", name: "min_humidity_percent", type: "number", step: "0.1", min: "0", value: "30" },
          { label: "Макс. влажность %", name: "max_humidity_percent", type: "number", step: "0.1", min: "0", value: "70" },
        ], "Добавить датчик", {
          disabledSubmit: warehouseUnavailable,
          submitHint: warehouseUnavailable ? "Сначала добавьте склад или кабинет." : "",
        })}
      </div>

      <div class="form-panel span-7">
        <h2>Внести показание</h2>
        ${form("sensor-reading-form", [
          { label: "Датчик", name: "device_id", type: "select", options: optionsFrom("sensorDevices", "Выберите датчик", (device) => `${device.name} · ${rawNameById("warehouses", device.warehouse_id)}`), required: true },
          { label: "Температура °C", name: "temperature_c", type: "number", step: "0.1" },
          { label: "Влажность %", name: "humidity_percent", type: "number", step: "0.1", min: "0" },
          { label: "Источник или заметка", name: "raw_payload", full: true, value: "ручной ввод" },
        ], "Сохранить показание", {
          disabledSubmit: deviceUnavailable,
          submitHint: deviceUnavailable ? "Сначала добавьте датчик слева." : "Заполните температуру или влажность. Система сама сравнит с порогами датчика.",
        })}
      </div>

      <div class="table-panel span-12">
        <div class="toolbar">
          <h2>Датчики хранения</h2>
          <button class="secondary" data-action="reload">Обновить</button>
        </div>
        ${table([
          { label: "Номер", key: "id" },
          { label: "Название", key: "name" },
          { label: "Склад", render: (row) => nameById("warehouses", row.warehouse_id) },
          { label: "Порог температуры", render: (row) => `${escapeHtml(row.min_temperature_c ?? "—")} … ${escapeHtml(row.max_temperature_c ?? "—")} °C` },
          { label: "Порог влажности", render: (row) => `${escapeHtml(row.min_humidity_percent ?? "—")} … ${escapeHtml(row.max_humidity_percent ?? "—")} %` },
          { label: "Последнее", render: (row) => {
            const reading = latestReadingForDevice(row.id);
            return reading ? `${escapeHtml(reading.temperature_c ?? "—")} °C · ${escapeHtml(reading.humidity_percent ?? "—")} %` : "—";
          } },
          { label: "Что не так", render: (row) => {
            const reading = latestReadingForDevice(row.id);
            if (!reading) return badge("pending");
            if (reading.status !== "warning") return badge("ok");
            return `<div class="condition-breach-list compact">${conditionBreachDetails(reading).map((item) => `<span>${escapeHtml(item)}</span>`).join("") || "Показание вне нормы"}</div>`;
          } },
        ], devices, "Датчиков пока нет. Добавьте датчик для склада или кабинета.")}
      </div>

      <div class="table-panel span-12">
        <div class="toolbar">
          <h2>Журнал температуры и влажности</h2>
          <button class="secondary" data-export-report="sensorReadings">Выгрузить CSV</button>
        </div>
        ${table([
          { label: "Время", render: (row) => dateText(row.recorded_at) },
          { label: "Датчик", render: (row) => escapeHtml(row.device_name || `#${row.device_id}`) },
          { label: "Склад", render: (row) => row.warehouse_name ? escapeHtml(row.warehouse_name) : nameById("warehouses", row.warehouse_id) },
          { label: "Температура", render: (row) => row.temperature_c === null || row.temperature_c === undefined ? "—" : `${escapeHtml(row.temperature_c)} °C` },
          { label: "Влажность", render: (row) => row.humidity_percent === null || row.humidity_percent === undefined ? "—" : `${escapeHtml(row.humidity_percent)} %` },
          { label: "Статус", render: (row) => badge(row.status) },
          { label: "Источник", render: (row) => escapeHtml(row.raw_payload || "—") },
        ], readings, "Показаний пока нет. Внесите первое вручную или запустите мост датчика.")}
      </div>
    </div>
  `;
}

function renderAnalytics() {
  const items = state.data.analytics.items || [];
  const toOrder = items.filter((row) => Number(row.recommended_order_quantity || 0) > 0);
  const important = items.filter((row) => row.abc_class === "A");
  const unstable = items.filter((row) => row.xyz_class === "Z" && Number(row.consumption_quantity || 0) > 0);
  const historyRows = filteredRows(state.data.abcXyzRuns.items || [], (row) => [
    row.id,
    row.warehouse_id,
    row.analysis_days,
    row.period_start,
    row.period_end,
    row.source,
    row.status,
    row.generated_at,
  ]);
  return `
    <div class="grid">
      <div class="panel span-3 metric"><span>Товаров в отчете</span><strong>${items.length}</strong></div>
      <div class="panel span-3 metric"><span>Важные A</span><strong>${important.length}</strong></div>
      <div class="panel span-3 metric"><span>Нужно заказать</span><strong>${toOrder.length}</strong></div>
      <div class="panel span-3 metric"><span>Нестабильный спрос</span><strong>${unstable.length}</strong></div>
      <div class="panel span-12">
        <div class="toolbar">
          <div>
            <h2>Матрица ABC/XYZ</h2>
            <span class="helper-text">Матрица показывает важность товара и стабильность расхода. Ячейки с заказом подсвечены.</span>
          </div>
          <button class="primary" data-action="save-abc-xyz-run">Сохранить расчет</button>
        </div>
        ${renderAbcXyzMatrix(items)}
      </div>
      <div class="panel span-12">
        <div class="toolbar">
          <div>
            <h2>Карта внимания ABC/XYZ</h2>
            <span class="helper-text">Точки справа дают основную стоимость расхода, точки сверху занимают больше свободного остатка.</span>
          </div>
        </div>
        ${renderAbcXyzScatter(items)}
      </div>
      <div class="table-panel span-12">
        <div class="toolbar">
          <h2>ABC/XYZ анализ и заказ</h2>
          <div class="row-actions">
            <button class="secondary" data-export-report="analytics">Выгрузить CSV</button>
            <button class="secondary" data-action="reload">Обновить</button>
          </div>
        </div>
        ${table([
          { label: "Товар", render: (row) => `${escapeHtml(row.product_name)}<br><span class="badge">${escapeHtml(row.sku)}</span>` },
          { label: "ABC", render: (row) => analyticsClassBadge(row.abc_class, "abc") },
          { label: "XYZ", render: (row) => analyticsClassBadge(row.xyz_class, "xyz") },
          { label: "Расход", key: "consumption_quantity" },
          { label: "Стоимость расхода", key: "consumption_value" },
          { label: "Свободно", key: "current_free_quantity" },
          { label: "Точка заказа", key: "reorder_point" },
          { label: "Заказать", render: (row) => Number(row.recommended_order_quantity || 0) > 0 ? `<strong>${escapeHtml(row.recommended_order_quantity)}</strong>` : "—" },
          { label: "Рекомендация", key: "recommendation" },
        ], filteredRows(items, (row) => [row.product_name, row.sku, row.abc_class, row.xyz_class, row.recommendation, row.recommended_order_quantity]), "Аналитика появится после приемки и расхода товаров.")}
      </div>
      <div class="table-panel span-12">
        <div class="toolbar">
          <h2>История расчетов</h2>
          <div class="row-actions">
            <button class="secondary" data-export-report="abcXyzRuns">Выгрузить CSV</button>
            <button class="secondary" data-action="reload">Обновить</button>
          </div>
        </div>
        ${table([
          { label: "Номер", key: "id" },
          { label: "Склад", render: (row) => row.warehouse_id ? nameById("warehouses", row.warehouse_id) : "Все склады" },
          { label: "Период", render: (row) => `${dateText(row.period_start)} — ${dateText(row.period_end)}` },
          { label: "Дней", key: "analysis_days" },
          { label: "Источник", render: (row) => escapeHtml(row.source === "background" ? "Автоматически" : "Вручную") },
          { label: "Статус", render: (row) => badge(row.status) },
          { label: "Позиций", key: "items_count" },
          { label: "Создан", render: (row) => dateText(row.generated_at) },
        ], historyRows, "Истории расчетов пока нет. Нажмите «Сохранить расчет», чтобы зафиксировать текущий анализ.")}
      </div>
    </div>
  `;
}

function renderAudit() {
  return `
    <div class="table-panel">
      <div class="toolbar"><h2>Журнал действий</h2><button class="secondary" data-export-report="audit">Выгрузить CSV</button></div>
      ${table([
        { label: "Время", render: (row) => dateText(row.created_at) },
        { label: "Пользователь", key: "actor_id" },
        { label: "Действие", key: "action" },
        { label: "Сущность", render: (row) => `${row.entity_type} #${row.entity_id}` },
        { label: "Склад", render: (row) => row.warehouse_id || "—" },
        { label: "Данные", render: (row) => `<code>${escapeHtml(JSON.stringify(row.payload))}</code>` },
      ], filteredRows(state.data.audit.items, (row) => [row.created_at, row.actor_id, row.action, row.entity_type, row.entity_id, row.warehouse_id, JSON.stringify(row.payload)]))}
    </div>
  `;
}

function renderSupplierPortal() {
  const application = state.data.supplierApplication;
  const canSubmit = !application || ["rejected", "needs_changes"].includes(application.status);
  const title = application?.status === "approved" ? "Кабинет поставщика" : "Стать поставщиком";
  const openRequests = filteredRows(state.data.supplierOpenPurchaseRequests, (row) => [
    row.id,
    row.product_name,
    row.sku,
    rawNameById("warehouses", row.warehouse_id),
    row.recommended_quantity,
    row.reason,
  ]);
  const myOffers = filteredRows(state.data.supplierOffers, (row) => [
    row.id,
    row.product_name,
    row.sku,
    row.status,
    row.unit_price,
    row.quantity,
    row.review_reason,
  ]);
  return `
    <div class="grid">
      <div class="panel span-12 supplier-portal-head">
        <div>
          <span class="eyebrow">Профиль поставщика</span>
          <h2>${escapeHtml(title)}</h2>
          <p>${escapeHtml(supplierApplicationStatusText(application))}</p>
        </div>
        ${application ? badge(application.status) : badge("draft")}
      </div>
      ${canSubmit ? `
        <div class="form-panel span-6">
          <h2>${application ? "Обновить заявку" : "Заявка поставщика"}</h2>
          ${form("supplier-application-form", [
            { label: "Название компании", name: "name", value: application?.name || "", required: true },
            { label: "БИН", name: "bin", value: application?.bin || "" },
            { label: "Телефон", name: "phone", value: application?.phone || "" },
            { label: "Email", name: "email", type: "email", value: application?.email || "" },
            { label: "Контактное лицо", name: "contact_person", value: application?.contact_person || "" },
            { label: "Адрес", name: "address", value: application?.address || "", full: true },
            { label: "Комментарий", name: "notes", type: "textarea", value: application?.notes || "", full: true },
          ], "Отправить на проверку")}
        </div>
        <div class="panel span-6">
          <h2>Как это работает</h2>
          <p class="confirm-message">После отправки заявка появится у менеджера склада на странице «Заявки» → раздел «Заявки поставщиков». После одобрения откроется полный кабинет поставщика с открытыми заявками на закупку.</p>
        </div>
      ` : ""}
      ${application?.status === "pending" ? `
        <div class="panel span-12 warning-panel">
          <strong>Заявка на проверке</strong>
          <span>Ожидайте одобрения менеджера склада. После одобрения здесь появятся заявки на закупку и возможность отправлять коммерческие предложения.</span>
          <button class="secondary" type="button" data-action="reload" style="margin-left:auto">Проверить статус</button>
        </div>
      ` : ""}
      ${application?.status === "approved" ? `
        <div class="panel span-3 metric"><span>Поставщик</span><strong>${escapeHtml(application.supplier_name || application.name)}</strong></div>
        <div class="panel span-3 metric"><span>Открытые заявки</span><strong>${state.data.supplierOpenPurchaseRequests.length}</strong></div>
        <div class="panel span-3 metric"><span>Мои КП</span><strong>${state.data.supplierOffers.length}</strong></div>
        <div class="panel span-3 metric"><span>Мои объявления</span><strong>${state.data.supplierCatalog.length}</strong></div>

        <div class="tab-panel span-12">
          <div class="tabs" id="supplier-portal-tabs">
            <button class="tab ${(!state.ui.supplierTab || state.ui.supplierTab === 'offers') ? 'tab-active' : ''}" data-supplier-tab="offers">Торги / КП</button>
            <button class="tab ${state.ui.supplierTab === 'listings' ? 'tab-active' : ''}" data-supplier-tab="listings">Мои объявления</button>
          </div>
        </div>

        ${(!state.ui.supplierTab || state.ui.supplierTab === 'offers') ? `
          <div class="form-panel span-4">
            <h2>Предложить поставку</h2>
            ${form("supplier-offer-form", [
              { label: "Заявка", name: "purchase_request_id", type: "select", options: staticOptions(state.data.supplierOpenPurchaseRequests.map((row) => [row.id, `#${row.id} ${row.product_name || rawNameById("products", row.product_id)} - ${row.recommended_quantity}`]), "Выберите заявку"), required: true },
              { label: "Цена за единицу", name: "unit_price", type: "number", step: "0.0001", required: true },
              { label: "Количество", name: "quantity", type: "number", step: "0.001", required: true },
              { label: "Дата поставки", name: "delivery_date", type: "date" },
              { label: "Предложение действительно до", name: "expires_at", type: "date" },
              { label: "Комментарий", name: "comment", type: "textarea", full: true },
            ], "Отправить КП", {
              disabledSubmit: state.data.supplierOpenPurchaseRequests.length === 0,
              submitHint: state.data.supplierOpenPurchaseRequests.length === 0 ? "Открытых заявок пока нет." : "",
            })}
          </div>
          <div class="table-panel span-8">
            <div class="toolbar">
              <h2>Открытые заявки Tetis</h2>
              <button class="secondary" type="button" data-action="reload">Обновить</button>
            </div>
            ${table([
              { label: "Заявка", render: (row) => `#${escapeHtml(row.id)}` },
              { label: "Товар", render: (row) => `${escapeHtml(row.product_name || rawNameById("products", row.product_id))}<br><span class="badge">${escapeHtml(row.sku || "без кода")}</span>` },
              { label: "Склад", render: (row) => nameById("warehouses", row.warehouse_id) },
              { label: "Количество", key: "recommended_quantity" },
              { label: "Причина", render: (row) => escapeHtml(row.reason || "—") },
              { label: "Мое КП", render: (row) => row.offer_id ? `${badge(row.offer_status)}<br>${escapeHtml(row.offer_unit_price || "—")} x ${escapeHtml(row.offer_quantity || "—")}` : "—" },
            ], openRequests, "Открытых заявок для поставщиков пока нет.")}
          </div>
          <div class="table-panel span-12">
            <div class="toolbar"><h2>Мои коммерческие предложения</h2><button class="secondary" type="button" data-action="reload">Обновить</button></div>
            ${table([
              { label: "КП", render: (row) => `#${escapeHtml(row.id)}` },
              { label: "Заявка", render: (row) => `#${escapeHtml(row.purchase_request_id)}` },
              { label: "Товар", render: (row) => escapeHtml(row.product_name || "—") },
              { label: "Цена", key: "unit_price" },
              { label: "Количество", key: "quantity" },
              { label: "Поставка", render: (row) => escapeHtml(row.delivery_date || "—") },
              { label: "Статус", render: (row) => badge(row.status) },
              { label: "Решение", render: (row) => escapeHtml(row.review_reason || "—") },
              { label: "", render: (row) => row.status === "submitted" ? `<button class="secondary compact-action" type="button" data-withdraw-offer="${escapeAttr(row.id)}">Отозвать</button>` : "" },
            ], myOffers, "Вы еще не отправляли коммерческие предложения.")}
          </div>
        ` : ""}

        ${state.ui.supplierTab === 'listings' ? `
          <div class="form-panel span-4">
            <h2>Новое объявление</h2>
            ${form("supplier-catalog-form", [
              { label: "Тип", name: "type", type: "select", options: staticOptions([["product", "Товар"], ["service", "Услуга"]], ""), required: true },
              { label: "Название", name: "title", required: true },
              { label: "Описание", name: "description", type: "textarea", full: true },
              { label: "Цена", name: "price", type: "number", step: "0.01" },
              { label: "Тип цены", name: "price_type", type: "select", options: staticOptions([["fixed", "Фикс."], ["hourly", "В час"], ["negotiable", "Договорная"]], "") },
              { label: "Единица", name: "unit", placeholder: "шт, час, м²..." },
              { label: "Категория услуги", name: "service_category", type: "select", options: staticOptions([["repair", "Ремонт оборудования"], ["cleaning", "Клининг / уборка"], ["logistics", "Логистика"], ["consulting", "Консалтинг / IT"]], "(не указана)") },
            ], "Добавить объявление")}
          </div>
          <div class="catalog-grid-panel span-8">
            <div class="toolbar"><h2>Мои объявления (${state.data.supplierCatalog.length})</h2><button class="secondary" type="button" data-action="reload">Обновить</button></div>
            ${state.data.supplierCatalog.length === 0 ? `<p class="empty-message">Объявлений пока нет. Добавьте свои товары или услуги.</p>` : `
              <div class="catalog-grid catalog-grid-owned">
                ${state.data.supplierCatalog.map((item) => `
                  <div class="catalog-card">
                    <div class="catalog-card-image">
                      ${item.image_file_id ? `<img src="${API}/catalog/${item.id}/image" alt="" loading="lazy">` : '<div class="catalog-card-no-image">📷</div>'}
                      <label class="catalog-upload-label" title="Загрузить фото">
                        📷
                        <input type="file" accept="image/*" class="catalog-image-upload" data-upload-image="${escapeAttr(item.id)}" style="display:none">
                      </label>
                    </div>
                    <div class="catalog-card-body">
                      <div class="catalog-card-meta">
                        ${item.type === "service" ? `<span class="badge badge-service">Услуга</span>` : `<span class="badge">Товар</span>`}
                        ${item.service_category ? `<span class="badge badge-category">${escapeHtml(SERVICE_CATEGORIES[item.service_category] || item.service_category)}</span>` : ""}
                      </div>
                      <div class="catalog-card-title">${escapeHtml(item.title)}</div>
                      ${item.price ? `<div class="catalog-card-price">${escapeHtml(item.price)} ₸${item.unit ? " / " + escapeHtml(item.unit) : ""}</div>` : ""}
                    </div>
                    <div class="catalog-card-actions">
                      <button class="danger compact-action" type="button" data-delete-catalog="${escapeAttr(item.id)}">Удалить</button>
                    </div>
                  </div>
                `).join("")}
              </div>
            `}
          </div>
        ` : ""}
      ` : ""}
    </div>
  `;
}

const SERVICE_CATEGORIES = {
  repair: "Ремонт оборудования",
  cleaning: "Клининг / уборка",
  logistics: "Логистика",
  consulting: "Консалтинг / IT",
};
const PRICE_TYPES = { fixed: "Фикс.", hourly: "В час", negotiable: "Договорная" };

function catalogItemCard(item) {
  const imgSrc = item.image_file_id ? `${API}/catalog/${item.id}/image` : "";
  const categoryLabel = item.type === "service" && item.service_category
    ? SERVICE_CATEGORIES[item.service_category] || item.service_category
    : "";
  const priceLabel = item.price
    ? `${escapeHtml(item.price)} ₸${item.unit ? " / " + escapeHtml(item.unit) : ""}`
    : PRICE_TYPES[item.price_type] || "Цена по запросу";
  return `
    <div class="catalog-card" data-item-id="${escapeAttr(item.id)}">
      <div class="catalog-card-image">${imgSrc ? `<img src="${escapeAttr(imgSrc)}" alt="" loading="lazy">` : '<div class="catalog-card-no-image">📷</div>'}</div>
      <div class="catalog-card-body">
        <div class="catalog-card-meta">
          ${item.type === "service" ? `<span class="badge badge-service">Услуга</span>` : `<span class="badge">Товар</span>`}
          ${categoryLabel ? `<span class="badge badge-category">${escapeHtml(categoryLabel)}</span>` : ""}
        </div>
        <div class="catalog-card-title">${escapeHtml(item.title)}</div>
        ${item.description ? `<div class="catalog-card-desc">${escapeHtml(item.description.slice(0, 120))}${item.description.length > 120 ? "…" : ""}</div>` : ""}
        <div class="catalog-card-footer">
          <strong class="catalog-card-price">${priceLabel}</strong>
          ${item.supplier_name ? `<span class="catalog-card-supplier">${escapeHtml(item.supplier_name)}</span>` : ""}
        </div>
      </div>
    </div>
  `;
}

function renderMarketplace() {
  const items = pageItems(state.data.marketplace);
  return `
    <div class="grid">
      <div class="panel span-12">
        <div class="toolbar">
          <h2>Товары и услуги поставщиков</h2>
          <button class="secondary" type="button" data-action="reload">Обновить</button>
        </div>
        <div class="marketplace-filters" id="marketplace-filters">
          <button class="chip ${state.ui.marketplaceType == null ? 'chip-active' : ''}" data-marketplace-filter-type="">Все</button>
          <button class="chip ${state.ui.marketplaceType === 'product' ? 'chip-active' : ''}" data-marketplace-filter-type="product">Товары</button>
          <button class="chip ${state.ui.marketplaceType === 'service' ? 'chip-active' : ''}" data-marketplace-filter-type="service">Услуги</button>
          ${Object.entries(SERVICE_CATEGORIES).map(([key, label]) =>
            `<button class="chip ${state.ui.marketplaceCategory === key ? 'chip-active' : ''}" data-marketplace-filter-category="${escapeAttr(key)}">${escapeHtml(label)}</button>`
          ).join("")}
        </div>
      </div>
      ${items.length === 0 ? `
        <div class="panel span-12"><p class="empty-message">Объявлений пока нет. Поставщики смогут добавлять свои товары и услуги в Кабинете поставщика.</p></div>
      ` : `
        <div class="catalog-grid span-12">
          ${items.map(catalogItemCard).join("")}
        </div>
      `}
    </div>
  `;
}

const renderers = {
  dashboard: renderDashboard,
  "tablet-writeoff": renderTabletWriteoff,
  catalog: renderCatalog,
  receipts: renderReceipts,
  documents: renderDocuments,
  operations: renderOperations,
  repacking: renderRepacking,
  returns: renderReturns,
  movements: renderMovements,
  reservations: renderReservations,
  "purchase-requests": renderPurchaseRequests,
  inventory: renderInventory,
  conditions: renderConditions,
  analytics: renderAnalytics,
  marketplace: renderMarketplace,
  notifications: renderNotifications,
  audit: renderAudit,
  "supplier-portal": renderSupplierPortal,
};

function render() {
  ensureAccessibleView();
  renderNav();
  const view = views.find(([id]) => id === state.view);
  el("view-title").textContent = view ? view[2] : "Склад";
  el("content").innerHTML = `${searchNotice()}${renderers[state.view]?.() || renderDashboard()}`;
  bindActions();
  applyDensity();
}

function renderAuthBlocked() {
  return `
    <div class="panel span-12 auth-blocked" role="status">
      <h2>Доступ временно ограничен</h2>
      <p>${escapeHtml(state.auth.blockedMessage)}</p>
      <button class="secondary" type="button" data-action="reload">Проверить снова</button>
    </div>
  `;
}

function applyDensity() {
  document.body.classList.toggle("compact", state.ui.density === "compact");
  const densityButton = el("density-button");
  densityButton.textContent = state.ui.density === "compact" ? "Обычный вид" : "Компактный вид";
  densityButton.setAttribute(
    "aria-pressed",
    state.ui.density === "compact" ? "true" : "false",
  );
}

async function loadAll() {
  try {
    state.loadWarnings = [];
    state.auth.blockedMessage = "";
    if (!el("auth-token").value.trim()) {
      await requestSkladTokenFromTetis();
    }
    const profile = await request("/me");
    applyActorProfile(profile);
    state.data.supplierApplication = await loadOptional("Профиль поставщика", request("/supplier-application/me"), null);
    if (state.data.supplierApplication?.status === "approved") {
      const [supplierOpenRequests, supplierOffers, supplierCatalog] = await Promise.all([
        loadOptional("Заявки для поставщика", request("/supplier/purchase-requests?status=draft&limit=100"), []),
        loadOptional("Предложения поставщика", request("/supplier/offers?limit=100"), []),
        loadOptional("Мои объявления", request("/supplier/catalog?limit=100"), { items: [], total: 0 }),
      ]);
      state.data.supplierOpenPurchaseRequests = supplierOpenRequests;
      state.data.supplierOffers = supplierOffers;
      state.data.supplierCatalog = pageItems(supplierCatalog);
    } else {
      state.data.supplierOpenPurchaseRequests = [];
      state.data.supplierOffers = [];
      state.data.supplierCatalog = [];
    }
    updateSupplierContext();
    if (!hasPermission("stock:read") && hasSupplierAccess()) {
      state.data.health = await loadOptional("Проверка связи", request("/health"), { status: "unknown" });
      state.view = "supplier-portal";
      render();
      return;
    }
    const [health, readiness, categories, suppliers, warehouses, productUnits, products] = await Promise.all([
      request("/health"),
      request("/health/ready"),
      request("/categories"),
      request("/suppliers"),
      request("/warehouses"),
      loadOptional("Единицы измерения", request("/product-units"), ["шт", "уп", "рулон", "флакон", "бут", "ампула"]),
      request("/products"),
    ]);
    state.data.health = health;
    state.data.readiness = readiness;
    state.data.categories = categories;
    state.data.suppliers = suppliers;
    state.data.warehouses = warehouses;
    state.data.productUnits = productUnits;
    state.data.products = products;
    reconcileWarehouseScope();
    const wf = warehouseFilterParam();
    const query = wf ? `?${wf}` : "";

    const [balances, batches, batchRecalls, reservations, quarantineReviews, purchaseRequests, notifications, audit, documents, inventorySessions, movements, repackings, analytics, abcXyzRuns, sensorDevices, sensorReadings] = await Promise.all([
      request(`/balances${query ? `${query}&limit=100` : "?limit=100"}`),
      request(`/batches${query ? `${query}&limit=100` : "?limit=100"}`),
      loadOptional("Отзывы партий", request("/batch-recalls?limit=100"), { items: [], total: 0 }),
      loadOptional("Бронирование", request(`/reservations${query ? `${query}&limit=100` : "?limit=100"}`), []),
      loadOptional("Карантинные проверки", request(`/quarantine-reviews${query ? `${query}&limit=100` : "?limit=100"}`), { items: [], total: 0 }),
      loadOptional("Заявки на закупку", request(`/purchase-requests${query ? `${query}&limit=100` : "?limit=100"}`), { items: [], total: 0 }),
      request(`/notifications${query ? `${query}&limit=100` : "?limit=100"}`),
      hasPermission("audit:read")
        ? loadOptional("Журнал действий", request(`/audit-log${query ? `${query}&limit=100` : "?limit=100"}`), { items: [], total: 0 })
        : Promise.resolve({ items: [], total: 0 }),
      loadOptional("Документы", request(`/stock-documents${query ? `${query}&limit=100` : "?limit=100"}`), { items: [], total: 0 }),
      loadOptional("Инвентаризация", request(`/inventory-sessions${query ? `${query}&limit=100` : "?limit=100"}`), []),
      loadOptional("Движения", request(`/stock-movements${query ? `${query}&limit=100` : "?limit=100"}`), { items: [], total: 0 }),
      loadOptional("Журнал фасовки", request(`/batch-transformations${query ? `${query}&limit=100` : "?limit=100"}`), { items: [], total: 0 }),
      loadOptional("Аналитика", request(`/analytics/abc-xyz${query ? `${query}&days=90` : "?days=90"}`), { items: [], analysis_days: 90, warehouse_id: null, generated_at: null }),
      loadOptional("История ABC/XYZ", request(`/analytics/abc-xyz/history${query ? `${query}&limit=100` : "?limit=100"}`), { items: [], total: 0 }),
      loadOptional("Датчики условий хранения", request(`/sensor-devices${query ? `${query}&limit=100` : "?limit=100"}`), []),
      loadOptional("Журнал условий хранения", request(`/sensor-readings${query ? `${query}&limit=100` : "?limit=100"}`), { items: [], total: 0 }),
    ]);
    state.data.balances = balances;
    state.data.batches = batches;
    state.data.batchRecalls = batchRecalls;
    state.data.reservations = reservations;
    state.data.quarantineReviews = quarantineReviews;
    state.data.purchaseRequests = pageItems(purchaseRequests);
    state.data.supplierAdminOffers = hasPermission("stock:read")
      ? await loadOptional("Предложения поставщиков", request(`/supplier-offers${query ? `${query}&limit=100` : "?limit=100"}`), [])
      : [];
    state.data.supplierApplications = hasPermission("admin:users")
      ? pageItems(await loadOptional("Заявки поставщиков", request("/supplier-applications?limit=100"), { items: [], total: 0 }))
      : [];
    state.data.marketplace = await loadOptional("Маркетплейс", request("/marketplace?limit=50"), { items: [], total: 0 });
    state.data.notifications = notifications;
    state.data.audit = audit;
    state.data.documents = pageItems(documents);
    state.data.inventorySessions = inventorySessions;
    state.data.movements = pageItems(movements);
    state.data.repackings = repackings;
    state.data.analytics = analytics;
    state.data.abcXyzRuns = abcXyzRuns;
    state.data.sensorDevices = sensorDevices;
    state.data.sensorReadings = sensorReadings;
    el("api-status").className = "status-dot ok";
    el("api-status").textContent = "Система доступна";
  } catch (error) {
    if (error instanceof AuthRequiredError) {
      state.auth.blockedMessage = "";
      el("api-status").className = "status-dot bad";
      el("api-status").textContent = "Сервер требует вход";
      showAlert("Сервер пока требует вход. Включите SKLAD_PUBLIC_ACCESS_ENABLED=true и перезапустите склад.", "error");
    } else {
      el("api-status").className = "status-dot bad";
      el("api-status").textContent = "Нет связи с сервером";
      showAlert(error.message, "error");
    }
  }
  render();
  if (!state.auth.blockedMessage) {
    connectRealtime();
  }
}

function scheduleRealtimeRefresh() {
  if (realtimeRefreshTimer) return;
  realtimeRefreshTimer = window.setTimeout(async () => {
    realtimeRefreshTimer = null;
    await loadAll();
  }, 350);
}

function connectRealtime() {
  const wf = warehouseFilterParam();
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const authToken = el("auth-token").value.trim();
  const params = new URLSearchParams(wf);
  if (authToken) params.set("access_token", authToken);
  const query = params.toString();
  const targetUrl = `${protocol}//${window.location.host}${API}/ws/balances${query ? `?${query}` : ""}`;
  if (balanceSocket && balanceSocket.url === targetUrl && balanceSocket.readyState <= WebSocket.OPEN) return;
  if (balanceSocket) balanceSocket.close();

  state.realtime = "connecting";
  const socket = new WebSocket(targetUrl);
  balanceSocket = socket;
  socket.addEventListener("open", () => {
    if (balanceSocket !== socket) return;
    state.realtime = "online";
    render();
  });
  socket.addEventListener("message", (event) => {
    const payload = parseJson(event.data, {});
    if ([
      "stock.balance.updated",
      "stock.transfer.posted",
      "stock.return.posted",
      "inventory.posted",
      "batch.recalled",
      "batch.status.updated",
      "sensor.reading.created",
      "notifications.updated",
    ].includes(payload.event_type)) {
      scheduleRealtimeRefresh();
    }
  });
  socket.addEventListener("close", () => {
    if (balanceSocket !== socket) return;
    state.realtime = "offline";
    render();
  });
  socket.addEventListener("error", () => {
    if (balanceSocket !== socket) return;
    state.realtime = "offline";
    render();
  });
}

function bindSubmit(id, handler, confirmMessage = null) {
  const node = document.getElementById(id);
  if (!node) return;
  node.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (node.dataset.pending === "true") return;
    const submitButton = node.querySelector('button[type="submit"]');
    try {
      clearFormError(node);
      const payload = collect(node);
      const controlledIssues = node.querySelector("input[name='patient_id'], input[name='doctor_id'], input[name='medical_record_no']")
        ? applyControlledWriteoffRequirements(node, payload)
        : [];
      if (controlledIssues.length) {
        showFormError(node, controlledWriteoffMessage());
        return;
      }
      const message = typeof confirmMessage === "function" ? confirmMessage(payload) : confirmMessage;
      if (message && !(await confirmAction(message))) return;
      node.dataset.pending = "true";
      setPending(submitButton, true);
      await handler(payload);
      showAlert("Операция выполнена");
      await loadAll();
    } catch (error) {
      showFormError(node, error.message);
      showAlert(error.message, "error");
    } finally {
      delete node.dataset.pending;
      setPending(submitButton, false);
    }
  });
}

function updateBatchAwareForm(formElement, { autofill = false } = {}) {
  const batchId = formElement.elements.batch_id?.value;
  const warehouseField = formElement.querySelector("[data-batch-warehouse-field]");
  if (autofill && batchId && warehouseField) {
    const balance = balanceForBatch(batchId);
    if (balance) warehouseField.value = String(balance.warehouse_id);
  }
  const warehouseId = warehouseField?.value || null;
  const summary = formElement.querySelector("[data-selected-batch-summary]");
  if (summary) summary.innerHTML = selectedBatchSummaryHtml(batchId, warehouseId);
  applyControlledWriteoffRequirements(formElement);
}

function bindBatchAwareForms() {
  document.querySelectorAll("form[data-batch-aware]").forEach((formElement) => {
    updateBatchAwareForm(formElement);
    formElement.querySelectorAll("select[name='batch_id'], [data-batch-warehouse-field]").forEach((input) => {
      input.addEventListener("change", () => {
        updateBatchAwareForm(formElement, { autofill: input.name === "batch_id" });
      });
    });
  });
}

function bindControlledWriteoffForms() {
  ["writeoff-form", "tablet-writeoff-form", "fefo-form"].forEach((id) => {
    const formElement = document.getElementById(id);
    if (!formElement) return;
    applyControlledWriteoffRequirements(formElement);
    formElement.querySelectorAll("select[name='batch_id'], select[name='product_id'], input[name='patient_id'], input[name='doctor_id'], input[name='medical_record_no'], input[name='second_approver_id']").forEach((input) => {
      input.addEventListener("change", () => applyControlledWriteoffRequirements(formElement));
      input.addEventListener("input", () => applyControlledWriteoffRequirements(formElement));
    });
  });
}

function bindActions() {
  document.querySelectorAll("[data-clear-search]").forEach((button) => {
    button.addEventListener("click", () => {
      state.ui.search = "";
      el("global-search").value = "";
      render();
    });
  });

  document.querySelectorAll("[data-go-view]").forEach((button) => {
    button.addEventListener("click", () => {
      state.view = safeViewTarget(button.dataset.goView);
      render();
    });
  });

  document.querySelectorAll("[data-batch-detail]").forEach((button) => {
    button.addEventListener("click", async () => {
      if (button.disabled) return;
      try {
        setPending(button, true, "Открываем");
        await showBatchTraceability(button.dataset.batchDetail);
      } catch (error) {
        showAlert(error.message, "error");
      } finally {
        setPending(button, false);
      }
    });
  });

  document.querySelectorAll("[data-export-report]").forEach((button) => {
    button.addEventListener("click", () => {
      exportReport(button.dataset.exportReport);
    });
  });
  document.querySelectorAll("[data-print-product-label]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        setPending(button, true, "Готовим");
        const result = await request("/products/barcode-labels", {
          method: "POST",
          body: JSON.stringify({ product_ids: [Number(button.dataset.printProductLabel)] }),
        });
        downloadText(`sklad-product-${button.dataset.printProductLabel}-label.zpl`, result.zpl);
        showAlert("Этикетка подготовлена");
      } catch (error) {
        showAlert(error.message, "error");
      } finally {
        setPending(button, false);
      }
    });
  });
  document.querySelectorAll("[data-print-batch-price-label]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        setPending(button, true, "Готовим");
        const result = await request(`/batches/${button.dataset.printBatchPriceLabel}/price-label?symbology=ean13`);
        downloadText(`sklad-batch-${button.dataset.printBatchPriceLabel}-price-label.zpl`, result.zpl);
        showAlert("Ценник подготовлен");
      } catch (error) {
        showAlert(error.message, "error");
      } finally {
        setPending(button, false);
      }
    });
  });
  document.querySelectorAll("[data-export-price-history]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        setPending(button, true, "Выгружаем");
        const result = await request(`/suppliers/${button.dataset.exportPriceHistory}/price-history?limit=500`);
        if (!result.items.length) {
          showAlert("История цен поставщика пока пустая", "error");
          return;
        }
        downloadCsv("sklad-supplier-price-history.csv", [
          { label: "Дата", value: (row) => dateText(row.recorded_at) },
          { label: "Поставщик", key: "supplier_name" },
          { label: "Товар", key: "product_name" },
          { label: "SKU", key: "sku" },
          { label: "Партия", value: (row) => row.lot || "" },
          { label: "Цена", key: "unit_price" },
          { label: "Источник", key: "source" },
        ], result.items);
        showAlert("История цен выгружена");
      } catch (error) {
        showAlert(error.message, "error");
      } finally {
        setPending(button, false);
      }
    });
  });
  document.querySelectorAll("[data-supplier-card]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        setPending(button, true, "Открываем");
        await showSupplierCard(button.dataset.supplierCard);
      } catch (error) {
        showAlert(error.message, "error");
      } finally {
        setPending(button, false);
      }
    });
  });
  document.querySelectorAll("[data-download-controlled-ledger]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        setPending(button, true, "Выгружаем");
        const query = warehouseFilterParam();
        const result = await request(`/controlled-substances/ledger/export${query ? `?${query}` : ""}`);
        downloadText(result.filename, result.csv, "text/csv;charset=utf-8");
        showAlert("Журнал ПКУ выгружен");
      } catch (error) {
        showAlert(error.message, "error");
      } finally {
        setPending(button, false);
      }
    });
  });
  document.querySelectorAll("[data-download-repack-form]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        setPending(button, true, "Выгружаем");
        const result = await request(`/stock-documents/${button.dataset.downloadRepackForm}/repack-print-form`);
        downloadText(`sklad-repack-document-${button.dataset.downloadRepackForm}.csv`, result.csv, "text/csv;charset=utf-8");
        showAlert("Печатная форма фасовки выгружена");
      } catch (error) {
        showAlert(error.message, "error");
      } finally {
        setPending(button, false);
      }
    });
  });
  document.querySelectorAll("[data-download-transfer-form]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        setPending(button, true, "Выгружаем");
        const result = await request(`/stock-documents/${button.dataset.downloadTransferForm}/transfer-print-form`);
        downloadText(`sklad-transfer-document-${button.dataset.downloadTransferForm}.csv`, result.csv, "text/csv;charset=utf-8");
        showAlert("Печатная форма перемещения выгружена");
      } catch (error) {
        showAlert(error.message, "error");
      } finally {
        setPending(button, false);
      }
    });
  });
  document.querySelectorAll("[data-download-quarantine-protocol]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        setPending(button, true, "Выгружаем");
        const result = await request(`/quarantine-reviews/${button.dataset.downloadQuarantineProtocol}/protocol`);
        downloadText(`sklad-quarantine-review-${button.dataset.downloadQuarantineProtocol}.csv`, result.csv, "text/csv;charset=utf-8");
        showAlert("Протокол карантинной проверки выгружен");
      } catch (error) {
        showAlert(error.message, "error");
      } finally {
        setPending(button, false);
      }
    });
  });
  document.querySelectorAll("[data-print-inventory]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        const session = selectedInventorySession();
        if (!session) return;
        setPending(button, true, "Готовим");
        const form = await request(`/inventory-sessions/${session.id}/print-form`);
        downloadText(`sklad-inventory-${session.id}-count-sheet.csv`, form.count_sheet_csv, "text/csv;charset=utf-8");
        showAlert("Печатная ведомость выгружена");
      } catch (error) {
        showAlert(error.message, "error");
      } finally {
        setPending(button, false);
      }
    });
  });
  document.querySelectorAll("[data-print-inventory-reconciliation]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        const session = selectedInventorySession();
        if (!session) return;
        setPending(button, true, "Готовим");
        const form = await request(`/inventory-sessions/${session.id}/print-form`);
        downloadText(`sklad-inventory-${session.id}-reconciliation.csv`, form.reconciliation_csv, "text/csv;charset=utf-8");
        showAlert("Сличительная ведомость выгружена");
      } catch (error) {
        showAlert(error.message, "error");
      } finally {
        setPending(button, false);
      }
    });
  });

  document.querySelectorAll("[data-approve-document]").forEach((button) => {
    button.addEventListener("click", async () => {
      if (button.disabled) return;
      try {
        const document = state.data.documents.find((entry) => Number(entry.id) === Number(button.dataset.approveDocument));
        const title = document ? documentTitle(document) : `Документ #${button.dataset.approveDocument}`;
        if (!(await confirmAction(`Утвердить ${title}? После утверждения документ можно провести.`, { confirmText: "Утвердить" }))) return;
        setPending(button, true, "Утверждаем");
        await mutate(`/stock-documents/${button.dataset.approveDocument}/approve`, {
          document_id: Number(button.dataset.approveDocument),
        });
      } catch (error) {
        showAlert(error.message, "error");
      } finally {
        setPending(button, false);
      }
    });
  });

  document.querySelectorAll("[data-edit-catalog]").forEach((button) => {
    button.addEventListener("click", () => {
      showCatalogEditModal(button.dataset.editCatalog, button.dataset.editId);
    });
  });

  document.querySelectorAll("[data-delete-catalog]").forEach((button) => {
    button.addEventListener("click", () => {
      deleteCatalogEntry(button.dataset.deleteCatalog, button.dataset.deleteId, button);
    });
  });

  document.querySelectorAll("[data-review-application]").forEach((button) => {
    button.addEventListener("click", async () => {
      if (button.disabled) return;
      const nextStatus = button.dataset.applicationNextStatus;
      const labels = { approved: "Одобрить", needs_changes: "Вернуть на доработку", rejected: "Отклонить", suspended: "Приостановить" };
      try {
        if (!(await confirmAction(`${labels[nextStatus] || nextStatus} заявку поставщика #${button.dataset.reviewApplication}?`, {
          confirmText: labels[nextStatus],
          tone: ["rejected", "suspended"].includes(nextStatus) ? "danger" : "normal",
        }))) return;
        setPending(button, true, "Сохраняем");
        await mutate(`/supplier-applications/${button.dataset.reviewApplication}/review`, {
          status: nextStatus,
          review_reason: nextStatus === "approved" ? null : "Решение принято менеджером склада",
        }, "PATCH");
      } catch (error) {
        showAlert(error.message, "error");
      } finally {
        setPending(button, false);
      }
    });
  });

  document.querySelectorAll("[data-withdraw-offer]").forEach((button) => {
    button.addEventListener("click", async () => {
      if (button.disabled) return;
      try {
        if (!(await confirmAction(`Отозвать коммерческое предложение #${button.dataset.withdrawOffer}?`, { confirmText: "Отозвать" }))) return;
        setPending(button, true, "Отзываем");
        await mutate(`/supplier/offers/${button.dataset.withdrawOffer}/withdraw`, { reason: "Отозвано поставщиком" }, "PATCH");
      } catch (error) {
        showAlert(error.message, "error");
      } finally {
        setPending(button, false);
      }
    });
  });

  document.querySelectorAll("[data-review-offer]").forEach((button) => {
    button.addEventListener("click", async () => {
      if (button.disabled) return;
      const nextStatus = button.dataset.offerNextStatus;
      const label = nextStatus === "accepted" ? "принять" : "отклонить";
      try {
        if (!(await confirmAction(`${label[0].toUpperCase()}${label.slice(1)} коммерческое предложение #${button.dataset.reviewOffer}?`, {
          confirmText: nextStatus === "accepted" ? "Принять" : "Отклонить",
        }))) return;
        setPending(button, true, "Сохраняем");
        await mutate(`/supplier-offers/${button.dataset.reviewOffer}/review`, {
          status: nextStatus,
          reason: nextStatus === "accepted" ? "Предложение принято" : "Предложение отклонено",
        }, "PATCH");
      } catch (error) {
        showAlert(error.message, "error");
      } finally {
        setPending(button, false);
      }
    });
  });

  bindSubmit("product-form", (payload) => mutate("/products", normalizeProductPayload(payload)));
  bindSubmit("category-form", (payload) => mutate("/categories", payload));
  bindSubmit("supplier-form", (payload) => mutate("/suppliers", normalizeSupplierPayload(payload)));
  document.querySelectorAll("[data-supplier-tab]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.ui.supplierTab = btn.dataset.supplierTab;
      render();
    });
  });

  document.querySelectorAll("[data-marketplace-filter-type]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const t = btn.dataset.marketplaceFilterType || null;
      state.ui.marketplaceType = t;
      state.ui.marketplaceCategory = null;
      const params = new URLSearchParams({ limit: "50" });
      if (t) params.set("type", t);
      state.data.marketplace = await loadOptional("Маркетплейс", request(`/marketplace?${params}`), { items: [], total: 0 });
      render();
    });
  });

  document.querySelectorAll("[data-marketplace-filter-category]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const cat = btn.dataset.marketplaceFilterCategory;
      state.ui.marketplaceCategory = cat;
      state.ui.marketplaceType = "service";
      const params = new URLSearchParams({ limit: "50", type: "service", service_category: cat });
      state.data.marketplace = await loadOptional("Маркетплейс", request(`/marketplace?${params}`), { items: [], total: 0 });
      render();
    });
  });

  document.querySelectorAll(".catalog-image-upload").forEach((input) => {
    input.addEventListener("change", async () => {
      const file = input.files?.[0];
      if (!file) return;
      const itemId = input.dataset.uploadImage;
      const formData = new FormData();
      formData.append("file", file);
      try {
        const authHeader = el("auth-token")?.value?.trim()
          ? { Authorization: `Bearer ${el("auth-token").value.trim()}` }
          : {};
        const res = await fetch(`${API}/supplier/catalog/${itemId}/image`, {
          method: "POST",
          headers: { "X-Actor-Id": currentActorId(), "X-Actor-Roles": currentRole(), ...authHeader },
          body: formData,
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({ message: "Ошибка загрузки" }));
          throw new Error(err?.detail?.message || err?.message || "Ошибка загрузки");
        }
        await loadAll();
      } catch (err) {
        showAlert(err.message, "error");
      }
    });
  });

  document.querySelectorAll("[data-delete-catalog]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const itemId = btn.dataset.deleteCatalog;
      if (!await confirmAction("Удалить это объявление?")) return;
      try {
        await removeResource(`/supplier/catalog/${itemId}`);
        await loadAll();
      } catch (err) {
        showAlert(err.message, "error");
      }
    });
  });

  bindSubmit("supplier-catalog-form", (payload) => mutate("/supplier/catalog", {
    type: payload.type || "product",
    title: payload.title,
    description: payload.description || null,
    price: payload.price ? Number(payload.price) : null,
    price_type: payload.price_type || "fixed",
    unit: payload.unit || null,
    service_category: payload.service_category || null,
  }));

  bindSubmit("supplier-application-form", (payload) => mutate("/supplier-application", {
    ...payload,
    bin: payload.bin || null,
    phone: payload.phone || null,
    email: payload.email || null,
    contact_person: payload.contact_person || null,
    address: payload.address || null,
    notes: payload.notes || null,
  }));
  bindSubmit("supplier-offer-form", (payload) => mutate(`/supplier/purchase-requests/${payload.purchase_request_id}/offers`, {
    purchase_request_id: Number(payload.purchase_request_id),
    unit_price: payload.unit_price,
    quantity: payload.quantity,
    delivery_date: payload.delivery_date || null,
    expires_at: payload.expires_at || null,
    comment: payload.comment || null,
  }));
  bindSubmit("warehouse-form", (payload) => mutate("/warehouses", {
    ...payload,
    department: payload.department || null,
    tetis_org_id: payload.tetis_org_id || null,
    external_tetis_id: payload.external_tetis_id || null,
    storage_zone: payload.storage_zone || null,
    capacity_limit: payload.capacity_limit ? Number(payload.capacity_limit) : null,
    storage_conditions: payload.storage_conditions || null,
    responsible_person: payload.responsible_person || null,
  }));
  bindSubmit("receipt-form", (payload) => mutate("/receipts", { ...payload, quarantine: true }));
  bindSubmit("receipt-doc-form", async (payload) => {
    const { supplier_id, warehouse_id } = payload;
    await mutate("/stock-documents/receipts", {
      supplier_id,
      warehouse_id,
      lines: receiptDocumentLinesPayload(),
    });
    resetDocumentLines("receipt");
  });
  bindSubmit("writeoff-doc-form", async (payload) => {
    const { warehouse_id } = payload;
    await mutate("/stock-documents/write-offs", {
      warehouse_id,
      lines: writeoffDocumentLinesPayload(),
    });
    resetDocumentLines("writeoff");
  }, () => `Создать черновик списания на ${state.documentForms.writeoff.lines.length} строк?`);
  bindSubmit("fefo-form", (payload) => mutate("/write-offs/fefo", payload), (payload) => `Списать ${payload.quantity} по ближайшему сроку годности? Остатки на выбранном складе уменьшатся.`);
  bindSubmit("writeoff-form", (payload) => mutate("/write-offs", payload), (payload) => operationPreview("writeoff", payload));
  bindSubmit("tablet-writeoff-form", (payload) => mutate("/write-offs", payload), (payload) => operationPreview("writeoff", payload));
  bindSubmit("transfer-form", (payload) => mutate("/transfers", payload), (payload) => operationPreview("transfer", payload));
  bindSubmit("repacking-form", (payload) => mutate("/stock-documents/repack", normalizeRepackingPayload(payload)), (payload) => repackingPreview(payload));
  bindSubmit("department-return-form", (payload) => mutate("/returns/from-department", payload), (payload) => operationPreview("department-return", payload));
  bindSubmit("supplier-return-form", (payload) => mutate("/returns/to-supplier", payload), (payload) => operationPreview("supplier-return", payload));
  bindSubmit("batch-status-form", (payload) => {
    const batchId = payload.batch_id;
    delete payload.batch_id;
    return mutate(`/batches/${batchId}/status`, payload, "PATCH");
  }, (payload) => `Изменить статус партии #${payload.batch_id} на “${humanStatus(payload.status)}”?`);
  bindSubmit("batch-recall-form", (payload) => {
    const batchId = payload.batch_id;
    return mutate(`/batches/${batchId}/recall`, {
      reason: payload.reason,
      source: payload.source || "manual",
      reference: payload.reference || null,
    });
  }, (payload) => recallPreview(payload));
  bindSubmit("reservation-form", (payload) => mutate("/reservations", payload), (payload) => `Зарезервировать партию #${payload.batch_id} в количестве ${payload.quantity}?`);
  bindSubmit("purchase-request-form", (payload) => mutate("/purchase-requests", payload), (payload) => `Создать заявку на закупку товара #${payload.product_id} в количестве ${payload.quantity}?`);
  bindSubmit("inventory-form", (payload) => {
    const prepared = {
      warehouse_id: payload.warehouse_id,
      category_ids: payload.category_id ? [Number(payload.category_id)] : [],
      responsible_ids: String(payload.responsible_ids || "")
        .split(",")
        .map((value) => value.trim())
        .filter(Boolean),
    };
    return mutate("/inventory-sessions", prepared);
  }, (payload) => `Начать инвентаризацию склада #${payload.warehouse_id} и заблокировать движения?`);
  bindSubmit("inventory-action-form", (payload) => mutate(`/inventory-sessions/${payload.session_id}/post`, { session_id: payload.session_id }), (payload) => inventoryCompletionPreview(payload.session_id));
  bindSubmit("sensor-device-form", (payload) => mutate("/sensor-devices", {
    ...payload,
    serial_number: payload.serial_number || null,
    min_temperature_c: payload.min_temperature_c || null,
    max_temperature_c: payload.max_temperature_c || null,
    min_humidity_percent: payload.min_humidity_percent || null,
    max_humidity_percent: payload.max_humidity_percent || null,
  }));
  bindSubmit("sensor-reading-form", (payload) => {
    if (!payload.temperature_c && !payload.humidity_percent) {
      throw new Error("Введите температуру или влажность.");
    }
    return mutate("/sensor-readings", {
      ...payload,
      temperature_c: payload.temperature_c || null,
      humidity_percent: payload.humidity_percent || null,
      raw_payload: payload.raw_payload || "ручной ввод",
    });
  }, (payload) => `Сохранить показание датчика #${payload.device_id}?`);

  bindBatchAwareForms();
  bindControlledWriteoffForms();

  document.querySelectorAll("[data-doc-header-field]").forEach((input) => {
    input.addEventListener("change", () => {
      state.documentForms[input.dataset.docLineKind][input.dataset.docHeaderField] = input.value;
    });
  });
  document.querySelectorAll("[data-doc-line-field]").forEach((input) => {
    input.addEventListener("input", () => {
      const index = Number(input.dataset.docLineIndex);
      const lines = state.documentForms[input.dataset.docLineKind].lines;
      lines[index][input.dataset.docLineField] = input.value;
    });
    input.addEventListener("change", () => {
      const index = Number(input.dataset.docLineIndex);
      const lines = state.documentForms[input.dataset.docLineKind].lines;
      lines[index][input.dataset.docLineField] = input.value;
    });
  });
  document.querySelectorAll("[data-doc-line-add]").forEach((button) => {
    button.addEventListener("click", () => {
      if (button.dataset.docLineAdd === "receipt") {
        state.documentForms.receipt.lines.push(newReceiptDocumentLine());
      }
      if (button.dataset.docLineAdd === "writeoff") {
        state.documentForms.writeoff.lines.push(newWriteoffDocumentLine());
      }
      render();
    });
  });
  document.querySelectorAll("[data-doc-line-remove]").forEach((button) => {
    button.addEventListener("click", () => {
      const kind = button.dataset.docLineRemove;
      const lines = state.documentForms[kind].lines;
      if (lines.length <= 1) return;
      lines.splice(Number(button.dataset.docLineIndex), 1);
      render();
    });
  });

  document.querySelectorAll("[data-release]").forEach((button) => {
    button.addEventListener("click", async () => {
      if (button.disabled) return;
      try {
        if (!(await confirmAction(`Снять бронь #${button.dataset.release}? Товар снова станет доступным для выдачи.`))) return;
        setPending(button, true);
        await mutate(`/reservations/${button.dataset.release}/release`, { reservation_id: Number(button.dataset.release) });
        await loadAll();
      } catch (error) { showAlert(error.message, "error"); }
      finally { setPending(button, false); }
    });
  });
  document.querySelectorAll("[data-use-reservation]").forEach((button) => {
    button.addEventListener("click", async () => {
      if (button.disabled) return;
      try {
        if (!(await confirmAction(`Использовать резерв #${button.dataset.useReservation}? Зарезервированное количество будет выдано со склада.`))) return;
        setPending(button, true, "Используем");
        await mutate(`/reservations/${button.dataset.useReservation}/use`, {
          reservation_id: Number(button.dataset.useReservation),
        });
        await loadAll();
      } catch (error) { showAlert(error.message, "error"); }
      finally { setPending(button, false); }
    });
  });
  document.querySelectorAll("[data-purchase-status]").forEach((button) => {
    button.addEventListener("click", async () => {
      if (button.disabled) return;
      const nextStatus = button.dataset.purchaseNextStatus;
      const statusText = nextStatus === "ordered" ? "пометить как заказанную" : "отменить";
      try {
        if (!(await confirmAction(`Заявку #${button.dataset.purchaseStatus} ${statusText}?`))) return;
        setPending(button, true);
        await request(`/purchase-requests/${button.dataset.purchaseStatus}`, {
          method: "PATCH",
          body: JSON.stringify({ status: nextStatus }),
        });
        await loadAll();
      } catch (error) { showAlert(error.message, "error"); }
      finally { setPending(button, false); }
    });
  });
  document.querySelectorAll("[data-quarantine-review]").forEach((button) => {
    button.addEventListener("click", async () => {
      if (button.disabled) return;
      const nextStatus = button.dataset.quarantineNextStatus;
      const label = nextStatus === "approved" ? "допустить партию"
        : nextStatus === "rejected" ? "забраковать партию"
        : "начать проверку";
      const decisionReason = nextStatus === "approved" ? "Документы и качество проверены"
        : nextStatus === "rejected" ? "Партия не прошла карантинную проверку"
        : null;
      try {
        if (!(await confirmAction(`Проверку #${button.dataset.quarantineReview}: ${label}?`, {
          tone: nextStatus === "rejected" ? "danger" : "normal",
          confirmText: nextStatus === "in_review" ? "Начать" : "Подтвердить",
        }))) return;
        setPending(button, true);
        await request(`/quarantine-reviews/${button.dataset.quarantineReview}`, {
          method: "PATCH",
          body: JSON.stringify({
            status: nextStatus,
            responsible_id: currentActorId() || null,
            decision_reason: decisionReason,
          }),
        });
        await loadAll();
      } catch (error) { showAlert(error.message, "error"); }
      finally { setPending(button, false); }
    });
  });
  document.querySelectorAll("[data-read]").forEach((button) => {
    button.addEventListener("click", async () => {
      if (button.disabled) return;
      try {
        setPending(button, true);
        await request(`/notifications/${button.dataset.read}/read`, {
          method: "PATCH",
          body: JSON.stringify({ is_read: true }),
        });
        await loadAll();
      } catch (error) { showAlert(error.message, "error"); }
      finally { setPending(button, false); }
    });
  });
  document.querySelectorAll("[data-post-document]").forEach((button) => {
    button.addEventListener("click", async () => {
      if (button.disabled) return;
      try {
        const document = state.data.documents.find((entry) => Number(entry.id) === Number(button.dataset.postDocument));
        const documentIssues = controlledWriteoffDocumentIssues(document);
        if (documentIssues.length) {
          showAlert(`Провести документ нельзя. ${controlledWriteoffMessage()}`, "error");
          return;
        }
        if (!(await confirmAction(`Провести документ #${button.dataset.postDocument}? После этого остатки на складе изменятся.`))) return;
        setPending(button, true);
        await mutate(`/stock-documents/${button.dataset.postDocument}/post`, {
          document_id: Number(button.dataset.postDocument),
        });
        await loadAll();
      } catch (error) { showAlert(error.message, "error"); }
      finally { setPending(button, false); }
    });
  });
  document.querySelectorAll("[data-cancel-document]").forEach((button) => {
    button.addEventListener("click", async () => {
      if (button.disabled) return;
      try {
        if (!(await confirmAction(`Отменить черновик документа #${button.dataset.cancelDocument}? Остатки на складе не изменятся.`))) return;
        setPending(button, true);
        await mutate(`/stock-documents/${button.dataset.cancelDocument}/cancel`, {
          document_id: Number(button.dataset.cancelDocument),
        });
        await loadAll();
      } catch (error) { showAlert(error.message, "error"); }
      finally { setPending(button, false); }
    });
  });
  document.querySelectorAll("[data-lock-warehouse]").forEach((button) => {
    button.addEventListener("click", async () => {
      if (button.disabled) return;
      const locked = button.dataset.lockValue === "true";
      try {
        if (!(await confirmAction(`${locked ? "Заблокировать складские операции" : "Разблокировать складские операции"} для склада #${button.dataset.lockWarehouse}?`))) return;
        setPending(button, true);
        await mutate(`/warehouses/${button.dataset.lockWarehouse}/inventory-lock`, { inventory_lock: locked }, "PATCH");
        await loadAll();
      } catch (error) { showAlert(error.message, "error"); }
      finally { setPending(button, false); }
    });
  });
  document.querySelectorAll("[data-save-inventory-line]").forEach((button) => {
    button.addEventListener("click", async () => {
      if (button.disabled) return;
      const lineId = button.dataset.saveInventoryLine;
      const sessionId = button.dataset.session;
      const input = document.querySelector(`[data-actual-line="${lineId}"]`);
      try {
        if (!input.value) {
          showAlert("Введите фактическое количество по строке инвентаризации", "error");
          input.focus();
          return;
        }
        setPending(button, true);
        await request(`/inventory-sessions/${sessionId}/lines/${lineId}`, {
          method: "PATCH",
          body: JSON.stringify({ actual_quantity: String(input.value) }),
        });
        await loadAll();
      } catch (error) { showAlert(error.message, "error"); }
      finally { setPending(button, false); }
    });
  });
  document.querySelectorAll("[data-action]").forEach((button) => {
    button.addEventListener("click", async () => {
      if (button.disabled) return;
      try {
        setPending(button, true);
        if (button.dataset.action === "reload") await loadAll();
        if (button.dataset.action === "generate-low-stock") {
          const wf = warehouseFilterParam();
          await request(`/notifications/generate-low-stock${wf ? `?${wf}` : ""}`, { method: "POST" });
          await loadAll();
        }
        if (button.dataset.action === "generate-expiry") {
          const wf = warehouseFilterParam();
          await request(`/notifications/generate-expiry${wf ? `?${wf}&days=30` : "?days=30"}`, { method: "POST" });
          await loadAll();
        }
        if (button.dataset.action === "generate-quarantine") {
          const wf = warehouseFilterParam();
          await request(`/notifications/generate-quarantine${wf ? `?${wf}&days=3` : "?days=3"}`, { method: "POST" });
          await loadAll();
        }
        if (button.dataset.action === "generate-purchase-requests") {
          const wf = warehouseFilterParam();
          await mutate(`/purchase-requests/generate-auto${wf ? `?${wf}` : ""}`, {
            source: "abc_xyz",
            analytics_days: state.data.analytics.analysis_days || 90,
          });
          await loadAll();
        }
        if (button.dataset.action === "save-abc-xyz-run") {
          const wf = warehouseFilterParam();
          await request(`/analytics/abc-xyz/runs${wf ? `?${wf}&days=90` : "?days=90"}`, {
            method: "POST",
            body: JSON.stringify({}),
          });
          await loadAll();
        }
        if (button.dataset.action === "expire-reservations") {
          setPending(button, false);
          if (!(await confirmAction("Снять всю просроченную бронь в выбранном складе? Товары снова станут доступными."))) return;
          setPending(button, true);
          const wf = warehouseFilterParam();
          await mutate(`/reservations/expire${wf ? `?${wf}` : ""}`, {});
          await loadAll();
        }
        if (button.dataset.action === "cancel-inventory") {
          const formNode = document.getElementById("inventory-action-form");
          const payload = collect(formNode);
          setPending(button, false);
          if (!(await confirmAction(`Отменить инвентаризацию #${payload.session_id}? Складские операции снова будут доступны.`))) return;
          setPending(button, true);
          await mutate(`/inventory-sessions/${payload.session_id}/cancel`, payload);
          await loadAll();
        }
      } catch (error) { showAlert(error.message, "error"); }
      finally { setPending(button, false); }
    });
  });
}

["actor-id", "actor-role", "actor-warehouses", "warehouse-filter", "auth-token"].forEach((id) => {
  el(id).addEventListener("change", loadAll);
});
el("refresh-button").addEventListener("click", loadAll);
el("global-search").addEventListener("input", (event) => {
  state.ui.search = event.target.value;
  render();
});
el("density-button").addEventListener("click", () => {
  state.ui.density = state.ui.density === "compact" ? "comfortable" : "compact";
  applyDensity();
});
el("supplier-mode-toggle")?.addEventListener("click", async () => {
  await toggleSupplierMode();
  const btn = el("supplier-mode-toggle");
  if (btn) btn.textContent = state.ui.supplierMode ? "Режим: Сотрудник склада" : "Режим: Поставщик";
});
el("become-supplier-button")?.addEventListener("click", () => {
  state.view = "supplier-portal";
  render();
});

render();
loadAll();
