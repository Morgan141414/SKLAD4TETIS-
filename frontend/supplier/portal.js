const API = "/api/v1";

const state = {
  token: localStorage.getItem("supplier_portal_token") || "",
  supplierId: null,
  fullName: "",
  view: "auctions",
  data: { auctions: [], myBids: {}, priceHistory: [], shipments: [], reviews: [] },
};

function decodeJwt(token) {
  try {
    const payload = token.split(".")[1];
    return JSON.parse(atob(payload.replace(/-/g, "+").replace(/_/g, "/")));
  } catch (_) {
    return null;
  }
}

function el(id) { return document.getElementById(id); }

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

async function api(path, options = {}) {
  const resp = await fetch(`${API}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${state.token}`,
      ...(options.headers || {}),
    },
  });
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const message = body?.detail?.message || body?.detail || "Ошибка запроса";
    throw new Error(message);
  }
  return body;
}

async function login(email, password) {
  const resp = await fetch(`${API}/auth/supplier-login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new Error(body?.detail?.message || body?.detail || "Неверный email или пароль");
  }
  state.token = body.access_token;
  localStorage.setItem("supplier_portal_token", state.token);
  const claims = decodeJwt(state.token);
  state.supplierId = claims?.supplier_id ?? null;
  state.fullName = claims?.full_name || "";
}

function logout() {
  state.token = "";
  localStorage.removeItem("supplier_portal_token");
  el("login-screen").style.display = "flex";
  el("app-root").style.display = "none";
}

const navItems = [
  ["auctions", "Аукционы"],
  ["my-bids", "Мои ставки"],
  ["price-history", "История цен"],
  ["shipments", "Мои поставки"],
  ["reviews", "Отзывы о нас"],
];

function renderNav() {
  el("nav").innerHTML = navItems.map(([id, label]) => `
    <button class="${state.view === id ? "active" : ""}" data-view="${id}">${escapeHtml(label)}</button>
  `).join("");
  el("nav").querySelectorAll("button").forEach((button) => {
    button.addEventListener("click", () => {
      state.view = button.dataset.view;
      document.querySelector(".sidebar")?.classList.remove("nav-open");
      render();
    });
  });
}

function fmtMoney(value) {
  return Number(value || 0).toLocaleString("ru-RU");
}

function renderAuctions() {
  const auctions = state.data.auctions;
  if (!auctions.length) return `<p style="color:var(--muted)">Открытых аукционов пока нет.</p>`;
  return auctions.map((a) => `
    <div class="panel" style="margin-bottom:12px">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:6px">
        <strong>${escapeHtml(a.title)}</strong>
        <span class="badge-chip" style="background:${a.status === "active" ? "var(--ok-bg)" : "var(--bg)"};border:1px solid ${a.status === "active" ? "var(--ok-border)" : "var(--line)"};color:${a.status === "active" ? "var(--ok)" : "var(--muted)"}">${escapeHtml(a.status)}</span>
      </div>
      <div style="color:var(--muted);font-size:.85rem;margin-bottom:8px">${escapeHtml(a.product_name || "")} · ${a.quantity} ${escapeHtml(a.unit)}</div>
      <div style="font-size:1.2rem;font-weight:700;margin-bottom:8px">${fmtMoney(a.current_price)} тг</div>
      ${a.status === "active" ? `
        <div style="display:flex;gap:8px">
          <input type="number" data-bid-input="${a.id}" placeholder="Ваша ставка < ${fmtMoney(a.current_price)}" style="max-width:220px" />
          <button class="primary" data-place-bid="${a.id}">Сделать ставку</button>
        </div>
      ` : ""}
    </div>
  `).join("");
}

function renderMyBids() {
  const entries = Object.entries(state.data.myBids);
  if (!entries.length) return `<p style="color:var(--muted)">Загрузите раздел «Аукционы», чтобы увидеть свои ставки по каждому.</p>`;
  return entries.map(([auctionId, bids]) => `
    <div class="panel" style="margin-bottom:12px">
      <strong>Аукцион #${escapeHtml(auctionId)}</strong>
      <div class="table-wrap" style="margin-top:8px">
        <table>
          <tr><th>Дата</th><th>Ваша ставка</th></tr>
          ${bids.map((b) => `<tr><td>${escapeHtml(String(b.created_at).slice(0, 16))}</td><td>${fmtMoney(b.bid_amount)} тг</td></tr>`).join("") || '<tr><td colspan="2" style="color:var(--muted)">Ставок пока нет</td></tr>'}
        </table>
      </div>
    </div>
  `).join("");
}

function renderPriceHistory() {
  const rows = state.data.priceHistory;
  return `
    <div class="table-wrap">
      <table>
        <tr><th>Дата</th><th>Товар</th><th>Партия</th><th>Цена</th></tr>
        ${rows.map((r) => `<tr><td>${escapeHtml(String(r.recorded_at).slice(0, 10))}</td><td>${escapeHtml(r.product_name)}</td><td>${escapeHtml(r.lot || "—")}</td><td>${fmtMoney(r.unit_price)}</td></tr>`).join("") || '<tr><td colspan="4" style="color:var(--muted)">Истории цен пока нет</td></tr>'}
      </table>
    </div>
  `;
}

function renderShipments() {
  const rows = state.data.shipments;
  const statusLabels = { in_transit: "В пути", delivered: "Доставлено", delayed: "Задержка", cancelled: "Отменено" };
  return `
    <div class="table-wrap">
      <table>
        <tr><th>Номер</th><th>Статус</th><th>Откуда</th><th>Сейчас</th><th>Ожидается</th></tr>
        ${rows.map((s) => `<tr><td>${escapeHtml(s.reference || "#" + s.id)}</td><td>${escapeHtml(statusLabels[s.status] || s.status)}</td><td>${escapeHtml(s.origin_city || "—")}</td><td>${escapeHtml(s.current_city || "—")}</td><td>${escapeHtml(s.estimated_arrival || "—")}</td></tr>`).join("") || '<tr><td colspan="5" style="color:var(--muted)">Поставок пока нет</td></tr>'}
      </table>
    </div>
  `;
}

function renderReviews() {
  const rows = state.data.reviews;
  if (!rows.length) return `<p style="color:var(--muted)">Отзывов пока нет.</p>`;
  return rows.map((r) => `
    <div class="panel" style="margin-bottom:10px">
      <span style="color:var(--warning)">${"★".repeat(r.rating)}${"☆".repeat(5 - r.rating)}</span>
      <span style="font-size:.78rem;color:var(--muted);margin-left:8px">${escapeHtml(String(r.created_at).slice(0, 10))} · ${escapeHtml(r.status)}</span>
      ${r.comment ? `<div style="margin-top:6px">${escapeHtml(r.comment)}</div>` : ""}
    </div>
  `).join("");
}

const titles = {
  auctions: "Аукционы",
  "my-bids": "Мои ставки",
  "price-history": "История цен",
  shipments: "Мои поставки",
  reviews: "Отзывы о нас",
};

function render() {
  renderNav();
  const renderers = {
    auctions: renderAuctions,
    "my-bids": renderMyBids,
    "price-history": renderPriceHistory,
    shipments: renderShipments,
    reviews: renderReviews,
  };
  el("content").innerHTML = `<h1>${titles[state.view]}</h1>${renderers[state.view]()}`;
  el("content").querySelectorAll("[data-place-bid]").forEach((button) => {
    button.addEventListener("click", () => placeBid(button.dataset.placeBid));
  });
}

async function placeBid(auctionId) {
  const input = document.querySelector(`[data-bid-input="${auctionId}"]`);
  const amount = Number(input?.value);
  if (!amount || amount <= 0) return;
  try {
    await api(`/auctions/${auctionId}/bids`, {
      method: "POST",
      body: JSON.stringify({ supplier_id: state.supplierId, bid_amount: amount }),
    });
    await loadAuctions();
    await loadMyBids(auctionId);
    render();
  } catch (err) {
    alert(err.message);
  }
}

async function loadAuctions() {
  const data = await api("/auctions");
  state.data.auctions = data.items || data || [];
}

async function loadMyBids(auctionId) {
  const bids = await api(`/auctions/${auctionId}/bids`);
  state.data.myBids[auctionId] = bids;
}

async function loadAll() {
  state.data.auctions = (await api("/auctions").catch(() => ({ items: [] }))).items || [];
  for (const a of state.data.auctions) {
    state.data.myBids[a.id] = await api(`/auctions/${a.id}/bids`).catch(() => []);
  }
  state.data.priceHistory = (await api(`/suppliers/${state.supplierId}/price-history?limit=50`).catch(() => ({ items: [] }))).items || [];
  state.data.shipments = (await api(`/shipments?supplier_id=${state.supplierId}`).catch(() => ({ items: [] }))).items || [];
  state.data.reviews = await api(`/suppliers/${state.supplierId}/reviews`).catch(() => []);
}

async function boot() {
  if (!state.token) return;
  const claims = decodeJwt(state.token);
  if (!claims || claims.exp * 1000 < Date.now()) {
    logout();
    return;
  }
  state.supplierId = claims.supplier_id;
  state.fullName = claims.full_name || "";
  el("supplier-name-label").textContent = state.fullName;
  el("login-screen").style.display = "none";
  el("app-root").style.display = "grid";
  await loadAll();
  render();
}

el("login-submit").addEventListener("click", async () => {
  const email = el("login-email").value.trim();
  const password = el("login-password").value;
  const errorBox = el("login-error");
  errorBox.style.display = "none";
  try {
    await login(email, password);
    await boot();
  } catch (err) {
    errorBox.textContent = err.message;
    errorBox.style.display = "block";
  }
});

el("login-password").addEventListener("keydown", (e) => {
  if (e.key === "Enter") el("login-submit").click();
});

el("logout-button").addEventListener("click", logout);

el("nav-toggle").addEventListener("click", () => {
  document.querySelector(".sidebar")?.classList.toggle("nav-open");
});

boot();
