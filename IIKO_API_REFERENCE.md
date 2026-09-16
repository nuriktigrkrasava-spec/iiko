# Справочник: как делать запросы к iiko (для проекта iiiko)

Это полный справочник по интеграции с iiko в этом проекте. Источник — реальный код
`iiko.py` и `api.py`. Можно отдать в отдельный чат как контекст.

В проекте ДВА разных API iiko, с разной авторизацией и форматами:

| | iiko Cloud (SaaS) | iiko Server / iikoWeb (самохостед) |
|---|---|---|
| Класс | `IikoClient` | `IikoWebClient` |
| База | `https://api-ru.iiko.services` | `https://{host}/resto` |
| Логин | `POST /api/1/access_token` (JSON) | `GET /api/auth` (query) |
| Токен | `Authorization: Bearer {token}` | `?key={token}` в query |
| Жизнь токена | 14 минут | 25 минут |
| Формат | JSON | JSON (v2) + XML (legacy) |
| Идентификатор филиала | `organizationId` = UUID | `Department` = **имя** (строка) |

**Прод Saya работает на самохостед-сервере** `https://saya-co.iiko.it:443/resto` —
то есть используется `IikoWebClient`. Все 13 филиалов сидят на ОДНОМ сервере под
одним логином и различаются в OLAP только фильтром `Department` (= имя филиала).

---

## 1. Авторизация

### iiko Cloud (`IikoClient`)
```python
POST https://api-ru.iiko.services/api/1/access_token
Headers: Content-Type: application/json
Body:    {"apiLogin": "<api_login>"}
→ {"token": "..."}        # живёт 14 мин, дальше авто-рефреш
```
Все остальные вызовы Cloud — `POST` с заголовком `Authorization: Bearer {token}`.
На 401 токен инвалидируется и запрос повторяется один раз.

### iiko Server (`IikoWebClient`)
```python
GET https://{host}/resto/api/auth?login=<login>&pass=<SHA1(password)>
→ "<токен в виде текста>"   # живёт 25 мин
```
- Пароль передаётся как **SHA1-хеш** (`hashlib.sha1(password).hexdigest()`).
- `verify=False` — самоподписанные сертификаты на самохостед обычны.
- Токен дальше идёт во всех запросах как `?key={token}`.
- Ошибки: 401 → неверный логин/пароль; 404 → это не iikoServer; ConnectError/Timeout → сервер недоступен.

URL нормализуется (`_normalize_iiko_url`): `saya-co.iiko.it` → `https://saya-co.iiko.it/resto`.

---

## 2. OLAP-отчёты (главный инструмент аналитики)

### Cloud
```http
POST /api/1/reports/olap
Authorization: Bearer {token}
{
  "organizationId": "<org-uuid>",
  "settings": {
    "queryFilter": { "dateFrom": "2026-06-14T00:00:00", "dateTo": "2026-06-14T23:59:59" },
    "groupByRowFields": ["OpenDate.Typed", "DishName"],
    "aggregateFields": ["DishAmountSum", "DishCount"]
  }
}
→ {"data": [ {...}, ... ]}
```

### Server (iikoWeb) — то, что реально используется на проде
```http
POST /resto/api/v2/reports/olap?key={token}
{
  "reportType": "SALES",
  "buildSummary": "false",
  "groupByRowFields": ["OpenDate.Typed"],
  "aggregateFields": ["DishAmountSum", "GuestNum", "OrdersCount"],
  "filters": {
    "OpenDate.Typed": {
      "filterType": "DateRange", "periodType": "CUSTOM",
      "from": "2026-06-14", "to": "2026-06-14",
      "includeLow": "true", "includeHigh": "true"
    },
    "OrderDeleted": { "filterType": "IncludeValues", "values": ["NOT_DELETED"] },
    "Department":   { "filterType": "IncludeValues", "values": ["Астана, ул. Г.Алиева 10 (EXPO)"] }
  }
}
→ {"data": [ {...} ]}   (или сразу список)
```

**Типы отчётов (`reportType`):**
- `SALES` — продажи/заказы. Дата режется по `OpenDate.Typed` (дата ОТКРЫТИЯ заказа, календарная).
- `DELIVERIES` — доставка/курьеры.
- `TRANSACTIONS` — проводки (накладные, списания, расходы). Дата режется по `DateTime.OperDayFilter` (учётный/операционный день).

**Типы фильтров:**
- `DateRange` — `periodType: "CUSTOM"`, `from`/`to` в `yyyy-MM-dd`, `includeLow`/`includeHigh`.
- `IncludeValues` — белый список значений (массив).

**Частые поля:**
- Группировка (row): `OpenDate.Typed`, `DishName`, `ProductCategory.Name`, `OrderType.Name`, `Department`, `Conception.Code`, `Delivery.Courier`, `Delivery.CustomerPhone`.
- Агрегаты: `DishAmountSum`, `DishDiscountSumInt` (реально оплачено, после скидок — сходится с кассой), `DishCount`, `OrdersCount`, `GuestNum`, `UniqOrderId.OrdersCount`.

> ⚠️ Для самохостеда `Department` в фильтре — это **имя филиала строкой**, и оно
> должно ТОЧНО совпадать с тем, как департамент назван в iiko. В проекте это имя
> берётся из БД (`organization_name`) через `_olap_dept()`.

---

## 3. ВАЖНО: выручка ≠ OLAP. Касса — это эталон

Главная ловушка iiko:

- **SALES OLAP** считает по `OpenDate.Typed` — дате открытия заказа (календарной).
- **Касса (кассовые смены)** считает по **операционному дню смены**.

Поэтому 1:1 с тем, что видит ресторатор в кассе/Office, совпадает ТОЛЬКО выручка из
кассовых смен. Для шапки дашборда берётся именно она; OLAP — только для гостей/чеков/графика.

### Кассовые смены (только самохостед)
```http
GET /resto/api/v2/cashshifts/list?key={token}
    &openDateFrom=2026-06-14&openDateTo=2026-06-14&status=ANY
→ [ { "id", "sessionNumber", "conceptionId", "payOrders",
      "salesCash", "salesCard", "salesCredit", "sessionStatus",
      "cashDiff", "openDate", "closeDate", ... } ]
```
- **Выручка смены = поле `payOrders`** (= salesCash + salesCard + salesCredit).
- `status=ANY` возвращает в т.ч. ОТКРЫТЫЕ и НЕпринятые смены.
- Эндпоинт возвращает смены **всех филиалов сервера** — фильтра по департаменту тут нет.

```http
GET /resto/api/v2/cashshifts/payments/list/{session_id}?key={token}&hideAccepted=false
→ { "cashlessRecords": [ { "originalSum", "actualSum", "paymentTypeId", ... } ] }
```
Показывает правки платежей при приёмке смены в офисе (original → actual).

### Как один филиал отделяется от других на общем сервере
Цепочка (без имён, детерминированно):
```
Department(имя филиала) ──OLAP Conception.Code──▶ коды концепции
        коды ──get_conceptions() code→id──▶ conceptionId
        смены, где session.conceptionId ∈ target_ids  ──▶ Σ payOrders
```
Если коды не определились: при ≤1 концепции на сервере берём все смены; при >1
(мультифилиальный сервер) — возвращаем `None`, и фронт откатывается на OLAP-сумму.

---

## 4. Справочники и сущности (iikoWeb)

| Эндпоинт | Метод | Что | Формат |
|---|---|---|---|
| `/api/corporation/departments` | GET | департаменты/филиалы | XML |
| `/api/corporation/stores` | GET | склады | XML |
| `/api/v2/entities/list?rootType=PaymentType` | GET | типы оплат | JSON |
| `/api/v2/entities/list?rootType=Conception` | GET | концепции (code↔id) | JSON |
| `/api/v2/entities/list?rootType=MeasureUnit` | GET | единицы измерения | JSON |
| `/api/v2/entities/products/list` | GET | номенклатура (см. ниже про `types`) | JSON |
| `/api/products` | GET | номенклатура (fallback) | XML |
| `/api/suppliers` | GET | поставщики | XML |
| `/api/employees` | GET | сотрудники (id→ФИО) | XML |
| `/api/employees/attendance?from=&to=` | GET | явки | XML |
| `/api/employees/roles` | GET | должности со **ставками** | XML |
| `/api/employees/attendance/types` | GET | типы явок с множителями | XML |

Все — с `?key={token}`. XML парсится `_xml_to_list_of_dicts()`.


### ФОТ: денег в явке нет, ставка лежит на должности (проверено 16.09.2026)

Главное, на чём легко ошибиться: `/api/employees/attendance` **не отдаёт сумм**.
Явка — это только интервал работы. ФОТ собирается из трёх запросов:

```
часы (attendance) × ставка должности (roles) × множитель типа явки (attendance/types)
```

`/api/employees/roles` → `<role>`: `id`, `code`, `name`, **`paymentPerHour`**,
`steadySalary`, `scheduleType` (`SESSION` | `HOURS`), `deleted`.

`/api/employees/attendance/types` → `<attendanceType>`: `id`, `code`, `name`,
**`payRate`** — множитель к ставке. У сети: Ночной 1.2, Праздничный 2.0,
Больничный 0.8, Прогул 0.

В самой явке рядом с часами приезжают `roleId` и `attendanceTypeId` — по ним и
собирается ставка. Плюс `personalDateFrom/To`, `attendanceType` (буква), `comment`.

**`rootType=Role` в `/api/v2/entities/list` НЕ поддерживается** (409 «Following
types are not supported»). Должности берутся только через `/api/employees/roles`.

#### Два подвоха, без которых цифра неверна

1. **Явки задваиваются**, когда сотрудник числится в двух ролях одновременно.
   Часы надо резать по пересечению, а не складывать. Обрезать, а не выбрасывать
   явку целиком: у второй роли своя ставка, и хвост считается по ней.
2. **Отбор по `departmentName` обязателен**: эндпоинт отдаёт явки ВСЕХ филиалов
   сервера, как и `cashshifts`. Запрос — один на сервер, а не на филиал.

#### Ставки заполнены НЕ у всех должностей (замер 07–13.09.2026)

По сети: 12 541 отработанный час, ставкой покрыто **34%**. У 7 должностей из 21
`paymentPerHour` заполнен, у остальных ноль — а ноль значит «не завели», не
«работа бесплатная». Крупнейшие дыры: Кассир (2595 ч), Курьер (1537 ч),
Тех персонал (1298 ч), Администратор (751 ч), Официант (660 ч). Два филиала
(Актау, Актобе) покрыты на 0%.

Поэтому ФОТ везде отдаётся вместе с покрытием в часах: сумма без этого выглядела
бы полной, а она неполная. Закрывается это в iiko Office — заведением ставки
должности; в приложении заводить ничего не нужно.

### Номенклатура: фильтр по типам (проверено на saya-co, 2026-08-23)

```http
GET /resto/api/v2/entities/products/list?key={token}&includeDeleted=false&types=GOODS
```

`types` **работает** и повторяется для нескольких типов (`&types=GOODS&types=SERVICE`).
Без него приезжает весь справочник — на saya-co это 1730 позиций и 7.3 МБ:

| type | что это | сколько на saya-co |
|---|---|---|
| `GOODS` | закупаемые товары — то, что бывает в накладной | 544 |
| `DISH` | блюда меню | 670 |
| `MODIFIER` | модификаторы («без лука») | 296 |
| `PREPARED` | полуфабрикаты (готовятся у себя) | 175 |
| `SERVICE` | услуги | 44 |
| `RATE` | тариф | 1 |

С `types=GOODS` ответ — 544 позиции и 1.2 МБ. Для сопоставления накладных берём
только `GOODS`: блюда и полуфабрикаты поставщик привезти не может, но в поиске
по названию исправно перебивают правильный товар.

Поля позиции: `id`, `name`, `num`, `code`, `type`, `mainUnit`, контейнеры (фасовки).
**`mainUnit` — это UUID**, а не «кг»: название берётся из
`/api/v2/entities/list?rootType=MeasureUnit`. Пока единица оставалась UUID,
сравнение единиц накладной и товара не совпадало никогда.

### Про 401 на `/api/auth`

Сервер отдаёт 401 не только на неверный пароль: частые повторные авторизации
одним логином он какое-то время отклоняет (сессия занята/лимит). Поэтому после
отказа iiko повторять запрос сразу же бессмысленно — в `_nomenclature_catalog`
стоит пауза (`NOMENCLATURE_FAIL_COOLDOWN`, 60с) и работа по последнему снимку
справочника из локальной таблицы `iiko_products`.


---

## 5. Накладные (документы)

### Cloud
```http
POST /api/1/documents/export/invoice_incoming   # выгрузка входящих
POST /api/1/documents/create/incomingInvoice     # создать черновик
POST /api/1/documents/setStatus                  # {organizationId, documentId, status}
```
`status`: `NEW` (черновик) / `PROCESSED` (провести).

### Server (iikoWeb) — XML
```http
POST /api/documents/import/incomingInvoice?key={token}   # тело — XML <document>
GET  /api/documents/export/incomingInvoice?key={token}
POST /api/documents/{id}/setStatus?key={token}&status=...
PUT  /api/documents/{id}/status?key={token}&status=...    # альтернативный путь
```
XML черновика:
```xml
<document>
  <documentNumber>..</documentNumber>
  <dateIncoming>..</dateIncoming>
  <supplier>..</supplier>
  <defaultStore>..</defaultStore>
  <status>NEW</status>
  <comment>..</comment>
  <items>
    <item><num>1</num><product>GUID</product><amount>..</amount>
          <price>..</price><sum>..</sum><store>GUID</store></item>
  </items>
</document>
```
Квирки импорта: ответ не содержит id → id ищется по номеру (`_resolve_incoming_doc_id`);
возможны дубли по номеру; проводка отдельным `setStatus=PROCESSED`.

---

## 6. Минимальный рабочий пример (Python, самохостед)

```python
import hashlib, httpx

BASE = "https://saya-co.iiko.it/resto"
login, password = "<login>", "<password>"

async def main():
    async with httpx.AsyncClient(verify=False, timeout=60) as c:
        # 1) токен
        pw = hashlib.sha1(password.encode()).hexdigest()
        token = (await c.get(f"{BASE}/api/auth",
                             params={"login": login, "pass": pw})).text.strip().strip('"')

        # 2) выручка филиала за вчера из кассовых смен (эталон)
        shifts = (await c.get(f"{BASE}/api/v2/cashshifts/list",
                  params={"key": token, "openDateFrom": "2026-06-14",
                          "openDateTo": "2026-06-14", "status": "ANY"})).json()
        revenue = sum(float(s.get("payOrders") or 0) for s in shifts)  # все филиалы!

        # 3) OLAP продаж за вчера по конкретному филиалу
        body = {"reportType": "SALES", "buildSummary": "false",
                "groupByRowFields": ["OpenDate.Typed"],
                "aggregateFields": ["DishAmountSum", "GuestNum", "OrdersCount"],
                "filters": {
                    "OpenDate.Typed": {"filterType": "DateRange", "periodType": "CUSTOM",
                                       "from": "2026-06-14", "to": "2026-06-14",
                                       "includeLow": "true", "includeHigh": "true"},
                    "OrderDeleted": {"filterType": "IncludeValues", "values": ["NOT_DELETED"]},
                    "Department": {"filterType": "IncludeValues",
                                   "values": ["Астана, ул. Г.Алиева 10 (EXPO)"]}}}
        olap = (await c.post(f"{BASE}/api/v2/reports/olap",
                params={"key": token}, json=body)).json()
```

---

## 7. Готовый клиент в проекте

```python
from iiko import get_client
client = get_client(api_login, iiko_server, api_password)   # вернёт IikoWebClient если задан iiko_server
orgs = await client.get_organizations()
rev  = client.cashshifts_revenue(await client.get_cashshifts("2026-06-14", "2026-06-14"))
r    = await client.olap_report(dept_name, "2026-06-14", "2026-06-14",
                                ["OpenDate.Typed"], ["DishAmountSum"])
```
- `get_client()` кеширует клиентов по ключу `web:{login}@{server}` / `cloud:{login}`.
- Пароли в БД зашифрованы Fernet (`ENCRYPTION_KEY`). Локально ключ ≠ продовому,
  поэтому локально живые запросы к проду не пройдут — отлаживать на деплое.
