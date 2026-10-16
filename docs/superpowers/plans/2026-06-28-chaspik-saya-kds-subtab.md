# Суб-вкладка «saya-kds» — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить под главной вкладкой «Сотрудники» новую суб-вкладку «saya-kds», видимую только tg-id `123456789` и `123456789`, которая через серверный прокси показывает аналитику доставки/кухни из внешнего сервиса saya-kds.

**Architecture:** Тонкий серверный прокси `GET /api/chaspik` в `api.py` держит секрет `X-API-Key` на бэке, проверяет tg-id и прозрачно отдаёт JSON из `saya-kds.onrender.com/admin/analytics/export`. Фронт (`index.html`, vanilla JS) добавляет сабтаб (кнопка удаляется из DOM для чужих id), грузит `/api/chaspik` обычным `X-Telegram-Init-Data`-путём и рендерит 4 секции чистым JS.

**Tech Stack:** FastAPI + httpx (бэк), vanilla JS + Telegram WebApp SDK (фронт). Тесты бэка — простые python-файлы `test_*.py` (как в репо: функции + `__main__`-раннер, без pytest), запуск `python3 test_x.py`. JS-тест-харнесса в репо нет — фронт проверяется вручную в мини-аппе.

## Global Constraints

- Секрет `X-API-Key` НЕ попадает во фронт/URL — только в заголовке серверного запроса.
- Разрешённые tg-id (один и тот же набор на фронте и бэке): `123456789`, `123456789`.
- Часовой пояс/даты — на стороне saya-kds (UTC+5); дефолты периода (7 дней / сегодня / sla 45) не дублируем у себя.
- Единицы из ответа saya-kds: `*_seconds`/`avg`/`median`/`p95` — секунды; `sla.rate` — доля 0–1.
- Прод деплоится Render'ом с ветки `deploy-cashshifts`.
- Стиль тестов — как в `test_invoice_units.py`: plain функции `test_*`, `if __name__ == "__main__"` раннер, без pytest.

---

### Task 1: Бэкенд-прокси `GET /api/chaspik`

**Files:**
- Modify: `api.py` (env-блок ~строки 103–107; новый эндпоинт рядом с другими `@app.get`, например после `/api/load-heatmap`)
- Test: `test_chaspik_proxy.py` (создать в корне репо)

**Interfaces:**
- Consumes: `get_current_user` (Depends), `httpx` (импортирован), `HTTPException`, `Query` (уже импортированы в `api.py`).
- Produces:
  - `CHASPIK_TG_IDS: set[int]` — `{123456789, 123456789}`
  - `ANALYTICS_API_KEY: str` (env, дефолт `""`), `CHASPIK_ORG_ID: str` (env, дефолт `""`), `CHASPIK_BASE_URL: str` (env, дефолт `"https://saya-kds.onrender.com"`)
  - `async def chaspik_export(from_=Query(None, alias="from"), to=Query(None), sla_minutes=Query(None), user=Depends(get_current_user)) -> dict` — маршрут `GET /api/chaspik`. Гейт по id → 403; не настроено → 503; ошибка upstream → 502; иначе JSON saya-kds.

- [ ] **Step 1: Написать падающий тест**

Создать `test_chaspik_proxy.py`:

```python
"""Тест прокси /api/chaspik: гейт по tg-id, 503 без конфигурации,
прозрачная передача с заголовком X-API-Key и org_id из env.
Запуск: python3 test_chaspik_proxy.py
"""
import os, asyncio, tempfile
os.environ.setdefault("DB_PATH", tempfile.mktemp(suffix="_chaspik_test.db"))
# Бэкенд читает эти env при импорте — задаём ДО import api.
os.environ["ANALYTICS_API_KEY"] = "secret-test-key"
os.environ["CHASPIK_ORG_ID"] = "org-alieva"
os.environ["CHASPIK_BASE_URL"] = "https://saya-kds.example"

import database; database.init_db()
import api
from fastapi import HTTPException

ALLOWED = {"id": 123456789, "username": "boss", "first_name": "B"}
OTHER = {"id": 111, "username": "x", "first_name": "X"}


class FakeResp:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.text = text
    def json(self):
        return self._payload


class FakeClient:
    captured = {}
    next_resp = None
    def __init__(self, *a, **k): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def get(self, url, params=None, headers=None):
        FakeClient.captured = {"url": url, "params": dict(params or {}),
                               "headers": dict(headers or {})}
        return FakeClient.next_resp or FakeResp(
            200, {"ok": True, "org_id": (params or {}).get("org_id")})


def _call(**kw):
    return asyncio.run(api.chaspik_export(**kw))


def test_forbidden_for_other_id():
    try:
        _call(from_=None, to=None, sla_minutes=None, user=OTHER)
    except HTTPException as e:
        assert e.status_code == 403, f"ждали 403, got {e.status_code}"
        print("  [OK] чужой id → 403")
        return
    raise AssertionError("ожидался HTTPException 403")


def test_503_when_unconfigured():
    saved = api.ANALYTICS_API_KEY
    api.ANALYTICS_API_KEY = ""
    try:
        _call(from_=None, to=None, sla_minutes=None, user=ALLOWED)
    except HTTPException as e:
        assert e.status_code == 503, f"ждали 503, got {e.status_code}"
        print("  [OK] нет ANALYTICS_API_KEY → 503")
        return
    finally:
        api.ANALYTICS_API_KEY = saved
    raise AssertionError("ожидался HTTPException 503")


def test_proxies_with_key_and_org():
    api.httpx.AsyncClient = FakeClient
    FakeClient.next_resp = FakeResp(200, {"hello": "world", "org_id": "org-alieva"})
    out = _call(from_="2026-06-01", to="2026-06-28", sla_minutes=30, user=ALLOWED)
    assert out == {"hello": "world", "org_id": "org-alieva"}, out
    cap = FakeClient.captured
    assert cap["headers"].get("X-API-Key") == "secret-test-key", cap["headers"]
    assert cap["params"].get("org_id") == "org-alieva", cap["params"]
    assert cap["params"].get("from") == "2026-06-01", cap["params"]
    assert cap["params"].get("to") == "2026-06-28", cap["params"]
    assert cap["params"].get("sla_minutes") == 30, cap["params"]
    assert cap["url"].endswith("/admin/analytics/export"), cap["url"]
    print("  [OK] проксирует с X-API-Key и org_id из env")


def test_upstream_error_becomes_502():
    api.httpx.AsyncClient = FakeClient
    FakeClient.next_resp = FakeResp(401, None, "bad key")
    try:
        _call(from_=None, to=None, sla_minutes=None, user=ALLOWED)
    except HTTPException as e:
        assert e.status_code == 502, f"ждали 502, got {e.status_code}"
        print("  [OK] upstream 401 → 502")
        return
    raise AssertionError("ожидался HTTPException 502")


if __name__ == "__main__":
    failed = 0
    for t in (test_forbidden_for_other_id, test_503_when_unconfigured,
              test_proxies_with_key_and_org, test_upstream_error_becomes_502):
        print(f"\n>>> {t.__name__}")
        try:
            t()
        except AssertionError as e:
            failed += 1; print(f"  [FAIL] {e}")
        except Exception as e:
            failed += 1; print(f"  [ERROR] {type(e).__name__}: {e}")
    try:
        os.remove(os.environ["DB_PATH"])
    except OSError:
        pass
    print(f"\n{'='*50}\n{'ВСЕ ТЕСТЫ ОК' if not failed else f'ПРОВАЛЕНО: {failed}'}")
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `python3 test_chaspik_proxy.py`
Expected: FAIL/ERROR — `api.chaspik_export` ещё не существует (`AttributeError: module 'api' has no attribute 'chaspik_export'`).

- [ ] **Step 3: Добавить env + константу в `api.py`**

После блока `DEMO_ONLY = ...` (≈строка 103), перед комментарием про часовой пояс, вставить:

```python
# ── saya-kds (внешняя аналитика доставки/кухни) ──
# Прокси /api/chaspik держит ключ на бэке и шлёт его в заголовке X-API-Key.
ANALYTICS_API_KEY = os.getenv("ANALYTICS_API_KEY", "")
CHASPIK_ORG_ID = os.getenv("CHASPIK_ORG_ID", "")
CHASPIK_BASE_URL = os.getenv("CHASPIK_BASE_URL", "https://saya-kds.onrender.com")
CHASPIK_TG_IDS = {123456789, 123456789}
```

- [ ] **Step 4: Добавить эндпоинт в `api.py`**

Сразу после функции `load_heatmap` (после её `return`, ≈строка 1536, перед `@app.get("/api/foodcost/{org_id}")`) вставить:

```python
@app.get("/api/chaspik")
async def chaspik_export(
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
    sla_minutes: Optional[int] = Query(None),
    user: Dict = Depends(get_current_user),
):
    """Прокси к saya-kds /admin/analytics/export. Виден только CHASPIK_TG_IDS.
    Ключ X-API-Key держим на бэке и не отдаём во фронт."""
    if int(user.get("id", 0)) not in CHASPIK_TG_IDS:
        raise HTTPException(status_code=403, detail="forbidden")
    if not ANALYTICS_API_KEY or not CHASPIK_ORG_ID:
        raise HTTPException(
            status_code=503,
            detail="saya-kds выгрузка не настроена (нет ANALYTICS_API_KEY или CHASPIK_ORG_ID)")
    params: Dict = {"org_id": CHASPIK_ORG_ID}
    if from_:
        params["from"] = from_
    if to:
        params["to"] = to
    if sla_minutes is not None:
        params["sla_minutes"] = sla_minutes
    try:
        async with httpx.AsyncClient(timeout=60.0) as c:
            r = await c.get(f"{CHASPIK_BASE_URL}/admin/analytics/export",
                            params=params, headers={"X-API-Key": ANALYTICS_API_KEY})
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"saya-kds недоступен: {e}")
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"saya-kds {r.status_code}: {r.text[:200]}")
    return r.json()
```

- [ ] **Step 5: Запустить тест — убедиться, что проходит**

Run: `python3 test_chaspik_proxy.py`
Expected: `ВСЕ ТЕСТЫ ОК` (4 теста [OK]).

- [ ] **Step 6: Коммит**

```bash
git add api.py test_chaspik_proxy.py
git commit -m "feat(chaspik): серверный прокси /api/chaspik к saya-kds

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Фронт — сабтаб «saya-kds», гейтинг, контейнер, разводка

**Files:**
- Modify: `index.html` — сабтабы Staff (≈888), контейнеры (≈952), `initApp` (≈1616), константа (≈1745), `setStaffSubtab` (≈3027)

**Interfaces:**
- Consumes: `getMyTgId()` (строка 1746), `setStaffSubtab(view, el)` (строка 3027), `apiGet(path)`.
- Produces:
  - `CHASPIK_TG_IDS` (JS, массив) — `[123456789, 123456789]`
  - `applyChaspikGate()` — удаляет кнопку `#staff-sub-kds` из DOM, если `getMyTgId()` не в наборе
  - `loadChaspik()` — заглушка (наполняется в Task 3), вызывается из `setStaffSubtab` при `view === 'kds'`

- [ ] **Step 1: Добавить JS-константу разрешённых id**

После строки `const PLAN_BRANCH_SWITCHER_TG_ID = 123456789;` (строка 1745) добавить:

```javascript
const CHASPIK_TG_IDS = [123456789, 123456789];  // кому видна суб-вкладка «saya-kds»
```

- [ ] **Step 2: Добавить кнопку сабтаба**

После строки 888 (`<div class="subtab" id="staff-sub-heatmap" ...>Час пик</div>`) добавить:

```html
      <div class="subtab" id="staff-sub-kds" onclick="setStaffSubtab('kds', this)">saya-kds</div>
```

- [ ] **Step 3: Добавить контейнер-вью**

После закрывающего `</div>` блока `staff-view-heatmap` (≈строка 952) добавить пустой контейнер с местами под 4 секции:

```html
    <div id="staff-view-kds" style="display:none">
      <div id="kds-status" style="color:var(--text-secondary);font-size:13px;margin-top:12px"></div>
      <div id="kds-zoneload"></div>
      <div id="kds-sla"></div>
      <div id="kds-kitchen"></div>
      <div id="kds-anomalies"></div>
    </div>
```

- [ ] **Step 4: Разводка в `setStaffSubtab`**

Заменить тело функции `setStaffSubtab` (строки 3027–3035) на версию с `kds`:

```javascript
function setStaffSubtab(view, el) {
  const views = ['waiters', 'couriers', 'heatmap', 'kds'];
  views.forEach(v => {
    const sub = document.getElementById('staff-sub-' + v);
    if (sub) sub.classList.toggle('active', v === view);
    const vw = document.getElementById('staff-view-' + v);
    if (vw) vw.style.display = v === view ? '' : 'none';
  });
  if (view === 'couriers' && !_couriersLoaded) loadCouriers();
  if (view === 'heatmap') loadHeatmap();
  if (view === 'kds') loadChaspik();
}
```

- [ ] **Step 5: Добавить гейт + заглушку `loadChaspik`**

Сразу перед `function setStaffSubtab(` (строка 3027) добавить:

```javascript
function applyChaspikGate() {
  if (!CHASPIK_TG_IDS.includes(getMyTgId())) {
    document.getElementById('staff-sub-kds')?.remove();
  }
}

async function loadChaspik() {
  const status = document.getElementById('kds-status');
  if (status) status.textContent = 'Загрузка…';
}
```

- [ ] **Step 6: Вызвать гейт при инициализации**

В `initApp` (строка 1616) после `updateDate();` (строка 1621) добавить строку:

```javascript
  applyChaspikGate();
```

- [ ] **Step 7: Ручная проверка в мини-аппе**

Запустить локально: `python3 api.py` (поднимает uvicorn на :8000). Открыть мини-апп.
- Под разрешённым id: на вкладке «Сотрудники» видны 4 сабтаба, последний — «saya-kds»; клик переключает на пустой вью с текстом «Загрузка…».
- Эмуляция чужого id (в DevTools-консоли мини-аппа): временно `window.Telegram.WebApp.initDataUnsafe.user.id = 111; applyChaspikGate();` — кнопка «saya-kds» исчезает.

Ожидаемо: нет ошибок в консоли, переключение остальных сабтабов не сломано.

- [ ] **Step 8: Коммит**

```bash
git add index.html
git commit -m "feat(chaspik): сабтаб saya-kds в Сотрудниках с гейтом по tg-id

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Фронт — рендер 4 секций в `loadChaspik`

**Files:**
- Modify: `index.html` — функция `loadChaspik` (заглушка из Task 2)

**Interfaces:**
- Consumes: `apiGet('/api/chaspik')` → JSON saya-kds (поля `zone_load`, `stage_stats`, `kitchen_zones`, `anomalies`, `journal`), `escHtml(...)` (уже есть в файле, использовался в `renderPlanBranchBar`).
- Produces: заполняет `#kds-status`, `#kds-zoneload`, `#kds-sla`, `#kds-kitchen`, `#kds-anomalies`.

- [ ] **Step 1: Реализовать `loadChaspik` с рендером**

Заменить заглушку `loadChaspik` (из Task 2, Step 5) на полную версию:

```javascript
function _fmtSec(s) {
  s = Math.round(Number(s) || 0);
  const m = Math.floor(s / 60), r = s % 60;
  return m ? `${m} мин ${r} с` : `${r} с`;
}

async function loadChaspik() {
  const status = document.getElementById('kds-status');
  const elZone = document.getElementById('kds-zoneload');
  const elSla = document.getElementById('kds-sla');
  const elKit = document.getElementById('kds-kitchen');
  const elAno = document.getElementById('kds-anomalies');
  [elZone, elSla, elKit, elAno].forEach(e => { if (e) e.innerHTML = ''; });
  if (status) status.textContent = 'Загрузка…';
  let data;
  try {
    data = await apiGet('/api/chaspik');
  } catch (e) {
    if (status) status.textContent = 'Ошибка сети';
    return;
  }
  if (data && data.detail) {  // 403/503/502 от прокси приходят как {detail: "..."}
    if (status) status.textContent = 'saya-kds: ' + data.detail;
    return;
  }
  if (status) status.textContent = '';

  // ── 1. Нагрузка по часам/зонам (zone_load) ──
  const zl = data.zone_load || {};
  const zones = zl.zones || [];
  const hours = zl.hours || [];
  const cells = zl.cells || {};
  if (zones.length && hours.length) {
    let max = 1;
    zones.forEach(z => hours.forEach(h => {
      const c = (cells[z] && cells[z][h]) ? cells[z][h].count || 0 : 0;
      if (c > max) max = c;
    }));
    let peakHour = null, peakVal = -1;
    hours.forEach(h => {
      let sum = 0; zones.forEach(z => { sum += (cells[z] && cells[z][h]) ? (cells[z][h].count || 0) : 0; });
      if (sum > peakVal) { peakVal = sum; peakHour = h; }
    });
    let html = '<div class="card" style="margin-top:12px;padding:12px">';
    html += '<div class="card-title" style="margin-bottom:8px">Нагрузка по часам и зонам</div>';
    if (peakHour !== null) html += `<div style="font-size:13px;margin-bottom:8px">⏰ Пик в <span style="color:#34C759">${peakHour}:00</span></div>`;
    html += `<div style="overflow-x:auto"><table style="border-collapse:collapse;font-size:11px">`;
    html += '<tr><th style="text-align:left;padding:2px 6px">Зона\\Час</th>' +
      hours.map(h => `<th style="padding:2px 4px;color:var(--text-secondary)">${h}</th>`).join('') + '</tr>';
    zones.forEach(z => {
      html += `<tr><td style="padding:2px 6px;font-weight:600">${escHtml(z)}</td>`;
      hours.forEach(h => {
        const c = (cells[z] && cells[z][h]) ? (cells[z][h].count || 0) : 0;
        const a = c ? (0.15 + 0.85 * c / max).toFixed(2) : 0;
        html += `<td style="padding:2px 4px;text-align:center;background:rgba(52,199,89,${a})">${c || ''}</td>`;
      });
      html += '</tr>';
    });
    html += '</table></div></div>';
    elZone.innerHTML = html;
  }

  // ── 2. SLA и этапы пути (stage_stats) ──
  const ss = data.stage_stats || {};
  const stages = (ss.stage_aggregates && ss.stage_aggregates.stages) || [];
  const sla = ss.sla || {};
  const bott = ss.bottleneck_distribution || {};
  if (stages.length || Object.keys(sla).length) {
    let html = '<div class="card" style="margin-top:12px;padding:12px">';
    html += '<div class="card-title" style="margin-bottom:8px">SLA и этапы пути</div>';
    if (typeof sla.rate === 'number') {
      const pct = (sla.rate * 100).toFixed(1);
      html += `<div style="font-size:13px;margin-bottom:8px">Просрочка SLA: <span style="color:#FF3B30">${pct}%</span> (${sla.breached || 0} из ${sla.total || 0})</div>`;
    }
    const bottTop = Object.entries(bott).sort((a, b) => b[1] - a[1])[0];
    if (bottTop) html += `<div style="font-size:13px;margin-bottom:8px">Узкое место: <b>${escHtml(bottTop[0])}</b></div>`;
    if (stages.length) {
      html += '<table style="border-collapse:collapse;font-size:12px;width:100%">';
      html += '<tr><th style="text-align:left;padding:3px 6px">Этап</th><th style="padding:3px 6px">avg</th><th style="padding:3px 6px">median</th><th style="padding:3px 6px">p95</th></tr>';
      stages.forEach(st => {
        html += `<tr><td style="padding:3px 6px">${escHtml(st.label || st.key)}</td>` +
          `<td style="padding:3px 6px;text-align:right">${_fmtSec(st.avg)}</td>` +
          `<td style="padding:3px 6px;text-align:right">${_fmtSec(st.median)}</td>` +
          `<td style="padding:3px 6px;text-align:right">${_fmtSec(st.p95)}</td></tr>`;
      });
      html += '</table>';
    }
    html += '</div>';
    elSla.innerHTML = html;
  }

  // ── 3. Кухня по зонам + сотрудники (kitchen_zones) ──
  const kz = (data.kitchen_zones && data.kitchen_zones.zones) || [];
  if (kz.length) {
    let html = '<div class="card" style="margin-top:12px;padding:12px">';
    html += '<div class="card-title" style="margin-bottom:8px">Кухня по зонам</div>';
    kz.forEach(z => {
      html += `<div style="margin-bottom:10px"><div style="font-weight:600;font-size:13px">${escHtml(z.zone)} · ${z.count || 0} шт · ср. ${_fmtSec(z.avg)}</div>`;
      (z.employees || []).forEach(e => {
        html += `<div style="font-size:12px;color:var(--text-secondary);padding-left:8px">${escHtml(e.name)} — ${e.count || 0} шт, ${_fmtSec(e.avg)}</div>`;
      });
      html += '</div>';
    });
    html += '</div>';
    elKit.innerHTML = html;
  }

  // ── 4. Аномалии + журнал (anomalies, journal) ──
  const ano = data.anomalies || {};
  const fast = ano.fast || [], reverts = ano.reverts || [];
  const rows = (data.journal && data.journal.rows) || [];
  let html = '<div class="card" style="margin-top:12px;padding:12px">';
  html += '<div class="card-title" style="margin-bottom:8px">Аномалии и журнал</div>';
  if (fast.length) {
    html += '<div style="font-size:13px;font-weight:600;margin:6px 0">⚡ Подозрительно быстрые</div>';
    fast.slice(0, 10).forEach(f => {
      html += `<div style="font-size:12px;color:var(--text-secondary)">№${escHtml(String(f.order_number))} · ${escHtml(f.item_name || '')} · ${_fmtSec(f.prep_seconds)} · ${escHtml(f.name || '')}</div>`;
    });
  }
  if (reverts.length) {
    html += '<div style="font-size:13px;font-weight:600;margin:6px 0">↩️ Возвраты</div>';
    reverts.slice(0, 10).forEach(r => {
      html += `<div style="font-size:12px;color:var(--text-secondary)">№${escHtml(String(r.order_number))} · ${r.count || 0}×</div>`;
    });
  }
  if (rows.length) {
    html += '<div style="font-size:13px;font-weight:600;margin:6px 0">📋 Журнал (последние)</div>';
    rows.slice(-20).reverse().forEach(r => {
      const t = String(r.at || '').slice(11, 16);
      html += `<div style="font-size:11px;color:var(--text-secondary)">${t} · №${escHtml(String(r.order_number || ''))} · ${escHtml(r.type || '')} · ${escHtml(r.actor_name || '')} ${escHtml(r.item_name || '')}</div>`;
    });
  }
  if (!fast.length && !reverts.length && !rows.length) html += '<div style="font-size:12px;color:var(--text-secondary)">Нет данных за период</div>';
  html += '</div>';
  elAno.innerHTML = html;
}
```

- [ ] **Step 2: Ручная проверка с реальными данными**

Поднять локально с настроенными env (`ANALYTICS_API_KEY`, `CHASPIK_ORG_ID`, при необходимости `CHASPIK_BASE_URL`):

```bash
ANALYTICS_API_KEY=<секрет> CHASPIK_ORG_ID=<id_алиева> python3 api.py
```

Под разрешённым id открыть «Сотрудники → saya-kds». Ожидаемо: 4 карточки заполнены (нагрузка час×зона с подсветкой, SLA + этапы в мин/сек, кухня по зонам с поварами, аномалии+журнал). Без настроенных env: вместо секций — текст «saya-kds: …не настроена…».

Проверка консоли: нет JS-ошибок.

- [ ] **Step 3: Коммит**

```bash
git add index.html
git commit -m "feat(chaspik): рендер 4 секций saya-kds (нагрузка, SLA, кухня, аномалии)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Деплой-конфигурация и финальная проверка

**Files:** нет изменений кода — операционная настройка.

- [ ] **Step 1: Задать env на saya-kds**

Render → сервис `saya-kds` → Environment → `ANALYTICS_API_KEY` = `<секрет>` (см. доку saya-kds). Сохранить (Render передеплоит).

- [ ] **Step 2: Задать env на бэкенде мини-аппа**

Render → сервис этого репо (где крутится `api.py`) → Environment:
- `ANALYTICS_API_KEY` = тот же `<секрет>`
- `CHASPIK_ORG_ID` = `<id филиала Алиева в saya-kds>`
- (опц.) `CHASPIK_BASE_URL`, если адрес saya-kds отличается от дефолта.

Сохранить (передеплой).

- [ ] **Step 3: Прод-проверка**

После деплоя (ветка `deploy-cashshifts`) под разрешённым tg-id открыть «Сотрудники → saya-kds» в проде — секции заполнены реальными данными. Под чужим id кнопки нет.

- [ ] **Step 4: Слить ветку фичи в `deploy-cashshifts`** (если работа велась в отдельной ветке/worktree)

Действовать по skill `superpowers:finishing-a-development-branch`.

---

## Self-Review

**Spec coverage:**
- Прокси с ключом на бэке, 403/503/502, прозрачный JSON → Task 1. ✓
- Сабтаб «saya-kds» под Staff, гейт по 2 id (кнопка из DOM + бэк-403) → Task 2. ✓
- 4 секции (zone_load, stage_stats/SLA, kitchen_zones, anomalies+journal) → Task 3. ✓
- org_id из env `CHASPIK_ORG_ID`, ключ в двух сервисах, дефолт base url → Task 1 + Task 4. ✓
- Вне объёма (demand, кэш, переключатель периода, мульти-филиал) — не реализуется. ✓

**Placeholder scan:** код приведён полностью во всех code-степах; «заглушка» в Task 2 явно заменяется в Task 3. Без TBD/TODO.

**Type consistency:** `CHASPIK_TG_IDS` — set[int] на бэке (Task 1), массив на фронте (Task 2), наборы совпадают. `loadChaspik()` объявлена в Task 2 и доопределена в Task 3 — то же имя. `setStaffSubtab` массив `['waiters','couriers','heatmap','kds']` согласован с контейнерами `staff-view-*` и кнопками `staff-sub-*`. `apiGet('/api/chaspik')` совпадает с маршрутом `@app.get("/api/chaspik")`.
