# Суб-вкладка «saya-kds» (аналитика доставки/кухни) — дизайн

Дата: 2026-06-28
Ветка прода: `deploy-cashshifts`

## Цель

Подключить внешний экспорт аналитики saya-kds
(`GET https://saya-kds.onrender.com/admin/analytics/export`) в Telegram-мини-апп
новой суб-вкладкой **«saya-kds»** под главной вкладкой «Сотрудники». Вкладка
видна только двум пользователям: Telegram id `123456789` и `123456789`.

Контент: нагрузка по часам/зонам, SLA + этапы пути, кухня по зонам с
сотрудниками, аномалии + журнал.

## Контекст / факты кодовой базы

- Фронт — один файл `index.html` (vanilla JS, Telegram WebApp SDK, Chart.js).
- Сабтабы Staff заданы на строках 885–888; контейнеры `staff-view-*`;
  обработчик `setStaffSubtab(view, el)` (строка 3027) переключает массив
  `['waiters','couriers','heatmap']` и лениво грузит данные.
- Существует локальная суб-вкладка «Час пик» (`heatmap`) — НЕ трогаем, это
  отдельный локальный хитмап для всех пользователей.
- Текущий tg-id: `getMyTgId()` (строка 1746). Пример гейтинга по id —
  `PLAN_BRANCH_SWITCHER_TG_ID` (строка 1745, использование 3636).
- Фронт зовёт бэк через `apiGet(path)` (шлёт `X-Telegram-Init-Data`),
  `API_BASE=''` (тот же хост).
- Бэк — `api.py` (FastAPI). Аутентификация — `Depends(get_current_user)`
  (строка 197); при отсутствии init data и заданном `BOT_TOKEN` → 401.
- HTTP-клиент — `httpx.AsyncClient` (уже импортирован, строка 3). Env читается
  через `os.getenv(...)` в начале файла.
- Эндпоинт saya-kds — во **внешнем** сервисе, НЕ в этом репо. Защищён
  заголовком `X-API-Key`; без ключа на той стороне → 503; неверный ключ → 401.

## Архитектура

Ключ `X-API-Key` НЕ должен попадать в браузер. Поэтому добавляем тонкий
серверный прокси в `api.py`; фронт ходит к своему бэку обычным
`X-Telegram-Init-Data`-путём.

```
Браузер (мини-апп)                 Бэк этого репо (api.py)            saya-kds
  apiGet('/api/chaspik')  ──X-Tg-Init──►  GET /api/chaspik
                                            ├─ проверка tg-id ∈ {2 id} → иначе 403
                                            ├─ нет ANALYTICS_API_KEY / CHASPIK_ORG_ID → 503
                                            └─ GET /admin/analytics/export
                                                 ?org_id=CHASPIK_ORG_ID&from&to&sla_minutes
                                                 header X-API-Key  ──────────────────►  JSON
                                            ◄─ прозрачно вернуть JSON ◄────────────────────
  ◄─ JSON saya-kds
```

### Бэкенд (`api.py`)

Новые env (читаются рядом с другими `os.getenv`, ~строки 97–107):
- `ANALYTICS_API_KEY` — секрет для заголовка `X-API-Key` (тот же, что на
  saya-kds).
- `CHASPIK_ORG_ID` — id организации (филиал Алиева) для параметра `org_id`.
- `CHASPIK_BASE_URL` — дефолт `https://saya-kds.onrender.com`.

Константа доступа: `CHASPIK_TG_IDS = {123456789, 123456789}`.

Новый эндпоинт:

```python
@app.get("/api/chaspik")
async def chaspik_export(
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
    sla_minutes: Optional[int] = Query(None),
    user: Dict = Depends(get_current_user),
):
    if int(user.get("id", 0)) not in CHASPIK_TG_IDS:
        raise HTTPException(status_code=403, detail="forbidden")
    if not ANALYTICS_API_KEY or not CHASPIK_ORG_ID:
        raise HTTPException(status_code=503,
            detail="saya-kds выгрузка не настроена (нет ANALYTICS_API_KEY или CHASPIK_ORG_ID)")
    params = {"org_id": CHASPIK_ORG_ID}
    if from_: params["from"] = from_
    if to: params["to"] = to
    if sla_minutes is not None: params["sla_minutes"] = sla_minutes
    try:
        async with httpx.AsyncClient(timeout=60.0) as c:
            r = await c.get(f"{CHASPIK_BASE_URL}/admin/analytics/export",
                            params=params, headers={"X-API-Key": ANALYTICS_API_KEY})
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"saya-kds недоступен: {e}")
    if r.status_code != 200:
        raise HTTPException(status_code=502,
            detail=f"saya-kds {r.status_code}: {r.text[:200]}")
    return r.json()
```

Поведение:
- Прозрачный прокси: тело saya-kds возвращается как есть.
- Дефолты периода (7 дней / сегодня / sla 45) НЕ дублируем на нашей стороне —
  их выставляет saya-kds, если параметры не переданы.
- Ошибки upstream сворачиваем в `502` с коротким текстом (без утечки ключа).

### Фронтенд (`index.html`)

Константа доступа (рядом с `PLAN_BRANCH_SWITCHER_TG_ID`, строка 1745):
```js
const CHASPIK_TG_IDS = [123456789, 123456789];
```

1. **Кнопка сабтаба** (после строки 888). Рендерится в DOM только для
   разрешённых id. Простейший способ без рефактора разметки — добавить кнопку
   статически, но скрыть/удалить её при инициализации, если id не подходит.
   Реализация: добавить
   `<div class="subtab" id="staff-sub-kds" onclick="setStaffSubtab('kds', this)">saya-kds</div>`
   и в init-коде (там же, где решается видимость switcher'а) выполнить
   `if (!CHASPIK_TG_IDS.includes(getMyTgId())) document.getElementById('staff-sub-kds')?.remove();`.

2. **Контейнер** (после `staff-view-heatmap`, ~строка 952):
   `<div id="staff-view-kds" style="display:none"> … 4 карточки … </div>`.

3. **Обработчик** `setStaffSubtab` (строка 3027): массив →
   `['waiters','couriers','heatmap','kds']`; добавить
   `if (view === 'kds') loadChaspik();`.

4. **`loadChaspik()`** (по образцу `loadHeatmap`, строка 3040):
   - `const data = await apiGet('/api/chaspik');` (без org_id — он на сервере).
   - При 403/503/502 (`data.detail`) — показать понятную плашку.
   - Рендер 4 секций чистым JS в `#staff-view-kds`:
     - **Нагрузка по часам/зонам** — из `zone_load` (`zones`, `hours`,
       `cells[zone][hour]`, `totals_by_zone`): таблица/хитмап час×зона, подсветка
       пиковых ячеек; плюс строка «пик» (час с макс. count).
     - **SLA и этапы пути** — из `stage_stats`:
       `stage_aggregates.stages[]` (label, avg/median/p95 в секундах →
       форматировать в мин/сек), `sla.rate` (доля 0–1 → проценты), `breached`,
       `bottleneck_distribution` (узкое место), при наличии — `sla.by_hour`.
     - **Кухня по зонам + сотрудники** — из `kitchen_zones.zones[]`
       (`zone`, `count`, `avg`, `median`, `employees[]`).
     - **Аномалии + журнал** — `anomalies.fast[]`, `anomalies.reverts[]`;
       последние N строк `journal.rows[]` (at, order_number, type, actor_name,
       item_name).
   - Единицы: `*_seconds`/`avg`/`p95` — секунды; `rate` — доля 0–1.

5. **Период**: на старте без переключателя — берём дефолт saya-kds (7 дней).
   Переключатель неделя/месяц — отдельная будущая итерация (YAGNI).

## Гейтинг (defense in depth)

- Фронт: кнопка отсутствует в DOM для чужих id.
- Бэк: `/api/chaspik` всё равно возвращает `403`, если tg-id не из набора.
- Источник правды по id — две константы с одинаковым набором (`CHASPIK_TG_IDS`)
  на фронте и на бэке.

## Деплой / конфигурация

Env-переменные задать на двух Render-сервисах:
- `saya-kds`: `ANALYTICS_API_KEY` (как в доке saya-kds).
- бэкенд этого мини-аппа (сервис, где крутится `api.py`):
  `ANALYTICS_API_KEY` (тот же секрет), `CHASPIK_ORG_ID` (id филиала Алиева),
  при необходимости `CHASPIK_BASE_URL`.

Прод этого репо деплоится Render'ом с ветки `deploy-cashshifts`.

## Вне объёма (YAGNI)

- Карта спроса (`demand`).
- Кэш ответа (saya-kds считает на лету).
- Переключатель периода и кастомные даты в UI.
- Мульти-филиальный выбор org_id (пока один филиал — Алиева).

## Критерии готовности

- Разрешённый id видит сабтаб «saya-kds» и при открытии получает 4 секции с
  реальными данными saya-kds.
- Неразрешённый id не видит кнопку; прямой запрос `/api/chaspik` от него → 403.
- Если env не заданы → `/api/chaspik` → 503 с понятным сообщением, UI
  показывает плашку, а не пустоту/ошибку JS.
- Ключ `X-API-Key` нигде не появляется во фронте/URL.
