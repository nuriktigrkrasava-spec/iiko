# RUNBOOK — куда стучаться (для разработки и будущих сессий)

> Краткая карта проекта + готовые рецепты ad-hoc запросов к iiko и деплоя.
> Обновлено: 2026-06-12.

## 1. Где код и как устроено
- **Локальный путь (актуальный):** `/Users/kiluazoldik/Documents/Work/iiiko`
  (раньше был `Desktop/iiiko` — переехал в `Work/`. Старый клон `~/PycharmProjects/iiko` — МЁРТВЫЙ, от 3 мая, не использовать.)
- **GitHub (прод):** `https://github.com/nuriktigrkrasava-spec/iiko` — именно отсюда собирается Render.
  `nurtirek/iiko` — СТАРЫЙ адрес, на него по-прежнему смотрит локальный `origin`, и пуш туда прод не обновляет.
  Локальный `gh` залогинен как `nurtirek`, доступа к прод-репозиторию у него НЕТ: обычный `git push` падает с
  `Repository not found`, что выглядит как проблема сети. Пушить токеном владельца, разово и не сохраняя:
  `git push "https://<TOKEN>@github.com/nuriktigrkrasava-spec/iiko.git" HEAD:deploy-cashshifts`
  (токен именно в URL: `credential.helper=osxkeychain` молча подставляет `nurtirek`). После пуша токен отозвать.
- **Рабочая ветка:** `deploy-cashshifts` (НЕ `main`).
- **Стек:** FastAPI (`api.py` ~4000 строк), `iiko.py` (клиент iikoServer/iikoWeb), `database.py` (SQLite, сырой sqlite3), `claude_api.py` (Anthropic Vision/чат). Фронт — единый `index.html` (Vanilla JS).

## 2. Деплой (Render)
- Сервис **`iiko`**, serviceId `srv-d96bgc77f7vs73dadd50`, env Python.
  (`srv-d7vh5ipj2pic73eg10mg` из прежней редакции неверен — API отдаёт по нему `not found`.)
- **Auto-deploy с ветки `deploy-cashshifts`** (НЕ main!). Пуш в эту ветку триггерит сборку.
- Render собирает то, что лежит НА ВЕТКЕ. Render API ключом код не задеплоить: `POST /deploys`
  пересоберёт текущий коммит ветки, то есть старый код. Пуш на GitHub обязателен в любом случае.
- Перед пушем: `cd web && npm run build` и коммит `web/dist` — FastAPI отдаёт сайт из собранной
  папки в репозитории. Проверять деплой по имени бандла в HTML (`assets/index-*.js`).
- **БД на проде:** persistent disk, `DB_PATH=/data/iiko_boss.db`. `ENCRYPTION_KEY` (Fernet) шифрует iiko-пароли — должен совпадать локально и на проде.
- **Ручной деплой / статус через Render API** (нужен Render API key `rnd_…`, держится у владельца, в репо НЕ хранить):
  - статусы: `GET https://api.render.com/v1/services/srv-d96bgc77f7vs73dadd50/deploys?limit=5` (заголовок `Authorization: Bearer <rnd_…>`)
  - отмена зависшей сборки: `POST .../deploys/<dep-id>/cancel`
  - Deploy Hook (стартует сборку): `https://api.render.com/deploy/srv-d96bgc77f7vs73dadd50?key=<KEY>`
- **Render Shell** (Dashboard → сервис → Shell): есть `sqlite3` и `python3`, можно читать прод-БД и запускать ad-hoc скрипты.
- Сборки иногда подвисают в `build_in_progress` — лечится отменой зависшей + повторным триггером.

## 3. Ad-hoc запросы к iiko (OLAP) — два способа

### Способ A — локально (быстрее всего, есть креды в локальной БД)
Локальная `iiko_boss.db` содержит рестораны с (зашифрованными) кредами; `.env` содержит `ENCRYPTION_KEY`. Скрипт кладём в корень проекта и запускаем venv-питоном (`.venv/bin/python`). Каркас:

```python
import os, asyncio
for line in open(".env", encoding="utf-8"):
    if line.strip().startswith("ENCRYPTION_KEY="):
        os.environ["ENCRYPTION_KEY"] = line.strip().split("=", 1)[1].strip().strip('"').strip("'")
from database import get_restaurants
from iiko import get_client
import httpx

TID = 8727082281                                  # telegram_id владельца филиалов в локальной БД
ORG = "38abc1d1-bd20-4622-b78e-dd6a78d88706"      # пример: Астана, Г.Алиева 10 (EXPO)

async def main():
    r = next(x for x in get_restaurants(TID) if x["organization_id"] == ORG)
    c = get_client(r["api_login"], r.get("iiko_server"), r.get("api_password"))
    dept = r.get("organization_name") or ORG       # для iikoServer Department = НАЗВАНИЕ филиала
    token = await c._ensure_token()
    payload = { ... }                               # см. рецепты ниже
    async with httpx.AsyncClient(timeout=90, verify=False) as cli:
        resp = await cli.post(c.base_url + "/api/v2/reports/olap", params={"key": token}, json=payload)
    rows = resp.json(); rows = rows if isinstance(rows, list) else rows.get("data", [])
    ...
asyncio.run(main())
```
Запуск: положить как `_tmp.py` в корень → `.venv/bin/python _tmp.py` → удалить файл.

### Способ B — Render Shell (когда нет локальных кредов / нужна прод-БД)
Тот же скрипт, но `DB_PATH` берётся из env (`/data/iiko_boss.db`), `ENCRYPTION_KEY` уже в окружении. Вставлять в Shell через heredoc `python3 << 'EOF' … EOF` (без лишних отступов; закрывающий `EOF` — в начале строки).

### Рецепт 1 — любимые блюда клиентов (DELIVERIES, телефон × блюдо)
```python
payload = {"reportType": "DELIVERIES", "buildSummary": "false",
  "groupByRowFields": ["Delivery.CustomerPhone", "DishName"],
  "aggregateFields": ["UniqOrderId.OrdersCount", "DishDiscountSumInt"],
  "filters": {"OpenDate.Typed": c._date_filter("2026-01-01", "2026-06-12"),
              "Department": {"filterType": "IncludeValues", "values": [dept]}}}
```

### Рецепт 2 — когда заказывают (DELIVERIES, час × дата)
```python
payload = {"reportType": "DELIVERIES", "buildSummary": "false",
  "groupByRowFields": ["HourOpen", "OpenDate.Typed"],
  "aggregateFields": ["UniqOrderId.OrdersCount"],
  "filters": {"OpenDate.Typed": c._date_filter("2026-01-01", "2026-06-12"),
              "Department": {"filterType": "IncludeValues", "values": [dept]}}}
# HourOpen вида "18:00"; день недели = datetime.strptime(OpenDate.Typed[:10], "%Y-%m-%d").weekday() (0=Пн)
```

### Рецепт 3 — во сколько заказывает конкретный клиент (телефон × час)
```python
payload = {"reportType": "DELIVERIES", "buildSummary": "false",
  "groupByRowFields": ["Delivery.CustomerPhone", "HourOpen"],
  "aggregateFields": ["UniqOrderId.OrdersCount"],
  "filters": {"OpenDate.Typed": c._date_filter("2026-01-01", "2026-06-12"),
              "Department": {"filterType": "IncludeValues", "values": [dept]}}}
# Обработка ответа:
#   by[phone] = {"o": сумма заказов, "h": {час: кол-во}}
#   РЕАЛЬНЫЕ клиенты = 5 <= o <= 500  (отсекаем одноразовых <5 и агрегаторов >500)
#   "чаще всего в" = час с максимальным кол-вом (mode); сортировка by по o desc → топ-клиенты
#   PII: телефон НЕ показываем — выводим как «Клиент N».
# Пример вывода (филиал Алиева, 2026, 202 реальных клиента):
#   Клиент 1 — 62 заказа | чаще всего в 17:00 | 17:00×10, 20:00×9, 14:00×8 ...
#   Клиент 2 — 36 заказов | чаще всего в 14:00 (обеденный)
```

## 4. Справочник OLAP-полей (iikoWeb v2 /api/v2/reports/olap)
- **reportType:** `DELIVERIES` (доставки, есть телефон клиента) | `SALES` (все продажи).
- **groupByRowFields:** `Delivery.CustomerPhone`, `DishName`, `HourOpen` ("HH:00"), `OpenDate.Typed` ("YYYY-MM-DD"), `OrderType.Name`, `ProductCategory.Name`, `WaiterName`.
- **aggregateFields:** `UniqOrderId.OrdersCount` (кол-во заказов, DELIVERIES), `OrdersCount` (SALES), `DishDiscountSumInt` (ВЫРУЧКА со скидкой — сходится с кассой), `DishAmountSum`, `GuestNum`, `DishCount`.
- **Department:** для iikoServer фильтруется по НАЗВАНИЮ филиала (`organization_name`), в облаке — по UUID. В коде это `_olap_dept(real_org, info)`.
- Готовый метод-обёртка SALES: `client.olap_report(dept, date_from, date_to, group_by=[...], aggregates=[...])`.

## 5. Подводные камни данных (важно!)
- **Агрегаторы маскируются под одного клиента:** топ-телефоны по числу заказов (тысячи заказов) — это НЕ люди, а Wolt/Яндекс/колл-центр. Для «реальных гостей» фильтровать аномальные/пустые номера (порог: например ≤ N заказов/мес).
- **`DishName` шумный:** строки с «−» в начале — это модификаторы/добавки («−Кока кола», «−соус»), не основные блюда. Для «любимых блюд» отсекать модификаторы.
- **Выручка:** только `DishDiscountSumInt` (после скидок) сходится с кассой; `DishSumInt`/`DishAmountSum` — до скидок, не сходятся.

## 6. Где что в коде
- **Клиенты/лояльность + RFM:** `api.py` → `clients_loyalty` (`/api/clients/{org_id}`), `_clients_segments`, `_compute_rfm`; OLAP — `iiko.py` → `olap_clients`, `olap_clients_rfm`. Фронт — `index.html` → `renderClients`.
- **Час пик (дни×часы):** `api.py` → `/api/load-heatmap`; фронт — `index.html` → `loadHeatmap` (вкладка Персонал → «Час пик»).
- **Накладные (бот → редактор → iiko):** распознавание `claude_api.py` → `analyze_invoice_photos`; создание черновика `iiko.py` → `create_incoming_invoice`; список `/api/invoices/{org_id}`; редактор — `index.html` `ie*`-функции.
- **Выручка дашборда:** из кассовых смен (`cashshifts/list`), `/api/revenue`.

## 7. Известные открытые баги/долги
- `create_incoming_invoice` (iikoServer) не всегда возвращает `documentId` → `iiko_doc_id` пустой → in-app «Провести» (`/api/invoices/{id}/post`) не работает; проводят вручную в iikoOffice. Диагностика тела ответа добавлена (лог при пустом documentId).
- `set_document_status` (проводка) перебирает 2 URL «наугад» — точный путь зависит от версии iikoServer.
- Почти нет автотестов; `api.py`/`index.html` — монолиты.

## 8. Секреты
Не хранятся в репо. GitHub PAT, Render API key, Deploy Hook key — у владельца (передаются по запросу, периодически ротируются). `.env` (локально) и Render Environment — содержат `ENCRYPTION_KEY`, `TELEGRAM_BOT_TOKEN`, `ANTHROPIC_API_KEY` и т.д.
