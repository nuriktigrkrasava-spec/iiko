# Price Search Mini App + Editor add/remove — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `📊 Цены` subtab in Mini App «Накладные» with nomenclature search + best-price-per-supplier card (sourced from iiko invoice history + local `bot_invoices`), and add 🗑/➕ buttons to the invoice editor for deleting/adding line items.

**Architecture:** Pure additive change. One new GET endpoint `/api/price-stats/{org_id}` in `api.py` that calls existing `IikoClient.get_invoices` (iiko.py:187), aggregates by supplier, blends with rows from existing `database.get_price_history`. Frontend adds a subview switcher inside the existing `expense-tab=invoices` panel + scoped JS, plus two tiny editor patches. No DB schema changes. No new dependencies. No modifications to existing endpoints, callbacks, or `iiko.py` methods.

**Tech Stack:** FastAPI / SQLite (read-only here) / Anthropic SDK (untouched) / Telegram Bot API (untouched) / vanilla JS + existing `apiGet` helpers.

**No test framework:** the project has no pytest. Verification via `python -c "..."` smoke scripts for backend + manual Mini App smoke test for frontend. No new dependencies added.

**Spec:** `docs/superpowers/specs/2026-05-13-price-search-and-editor-add-remove-design.md`.

**Pre-flight:** Confirm production is back up (commits `085bf0d`..`008afec` deployed, no `ImportError` in Render logs) before starting Task 1. If prod is in crash-loop, fix that first (push `database.py` from the WIP commit `8791234` baseline forward).

---

## File Structure

| File | Responsibility | Change type |
|---|---|---|
| `api.py` | FastAPI app + Telegram webhook + endpoints | Add: 1 new GET endpoint `/api/price-stats/{org_id}` + small in-module cache dict |
| `index.html` | Mini App SPA — markup + state + JS | Add: subview toggle pills, price-search panel markup, 5 new JS functions, 2 small edits to `ieRenderItems` and `ieCloseModal` |
| `database.py` | DB layer | No changes (we already have `get_price_history` from previous feature) |
| `iiko.py` | iiko API client | No changes (we reuse existing `get_invoices`) |

---

## Task 1: Backend endpoint `/api/price-stats/{org_id}`

**Files:**
- Modify: `api.py` — add new endpoint right after the existing `/api/invoices/{org_id}` handler (around line 938). Also add a tiny module-level cache dict near other in-file caches.

- [ ] **Step 1: Locate insertion point**

Run: `grep -n "^@app.get(\"/api/invoices/{org_id}\")\|^async def invoices(" /path/to/workspace/iiiko/api.py`
Expected: 2 lines (decorator + handler) around line 938-940. New endpoint goes right after the `invoices()` handler closes (look for the matching `return` and blank line).

Also note the path of imports — find `from iiko import` to confirm the import structure of `get_client`. Run:
`grep -n "^from iiko" /path/to/workspace/iiiko/api.py`

- [ ] **Step 2: Add the cache dict + endpoint**

Insert right after the existing `invoices()` function ends in `api.py`:

```python
# ============ PRICE STATS (Mini App «📊 Цены») ============
# Cache of iiko invoice exports per (org_id, days) → (timestamp, raw_payload).
# TTL 1 hour. Avoids hitting iiko on every nomenclature pick.
_price_stats_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_PRICE_STATS_TTL_SECONDS = 3600


@app.get("/api/price-stats/{org_id}")
async def price_stats(org_id: str, product_id: str = Query(..., min_length=1),
                       days: int = Query(180, ge=1, le=365),
                       user: Dict = Depends(get_current_user)):
    """Агрегат цен товара по поставщикам за `days` дней.
    Источник: iiko export invoice_incoming + локальные bot_invoices.
    """
    import time
    if _is_demo_user(user) or org_id == "demo-org-1":
        return {"product": {"id": product_id, "name": "—", "unit": ""},
                "best": None, "suppliers": [], "stats": {"purchases": 0, "days": days}}

    real_org = _get_org_id(org_id, user)
    info = _get_restaurant_info(real_org, user)
    client = get_client(info["api_login"], info.get("iiko_server"), info.get("api_password"))

    date_to = datetime.now().strftime("%Y-%m-%d")
    date_from = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    cache_key = f"{real_org}|{days}"
    now_ts = time.time()
    cached = _price_stats_cache.get(cache_key)
    if cached and (now_ts - cached[0]) < _PRICE_STATS_TTL_SECONDS:
        raw = cached[1]
    else:
        try:
            raw = await client.get_invoices([_olap_dept(real_org, info)], date_from, date_to)
            _price_stats_cache[cache_key] = (now_ts, raw)
        except Exception as e:
            logger.warning(f"[price_stats] iiko fetch failed: {e}")
            raw = {"invoiceIncomings": []}

    # raw["invoiceIncomings"] — список накладных, у каждой items[] с productId, amount, price, sum
    invoices_list = raw.get("invoiceIncomings", []) if isinstance(raw, dict) else []

    # Поиск имени и unit товара по первому встреченному matched item
    product_name = "—"
    product_unit = ""

    # Группируем по supplier — для каждого минимум по цене
    by_supplier: Dict[str, Dict[str, Any]] = {}
    purchases_count = 0
    for inv in invoices_list:
        supplier_name = inv.get("supplier") or inv.get("supplierName") or "—"
        supplier_id = inv.get("supplierId") or supplier_name
        inv_date = (inv.get("dateIncoming") or inv.get("documentDate") or "")[:10]
        for it in (inv.get("items") or []):
            if (it.get("productId") or it.get("product")) != product_id:
                continue
            amount = float(it.get("amount") or 0)
            if amount <= 0:
                continue
            price = it.get("price")
            if price is None:
                total_sum = float(it.get("sum") or 0)
                price = total_sum / amount if amount else 0
            price = float(price)
            if price <= 0:
                continue
            unit = it.get("amountUnit") or it.get("unit") or ""
            purchases_count += 1
            if not product_name or product_name == "—":
                product_name = it.get("productName") or it.get("name") or product_name
                product_unit = unit
            cur = by_supplier.get(supplier_id)
            if cur is None or price < cur["price_per_unit"]:
                by_supplier[supplier_id] = {
                    "supplier_id": supplier_id,
                    "supplier_name": supplier_name,
                    "price_per_unit": price,
                    "date": inv_date,
                    "unit": unit,
                }

    # Догружаем локальные bot_invoices с тем же iiko_product_id
    try:
        local = get_price_history(user.get("id") or 0, days=days)
    except Exception:
        local = []
    for h in local:
        if h["key"] != product_id:
            continue
        sid = f"local:{h['supplier']}"
        purchases_count += 1
        cur = by_supplier.get(sid)
        if cur is None or h["price_per_unit"] < cur["price_per_unit"]:
            by_supplier[sid] = {
                "supplier_id": sid,
                "supplier_name": h["supplier"],
                "price_per_unit": h["price_per_unit"],
                "date": h["date"],
                "unit": h["unit"] or product_unit,
            }

    suppliers = sorted(by_supplier.values(), key=lambda r: r["price_per_unit"])
    best = suppliers[0] if suppliers else None
    if best:
        for s in suppliers:
            s["delta_pct"] = ((s["price_per_unit"] - best["price_per_unit"]) /
                              best["price_per_unit"] * 100) if best["price_per_unit"] > 0 else 0.0

    return {
        "product": {"id": product_id, "name": product_name, "unit": product_unit},
        "best": best,
        "suppliers": suppliers,
        "stats": {"purchases": purchases_count, "days": days},
    }
```

If any of these imports are missing at the top of `api.py`, add them:
- `from typing import Tuple` (likely already present, check)
- `from fastapi import Query` (likely already present)
- `from datetime import datetime, timedelta` (almost certainly already present)

Run: `grep -n "^from typing\|^from datetime\|^from fastapi" /path/to/workspace/iiiko/api.py | head -5`
If `Tuple` is missing from `typing` imports, add it.

- [ ] **Step 3: Verify api.py parses**

Run: `python -c "import ast; ast.parse(open('/path/to/workspace/iiiko/api.py').read()); print('OK')"`
Expected output: `OK`.

- [ ] **Step 4: Smoke test endpoint registration**

Run:
```bash
cd /path/to/workspace/iiiko && python -c "
import sys; sys.path.insert(0, '.')
from api import app
routes = [(r.path, r.methods) for r in app.routes if hasattr(r, 'path')]
matches = [r for r in routes if '/api/price-stats' in r[0]]
assert matches, f'price-stats endpoint not registered. Got: {routes[-10:]}'
print(f'OK — registered: {matches}')"
```
Expected output: contains `('/api/price-stats/{org_id}', {'GET'})` or similar.

- [ ] **Step 5: Smoke test demo path (no real iiko call)**

Run:
```bash
cd /path/to/workspace/iiiko && python -c "
import sys; sys.path.insert(0, '.')
from fastapi.testclient import TestClient
from api import app
client = TestClient(app)
# We can't easily forge initData here, so this just confirms the route exists and demands auth
r = client.get('/api/price-stats/demo-org-1?product_id=test')
# Without proper auth headers, we expect 401/403/422 — NOT 404.
assert r.status_code != 404, f'route not registered: {r.status_code} {r.text[:200]}'
print(f'OK — route exists, returned {r.status_code} (expected non-404 for unauth request)')"
```
Expected output: `OK — route exists, returned <some non-404 code>`.

If TestClient is not available (`ImportError`), skip this step — Step 4 already proved registration.

- [ ] **Step 6: Commit**

```bash
git add api.py
git commit -m "feat(price-stats): GET /api/price-stats/{org_id} for Mini App price search

Aggregates iiko invoice_incoming history (last N days, default 180) by
supplier for a given productId. Best price + per-supplier minimums +
delta_pct vs best. Blends in local bot_invoices rows matched by
iiko_product_id. In-endpoint cache of iiko exports per (org, days)
with 1-hour TTL avoids re-hitting iiko on subsequent product picks.

No changes to existing endpoints or iiko.py — reuses IikoClient.get_invoices."
```

---

## Task 2: Frontend — subview toggle inside «Накладные»

**Files:**
- Modify: `index.html` — add CSS for new pills + price panel; add HTML markup inside the invoices subtab; add `switchInvoiceSubview` JS function.

- [ ] **Step 1: Locate the invoices subtab in index.html**

Run: `grep -n "subtab.*invoices\|invoice-list\|invoices-list" /path/to/workspace/iiiko/index.html | head -10`
Expected: shows where `id="invoices-list"` is rendered (around line ~1100-1200). The whole subtab markup is around that area.

Run: `grep -n 'data-subtab="invoices"\|state.expenseTab' /path/to/workspace/iiiko/index.html | head -10`
Expected: shows the subtab container element. Identify the `<div>` that wraps the existing list — we'll add markup BEFORE it.

- [ ] **Step 2: Add CSS for subview toggle and price-search panel**

Find a CSS section near the existing `.ie-` rules (around line 425) and append:

```css
/* Invoices → 📊 Цены подвкладка */
.inv-subview { display:flex; gap:8px; padding:8px 16px 12px; }
.inv-subview-pill { padding:7px 14px; border-radius:18px; border:1px solid var(--card-border); background:var(--bg-card); color:var(--text-secondary); font-size:13px; font-weight:500; cursor:pointer; }
.inv-subview-pill.active { background:var(--accent); color:var(--bg); border-color:var(--accent); font-weight:600; }

#price-search-panel { padding:0 16px 16px; }
.ps-input { width:100%; padding:12px 14px; border:1px solid var(--card-border); border-radius:12px; font-size:15px; outline:none; background:var(--bg-secondary); color:var(--text); font-family:inherit; box-sizing:border-box; }
.ps-results { margin-top:6px; max-height:240px; overflow-y:auto; border:1px solid var(--card-border); border-radius:10px; background:var(--bg-secondary); display:none; }
.ps-results.active { display:block; }
.ps-result { padding:10px 12px; border-bottom:1px solid var(--divider); cursor:pointer; }
.ps-result:last-child { border-bottom:none; }
.ps-result-name { font-size:14px; color:var(--text); }
.ps-result-meta { font-size:11px; color:var(--text-secondary); margin-top:2px; }
.ps-card { margin-top:14px; background:var(--bg-card); border:1px solid var(--card-border); border-radius:14px; padding:16px; }
.ps-card-title { font-size:16px; font-weight:700; color:var(--text); margin-bottom:10px; }
.ps-best { background:var(--bg-secondary); border-radius:10px; padding:12px; margin-bottom:14px; }
.ps-best-label { font-size:12px; color:var(--text-secondary); margin-bottom:4px; }
.ps-best-price { font-size:22px; font-weight:700; color:var(--green, #2bb673); }
.ps-best-supplier { font-size:13px; color:var(--text); margin-top:4px; }
.ps-best-date { font-size:11px; color:var(--text-secondary); margin-top:2px; }
.ps-suppliers-title { font-size:13px; color:var(--text-secondary); margin-bottom:8px; }
.ps-supplier-row { display:flex; justify-content:space-between; align-items:flex-start; padding:8px 0; border-bottom:1px solid var(--divider); }
.ps-supplier-row:last-child { border-bottom:none; }
.ps-supplier-name { font-size:14px; color:var(--text); flex:1; min-width:0; }
.ps-supplier-date { font-size:11px; color:var(--text-secondary); margin-top:2px; }
.ps-supplier-price { font-size:14px; font-weight:600; color:var(--text); white-space:nowrap; padding-left:8px; }
.ps-supplier-delta { font-size:11px; color:var(--text-secondary); margin-top:2px; text-align:right; }
.ps-supplier-delta.warn { color:var(--red, #e25c5c); }
.ps-empty { padding:20px; text-align:center; color:var(--text-secondary); font-size:13px; }
.ps-stats { margin-top:10px; font-size:11px; color:var(--text-secondary); text-align:center; }
```

- [ ] **Step 3: Add HTML markup inside the invoices subtab**

Find the existing `<div id="invoices-list">...</div>` (the current rendering target). Wrap surrounding logic so we have a switch.

Specifically, locate the parent that has the existing invoices list. Right BEFORE that wrapper, insert:

```html
<div class="inv-subview">
  <button class="inv-subview-pill active" id="inv-pill-list" onclick="switchInvoiceSubview('list')">📋 Список</button>
  <button class="inv-subview-pill" id="inv-pill-prices" onclick="switchInvoiceSubview('prices')">📊 Цены</button>
</div>

<div id="price-search-panel" style="display:none;">
  <input class="ps-input" id="ps-input" type="text" placeholder="🔍 Поиск товара по номенклатуре..." oninput="psSearchProducts()">
  <div class="ps-results" id="ps-results"></div>
  <div id="ps-card-host"></div>
</div>
```

Wrap the existing invoice list rendering area with `<div id="invoices-list-wrap">...</div>` so we can toggle it. If the existing parent already serves as a single switchable region, just add an `id` to it: locate the `<div>` that contains `<div id="invoices-list"></div>` and ensure it (or the parent) has `id="invoices-list-wrap"`.

Use the Edit tool with sufficient context to make the change unambiguous. If the existing markup is:
```html
<div id="invoices-list"></div>
```
without a wrapping div, wrap it:
```html
<div id="invoices-list-wrap">
  <div id="invoices-list"></div>
</div>
```

- [ ] **Step 4: Add `switchInvoiceSubview` JS**

In the JS section (find by `grep -n "function switchTab\|function loadExpenses" /path/to/workspace/iiiko/index.html`), append near other invoice-tab functions:

```javascript
// Invoices subview (📋 Список / 📊 Цены)
state.invoiceSubview = state.invoiceSubview || 'list';
state.priceSearch = state.priceSearch || { query: '', timer: null };

function switchInvoiceSubview(view) {
  state.invoiceSubview = view;
  document.getElementById('inv-pill-list').classList.toggle('active', view === 'list');
  document.getElementById('inv-pill-prices').classList.toggle('active', view === 'prices');
  document.getElementById('invoices-list-wrap').style.display = (view === 'list') ? '' : 'none';
  document.getElementById('price-search-panel').style.display = (view === 'prices') ? '' : 'none';
}
```

- [ ] **Step 5: Verify HTML is still valid (basic check)**

Run: `python -c "
import re, sys
html = open('/path/to/workspace/iiiko/index.html').read()
# Sanity: balanced div tags (approximation, not full XML parser)
opens = len(re.findall(r'<div\b', html))
closes = len(re.findall(r'</div>', html))
assert abs(opens - closes) < 3, f'div imbalance: {opens} open vs {closes} close'
assert 'switchInvoiceSubview' in html, 'switchInvoiceSubview not present'
assert 'inv-subview-pill' in html, 'pill markup not present'
print('OK')
"`
Expected output: `OK`.

- [ ] **Step 6: Commit**

```bash
git add index.html
git commit -m "feat(miniapp): add 📋 Список / 📊 Цены subview toggle in invoices tab

Adds CSS + HTML markup + switchInvoiceSubview JS for a new subview
inside Расходы → Накладные. List view is unchanged. Prices view shows
an empty placeholder for now — price search behavior added in next task."
```

---

## Task 3: Frontend — price search behavior + results rendering

**Files:**
- Modify: `index.html` — add 3 JS functions: `psSearchProducts` (debounced nomenclature search), `psSelectProduct` (fetch stats + render card), `psRenderCard` (HTML).

- [ ] **Step 1: Add the JS functions**

In the same JS area as `switchInvoiceSubview`, append:

```javascript
function psSearchProducts() {
  clearTimeout(state.priceSearch.timer);
  const q = document.getElementById('ps-input').value.trim();
  state.priceSearch.query = q;
  const resultsEl = document.getElementById('ps-results');
  if (q.length < 2) {
    resultsEl.classList.remove('active');
    resultsEl.innerHTML = '';
    return;
  }
  state.priceSearch.timer = setTimeout(async () => {
    const orgId = state.restaurant?.organization_id;
    if (!orgId) return;
    try {
      const data = await apiGet(`/api/nomenclature/search/${orgId}?q=${encodeURIComponent(q)}&limit=15`);
      const products = data.products || [];
      if (!products.length) {
        resultsEl.innerHTML = '<div class="ps-empty">Ничего не найдено</div>';
      } else {
        resultsEl.innerHTML = products.map(p => `
          <div class="ps-result" onclick="psSelectProduct('${(p.id || '').replace(/'/g, "\\'")}', \`${(p.name || '').replace(/`/g, '\\`')}\`, '${(p.unit || '').replace(/'/g, "\\'")}')">
            <div class="ps-result-name">${escapeHtml(p.name || '—')}</div>
            <div class="ps-result-meta">${escapeHtml(p.unit || '')} ${p.code ? '· ' + escapeHtml(p.code) : ''}</div>
          </div>
        `).join('');
      }
      resultsEl.classList.add('active');
    } catch (e) {
      resultsEl.innerHTML = '<div class="ps-empty">Ошибка поиска</div>';
      resultsEl.classList.add('active');
    }
  }, 300);
}

async function psSelectProduct(productId, productName, unit) {
  // Close dropdown, lock input to picked name
  document.getElementById('ps-input').value = productName;
  document.getElementById('ps-results').classList.remove('active');
  const host = document.getElementById('ps-card-host');
  host.innerHTML = '<div class="ps-card"><div class="ps-empty">⏳ Загрузка истории закупок...</div></div>';
  const orgId = state.restaurant?.organization_id;
  if (!orgId || !productId) return;
  try {
    const data = await apiGet(`/api/price-stats/${orgId}?product_id=${encodeURIComponent(productId)}&days=180`);
    host.innerHTML = psRenderCard(data, productName, unit);
  } catch (e) {
    host.innerHTML = `<div class="ps-card"><div class="ps-empty">❌ Не удалось загрузить: ${escapeHtml(e?.message || 'ошибка')}</div></div>`;
  }
}

function psRenderCard(data, fallbackName, fallbackUnit) {
  const name = data?.product?.name || fallbackName || '—';
  const unit = data?.product?.unit || fallbackUnit || 'ед';
  const suppliers = data?.suppliers || [];
  const best = data?.best;
  const purchases = data?.stats?.purchases || 0;

  if (!suppliers.length) {
    return `
      <div class="ps-card">
        <div class="ps-card-title">${escapeHtml(name)}</div>
        <div class="ps-empty">📭 За 180 дней закупок этого товара не было.</div>
      </div>`;
  }

  const bestHtml = best ? `
    <div class="ps-best">
      <div class="ps-best-label">🟢 Лучшая цена</div>
      <div class="ps-best-price">${fmtMoney(best.price_per_unit)} ₸/${escapeHtml(best.unit || unit)}</div>
      <div class="ps-best-supplier">${escapeHtml(best.supplier_name || '—')}</div>
      <div class="ps-best-date">${escapeHtml(best.date || '')}</div>
    </div>` : '';

  const rows = suppliers.map(s => {
    const delta = s.delta_pct || 0;
    const deltaTxt = (delta > 0.5) ? `+${delta.toFixed(0)}%` : (delta < -0.5 ? `${delta.toFixed(0)}%` : '—');
    const warn = delta >= 10 ? ' warn' : '';
    return `
      <div class="ps-supplier-row">
        <div class="ps-supplier-name">
          ${escapeHtml(s.supplier_name || '—')}
          <div class="ps-supplier-date">${escapeHtml(s.date || '')}</div>
        </div>
        <div>
          <div class="ps-supplier-price">${fmtMoney(s.price_per_unit)} ₸/${escapeHtml(s.unit || unit)}</div>
          <div class="ps-supplier-delta${warn}">${deltaTxt}</div>
        </div>
      </div>`;
  }).join('');

  return `
    <div class="ps-card">
      <div class="ps-card-title">${escapeHtml(name)}</div>
      ${bestHtml}
      <div class="ps-suppliers-title">Все поставщики:</div>
      ${rows}
      <div class="ps-stats">Закупок за ${data?.stats?.days || 180} дней: ${purchases}</div>
    </div>`;
}

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function fmtMoney(n) {
  return Math.round(Number(n) || 0).toLocaleString('ru-RU').replace(/,/g, ' ');
}
```

**Important:** if `escapeHtml` or `fmtMoney` is already defined elsewhere in `index.html` (likely — there's `ieEscape` and `ieFormatMoney` at line 3309/3305), DO NOT redefine. In that case, use the existing names `ieEscape` / `ieFormatMoney` in the code above (replace all `escapeHtml` with `ieEscape` and all `fmtMoney` with `ieFormatMoney`).

Run: `grep -n "^function escapeHtml\|^function fmtMoney\|^function ieEscape\|^function ieFormatMoney" /path/to/workspace/iiiko/index.html`
If `ieEscape` and `ieFormatMoney` exist (they should), substitute them in the new code; if neither pair exists, keep `escapeHtml`/`fmtMoney` as defined.

- [ ] **Step 2: Basic JS sanity check**

Run: `python -c "
html = open('/path/to/workspace/iiiko/index.html').read()
for fn in ['psSearchProducts', 'psSelectProduct', 'psRenderCard']:
    assert f'function {fn}' in html, f'{fn} not defined'
print('OK — all 3 functions defined')
"`
Expected: `OK — all 3 functions defined`.

- [ ] **Step 3: Commit**

```bash
git add index.html
git commit -m "feat(miniapp): wire up 📊 Цены search → /api/price-stats card

Adds psSearchProducts (debounced nomenclature search via existing
/api/nomenclature/search endpoint), psSelectProduct (calls new
/api/price-stats endpoint), and psRenderCard (per-supplier table
with best-price highlight). No new dependencies; reuses apiGet
and existing ieEscape/ieFormatMoney helpers where available."
```

---

## Task 4: Frontend — editor 🗑 delete button per row

**Files:**
- Modify: `index.html` — `ieRenderItems` function (around line 3267-3293) to include delete button; add `ieDeleteItem` JS function.

- [ ] **Step 1: Locate `ieRenderItems` and read the exact current template**

Run: `sed -n '3267,3293p' /path/to/workspace/iiiko/index.html`
Expected: shows the current template that renders each `.ie-item` row.

- [ ] **Step 2: Replace `ieRenderItems` to include 🗑 button**

Use the Edit tool to replace the existing `ieRenderItems` function. The new version differs only inside the per-row template — adds a `<button class="ie-item-edit" onclick="ieDeleteItem(${i})">🗑</button>` right after the ✏️ button. Replace exactly:

```javascript
function ieRenderItems() {
  const wrap = document.getElementById('ie-items');
  if (!ieState.items.length) {
    wrap.innerHTML = '<div class="ie-empty">Позиций нет</div>';
    return;
  }
  wrap.innerHTML = ieState.items.map((it, i) => {
    const qty = it.quantity ?? '—';
    const unit = it.unit || '';
    const price = it.price_per_unit != null ? ieFormatMoney(it.price_per_unit) : '—';
    const total = it.total != null ? ieFormatMoney(it.total) : '—';
    const mapped = it.iiko_product_id
      ? `<div class="ie-item-mapped">✓ ${ieEscape(it.iiko_product_name || 'сопоставлено')}</div>`
      : `<div class="ie-item-unmapped">⚠ не сопоставлено</div>`;
    return `
      <div class="ie-item">
        <div class="ie-item-body">
          <div class="ie-item-name">${ieEscape(it.name || '—')}</div>
          ${mapped}
          <div class="ie-item-info">${qty} ${ieEscape(unit)} × ${price} ₸</div>
        </div>
        <div class="ie-item-total">${total} ₸</div>
        <button class="ie-item-edit" onclick="ieOpenItem(${i})">✏️</button>
      </div>
    `;
  }).join('');
}
```

with:

```javascript
function ieRenderItems() {
  const wrap = document.getElementById('ie-items');
  if (!ieState.items.length) {
    wrap.innerHTML = '<div class="ie-empty">Позиций нет</div>'
      + '<button class="ie-add-btn" onclick="ieAddItem()">➕ Добавить позицию</button>';
    return;
  }
  const rows = ieState.items.map((it, i) => {
    const qty = it.quantity ?? '—';
    const unit = it.unit || '';
    const price = it.price_per_unit != null ? ieFormatMoney(it.price_per_unit) : '—';
    const total = it.total != null ? ieFormatMoney(it.total) : '—';
    const mapped = it.iiko_product_id
      ? `<div class="ie-item-mapped">✓ ${ieEscape(it.iiko_product_name || 'сопоставлено')}</div>`
      : `<div class="ie-item-unmapped">⚠ не сопоставлено</div>`;
    return `
      <div class="ie-item">
        <div class="ie-item-body">
          <div class="ie-item-name">${ieEscape(it.name || '—')}</div>
          ${mapped}
          <div class="ie-item-info">${qty} ${ieEscape(unit)} × ${price} ₸</div>
        </div>
        <div class="ie-item-total">${total} ₸</div>
        <button class="ie-item-edit" onclick="ieOpenItem(${i})">✏️</button>
        <button class="ie-item-edit" onclick="ieDeleteItem(${i})" title="Удалить">🗑</button>
      </div>
    `;
  }).join('');
  wrap.innerHTML = rows + '<button class="ie-add-btn" onclick="ieAddItem()">➕ Добавить позицию</button>';
}
```

- [ ] **Step 3: Add `ieDeleteItem` JS**

Insert this function right after `ieRenderItems`:

```javascript
function ieDeleteItem(idx) {
  if (idx < 0 || idx >= ieState.items.length) return;
  const it = ieState.items[idx];
  const name = it.name || 'эту позицию';
  if (!confirm(`Удалить "${name}"?`)) return;
  ieState.items.splice(idx, 1);
  ieRenderItems();
  ieRecalcTotals();
}
```

- [ ] **Step 4: Add CSS for `.ie-add-btn`**

Find the `.ie-` CSS block (around line 425-456) and append:

```css
.ie-add-btn { display:block; width:100%; padding:12px; margin-top:12px; background:var(--bg-secondary); border:1px dashed var(--card-border); border-radius:10px; color:var(--text-secondary); font-size:14px; font-weight:500; cursor:pointer; }
.ie-add-btn:hover { color:var(--text); border-color:var(--text-secondary); }
```

- [ ] **Step 5: Verify**

Run: `python -c "
html = open('/path/to/workspace/iiiko/index.html').read()
assert 'function ieDeleteItem' in html, 'ieDeleteItem missing'
assert 'function ieAddItem' in html or 'ieAddItem' in html, 'ieAddItem referenced but not yet defined (will be added in Task 5)'
assert '🗑' in html, '🗑 button missing'
assert 'ie-add-btn' in html, 'add button class missing'
print('OK')
"`
Expected: `OK`.

Note: `ieAddItem` is referenced from the new HTML but not yet defined — that's expected. Task 5 adds it. The Mini App will throw if user clicks ➕ between commits — that's the trade-off of bite-sized commits. Acceptable because no production deploy happens until both are pushed together.

- [ ] **Step 6: Commit**

```bash
git add index.html
git commit -m "feat(miniapp/editor): 🗑 delete button per item row + scaffolding for ➕

Adds delete-with-confirm on each editor row, and the ➕ add button
at the end of the list. ieDeleteItem is implemented; ieAddItem is
referenced but defined in the next commit (paired feature)."
```

---

## Task 5: Frontend — editor ➕ add item + modal rollback

**Files:**
- Modify: `index.html` — add `ieAddItem` function; patch `ieCloseModal` to handle rollback of unsaved new items; patch `ieSaveItem` to clear the addingNew flag.

- [ ] **Step 1: Locate `ieCloseModal` and `ieSaveItem`**

Run: `grep -n "^function ieCloseModal\|^function ieSaveItem" /path/to/workspace/iiiko/index.html`
Expected: shows their line numbers. Read them with `sed -n` to know their current bodies.

Run: `sed -n '3325,3340p' /path/to/workspace/iiiko/index.html` to see `ieCloseModal`.
Run: `sed -n '3370,3395p' /path/to/workspace/iiiko/index.html` to see `ieSaveItem` (adjust offset if needed).

- [ ] **Step 2: Add `ieAddItem` and patch `ieCloseModal` + `ieSaveItem`**

Right after `ieDeleteItem` (added in Task 4), insert:

```javascript
function ieAddItem() {
  ieState.items.push({
    name: '',
    quantity: 0,
    unit: 'кг',
    price_per_unit: 0,
    total: 0
  });
  const newIdx = ieState.items.length - 1;
  ieState._addingNew = newIdx;
  ieRenderItems();
  ieOpenItem(newIdx);
}
```

Replace `ieCloseModal` exactly:

```javascript
function ieCloseModal() {
  ieState.editingIndex = null;
  document.getElementById('ie-modal-back').classList.remove('active');
}
```

with:

```javascript
function ieCloseModal() {
  // If user cancelled adding a NEW item (didn't save it) — roll back the placeholder.
  if (ieState._addingNew !== null && ieState._addingNew !== undefined) {
    const idx = ieState._addingNew;
    ieState._addingNew = null;
    if (idx >= 0 && idx < ieState.items.length) {
      ieState.items.splice(idx, 1);
      ieRenderItems();
      ieRecalcTotals();
    }
  }
  ieState.editingIndex = null;
  document.getElementById('ie-modal-back').classList.remove('active');
}
```

Find `ieSaveItem` and add ONE LINE at the very end (right before the closing `}`):

Locate the function:
```javascript
function ieSaveItem() {
  // ... existing body that updates ieState.items[editingIndex] ...
  ieRenderItems();
  ieRecalcTotals();
  ieCloseModal();
}
```

Before the closing `}`, but BEFORE the `ieCloseModal()` call (because ieCloseModal will roll back if _addingNew is set!), set `ieState._addingNew = null;`. Use Edit tool to replace:

```javascript
  ieRenderItems();
  ieRecalcTotals();
  ieCloseModal();
}
```

with:

```javascript
  ieState._addingNew = null;
  ieRenderItems();
  ieRecalcTotals();
  ieCloseModal();
}
```

Be careful: this exact sequence (`ieRenderItems(); ieRecalcTotals(); ieCloseModal();`) might appear elsewhere — read enough context around `ieSaveItem` to make the Edit `old_string` unique.

- [ ] **Step 3: Verify**

Run: `python -c "
html = open('/path/to/workspace/iiiko/index.html').read()
assert 'function ieAddItem' in html, 'ieAddItem missing'
assert '_addingNew' in html, '_addingNew flag missing'
# Make sure _addingNew is reset in ieSaveItem
import re
m = re.search(r'function ieSaveItem.*?\\n\\}', html, re.DOTALL)
assert m, 'cannot find ieSaveItem'
assert '_addingNew' in m.group(0), 'ieSaveItem does not reset _addingNew'
print('OK')
"`
Expected: `OK`.

- [ ] **Step 4: Commit**

```bash
git add index.html
git commit -m "feat(miniapp/editor): ➕ add item + modal cancel rolls back new placeholder

ieAddItem pushes an empty item and opens the edit modal. If the user
cancels the modal without saving, ieCloseModal removes the placeholder
so canceled additions don't leave empty rows. ieSaveItem clears the
_addingNew flag before closing the modal to prevent rollback after
a successful save."
```

---

## Task 6: Manual integration smoke test

**Files:** none modified. End-to-end check.

- [ ] **Step 1: Push all commits + verify prod deploy**

```bash
git push origin main
```

If push to main is blocked by harness — instruct user to run `! git push origin main` themselves. Wait for Render redeploy to finish (~2-5 min). Verify no `ImportError` in Render logs.

- [ ] **Step 2: Mini App — open Накладные → 📊 Цены**

- Open Mini App in Telegram
- Navigate: Расходы → Накладные
- Verify: two pills at top — `📋 Список` (active) and `📊 Цены`
- Tap `📊 Цены` → input field appears, list disappears
- Tap `📋 Список` → input disappears, list returns

Acceptance: subview toggle works, no console errors.

- [ ] **Step 3: Mini App — search & select a product**

- On `📊 Цены`, type "помидор" (or any product you know exists in iiko nomenclature)
- After 300ms — dropdown shows matching products
- Tap a product → loading spinner → card appears

Acceptance: card shows either price stats OR "📭 За 180 дней закупок не было" if no history.

- [ ] **Step 4: Mini App — editor delete**

- Go to Накладные list, tap `✏️ Сопоставить и отправить` on a saved invoice (or open via bot edit link)
- In editor — each item row has `✏️` and `🗑` next to each other
- Tap `🗑` on any item → confirm dialog "Удалить ..." → tap OK → item disappears, totals recalculate

Acceptance: delete works with confirmation, totals update.

- [ ] **Step 5: Mini App — editor add (save flow)**

- In same editor — tap `➕ Добавить позицию` at bottom
- Modal opens empty
- Fill: name, search nomenclature, pick product, enter quantity, price → tap «Сохранить»
- Modal closes, new item appears in list

Acceptance: new item visible, totals include it.

- [ ] **Step 6: Mini App — editor add (cancel rollback)**

- Tap `➕ Добавить позицию` again
- Modal opens empty (but list now temporarily has an empty row — that's fine, it's a placeholder)
- Tap «Отмена»
- Modal closes, list returns to previous state (NO empty row remains)

Acceptance: cancelled additions don't leave empty rows.

- [ ] **Step 7: Regression check**

- Bot: send a fresh invoice photo → preview shows 5 buttons including `📊 Сравнить цены`. Tap each (Отправить in iiko / Редактировать / Отменить / Добавить фото / Сравнить цены) — all still behave as before.
- Mini App `📋 Список` of Накладные still loads correctly.

Acceptance: nothing pre-existing broke.

- [ ] **Step 8: If all passes, no final commit (smoke test is observation-only)**

Run: `git status`
Expected: `nothing to commit, working tree clean`.

---

## Out of scope (NOT in this plan)

- iiko-sourced price comparison in the BOT button `📊 Сравнить цены` (still uses only local `bot_invoices`)
- Multi-org aggregation in `📊 Цены`
- Charts / trend lines
- CSV export of price stats
- Pagination of supplier list (assumes < 20 unique suppliers per product per 180d)
- Reordering items in editor

---

## Verification — final acceptance

After Task 6 passes:
- ✅ Subview toggle `📋 Список / 📊 Цены` inside Накладные
- ✅ Nomenclature search → tap → price stats card with best price + supplier list
- ✅ Card sources data from iiko AND local bot_invoices
- ✅ Cache of iiko invoice export per org (1 hour TTL)
- ✅ Editor: 🗑 deletes with confirm
- ✅ Editor: ➕ adds new item, opens modal; cancel rolls back; save keeps
- ✅ No existing endpoint, callback, or behavior modified
