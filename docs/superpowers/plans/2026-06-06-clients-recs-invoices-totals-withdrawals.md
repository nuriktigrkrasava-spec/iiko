# Клиенты-рекомендации, Итоги накладных, Изъятия — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить рекомендации по клиенту при клике, итог+переключатель периода в накладных, суб-вкладку изъятий из iiko; устранить баг несохранения ссылок.

**Architecture:** Frontend — Vanilla JS в `index.html` (правки `renderClients`, вкладки Накладные, новая вкладка Изъятия). Backend — FastAPI `api.py` (`total` в `/api/invoices`, новый `/api/withdrawals`), `iiko.py` (новый OLAP-метод изъятий по образцу `get_writeoffs`). Без новых зависимостей.

**Tech Stack:** Python 3 / FastAPI / SQLite / Vanilla JS. Тесты бэкенда — точечные `python -c` / curl-проверки (в проекте нет pytest-инфры); фронт — ручная проверка в Mini App.

**Spec:** `docs/superpowers/specs/2026-06-06-clients-recs-invoices-totals-withdrawals-design.md`

## File Structure
- `index.html` — `renderClients` (карточка+рекомендация), вкладка Накладные (переключатель+итого), новая вкладка Изъятия.
- `api.py` — `invoices` (поля `total_amount`/`count`), новый `withdrawals` эндпоинт, демо-данные изъятий.
- `iiko.py` — новый `get_cash_withdrawals` (и заглушка в демо-клиенте, если есть).
- `database.py` — только если баг ссылок окажется на стороне БД/пути.

---

## Task 1: Клиенты — общая плашка «лояльные принесли / могут принести»

**Files:**
- Modify: `index.html` (функция `renderClients`, ~2297-2330)

- [ ] **Step 1: Добавить плашку после сетки сегментов**

В `renderClients`, сразу после блока `<div class="seg-grid" style="margin-top:10px"> ... </div>` (две карточки LTV/Выручка), вставить в строку `html` дополнительный блок, использующий `s.loyal_revenue` и `s.loyal_potential` (поля уже приходят из бэка):

```javascript
  if (s.loyal_revenue || s.loyal_potential) {
    html += `<div class="card" style="margin-top:10px">
      <div style="font-size:13px;color:var(--text-secondary);margin-bottom:4px">Потенциал лояльных</div>
      <div style="font-size:15px;font-weight:600">Принесли ${formatMoney(s.loyal_revenue)} · могут принести ещё <span style="color:#34C759">+${formatMoney(s.loyal_potential)}</span></div>
    </div>`;
  }
```

- [ ] **Step 2: Проверить в приложении**

Запустить локально (см. project run-инструкцию), открыть Продажи → Клиенты (source=iiko или table с данными). Ожидается: под сегментами видна плашка «Принесли X · могут принести ещё +Z». На демо-аккаунте (segments=null) плашки нет — без ошибок в консоли.

- [ ] **Step 3: Commit**

```bash
git add index.html
git commit -m "feat(clients): плашка потенциала лояльных клиентов"
```

---

## Task 2: Клиенты — клик по строке «Топ клиенты» раскрывает карточку с рекомендацией

**Files:**
- Modify: `index.html` (функция `renderClients`, таблица `top_vip`; добавить функцию `toggleClientCard`)

- [ ] **Step 1: Сделать строки кликабельными и добавить скрытую строку-карточку**

Заменить генерацию `<tbody>` в блоке «Топ клиенты» на вариант с `data`-атрибутами и второй (скрытой) строкой под каждым клиентом:

```javascript
<tbody>${data.top_vip.map((v, i) => {
  const avg = v.orders ? Math.round(v.spend / v.orders) : 0;
  const rec = v.orders >= 10
    ? 'VIP-клиент. Удержание: персональная акция или привилегия.'
    : `До VIP осталось ${10 - v.orders} заказов ≈ +${formatMoney((10 - v.orders) * avg)}`;
  return `
    <tr onclick="toggleClientCard(${i})" style="cursor:pointer">
      <td class="name">${escHtml(v.phone)}</td><td class="num">${v.orders}</td><td class="num">${formatMoney(v.spend)}</td>
    </tr>
    <tr id="cli-card-${i}" style="display:none">
      <td colspan="3" style="background:var(--bg-secondary);font-size:13px;padding:10px">
        <div>Принёс: <b>${formatMoney(v.spend)}</b> · Заказов: <b>${v.orders}</b> · Средний чек: <b>${formatMoney(avg)}</b></div>
        <div style="margin-top:6px;color:var(--text-secondary)">💡 ${rec}</div>
      </td>
    </tr>`;
}).join('')}</tbody>
```

- [ ] **Step 2: Добавить функцию toggle (рядом с `renderClients`)**

```javascript
function toggleClientCard(i) {
  const el = document.getElementById('cli-card-' + i);
  if (el) el.style.display = el.style.display === 'none' ? '' : 'none';
}
```

- [ ] **Step 3: Проверить в приложении**

Открыть Продажи → Клиенты, кликнуть строку в «Топ клиенты». Ожидается: раскрывается карточка с принёс/заказов/средний чек и строкой рекомендации. Повторный клик скрывает. Для клиента с 10+ заказов — текст про VIP-удержание.

- [ ] **Step 4: Commit**

```bash
git add index.html
git commit -m "feat(clients): карточка клиента с рекомендацией по клику"
```

---

## Task 3: Накладные — backend возвращает `total_amount` и `count`

**Files:**
- Modify: `api.py` (функция `invoices`, ~1074-1145)

- [ ] **Step 1: Считать полную сумму бот-накладных за период (без обрезки до 10)**

В `invoices` бот-накладные сейчас берутся `get_bot_invoices(limit=10, organization_id=real_org)`. Для корректного итога нужны все за период. Заменить выборку: получить все бот-накладные организации и отфильтровать по дате диапазона перед добавлением в `result_list`. Найти строку:

```python
        bot_invs = get_bot_invoices(limit=10, organization_id=real_org)
```

заменить на:

```python
        bot_invs = get_bot_invoices(limit=1000, organization_id=real_org)
        d_from, d_to = date_from[:10], date_to[:10]
        bot_invs = [b for b in bot_invs
                    if d_from <= ((b.get("date") or b.get("created_at") or "")[:10]) <= d_to]
```

- [ ] **Step 2: Добавить total_amount и count в ответ**

Найти финальную сборку результата:

```python
        result_list.sort(key=lambda x: x["date"], reverse=True)
        result = {"invoices": result_list}
```

заменить на:

```python
        result_list.sort(key=lambda x: x["date"], reverse=True)
        total_amount = round(sum(float(x.get("amount") or 0) for x in result_list))
        result = {"invoices": result_list, "total_amount": total_amount, "count": len(result_list)}
```

- [ ] **Step 3: Проверить ответ эндпоинта**

С запущенным сервером и подключённым реальным org (или через демо-ветку добавить `total_amount`/`count` и в demo-возврат — см. ниже). Быстрая проверка демо-ветки: убедиться, что фронт не падает при отсутствии полей (Task 5 их подстрахует). Для реального org:

Run: `curl -s "http://localhost:8000/api/invoices/<org>?period=month" -H "<auth>" | python -m json.tool | head`
Expected: в JSON присутствуют `total_amount` и `count`.

- [ ] **Step 4: Commit**

```bash
git add api.py
git commit -m "feat(invoices): total_amount и count за период в ответе"
```

---

## Task 4: Накладные — переключатель периода + строка «Итого» во фронте

**Files:**
- Modify: `index.html` (разметка вкладки Накладные ~1066-1069; ветка `state.expenseTab === 'invoices'` в `loadExpenses` ~2767-2812)

- [ ] **Step 1: Добавить разметку пилюль и строки итога**

В `#invoices-list-wrap` перед `<div id="invoices-list"></div>` (или сразу под заголовком «Список накладных») добавить:

```html
<div class="subtabs" id="inv-period-tabs" style="margin-bottom:10px">
  <div class="subtab" data-p="day" onclick="setInvoicePeriod('day', this)">День</div>
  <div class="subtab" data-p="week" onclick="setInvoicePeriod('week', this)">Неделя</div>
  <div class="subtab active" data-p="month" onclick="setInvoicePeriod('month', this)">Месяц</div>
</div>
<div id="inv-total" style="font-weight:700;font-size:15px;margin-bottom:10px"></div>
```

(класс `subtabs`/`subtab` — как у существующих суб-вкладок; если в проекте другой класс контейнера, использовать тот же, что у `#expense-tabs`/клиентских суб-вкладок.)

- [ ] **Step 2: Ввести состояние периода и обработчик**

Рядом с другими `state.*` для накладных добавить дефолт и функцию:

```javascript
state.invoicePeriod = state.invoicePeriod || 'month';
function setInvoicePeriod(p, el) {
  haptic();
  state.invoicePeriod = p;
  document.querySelectorAll('#inv-period-tabs .subtab').forEach(t => t.classList.remove('active'));
  if (el) el.classList.add('active');
  loadExpenses();
}
```

- [ ] **Step 3: Использовать период в запросе и показать итог**

В ветке `if (state.expenseTab === 'invoices')` заменить:

```javascript
      const data = await apiGet(`/api/invoices/${orgId}?period=week`);
```

на:

```javascript
      const data = await apiGet(`/api/invoices/${orgId}?period=${state.invoicePeriod}`);
      const totalEl = document.getElementById('inv-total');
      if (totalEl) totalEl.textContent = `Итого за период: ${data.count || (data.invoices||[]).length} накладных на сумму ${formatMoney(data.total_amount || 0)}`;
```

- [ ] **Step 4: Проверить в приложении**

Открыть Расходы → Накладные. Ожидается: пилюли День/Неделя/Месяц (актив — Месяц), строка «Итого за период: N накладных на сумму X», список под ней. Переключение пилюль перезапрашивает и обновляет и список, и итог.

- [ ] **Step 5: Commit**

```bash
git add index.html
git commit -m "feat(invoices): переключатель периода и строка Итого"
```

---

## Task 5: Баг ссылок — локализовать причину

**Files:**
- Inspect: `database.py:8` (`DB_PATH`), Render env/disk; `api.py` (`set_plan_url`/`get_plan_url` вызовы)

> Use superpowers:systematic-debugging. Сначала воспроизвести, потом чинить.

- [ ] **Step 1: Проверить путь БД и его персистентность**

Локально:

Run: `python -c "import database, os; print('DB_PATH=', database.DB_PATH, 'exists=', os.path.exists(database.DB_PATH))"`
Записать значение. Затем проверить на Render: переменную окружения `DB_PATH` и смонтирован ли persistent disk (через дашборд/`render.yaml`, если есть). Зафиксировать: лежит ли `DB_PATH` на persistent mount.

- [ ] **Step 2: Проверить сохранение и чтение локально (один org_id)**

Run:
```bash
python -c "
import database as d
d.init_db()
d.set_client_url('test-org', 'https://example.com/x')
print('read=', d.get_client_url('test-org'))
"
```
Expected: `read= https://example.com/x`. Если PASS — запись/чтение исправны, причина в персистентности диска (Step 3a). Если FAIL — баг в БД-слое (чинить здесь).

- [ ] **Step 3: Записать вывод о причине**

Зафиксировать в коммит-сообщении/заметке какая из гипотез подтвердилась:
- (a) Диск эфемерный → переходим к Task 6.
- (b) Код-баг org_id / «Все филиалы» → исправить рассинхрон ключа в соответствующей ветке `api.py`, добавить проверку и закоммитить здесь.

(Эта задача — расследование; коммит только если найден и исправлен код-баг.)

---

## Task 6: Баг ссылок — устойчивый путь БД (если причина — эфемерный диск)

**Files:**
- Modify: `database.py:8`

> Выполнять только если Task 5 показал, что причина — БД на эфемерном диске.

- [ ] **Step 1: Сделать дефолтный путь устойчивым к persistent disk**

Заменить:

```python
DB_PATH = os.getenv("DB_PATH", "iiko_boss.db")
```

на:

```python
_DEFAULT_DB_DIR = "/data" if os.path.isdir("/data") else "."
DB_PATH = os.getenv("DB_PATH", os.path.join(_DEFAULT_DB_DIR, "iiko_boss.db"))
```

(`/data` — типичный mount persistent disk на Render. Если у проекта другой mount — использовать его; финально задать `DB_PATH` env-переменной на проде на путь внутри persistent disk.)

- [ ] **Step 2: Проверить, что путь резолвится без ошибок**

Run: `python -c "import database; print(database.DB_PATH)"`
Expected: путь внутри `/data` (если каталог есть) либо `./iiko_boss.db` локально — без исключений.

- [ ] **Step 3: Commit**

```bash
git add database.py
git commit -m "fix(db): хранить SQLite на persistent disk если смонтирован"
```

- [ ] **Step 4: Задеплоить и проверить персистентность**

После деплоя: сохранить ссылку в План/Клиенты, инициировать редеплой, проверить что ссылка осталась. (Деплой — по согласованию с пользователем; не пушить без подтверждения.)

---

## Task 7: Изъятия — подтвердить OLAP-код типа транзакции

**Files:**
- Inspect: iiko columns-introspection (URL в памяти `reference_iiko_olap_fields`)

> Минимум запросов к iiko (см. память `feedback_iiko_testing`). Один запрос introspection, не в цикле.

- [ ] **Step 1: Получить список значений TransactionType / типов кассовых операций**

Сделать ОДИН запрос columns-introspection к iiko OLAP (TRANSACTIONS) на реальном сервере, найти значение типа, соответствующее изъятию наличных из кассовой смены (выемка/инкассация). Записать точный код (например, кандидат `CASH_REMOVAL` — подтвердить фактическим значением, не зашивать наугад).

- [ ] **Step 2: Зафиксировать найденный код**

Дописать строку в память `reference_iiko_olap_fields` (или новый reference-файл) с подтверждённым типом транзакции изъятий. Это разблокирует Task 8.

---

## Task 8: Изъятия — backend (iiko метод + эндпоинт + демо)

**Files:**
- Modify: `iiko.py` (новый метод по образцу `get_writeoffs`, ~696-730)
- Modify: `api.py` (новый эндпоинт по образцу `writeoffs`, ~1252; демо-данные рядом с `DEMO_WRITEOFFS` ~339)

- [ ] **Step 1: Демо-данные изъятий в api.py**

Рядом с `DEMO_WRITEOFFS` добавить:

```python
DEMO_WITHDRAWALS = {
    "withdrawals": [
        {"date": "2026-06-05", "sum": 120000, "comment": "Инкассация"},
        {"date": "2026-06-04", "sum": 35000, "comment": "Выемка на закуп"},
    ],
    "total": 155000,
}
```

- [ ] **Step 2: Метод `get_cash_withdrawals` в iiko.py**

По образцу `get_writeoffs`, с подтверждённым в Task 7 типом транзакции (здесь показан кандидат — заменить на фактический код из Task 7):

```python
    async def get_cash_withdrawals(self, org_ids: List[str], date_from: str, date_to: str) -> Dict[str, Any]:
        """Изъятия наличных из кассы через OLAP TRANSACTIONS."""
        filters: Dict[str, Any] = {
            "DateTime.OperDayFilter": self._tx_date_filter(date_from, date_to),
            "TransactionType": {"filterType": "IncludeValues", "values": ["CASH_REMOVAL"]},
        }
        if org_ids and org_ids[0] and org_ids[0] != "demo":
            filters["Department"] = {"filterType": "IncludeValues", "values": org_ids}
        payload = {
            "reportType": "TRANSACTIONS",
            "buildSummary": "false",
            "groupByRowFields": ["DateTime.OperDayFilter", "Account.Name"],
            "aggregateFields": ["Sum.Outgoing"],
            "filters": filters,
        }
        token = await self._ensure_token()
        async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
            resp = await client.post(
                f"{self.base_url}/api/v2/reports/olap",
                params={"key": token}, json=payload)
            resp.raise_for_status()
            raw = resp.json()
            rows = raw if isinstance(raw, list) else raw.get("data", [])
            withdrawals = [
                {"date": (r.get("DateTime.OperDayFilter") or "")[:10],
                 "sum": float(r.get("Sum.Outgoing") or 0),
                 "comment": r.get("Account.Name") or "Изъятие"}
                for r in rows if float(r.get("Sum.Outgoing") or 0) > 0
            ]
            return {"withdrawals": withdrawals}
```

- [ ] **Step 3: Эндпоинт `/api/withdrawals/{org_id}` в api.py**

По образцу `writeoffs`:

```python
@app.get("/api/withdrawals/{org_id}")
async def withdrawals(org_id: str, period: str = "month", user: Dict = Depends(get_current_user)):
    if _is_demo_user(user) or org_id == "demo-org-1":
        return DEMO_WITHDRAWALS
    real_org = _get_org_id(org_id, user)
    info = _get_restaurant_info(real_org, user)
    key = _cache_key(user.get("id", 0), "withdrawals", real_org, period)
    cached = _get_cached(key)
    if cached:
        return cached
    date_from, date_to = get_period_dates(period)
    client = get_client(info["api_login"], info.get("iiko_server"), info.get("api_password"))
    try:
        if not hasattr(client, "get_cash_withdrawals"):
            return {"withdrawals": [], "total": 0}
        data = await client.get_cash_withdrawals([_olap_dept(real_org, info)], date_from, date_to)
        ws = data.get("withdrawals", [])
        result = {"withdrawals": ws, "total": round(sum(float(w.get("sum") or 0) for w in ws))}
        _set_cached(key, result)
        return result
    except Exception as e:
        print(f"[withdrawals] {e}")
        return DEMO_WITHDRAWALS
```

- [ ] **Step 4: Проверить эндпоинт**

Run: `python -c "import api"` (импорт без ошибок — синтаксис/имена корректны)
Expected: без traceback. Затем (опц.) curl на демо-org → JSON с `withdrawals` и `total`.

- [ ] **Step 5: Commit**

```bash
git add api.py iiko.py
git commit -m "feat(withdrawals): OLAP-метод изъятий + эндпоинт + демо"
```

---

## Task 9: Изъятия — суб-вкладка во фронте

**Files:**
- Modify: `index.html` (`#expense-tabs` ~962; контейнер вкладок; `setExpenseTab` список ~2839; ветка в `loadExpenses`)

- [ ] **Step 1: Добавить кнопку суб-вкладки и контейнер**

В `#expense-tabs` рядом с «Накладные» добавить:

```html
<div class="tab" onclick="setExpenseTab('withdrawals_cash', this)">Изъятия</div>
```

И блок-контейнер рядом с другими `#tab-*`:

```html
<div id="tab-withdrawals_cash" style="display:none">
  <div class="card">
    <div class="card-title" style="margin-bottom:8px">Изъятия наличных</div>
    <div id="cashw-total" style="font-weight:700;font-size:15px;margin-bottom:10px"></div>
    <div id="cashw-list"></div>
  </div>
</div>
```

(Имя `withdrawals_cash` выбрано, чтобы не конфликтовать с существующим `writeoffs`/`tab-writeoffs`.)

- [ ] **Step 2: Зарегистрировать вкладку в setExpenseTab**

В `setExpenseTab` массив переключения видимости:

```javascript
  ['foodcost', 'expenses', 'invoices', 'writeoffs'].forEach(t => {
```

заменить на:

```javascript
  ['foodcost', 'expenses', 'invoices', 'writeoffs', 'withdrawals_cash'].forEach(t => {
```

- [ ] **Step 3: Ветка загрузки в loadExpenses**

Добавить рядом с другими ветками `if (state.expenseTab === ...)`:

```javascript
  if (state.expenseTab === 'withdrawals_cash') {
    try {
      const data = await apiGet(`/api/withdrawals/${orgId}?period=month`);
      document.getElementById('cashw-total').textContent = `Итого изъято за период: ${formatMoney(data.total || 0)}`;
      const ws = data.withdrawals || [];
      document.getElementById('cashw-list').innerHTML = ws.length
        ? ws.map(w => `
          <div class="wc-item">
            <div class="wc-header"><div class="wc-name">${escHtml(w.comment || 'Изъятие')}</div><div class="wc-pct">${formatMoney(w.sum)}</div></div>
            <div class="wc-meta">${w.date || ''}</div>
          </div>`).join('')
        : '<div style="color:var(--text-secondary);font-size:13px">Нет изъятий за период</div>';
    } catch(e) { console.error(e); }
  }
```

(переиспользуем существующие классы `.wc-item/.wc-header/.wc-name/.wc-pct/.wc-meta` от вкладки списаний.)

- [ ] **Step 4: Проверить в приложении**

Открыть Расходы → Изъятия. На демо-аккаунте: «Итого изъято: 155 000 ₸» и две строки. На реальном org с изъятиями — реальные данные; без изъятий — «Нет изъятий за период».

- [ ] **Step 5: Commit**

```bash
git add index.html
git commit -m "feat(withdrawals): суб-вкладка Изъятия в разделе Расходы"
```

---

## Self-Review (выполнено при написании плана)

- **Spec coverage:** §1 Клиенты → Task 1-2; §2 Накладные → Task 3-4; §3 Изъятия → Task 7-9; §4 Баг ссылок → Task 5-6; §5 FAQ → уже сделано до плана. Информационный OLAP-вопрос — вне build (по spec).
- **Placeholders:** OLAP-код типа транзакции явно вынесен в Task 7 как «подтвердить введением», кандидат `CASH_REMOVAL` помечен как требующий подтверждения — это не плейсхолдер реализации, а зависимость с явным шагом.
- **Type consistency:** поля `total_amount`/`count` (накладные), `withdrawals`/`total` (изъятия), id вкладки `withdrawals_cash`, функции `toggleClientCard`/`setInvoicePeriod` согласованы между задачами фронта и бэка.
