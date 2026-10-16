# План: выбор филиала в «Плане» + день/период с синхроном — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Дать шефу (tg id 123456789) переключатель филиала в суб-вкладке «План», и для всех — выбор одного дня + произвольного периода в модалке дат с синхроном между Главной и Продажами.

**Architecture:** Чистый фронтенд (`index.html`, Vanilla JS, единый `state`). Бэкенд не меняем. Период становится единым источником правды через центральный сеттер `applyGlobalPeriod`, держащий пары полей main/sales в жёсткой синхронизации. Модалка дат получает тумблер «День/Период». «План» получает session-only `state.planOrgId` и UI-чип, видимый только шефу.

**Tech Stack:** HTML + Vanilla JS, Telegram WebApp SDK (`window.Telegram.WebApp`), CSS-классы `.date-chip` / `.modal-overlay` / `.modal-sheet` / `.rest-chip`.

**Тестирование:** Для фронта в проекте нет JS-тест-харнесса. Проверка — ручная через запуск приложения в браузере (Playwright MCP) и dev-режим (без BOT_TOKEN бэк возвращает `{"id":0,...}`, поэтому tg id берём на фронте из `initDataUnsafe`). Для гейта по шефу проверяем подменой возвращаемого значения хелпера в консоли. Коммитим после каждой задачи.

---

## File Structure

Единственный изменяемый файл — `/path/to/workspace/iiiko/index.html`:

- **STATE** (`~1450`): добавить `planOrgId`.
- **Helpers** (`~1637`): добавить `getMyTgId()`, `applyGlobalPeriod()`, `renderDateFilters()`, константу `PLAN_BRANCH_SWITCHER_TG_ID`, `formatPeriodChipLabel()`.
- **Date modal HTML** (`~1411`): тумблер «День/Период» + одиночный date-input.
- **Date functions** (`~2014`, `~2198`, `~2218`, `~2233`): `setPeriod`/`setSalesPeriod`/`openDateRangeModal`/`applyDateRange` → делегируют/режимы.
- **План HTML** (`~1284`): контейнер чипа филиала.
- **План JS** (`~3351`): `loadPlan` использует `planOrgId`, рендер чипа + sheet выбора.
- **Plan branch modal HTML** (`~1441`): новый single-select sheet.
- **Reset** (`selectRestaurant ~1918`, `applyBranches ~2285`): сброс `planOrgId`.

Бэкенд (`api.py`): **без изменений.**

---

## Часть B — Синхрон периода (делаем первой: фундамент для модалки дня)

### Task 1: Центральный сеттер периода и единая перерисовка фильтров

**Files:**
- Modify: `index.html` — helpers рядом с `buildPeriodQuery` (`~1637`), `state` (`~1455`)

- [ ] **Step 1: Добавить хелпер форматирования метки чипа дат**

В `index.html` сразу после функции `cacheKeyFor` (после строки `}` на `~1664`) добавить:

```javascript
// Метка чипа «Даты»: один день → «📅 05.06»; диапазон → «📅 05.06–20.06»; иначе «📅 Даты»
function formatPeriodChipLabel() {
  const r = state.customRange;
  if (state.period !== 'custom' || !r?.from || !r?.to) return '📅 Даты';
  const fmt = s => s.slice(8, 10) + '.' + s.slice(5, 7);
  return r.from === r.to ? `📅 ${fmt(r.from)}` : `📅 ${fmt(r.from)}–${fmt(r.to)}`;
}
```

- [ ] **Step 2: Добавить единую перерисовку обеих панелей фильтров**

Сразу после `formatPeriodChipLabel` добавить:

```javascript
// Перерисовать подсветку чипов и текст «Даты» сразу для ОБЕИХ панелей (main + sales).
// Обе панели всегда в DOM, поэтому переключение вкладок берёт состояние отсюда.
function renderDateFilters() {
  const label = formatPeriodChipLabel();
  // пресет → значение в onclick: setPeriod('today',...) / setSalesPeriod('today',...)
  const presetOf = chip => {
    const m = /set(?:Sales)?Period\('([^']+)'/.exec(chip.getAttribute('onclick') || '');
    return m ? m[1] : null;
  };
  ['main-date-filters', 'sales-date-filters'].forEach(barId => {
    const bar = document.getElementById(barId);
    if (!bar) return;
    bar.querySelectorAll('.date-chip').forEach(chip => {
      if (chip.id === 'main-date-chip' || chip.id === 'sales-date-chip') {
        chip.textContent = label;
        chip.classList.toggle('active', state.period === 'custom');
      } else {
        chip.classList.toggle('active', state.period !== 'custom' && presetOf(chip) === state.period);
      }
    });
  });
}
```

- [ ] **Step 3: Добавить центральный сеттер периода**

Сразу после `renderDateFilters` добавить:

```javascript
// Единственная точка записи периода. Держит пары main/sales в синхроне,
// перерисовывает обе панели и перезагружает данные обеих вкладок.
function applyGlobalPeriod(period, customRange) {
  state.period = period;
  state.salesPeriod = period;
  state.customRange = customRange || null;
  state.salesCustomRange = customRange || null;
  delete state.olapCache[cacheKeyFor(period, state.customRange)];
  renderDateFilters();
  loadDashboard();
  loadSales();
  if (state.salesTab === 'cancels') renderCancels().catch(console.error);
  if (state.salesTab === 'cart') renderCart().catch(console.error);
}
```

- [ ] **Step 4: Проверка (визуально, после Task 2-3) — отложенная**

Самостоятельно функции ещё не вызываются. Финальная проверка — после Task 3 ниже. Пока убедиться, что страница не падает: открыть приложение, в консоли выполнить `typeof applyGlobalPeriod === 'function' && typeof renderDateFilters === 'function'` → должно вернуть `true`.

- [ ] **Step 5: Commit**

```bash
git add index.html
git commit -m "feat(dates): центральный сеттер периода + единая перерисовка фильтров (Главная/Продажи)"
```

---

### Task 2: Переключить setPeriod / setSalesPeriod на центральный сеттер

**Files:**
- Modify: `index.html` — `setPeriod` (`~2014-2026`), `setSalesPeriod` (`~2198-2213`)

- [ ] **Step 1: Заменить `setPeriod`**

Заменить весь блок `function setPeriod(p, el) { ... }` на:

```javascript
function setPeriod(p, el) {
  haptic();
  applyGlobalPeriod(p, null);
}
```

- [ ] **Step 2: Заменить `setSalesPeriod`**

Заменить весь блок `function setSalesPeriod(p, el) { ... }` на:

```javascript
function setSalesPeriod(p, el) {
  haptic();
  applyGlobalPeriod(p, null);
}
```

- [ ] **Step 3: Проверка в браузере (Playwright MCP)**

Запустить приложение (см. skill `run`). На вкладке «Главная» нажать «Вчера» → дашборд перегрузился, чип «Вчера» активен. Переключиться на «Продажи» → там тоже активен «Вчера» (не «Сегодня»). Нажать на «Продажах» «Эта неделя» → вернуться на «Главную» → активна «Эта неделя».
Ожидаемо: выбор периода синхронен между вкладками.

- [ ] **Step 4: Commit**

```bash
git add index.html
git commit -m "feat(dates): синхрон периода между Главной и Продажами через applyGlobalPeriod"
```

---

### Task 3: Модалка дат — тумблер «День / Период»

**Files:**
- Modify: `index.html` — modal HTML (`~1411-1424`), `openDateRangeModal` (`~2218-2226`), `applyDateRange` (`~2233-2260`)

- [ ] **Step 1: Заменить HTML модалки `#date-range-modal`**

Заменить блок `<!-- Date range modal --> ... </div>` (строки ~1411-1424) на:

```html
<!-- Date range modal -->
<div class="modal-overlay" id="date-range-modal" onclick="closeDateRangeModal(event)">
  <div class="modal-sheet">
    <div class="modal-title">Выбор даты</div>
    <div class="date-mode-tabs" style="display:flex;gap:8px;margin-bottom:14px;">
      <div class="date-chip active" id="dr-mode-day" onclick="setDateMode('day')" style="flex:1;text-align:center;">День</div>
      <div class="date-chip" id="dr-mode-range" onclick="setDateMode('range')" style="flex:1;text-align:center;">Период</div>
    </div>
    <div id="dr-day-wrap" style="display:flex;flex-direction:column;gap:8px;">
      <label style="font-size:13px;color:var(--text-secondary);">Дата</label>
      <input type="date" class="input-field" id="dr-day" style="color:var(--text);background:var(--bg-secondary);">
    </div>
    <div id="dr-range-wrap" style="display:none;flex-direction:column;gap:8px;">
      <label style="font-size:13px;color:var(--text-secondary);">С</label>
      <input type="date" class="input-field" id="dr-from" style="color:var(--text);background:var(--bg-secondary);">
      <label style="font-size:13px;color:var(--text-secondary);">По</label>
      <input type="date" class="input-field" id="dr-to" style="color:var(--text);background:var(--bg-secondary);">
    </div>
    <div style="display:flex;flex-direction:column;gap:12px;margin-top:14px;">
      <button class="btn-full btn-primary" onclick="applyDateRange()">Применить</button>
      <button class="btn-full" style="background:var(--bg-secondary);color:var(--text);border:none;padding:14px;border-radius:14px;font-size:16px;cursor:pointer;" onclick="closeDateRangeModalDirect()">Отмена</button>
    </div>
  </div>
</div>
```

- [ ] **Step 2: Добавить переключатель режима `setDateMode` и состояние режима**

Перед `function openDateRangeModal` (`~2218`), рядом с `let _dateModalScope = 'main';`, добавить:

```javascript
let _dateMode = 'day'; // 'day' | 'range'
function setDateMode(mode) {
  _dateMode = mode;
  document.getElementById('dr-mode-day').classList.toggle('active', mode === 'day');
  document.getElementById('dr-mode-range').classList.toggle('active', mode === 'range');
  document.getElementById('dr-day-wrap').style.display = mode === 'day' ? 'flex' : 'none';
  document.getElementById('dr-range-wrap').style.display = mode === 'range' ? 'flex' : 'none';
}
```

- [ ] **Step 3: Заменить `openDateRangeModal`**

Заменить весь блок `function openDateRangeModal(scope) { ... }` на:

```javascript
function openDateRangeModal(scope) {
  haptic();
  _dateModalScope = scope; // сохранён для совместимости; период теперь общий
  const cur = state.customRange;
  const today = new Date().toISOString().slice(0, 10);
  const isDay = !cur || cur.from === cur.to;
  setDateMode(isDay ? 'day' : 'range');
  document.getElementById('dr-day').value = (cur && cur.from) || today;
  document.getElementById('dr-from').value = (cur && cur.from) || today;
  document.getElementById('dr-to').value = (cur && cur.to) || today;
  document.getElementById('date-range-modal').classList.add('active');
}
```

- [ ] **Step 4: Заменить `applyDateRange`**

Заменить весь блок `function applyDateRange() { ... }` на:

```javascript
function applyDateRange() {
  let from, to;
  if (_dateMode === 'day') {
    const d = document.getElementById('dr-day').value;
    if (!d) { showToast('Укажи дату'); return; }
    from = to = d;
  } else {
    from = document.getElementById('dr-from').value;
    to = document.getElementById('dr-to').value;
    if (!from || !to) { showToast('Укажи обе даты'); return; }
    if (from > to) { showToast('Дата "С" должна быть раньше "По"'); return; }
  }
  closeDateRangeModalDirect();
  applyGlobalPeriod('custom', { from, to });
}
```

- [ ] **Step 5: Проверка в браузере (Playwright MCP)**

Открыть приложение. На «Главной» нажать «📅 Даты»:
1. Режим «День» (по умолчанию активен) → выбрать дату, «Применить». Чип стал `📅 ДД.ММ`. Перейти на «Продажи» — чип там тот же `📅 ДД.ММ`, активен.
2. Снова «📅 Даты» → переключить на «Период» → выбрать С<По, «Применить». Чип `📅 ДД.ММ–ДД.ММ` на обеих вкладках.
3. Открыть «📅 Даты» ещё раз → модалка открылась на «Период» (т.к. текущий выбор — диапазон).
4. Нажать пресет «Сегодня» → чип вернулся к «📅 Даты», синхронно на обеих вкладках.

- [ ] **Step 6: Commit**

```bash
git add index.html
git commit -m "feat(dates): модалка с тумблером «День/Период», выбор одного дня"
```

---

## Часть A — Выбор филиала в суб-вкладке «План» (только шеф)

### Task 4: Хелпер telegram id и константа шефа

**Files:**
- Modify: `index.html` — helpers (`~1648`)

- [ ] **Step 1: Добавить константу и хелпер**

Рядом с `getActiveOrgIds` (`~1649`) добавить:

```javascript
// Telegram id, которому показываем переключатель филиалов в «Плане». См. spec 2026-06-11.
const PLAN_BRANCH_SWITCHER_TG_ID = 123456789;
function getMyTgId() {
  return window.Telegram?.WebApp?.initDataUnsafe?.user?.id || null;
}
```

- [ ] **Step 2: Проверка**

В консоли браузера: `typeof getMyTgId === 'function' && PLAN_BRANCH_SWITCHER_TG_ID === 123456789` → `true`.

- [ ] **Step 3: Commit**

```bash
git add index.html
git commit -m "feat(plan): хелпер getMyTgId + константа шефа для переключателя филиалов"
```

---

### Task 5: Состояние planOrgId + использование в loadPlan + сброс

**Files:**
- Modify: `index.html` — `state` (`~1455`), `loadPlan` (`~3351-3366`), `selectRestaurant` (`~1918-1940`), `applyBranches` (`~2285-2304`)

- [ ] **Step 1: Добавить поле в state**

В объекте `state` после строки `salesCustomRange: null,  // ...` добавить:

```javascript
  planOrgId: null,         // выбранный филиал в суб-вкладке «План» (только шеф); null = первый активный
```

- [ ] **Step 2: Использовать `planOrgId` в `loadPlan`**

В `loadPlan` заменить строку:

```javascript
  const orgId = getActiveOrgIds()[0] || state.restaurant.organization_id;
```

на:

```javascript
  const orgId = state.planOrgId || getActiveOrgIds()[0] || state.restaurant.organization_id;
```

- [ ] **Step 3: Сброс `planOrgId` при смене филиала (single)**

В `selectRestaurant`, сразу после строки `state.selectedBranches = null;` (`~1920`), добавить:

```javascript
  state.planOrgId = null;
```

- [ ] **Step 4: Сброс `planOrgId` при мультивыборе**

В `applyBranches`, сразу после строки `state.selectedBranches = checked;` (`~2295`), добавить:

```javascript
  state.planOrgId = null;
```

- [ ] **Step 5: Проверка**

Приложение запускается, «План» грузится как раньше (для не-шефа поведение не изменилось: `planOrgId` остаётся `null`). Смена филиала в верхнем селекторе не ломает «План».

- [ ] **Step 6: Commit**

```bash
git add index.html
git commit -m "feat(plan): state.planOrgId — выбранный филиал плана + сброс при смене филиала"
```

---

### Task 6: Чип филиала в «Плане» + single-select sheet (гейт по шефу)

**Files:**
- Modify: `index.html` — план HTML (`~1284`), plan-branch modal HTML (после branches-modal `~1441`), план JS (`~3349`)

- [ ] **Step 1: Добавить контейнер чипа в HTML «Плана»**

В `#comp-view-plan`, перед `<div id="plan-status" ...>` (строка `~1284`), добавить:

```html
        <div id="plan-branch-bar" style="display:none;margin-bottom:12px"></div>
```

- [ ] **Step 2: Добавить sheet выбора филиала плана**

После блока `<!-- Branches modal --> ... </div>` (после строки `~1441`) добавить:

```html
<!-- Plan branch modal (single-select, только шеф) -->
<div class="modal-overlay" id="plan-branch-modal" onclick="closePlanBranchModal(event)">
  <div class="modal-sheet">
    <div class="modal-title">Филиал плана</div>
    <div id="plan-branch-list" style="display:flex;flex-direction:column;gap:8px;max-height:50vh;overflow-y:auto;"></div>
    <button class="btn-full" style="background:var(--bg-secondary);color:var(--text);border:none;padding:14px;border-radius:14px;font-size:16px;cursor:pointer;margin-top:12px;" onclick="closePlanBranchModalDirect()">Отмена</button>
  </div>
</div>
```

- [ ] **Step 3: Добавить рендер чипа и функции модалки**

Перед `async function loadPlan()` (`~3351`) добавить:

```javascript
// Чип выбора филиала в «Плане» — только шефу и только при >1 филиала.
function renderPlanBranchBar() {
  const bar = document.getElementById('plan-branch-bar');
  if (!bar) return;
  const show = getMyTgId() === PLAN_BRANCH_SWITCHER_TG_ID && state.restaurants.length > 1;
  if (!show) { bar.style.display = 'none'; bar.innerHTML = ''; return; }
  const curId = state.planOrgId || getActiveOrgIds()[0] || state.restaurant?.organization_id;
  const cur = state.restaurants.find(r => r.organization_id === curId);
  const name = cur ? cur.organization_name : 'Филиал';
  bar.style.display = 'block';
  bar.innerHTML = `<div class="rest-chip active" style="display:inline-block" onclick="openPlanBranchModal()">🏢 ${escHtml(name)} ▾</div>`;
}
function openPlanBranchModal() {
  haptic();
  const curId = state.planOrgId || getActiveOrgIds()[0] || state.restaurant?.organization_id;
  const list = document.getElementById('plan-branch-list');
  list.innerHTML = state.restaurants.map(r => `
    <div class="rest-chip ${r.organization_id === curId ? 'active' : ''}" style="text-align:left"
         onclick='selectPlanBranch(${JSON.stringify(r.organization_id)})'>${escHtml(r.organization_name)}</div>
  `).join('');
  document.getElementById('plan-branch-modal').classList.add('active');
}
function closePlanBranchModal(e) {
  if (e.target === document.getElementById('plan-branch-modal')) closePlanBranchModalDirect();
}
function closePlanBranchModalDirect() {
  document.getElementById('plan-branch-modal').classList.remove('active');
}
function selectPlanBranch(orgId) {
  haptic();
  state.planOrgId = orgId;
  closePlanBranchModalDirect();
  _planLoaded = false;
  loadPlan();
}
```

- [ ] **Step 4: Вызвать рендер чипа в `loadPlan`**

В `loadPlan`, сразу после строки `const wrap = document.getElementById('plan-table-wrap');` (`~3355`), добавить:

```javascript
  renderPlanBranchBar();
```

- [ ] **Step 5: Проверка в браузере (Playwright MCP)**

Для аккаунта с несколькими филиалами:
1. Подменить id шефа в консоли для теста UI:
   `window.Telegram.WebApp.initDataUnsafe = { user: { id: 123456789 } };`
   затем открыть «Год/год» → «План». Над таблицей виден чип `🏢 <Филиал> ▾`.
2. Тап по чипу → sheet со списком филиалов, текущий помечен `active`. Выбрать другой →
   sheet закрылся, план перезагрузился, чип показывает новый филиал, данные плана сменились.
3. Сбросить id: `window.Telegram.WebApp.initDataUnsafe = { user: { id: 1 } };`
   перезайти в «План» → чип отсутствует (`#plan-branch-bar` скрыт).

- [ ] **Step 6: Commit**

```bash
git add index.html
git commit -m "feat(plan): чип выбора филиала в суб-вкладке «План» (только шеф 123456789)"
```

---

## Финальная проверка (после всех задач)

- [ ] **Синхрон + день/период:** Главная и Продажи всегда показывают одинаковый период; «День» даёт `📅 ДД.ММ`, «Период» — `📅 ДД.ММ–ДД.ММ`; пресеты синхронны.
- [ ] **План:** под id шефа и при >1 филиале — чип филиала работает и меняет данные; под другим id / при 1 филиале — чип скрыт; смена филиала в верхнем селекторе сбрасывает выбор плана.
- [ ] **Регрессия:** загрузка дашборда, продаж, cancels, companions, ABC не сломаны (read-sites `salesPeriod`/`salesCustomRange` остались валидны, т.к. равны main-полям).
- [ ] **Бэкенд `api.py` не изменялся** (`git diff --stat` показывает только `index.html` + docs).

## Notes

- Гейтинг по tg id — клиентский, только для показа UI. Данные плана защищены на бэке
  (`/api/plan` отдаёт только филиалы пользователя), поэтому этого достаточно.
- `escHtml` уже существует в `index.html` (используется в `renderRestSelector`).
- В dev без Telegram `getMyTgId()` вернёт `null` → чип плана скрыт (ожидаемо).
