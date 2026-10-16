# Фудкост по техкартам — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Считать теоретический фудкост-% для самохостед iikoWeb-клиентов (без лицензии `DishCostSumInt`) из техкарт (`getPrepared`) и учётных цен ингредиентов (`balance/stores`), и показывать его на вкладке Расходы вместо «недоступно».

**Architecture:** Новые методы `IikoWebClient` тянут номенклатуру, техкарты и цены с iikoServer. Чистая функция свёртки считает себестоимость (нормы × цены), фудкост-% и покрытие. Оркестратор в `api.py` подключается в существующий `/api/foodcost` как ветка «нет `supports_cost`», с кешем результата на сутки и расчётом по кнопке. Фронт добавляет кнопку «Посчитать фудкост» и плашку покрытия.

**Tech Stack:** Python 3.12, FastAPI, httpx (async, verify=False — самоподписанные iiko-серты), iikoServer REST `/resto/api/v2/`, ванильный JS в `index.html`.

## Global Constraints

- **Только для самохостед** (`IikoWebClient`, `supports_cost=False`). Облачный путь (`IikoClient`, `supports_cost=True`) в `/api/foodcost` НЕ трогаем.
- **Норма:** `NORM_PCT = 30` (как сейчас, `api.py:1730`).
- **Период:** месяц (существующий `period="month"`).
- **Триггер:** расчёт по кнопке + кеш результата на **сутки** (не считать на каждом открытии вкладки).
- **Себестоимость ингредиента = `Σsum / Σamount`** из `reports/balance/stores` (агрегат по продукту; продукты с `amount<=0` пропускаем).
- **Техкарта:** `getPrepared` → `preparedCharts[0].items` = `[{productId, amount}]` (норма на 1 порцию, уже развёрнуто до сырья).
- **Матчинг блюдо→productId:** карта `имя(lower)→productId` из `/api/v2/entities/products/list` (type=DISH), кеш.
- **Честность:** покрытие = доля выручки, полностью посчитанной; блюдо без техкарты или с неоценёнными ингредиентами не считается «покрытым». Никогда не показываем выдуманный 0%.
- **Подпись фичи:** «теоретический фудкост по техкартам».
- **httpx:** все вызовы iikoServer — `verify=False`, через существующий `_ensure_token()`.
- **Тестов нет (pytest не установлен).** Чистые функции — verify-скрипты с ассертами на моках. Сетевые методы — `py_compile` + факт, что live-probe уже подтвердил доступность endpoint'ов. Живые вызовы к проду в субагентах НЕ выполняем.

Спека: `docs/superpowers/specs/2026-07-01-foodcost-by-recipes-design.md`.

---

### Task 1: IikoWebClient — номенклатура, техкарты, цены

**Files:**
- Modify: `iiko.py` (методы в классе `IikoWebClient`, рядом с `get_nomenclature` `iiko.py:717`)
- Verify: `scratchpad/verify_iiko_helpers.py` (чистые парс-хелперы на моках)

**Interfaces:**
- Produces:
  - `IikoWebClient._aggregate_stock_prices(rows: list) -> dict[str, float]` (чистая: `{productId: Σsum/Σamount}`)
  - `IikoWebClient._products_name_map(products: list) -> dict[str, str]` (чистая: `{name.lower(): productId}` для type==DISH)
  - `async IikoWebClient.get_products(self) -> list[dict]` (GET products/list)
  - `async IikoWebClient.get_dish_name_map(self) -> dict[str,str]`
  - `async IikoWebClient.get_assembly_prepared(self, product_id: str, date: str) -> list[dict]` (`[{productId, amount}]`)
  - `async IikoWebClient.get_stock_prices(self) -> dict[str, float]`

- [ ] **Step 1: Написать verify-скрипт для чистых хелперов**

Создать `scratchpad/verify_iiko_helpers.py`:

```python
import os, sys, tempfile
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "x.db")
sys.path.insert(0, "/path/to/workspace/Work/iiiko")
from iiko import IikoWebClient

agg = IikoWebClient._aggregate_stock_prices
# два склада одного продукта: (2.5, 7400) + (1.5, 4600) => (12000)/(4.0)=3000
rows = [
    {"product": "p1", "amount": 2.5, "sum": 7400},
    {"product": "p1", "amount": 1.5, "sum": 4600},
    {"product": "p2", "amount": 0, "sum": 500},     # amount<=0 -> пропуск
    {"product": "p3", "amount": 4.0, "sum": 800},   # 200
]
pr = agg(rows)
assert round(pr["p1"], 2) == 3000.0, pr
assert "p2" not in pr, pr
assert round(pr["p3"], 2) == 200.0, pr

nm = IikoWebClient._products_name_map
prods = [
    {"id": "d1", "name": "Боул", "type": "DISH"},
    {"id": "g1", "name": "Соль", "type": "GOODS"},   # не блюдо -> пропуск
    {"id": "d2", "name": "Латте", "type": "DISH"},
]
m = nm(prods)
assert m == {"боул": "d1", "латте": "d2"}, m
print("OK verify_iiko_helpers")
```

- [ ] **Step 2: Запустить (упадёт — методов нет)**

Run: `python3 scratchpad/verify_iiko_helpers.py`
Expected: `AttributeError: ... _aggregate_stock_prices` (метода ещё нет)

- [ ] **Step 3: Реализовать методы в `IikoWebClient`**

После `get_nomenclature` (`iiko.py:718`) добавить:

```python
    @staticmethod
    def _aggregate_stock_prices(rows: List[Dict[str, Any]]) -> Dict[str, float]:
        """Из строк balance/stores → {productId: средняя себестоимость = Σsum/Σamount}."""
        acc: Dict[str, List[float]] = {}
        for r in rows or []:
            pid = r.get("product")
            amt = float(r.get("amount", 0) or 0)
            summ = float(r.get("sum", 0) or 0)
            if not pid or amt <= 0:
                continue
            a = acc.setdefault(pid, [0.0, 0.0])
            a[0] += summ
            a[1] += amt
        return {pid: (s / a) for pid, (s, a) in acc.items() if a > 0}

    @staticmethod
    def _products_name_map(products: List[Dict[str, Any]]) -> Dict[str, str]:
        """{имя блюда в нижнем регистре: productId} только для type==DISH."""
        out: Dict[str, str] = {}
        for p in products or []:
            if (p.get("type") == "DISH") and p.get("id") and p.get("name"):
                out[str(p["name"]).strip().lower()] = p["id"]
        return out

    async def get_products(self) -> List[Dict[str, Any]]:
        token = await self._ensure_token()
        async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
            resp = await client.get(
                f"{self.base_url}/api/v2/entities/products/list",
                params={"key": token, "includeDeleted": "false"}
            )
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else data.get("data", [])

    async def get_dish_name_map(self) -> Dict[str, str]:
        return self._products_name_map(await self.get_products())

    async def get_assembly_prepared(self, product_id: str, date: str) -> List[Dict[str, Any]]:
        """Развёрнутая техкарта блюда на дату → [{productId, amount(норма на 1 порцию)}]."""
        token = await self._ensure_token()
        async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
            resp = await client.get(
                f"{self.base_url}/api/v2/assemblyCharts/getPrepared",
                params={"key": token, "date": date, "productId": product_id}
            )
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            charts = (resp.json() or {}).get("preparedCharts") or []
            if not charts:
                return []
            items = charts[0].get("items") or []
            return [{"productId": it.get("productId"), "amount": float(it.get("amount", 0) or 0)}
                    for it in items if it.get("productId")]

    async def get_stock_prices(self) -> Dict[str, float]:
        """Учётная себестоимость по ингредиентам из остатков складов."""
        token = await self._ensure_token()
        ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S.000")
        async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
            resp = await client.get(
                f"{self.base_url}/api/v2/reports/balance/stores",
                params={"key": token, "timestamp": ts}
            )
            resp.raise_for_status()
            data = resp.json()
            rows = data if isinstance(data, list) else data.get("data", [])
            return self._aggregate_stock_prices(rows)
```

(`datetime` и `httpx` уже импортированы в `iiko.py` — используются выше в файле.)

- [ ] **Step 4: Запустить verify — должно пройти**

Run: `python3 scratchpad/verify_iiko_helpers.py`
Expected: `OK verify_iiko_helpers`

- [ ] **Step 5: Smoke-компиляция**

Run: `python3 -m py_compile iiko.py`
Expected: без вывода

- [ ] **Step 6: Commit**

```bash
git add iiko.py
git commit -m "feat(foodcost): IikoWebClient — products/list, getPrepared техкарты, balance/stores цены"
```

---

### Task 2: Чистая свёртка расчёта фудкоста (отдельный модуль)

**Files:**
- Create: `foodcost_calc.py` (новый маленький модуль, только чистая функция — без зависимостей от api.py/FastAPI, чтобы легко тестировался)
- Verify: `scratchpad/verify_foodcost_calc.py`

**Interfaces:**
- Consumes: ничего (чистая функция, без импортов проекта).
- Produces:
  `compute_recipe_foodcost(sales: list, recipes: dict, prices: dict) -> dict`
  где `sales=[{"productId","name","category","revenue","count"}]`,
  `recipes={dish_pid: [{"productId","amount"}]}`, `prices={pid: unit_cost}`.
  Возвращает `{"fact_sum", "base_rev", "fact_pct", "coverage_pct", "dishes":[{name,category,revenue,count,cost_pct}]}`.

- [ ] **Step 1: Написать verify-скрипт**

Создать `scratchpad/verify_foodcost_calc.py`:

```python
import sys
sys.path.insert(0, "/path/to/workspace/Work/iiiko")
from foodcost_calc import compute_recipe_foodcost as f

# Блюдо А: 2 ингр, оба с ценой. норма*цена = 0.05*3000 + 0.1*200 = 150+20 = 170 за порцию.
# продано 10 -> cost 1700, выручка 5000
# Блюдо Б: ингр без цены -> частично; норма 0.2, цены нет -> cost 0, НЕ покрыто. выручка 3000, продано 5
# Блюдо В: нет техкарты -> пропуск в базе. выручка 2000
sales = [
    {"productId":"A","name":"A","category":"кухня","revenue":5000,"count":10},
    {"productId":"B","name":"B","category":"бар","revenue":3000,"count":5},
    {"productId":"C","name":"C","category":"кухня","revenue":2000,"count":4},
]
recipes = {
    "A":[{"productId":"i1","amount":0.05},{"productId":"i2","amount":0.1}],
    "B":[{"productId":"i3","amount":0.2}],
    # C — техкарты нет
}
prices = {"i1":3000.0, "i2":200.0}   # i3 без цены
r = f(sales, recipes, prices)
assert round(r["fact_sum"]) == 1700, r          # только A посчитан по цене
assert round(r["base_rev"]) == 8000, r          # A(5000)+B(3000) имеют техкарту; C нет
assert r["fact_pct"] == round(1700/8000*100,1), r
# покрытие = выручка полностью-оценённых блюд / вся выручка продаж = 5000 / 10000 = 50%
assert r["coverage_pct"] == 50.0, r
da = next(d for d in r["dishes"] if d["name"]=="A")
assert da["cost_pct"] == round(1700/5000*100,1), da
# выручка 0 -> fact_pct None
assert f([], {}, {})["fact_pct"] is None
print("OK verify_foodcost_calc")
```

- [ ] **Step 2: Запустить (упадёт — модуля нет)**

Run: `python3 scratchpad/verify_foodcost_calc.py`
Expected: `ModuleNotFoundError: No module named 'foodcost_calc'`

- [ ] **Step 3: Создать модуль `foodcost_calc.py`**

Создать файл `foodcost_calc.py` с содержимым:

```python
"""Чистый расчёт теоретического фудкоста из техкарт и цен. Без зависимостей от приложения."""


def compute_recipe_foodcost(sales: list, recipes: dict, prices: dict) -> dict:
    """Теоретический фудкост из техкарт и цен.
    sales=[{productId,name,category,revenue,count}], recipes={pid:[{productId,amount}]}, prices={pid:cost}.
    base_rev — выручка блюд, у которых ЕСТЬ техкарта (их можно оценить).
    coverage_pct — доля ВСЕЙ выручки продаж, приходящаяся на полностью оценённые блюда.
    """
    total_sold_rev = 0.0
    base_rev = 0.0
    fact_sum = 0.0
    covered_rev = 0.0
    out_dishes = []
    for s in sales:
        rev = float(s.get("revenue", 0) or 0)
        cnt = float(s.get("count", 0) or 0)
        total_sold_rev += rev
        recipe = recipes.get(s.get("productId"))
        if not recipe:
            out_dishes.append({"name": s.get("name", ""), "category": s.get("category", ""),
                               "revenue": rev, "count": cnt, "cost_pct": None})
            continue
        base_rev += rev
        cost_per_portion = 0.0
        all_priced = True
        for ing in recipe:
            price = prices.get(ing.get("productId"))
            if price is None:
                all_priced = False
                continue
            cost_per_portion += float(ing.get("amount", 0) or 0) * float(price)
        dish_cost = cost_per_portion * cnt
        fact_sum += dish_cost
        if all_priced and recipe:
            covered_rev += rev
        out_dishes.append({
            "name": s.get("name", ""), "category": s.get("category", ""),
            "revenue": rev, "count": cnt,
            "cost_pct": (round(dish_cost / rev * 100, 1) if rev else None),
        })
    fact_pct = round(fact_sum / base_rev * 100, 1) if base_rev else None
    coverage_pct = round(covered_rev / total_sold_rev * 100, 1) if total_sold_rev else 0.0
    out_dishes.sort(key=lambda d: (d["cost_pct"] if d["cost_pct"] is not None else -1), reverse=True)
    return {"fact_sum": fact_sum, "base_rev": base_rev, "fact_pct": fact_pct,
            "coverage_pct": coverage_pct, "dishes": out_dishes}
```

- [ ] **Step 4: Запустить verify — должно пройти**

Run: `python3 scratchpad/verify_foodcost_calc.py`
Expected: `OK verify_foodcost_calc`

- [ ] **Step 5: Smoke-компиляция**

Run: `python3 -m py_compile foodcost_calc.py`
Expected: без вывода

- [ ] **Step 6: Commit**

```bash
git add foodcost_calc.py
git commit -m "feat(foodcost): чистая свёртка compute_recipe_foodcost (нормы×цены, покрытие)"
```

---

### Task 3: Оркестратор + гейт в /api/foodcost

**Files:**
- Modify: `api.py` (оркестратор рядом с `_compute_recipe_foodcost`; ветка в `foodcost()` `api.py:1693`)

**Interfaces:**
- Consumes: `IikoWebClient.get_dish_name_map/get_assembly_prepared/get_stock_prices` (Task 1), `compute_recipe_foodcost` из `foodcost_calc` (Task 2), существующие `_foodcost_month`, `local_now`, `NORM_PCT`, кеш `_cache_key/_get_cached/_set_cached`, `get_client`.
- Produces: `async _foodcost_from_recipes(client, org_id, date_from, date_to) -> dict`.

- [ ] **Step 1: Добавить импорт и оркестратор**

В `api.py` рядом с прочими импортами из локальных модулей (напр. рядом с `from database import (...)`, `api.py:28`) добавить:

```python
from foodcost_calc import compute_recipe_foodcost
```

Затем после `_foodcost_month` (`api.py:770`) добавить оркестратор:

```python
# кеш техкарт: {(base_url, productId): (ts, items)}; техкарты меняются редко
_recipe_cache: Dict[tuple, tuple] = {}
_RECIPE_TTL = 24 * 3600

async def _get_recipe_cached(client, product_id: str, date: str) -> list:
    ck = (getattr(client, "base_url", ""), product_id)
    hit = _recipe_cache.get(ck)
    now = int(datetime.now().timestamp())
    if hit and now - hit[0] < _RECIPE_TTL:
        return hit[1]
    items = await client.get_assembly_prepared(product_id, date)
    _recipe_cache[ck] = (now, items)
    return items


async def _foodcost_from_recipes(client, org_id: str, date_from: str, date_to: str) -> dict:
    """Теоретический фудкост для самохостед iikoWeb: продажи×техкарты×цены."""
    # 1) продажи по блюдам за период
    sales_raw = await _foodcost_month(client, org_id, date_from, date_to)
    dishes_sold = sales_raw[0]        # [{name, category, revenue, count, cost_pct=None}]
    # 2) карта имя->productId и цены (параллельно)
    name_map, prices = await asyncio.gather(client.get_dish_name_map(), client.get_stock_prices())
    # 3) собираем sales с productId и тянем техкарты только по проданным
    date_for_recipe = date_to[:10]
    sales = []
    for d in dishes_sold:
        pid = name_map.get(str(d.get("name", "")).strip().lower())
        sales.append({"productId": pid, "name": d.get("name", ""),
                      "category": d.get("category", ""),
                      "revenue": d.get("revenue", 0), "count": d.get("count", 0)})
    recipes = {}
    pids = [s["productId"] for s in sales if s["productId"]]
    # пачками по 6 параллельно
    for i in range(0, len(pids), 6):
        batch = pids[i:i + 6]
        got = await asyncio.gather(*[_get_recipe_cached(client, p, date_for_recipe) for p in batch],
                                   return_exceptions=True)
        for p, items in zip(batch, got):
            recipes[p] = [] if isinstance(items, Exception) else items
    return compute_recipe_foodcost(sales, recipes, prices)
```

- [ ] **Step 2: Подключить ветку в `foodcost()`**

В `foodcost()` найти ветку, где `cost_available` False (сейчас `api.py:1755-1770`, `else:` с warning). Заменить её тело так, чтобы при `?compute=1` считать по техкартам, иначе — вернуть лёгкий ответ «нужен расчёт». Изменить сигнатуру эндпоинта, добавив параметр `compute`:

Сигнатуру `api.py:1694` заменить на:
```python
async def foodcost(org_id: str, period: str = "month", compute: int = 0, user: Dict = Depends(get_current_user)):
```

Блок `else:` (ветка «нет себестоимости», `api.py:1756-1770`) заменить на:
```python
        else:
            # Самохостед iikoWeb: считаем теоретический фудкост по техкартам.
            if not compute:
                resp = {
                    "norm_pct": NORM_PCT, "fact_pct": None, "diff_pct": None,
                    "norm_sum": round(total_rev * NORM_PCT / 100), "fact_sum": None,
                    "warning": None, "cost_available": False, "needs_compute": True,
                    "method": "recipes", "trend": trend, "dishes": dishes[:20],
                }
                return resp  # НЕ кешируем «заглушку» — расчёт по кнопке
            rec = await _foodcost_from_recipes(client, _olap_dept(real_org, info), date_from, date_to)
            fpct = rec["fact_pct"]
            resp = {
                "norm_pct": NORM_PCT,
                "fact_pct": fpct,
                "diff_pct": (round(fpct - NORM_PCT, 1) if fpct is not None else None),
                "norm_sum": round((rec["base_rev"] or total_rev) * NORM_PCT / 100),
                "fact_sum": round(rec["fact_sum"]),
                "coverage_pct": rec["coverage_pct"],
                "warning": (None if rec["coverage_pct"] >= 70 else
                            f"Оценка неполная: посчитано {rec['coverage_pct']}% выручки. "
                            f"Добавьте приходные цены/техкарты в iiko."),
                "cost_available": True, "method": "recipes",
                "trend": trend, "dishes": rec["dishes"][:20],
            }
```

(Существующие строки ниже — `_set_cached(key, resp); return resp` — остаются и кешируют посчитанный результат. Лёгкая «заглушка» с `needs_compute` возвращается раньше и в кеш не попадает.)

- [ ] **Step 3: Smoke-компиляция**

Run: `python3 -m py_compile api.py`
Expected: без вывода

- [ ] **Step 4: Проверка целостности ответа (структура)**

Run:
```bash
python3 -c "import ast; t=ast.parse(open('api.py').read()); print('parse ok')"
```
Expected: `parse ok`

- [ ] **Step 5: Ручная проверка (владелец, на реальном сервере)**

На самохостед-аккаунте открыть Расходы → Фудкост: без `compute` приходит `needs_compute:true` (кнопка); с `?compute=1` — реальный `fact_pct`, `coverage_pct`, топ блюд. Проверить, что iiko не дёргается на каждом открытии (только по кнопке), а повторный запрос отдаёт из кеша.

- [ ] **Step 6: Commit**

```bash
git add api.py
git commit -m "feat(foodcost): оркестратор _foodcost_from_recipes + гейт compute/кеш в /api/foodcost"
```

---

### Task 4: UI — кнопка «Посчитать фудкост» и покрытие

**Files:**
- Modify: `index.html` (`#tab-foodcost` разметка `1006-1055`; `loadExpenses` foodcost-ветка `3407-3435`)

**Interfaces:**
- Consumes: `/api/foodcost/{org}?period=month` (+`&compute=1`), поля `needs_compute`, `coverage_pct`, `method`.

- [ ] **Step 1: Добавить кнопку и плашку покрытия в разметку**

В `#tab-foodcost` сразу после `<div class="warn-banner" id="foodcost-warning" ...>...</div>` (`index.html:1010`) добавить:

```html
      <div id="fc-compute-box" style="display:none; text-align:center; margin:16px 0;">
        <button class="excel-btn" style="padding:12px 20px; font-size:15px;"
                onclick="computeFoodcost()">📊 Посчитать фудкост по техкартам</button>
        <div style="font-size:12px; color:var(--text-secondary); margin-top:8px;">
          Считается из ваших техкарт и приходных цен. Займёт несколько секунд.</div>
      </div>
      <div id="fc-coverage" style="display:none; font-size:12px; color:var(--text-secondary); margin:4px 0 12px; text-align:center;"></div>
```

- [ ] **Step 2: Обновить рендер `loadExpenses` (foodcost-ветка)**

В `loadExpenses`, foodcost-ветку (`index.html:3407` далее) заменить блок получения/рендера на вариант с поддержкой `needs_compute` и `coverage`. Заменить строки `3409-3421` на:

```javascript
      const data = await apiGet(`/api/foodcost/${orgId}?period=month`);
      if (data && data._iiko_error) { showIikoError(data._iiko_error); return; }
      window._fcOrgId = orgId;
      const needsCompute = data.needs_compute === true;
      document.getElementById('fc-compute-box').style.display = needsCompute ? 'block' : 'none';
      const cov = document.getElementById('fc-coverage');
      if (!needsCompute && typeof data.coverage_pct === 'number') {
        cov.style.display = 'block';
        cov.textContent = `Теоретический фудкост по техкартам · посчитано ${data.coverage_pct}% выручки`;
      } else { cov.style.display = 'none'; }
      const costNA = needsCompute || data.cost_available === false || data.fact_pct === null;
      document.getElementById('fc-norm-pct').textContent = data.norm_pct + '%';
      document.getElementById('fc-fact-pct').textContent = costNA ? '—' : data.fact_pct + '%';
      document.getElementById('fc-diff-pct').textContent = costNA ? '—'
        : ((data.diff_pct >= 0 ? '+' : '') + data.diff_pct + '%');
      document.getElementById('fc-norm-sum').textContent = formatMoney(data.norm_sum);
      document.getElementById('fc-fact-sum').textContent = costNA ? '—' : formatMoney(data.fact_sum);
      if (data.warning) {
        document.getElementById('foodcost-warning').style.display = 'flex';
        document.getElementById('foodcost-warning-text').textContent = data.warning;
      } else { document.getElementById('foodcost-warning').style.display = 'none'; }
```

- [ ] **Step 3: Добавить функцию `computeFoodcost`**

Перед функцией `loadExpenses` (`index.html:3403`) добавить:

```javascript
async function computeFoodcost() {
  const orgId = window._fcOrgId || (state.restaurant && state.restaurant.organization_id);
  if (!orgId) return;
  const box = document.getElementById('fc-compute-box');
  box.innerHTML = '<div style="padding:12px; color:var(--text-secondary);">⏳ Считаю фудкост по техкартам…</div>';
  try {
    const data = await apiGet(`/api/foodcost/${orgId}?period=month&compute=1`);
    if (data && data._iiko_error) { showIikoError(data._iiko_error); return; }
    await loadExpenses();  // перерисует уже с посчитанными данными (из кеша)
  } catch (e) {
    box.innerHTML = '<div style="padding:12px; color:var(--red);">Не удалось посчитать. Попробуйте ещё раз.</div>';
  }
}
```

- [ ] **Step 4: Smoke-проверка синтаксиса HTML/JS**

Run: `python3 -c "s=open('index.html').read(); assert 'computeFoodcost' in s and 'fc-compute-box' in s and 'fc-coverage' in s; print('ok')"`
Expected: `ok`

- [ ] **Step 5: Ручная проверка (владелец)**

Расходы → Фудкост на самохостед-аккаунте: видна кнопка «Посчитать фудкост»; нажатие → спиннер → реальный %, плашка «посчитано X% выручки», топ блюд; повторное открытие вкладки — сразу из кеша, кнопка скрыта.

- [ ] **Step 6: Commit**

```bash
git add index.html
git commit -m "feat(foodcost): UI — кнопка Посчитать фудкост + плашка покрытия"
```

---

## Self-Review

**Spec coverage:**
- Методы клиента (getPrepared, balance/stores цены, products/list) — Task 1 ✓
- Свёртка нормы×цены, покрытие, топ блюд — Task 2 ✓
- Гейт supports_cost, кнопка+кеш сутки, оркестратор — Task 3 ✓
- UI вкладки Расходы, кнопка, покрытие, «теоретический» подпись — Task 4 ✓
- Краевые случаи (нет техкарты → пропуск; нет цены → покрытие вниз; выручка 0 → fact_pct None; покрытие<70% → warning) — Task 2 (расчёт) + Task 3 (warning) ✓
- Нагрузка (только проданные, кеш техкарт 24ч, пачки по 6) — Task 3 ✓
- Не трогаем облачный путь — Task 3 гейт `if cost_available` (облако) остаётся ✓

**Открытые допущения (не блокеры):**
- Матчинг блюдо→productId по имени (Task 3): если в номенклатуре дубли имён — возьмётся последний. Приемлемо для MVP; при реализации, если у iikoWeb OLAP есть измерение GUID блюда (`DishId`), можно уточнить и заменить маппинг. Не блокирует.
- Fallback цен из `bot_invoices` для нулевых остатков — этап 2 спеки, в этот план НЕ входит (осознанно): MVP использует только `balance/stores`, непокрытое честно уходит в `coverage_pct`.

**Type consistency:** `compute_recipe_foodcost` (в `foodcost_calc.py`) возвращает `fact_sum/base_rev/fact_pct/coverage_pct/dishes` — ровно эти ключи читает Task 3. `get_dish_name_map/get_assembly_prepared/get_stock_prices` — сигнатуры совпадают между Task 1 (опр.) и Task 3 (вызов). Поля ответа (`needs_compute/coverage_pct/method`) — согласованы между Task 3 (бэк) и Task 4 (фронт).
