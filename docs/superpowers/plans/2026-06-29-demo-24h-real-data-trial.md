# Демо-бот: 24ч триал с реальными данными — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** В демо-боте после подключения iiko в чате дать клиенту 24 часа полного доступа к ЕГО реальным данным в Mini App, после — жёсткий замок + оффер (разработка 200 000 ₸ + подписка 30 000 ₸/мес).

**Architecture:** Один helper `_use_demo_data(user, org_id)` заменяет повторяющийся демо-гейт во всех ~26 аналитических эндпоинтах И в `_get_org_id`; он возвращает «отдавать демо» = False, когда демо-юзер в активном 24ч-триале, тогда эндпоинты идут обычным путём по его реальному org. Триал хранится в таблице `demo_trial` (epoch-таймштамп, один ряд на юзера, не перезапускается). Фронт демо-бота на старте спрашивает `/api/demo/trial` и ветвится: active → грузим реальный филиал + баннер-отсчёт; ended → полноэкранный замок; none → как сейчас (демо-сэмпл).

**Tech Stack:** FastAPI + SQLite (`database.py`), vanilla JS (`index.html`). Тесты — plain `test_*` функции + `if __name__ == "__main__"` раннер, без pytest, запуск `python3 test_x.py`.

## Global Constraints

- Триал = 24 часа **с момента подключения iiko** (env `DEMO_TRIAL_HOURS`, дефолт 24).
- **Один триал на клиента** — повторное подключение НЕ перезапускает (`INSERT OR IGNORE`).
- После истечения — **жёсткий замок** (полноэкранный), в аналитику не пускать; бэкенд при этом возвращает демо-сэмпл (реальные данные после 24ч не отдаём).
- Строгие гейты НЕ трогаем: write-зарплаты, `setup_validate`, лимит распознавания накладной остаются на `_is_demo_user`.
- Цена в оффере: **разработка 200 000 ₸ + подписка 30 000 ₸/мес**; гарантия возврата за 1-й месяц; контакт менеджера `https://t.me/wiregroup`.
- Только демо-сервис (`DEMO_ONLY=1`); на основном боте поведение не меняется (`_use_demo_data` на нём всегда False без обращения к БД).
- Самохостед iiko: фудкост недоступен (фикс A3) — в триале честно «недоступно».
- Деплой с ветки `deploy-cashshifts`.

---

### Task 1: Таблица `demo_trial` + DB-хелперы

**Files:**
- Modify: `database.py` (CREATE-блок в `init_db` рядом с `demo_invoice_usage` ~строка 128; новые функции рядом с `get_demo_invoice_count` ~строка 192)
- Test: `test_demo_trial.py` (создать в корне)

**Interfaces:**
- Produces:
  - `start_demo_trial(telegram_id: int, org_id: str, started_ts: int) -> None` — `INSERT OR IGNORE` (первое подключение фиксирует старт; повтор не сбрасывает).
  - `get_demo_trial(telegram_id: int) -> Optional[Dict]` — `{"org_id": str, "started_ts": int}` или None.

- [ ] **Step 1: Написать падающий тест**

Создать `test_demo_trial.py`:
```python
"""Тесты 24ч-триала демо-бота.
Запуск: python3 test_demo_trial.py
"""
import os, tempfile, asyncio
os.environ.setdefault("DB_PATH", tempfile.mktemp(suffix="_trial_test.db"))
os.environ["DEMO_ONLY"] = "1"  # триал живёт только на демо-боте

import database; database.init_db()
import api
from fastapi import HTTPException


def test_trial_insert_and_get():
    database.start_demo_trial(111, "org-A", 1_000_000)
    row = database.get_demo_trial(111)
    assert row and row["org_id"] == "org-A" and row["started_ts"] == 1_000_000, row
    print("  [OK] start_demo_trial + get_demo_trial")


def test_trial_not_reset_on_second_connect():
    database.start_demo_trial(222, "org-X", 5_000)
    database.start_demo_trial(222, "org-Y", 9_999)  # повтор не должен перезаписать
    row = database.get_demo_trial(222)
    assert row["org_id"] == "org-X" and row["started_ts"] == 5_000, row
    print("  [OK] повторное подключение не перезапускает триал")


def test_get_trial_none():
    assert database.get_demo_trial(999999) is None
    print("  [OK] нет триала → None")


if __name__ == "__main__":
    tests = [test_trial_insert_and_get, test_trial_not_reset_on_second_connect, test_get_trial_none]
    failed = 0
    for t in tests:
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

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `python3 test_demo_trial.py`
Expected: ERROR — `module 'database' has no attribute 'start_demo_trial'`.

- [ ] **Step 3: Добавить таблицу в `init_db`**

В `database.py` в большом `CREATE TABLE` блоке, сразу после таблицы `demo_invoice_usage` (после её `);`, ~строка 132), добавить:
```sql
    -- Демо-бот: 24ч триал с реальными данными (старт при подключении iiko)
    CREATE TABLE IF NOT EXISTS demo_trial (
        telegram_id INTEGER PRIMARY KEY,
        org_id      TEXT,
        started_ts  INTEGER
    );
```

- [ ] **Step 4: Добавить хелперы**

В `database.py` сразу после `inc_demo_invoice_count` (после её `return`, ~строка 215) добавить:
```python
def start_demo_trial(telegram_id: int, org_id: str, started_ts: int) -> None:
    """Фиксирует старт 24ч-триала. INSERT OR IGNORE — первое подключение побеждает,
    повторное НЕ перезапускает (нет вечного бесплатного доступа)."""
    conn = get_db()
    conn.execute(
        "INSERT OR IGNORE INTO demo_trial (telegram_id, org_id, started_ts) VALUES (?, ?, ?)",
        (telegram_id, org_id, started_ts)
    )
    conn.commit()
    conn.close()


def get_demo_trial(telegram_id: int):
    conn = get_db()
    row = conn.execute(
        "SELECT org_id, started_ts FROM demo_trial WHERE telegram_id = ?", (telegram_id,)
    ).fetchone()
    conn.close()
    return {"org_id": row["org_id"], "started_ts": int(row["started_ts"])} if row else None
```

- [ ] **Step 5: Запустить тест — проходит**

Run: `python3 test_demo_trial.py`
Expected: `ВСЕ ТЕСТЫ ОК` (3 [OK]).

- [ ] **Step 6: Коммит**
```bash
git add database.py test_demo_trial.py
git commit -m "feat(demo-trial): таблица demo_trial + start/get хелперы"
```

---

### Task 2: Backend — состояние триала и центральный гейт `_use_demo_data`

**Files:**
- Modify: `api.py` (импорт из database ~строка 31; конфиг рядом с `INIT_DATA_MAX_AGE` ~строка 101; новые функции рядом с `_is_demo_user` ~строка 902)
- Test: `test_demo_trial.py` (дополнить)

**Interfaces:**
- Consumes: `start_demo_trial`, `get_demo_trial` (Task 1); `DEMO_ONLY`, `_is_demo_user` (есть).
- Produces:
  - `DEMO_TRIAL_HOURS: int`
  - `_demo_trial_state(telegram_id: int) -> dict` — `{"state": "none"|"active"|"ended", "org_id"?, "seconds_left"?, "hours_left"?}`
  - `_trial_active(telegram_id: int) -> bool`
  - `_use_demo_data(user: Dict, org_id: str) -> bool`

- [ ] **Step 1: Написать падающий тест** (дополнить `test_demo_trial.py` перед `if __name__`)
```python
import time

def test_use_demo_data_active_trial():
    tid = 333
    database.start_demo_trial(tid, "org-real", int(time.time()))  # только что
    user = {"id": tid}
    # активный триал + реальный org → НЕ демо
    assert api._use_demo_data(user, "org-real") is False
    # но demo-org-1 всегда демо
    assert api._use_demo_data(user, "demo-org-1") is True
    print("  [OK] активный триал → реальные данные, demo-org-1 всё равно демо")


def test_use_demo_data_ended_trial():
    tid = 444
    database.start_demo_trial(tid, "org-real", int(time.time()) - 26 * 3600)  # сутки прошли
    assert api._use_demo_data({"id": tid}, "org-real") is True  # ended → демо
    st = api._demo_trial_state(tid)
    assert st["state"] == "ended", st
    print("  [OK] истёкший триал → демо-сэмпл, state=ended")


def test_use_demo_data_no_trial():
    assert api._use_demo_data({"id": 555}, "whatever") is True  # демо-юзер без триала
    assert api._demo_trial_state(555)["state"] == "none"
    print("  [OK] нет триала → демо")
```
И добавить их в список `tests` в раннере:
`test_use_demo_data_active_trial, test_use_demo_data_ended_trial, test_use_demo_data_no_trial`.

- [ ] **Step 2: Запустить — падает**

Run: `python3 test_demo_trial.py`
Expected: ERROR — `module 'api' has no attribute '_use_demo_data'`.

- [ ] **Step 3: Импорт хелперов + конфиг**

В `api.py` в блоке `from database import (...)` (где уже импортируются `get_demo_invoice_count, inc_demo_invoice_count`) добавить `start_demo_trial, get_demo_trial`.

Рядом с `INIT_DATA_MAX_AGE = ...` (~строка 101) добавить:
```python
# Демо-бот: длительность триала с реальными данными (часов).
DEMO_TRIAL_HOURS = int(os.getenv("DEMO_TRIAL_HOURS", "24"))
```

- [ ] **Step 4: Добавить функции** сразу после `_is_demo_user` (после её `return DEMO_ONLY`, ~строка 906):
```python
def _demo_trial_state(telegram_id: int) -> Dict[str, Any]:
    """Состояние 24ч-триала: none | active | ended (+ org_id, остаток секунд)."""
    row = get_demo_trial(telegram_id)
    if not row:
        return {"state": "none"}
    now = datetime.now(timezone.utc).timestamp()
    left = int(row["started_ts"] + DEMO_TRIAL_HOURS * 3600 - now)
    if left > 0:
        return {"state": "active", "org_id": row["org_id"],
                "seconds_left": left, "hours_left": round(left / 3600, 1)}
    return {"state": "ended", "org_id": row["org_id"], "seconds_left": 0}


def _trial_active(telegram_id: int) -> bool:
    return DEMO_ONLY and _demo_trial_state(telegram_id).get("state") == "active"


def _use_demo_data(user: Dict, org_id: str) -> bool:
    """Отдавать ли демо-сэмпл вместо реальных данных.
    - demo-org-1 → всегда демо;
    - демо-юзер без активного триала → демо;
    - демо-юзер с активным триалом → НЕ демо (его реальные данные).
    На основном боте `_is_demo_user` = False → возвращает False без обращения к БД."""
    if org_id == "demo-org-1":
        return True
    return _is_demo_user(user) and not _trial_active(int(user.get("id", 0) or 0))
```

- [ ] **Step 5: Запустить тест — проходит**

Run: `python3 test_demo_trial.py`
Expected: `ВСЕ ТЕСТЫ ОК` (6 [OK]).

- [ ] **Step 6: Коммит**
```bash
git add api.py test_demo_trial.py
git commit -m "feat(demo-trial): _demo_trial_state/_trial_active/_use_demo_data + конфиг часов"
```

---

### Task 3: Backend — сделать `_get_org_id` и ~26 аналитических гейтов trial-aware

**Files:**
- Modify: `api.py` (`_get_org_id` ~строка 909; ~26 строк `if _is_demo_user(user) or org_id == "demo-org-1":`)
- Test: `test_demo_trial.py` (дополнить — `_get_org_id` для триал-юзера)

**Interfaces:**
- Consumes: `_use_demo_data` (Task 2), `_get_org_id` (есть).

- [ ] **Step 1: Написать падающий тест** (дополнить `test_demo_trial.py`)
```python
def test_get_org_id_trial_returns_real():
    tid = 666
    database.start_demo_trial(tid, "org-real-666", int(time.time()))
    # во время триала _get_org_id НЕ должен схлопывать реальный org в "demo".
    # (без записи в restaurants реальный путь кинет 404 — это и проверяем: НЕ "demo")
    try:
        res = api._get_org_id("org-real-666", {"id": tid})
        assert res != "demo", f"ожидали не demo, got {res}"
        print("  [OK] _get_org_id в триале не схлопывает в demo")
    except HTTPException as e:
        assert e.status_code == 404
        print("  [OK] _get_org_id в триале идёт реальным путём (404 без записи в БД — ожидаемо)")


def test_get_org_id_no_trial_is_demo():
    res = api._get_org_id("anything", {"id": 777})  # демо-юзер без триала
    assert res == "demo", res
    print("  [OK] _get_org_id без триала → demo")
```
Добавить в раннер: `test_get_org_id_trial_returns_real, test_get_org_id_no_trial_is_demo`.

- [ ] **Step 2: Запустить — падает** (старый `_get_org_id` вернёт "demo" в триале)

Run: `python3 test_demo_trial.py`
Expected: FAIL на `test_get_org_id_trial_returns_real` (вернётся "demo").

- [ ] **Step 3: Сделать `_get_org_id` trial-aware**

Заменить начало `_get_org_id` (api.py ~909):
```python
def _get_org_id(org_id: str, user: Dict) -> str:
    if org_id == "demo-org-1" or _is_demo_user(user):
        return "demo"
```
на:
```python
def _get_org_id(org_id: str, user: Dict) -> str:
    if _use_demo_data(user, org_id):
        return "demo"
```

- [ ] **Step 4: Заменить ~26 аналитических гейтов**

Все 26 строк идентичны: `    if _is_demo_user(user) or org_id == "demo-org-1":`. Заменить КАЖДУЮ на `    if _use_demo_data(user, org_id):` (replace-all по точной строке). Это эндпоинты dashboard/revenue/sales/shifts/couriers/staff/heatmap/foodcost/expenses/price-stats/writeoffs/withdrawals/cancels/companions/retention/comparison/plan/clients/olap/stoplist/cashshifts/salary/reviews и т.п. — все они «отдают DEMO_* демо-юзеру».

Проверка после замены:
```bash
grep -c "if _is_demo_user(user) or org_id == \"demo-org-1\":" api.py   # ожидаем 0
grep -c "if _use_demo_data(user, org_id):" api.py                       # ожидаем ~27 (26 + _get_org_id)
```

- [ ] **Step 5: Запустить тесты — проходят (и не сломаны прежние)**

Run: `python3 test_demo_trial.py` → `ВСЕ ТЕСТЫ ОК` (8 [OK]).
Run: `python3 test_security_batch_a.py` → `ВСЕ ТЕСТЫ ОК` (демо-гейты не должны были тронуть security).
Run: `python3 -c "import ast; ast.parse(open('api.py').read()); print('OK')"`

- [ ] **Step 6: Коммит**
```bash
git add api.py test_demo_trial.py
git commit -m "feat(demo-trial): _get_org_id + ~26 аналитических гейтов через _use_demo_data (триал отдаёт реальные данные)"
```

---

### Task 4: Backend — старт триала при подключении, эндпоинт статуса, подсказки в чате

**Files:**
- Modify: `api.py` (`_handle_demo_registration` успех ~строка 4451; `DEMO_REG_PROMPTS` ~где определён; новый эндпоинт рядом с `/api/config` ~строка 831)
- Test: `test_demo_trial.py` (дополнить — `/api/demo/trial`)

**Interfaces:**
- Consumes: `start_demo_trial`, `_demo_trial_state`, `get_current_user`, `_tg_send`, `MINIAPP_URL`.
- Produces: `GET /api/demo/trial` → `_demo_trial_state` (или `{"state":"disabled"}` вне демо).

- [ ] **Step 1: Написать падающий тест** (дополнить `test_demo_trial.py`)
```python
def test_demo_trial_endpoint_active():
    tid = 888
    database.start_demo_trial(tid, "org-888", int(time.time()))
    out = asyncio.run(api.demo_trial(user={"id": tid}))
    assert out["state"] == "active" and out["org_id"] == "org-888", out
    print("  [OK] /api/demo/trial → active с org_id")
```
Добавить в раннер: `test_demo_trial_endpoint_active`.

- [ ] **Step 2: Запустить — падает** (`api.demo_trial` не существует)

Run: `python3 test_demo_trial.py`
Expected: ERROR — нет `demo_trial`.

- [ ] **Step 3: Добавить эндпоинт статуса**

В `api.py` сразу после `get_config` (после `return {"demo_only": DEMO_ONLY}`, ~строка 834) добавить:
```python
@app.get("/api/demo/trial")
async def demo_trial(user: Dict = Depends(get_current_user)):
    """Статус 24ч-триала для текущего демо-юзера (фронт ветвится по state)."""
    if not DEMO_ONLY:
        return {"state": "disabled"}
    return _demo_trial_state(int(user.get("id", 0) or 0))
```

- [ ] **Step 4: Стартовать триал при подключении iiko**

В `_handle_demo_registration`, в блоке успеха, заменить (api.py ~4451-4455):
```python
        create_user(telegram_id, username, username)
        for o in orgs:
            add_restaurant(telegram_id, login, o["id"], o.get("name") or "iiko", server, password)
        _demo_reg.pop(chat_id, None)
        await _tg_edit(chat_id, status, f"✅ iiko подключён ({orgs[0].get('name') or 'организация'}).")
```
на:
```python
        create_user(telegram_id, username, username)
        for o in orgs:
            add_restaurant(telegram_id, login, o["id"], o.get("name") or "iiko", server, password)
        _demo_reg.pop(chat_id, None)
        start_demo_trial(telegram_id, orgs[0]["id"],
                         int(datetime.now(timezone.utc).timestamp()))
        await _tg_edit(chat_id, status, f"✅ iiko подключён ({orgs[0].get('name') or 'организация'}).")
        await _tg_send(chat_id,
            "🎁 На <b>24 часа</b> открыл вам полный доступ к <b>вашей</b> аналитике в Mini App — "
            "реальная выручка, фудкост, смены, всё по-настоящему. Откройте и посмотрите свои цифры 👇\n\n"
            "Через сутки доступ закроется.",
            {"inline_keyboard": [[{"text": "📊 Открыть мою аналитику", "web_app": {"url": f"{MINIAPP_URL}/"}}]]})
```

- [ ] **Step 5: Подсказки в шагах подключения**

Найти `DEMO_REG_PROMPTS = {` и заменить значения на версии с подсказками:
```python
DEMO_REG_PROMPTS = {
    "server": ("🔌 Подключим ваш iiko — и накладная улетит к вам, плюс на 24 часа откроется "
               "ваша реальная аналитика.\n\n"
               "Шаг 1/3 — пришлите адрес вашего iiko-сервера. Это адрес, по которому вы открываете "
               "iikoWeb/iikoOffice в браузере (например <code>https://ваш-сервер.iiko.it/resto</code>) — "
               "скопируйте из адресной строки.\n\nОтменить — /cancel"),
    "login": ("Шаг 2/3 — логин API-пользователя iiko.\n"
              "Создаётся в iikoOffice → Администрирование → Сотрудники/Права: нужна роль с доступом к "
              "OLAP/REST API. Если не уверены — спросите вашего iiko-админа."),
    "password": ("Шаг 3/3 — пароль этого API-пользователя.\n\n"
                 "🔒 Сообщение с паролем удалю сразу после проверки."),
}
```

- [ ] **Step 6: Запустить тест — проходит**

Run: `python3 test_demo_trial.py`
Expected: `ВСЕ ТЕСТЫ ОК` (9 [OK]).
Run: `python3 -c "import ast; ast.parse(open('api.py').read()); print('OK')"`

- [ ] **Step 7: Коммит**
```bash
git add api.py test_demo_trial.py
git commit -m "feat(demo-trial): старт триала при подключении iiko + /api/demo/trial + подсказки в чате"
```

---

### Task 5: Backend — перестроить воронку (убрать 10-сек апселл, нудж, объяснение кнопки, текст оффера)

Новая воронка: после распознавания оффер НЕ шлём; оффер уходит ПОСЛЕ 24ч-триала (Task 6).

**Files:**
- Modify: `api.py` (`_demo_after_recognition`, `_demo_block_if_used`, объяснение кнопки в `_format_invoice_v2`, `DEMO_UPSELL_TEXT`→`DEMO_OFFER_TEXT`)

**Interfaces:**
- Produces: `DEMO_OFFER_TEXT: str` (используется планировщиком в Task 6 и пейволлом в Task 7).

- [ ] **Step 1: Убрать 10-сек апселл после распознавания**

Заменить `_demo_after_recognition`:
```python
async def _demo_after_recognition(chat_id: int, telegram_id: int) -> None:
    """Демо-бот: фиксируем лимит распознавания. Оффер здесь НЕ шлём —
    он уходит после 24ч-триала (см. _demo_sales_scheduler)."""
    if DEMO_ONLY:
        inc_demo_invoice_count(telegram_id)
```

- [ ] **Step 2: Мягкий нудж вместо оффера на лимите**

Заменить `_demo_block_if_used`:
```python
async def _demo_block_if_used(chat_id: int, telegram_id: int) -> bool:
    """Демо-бот: после 1-го распознавания — мягкий нудж подключить iiko (НЕ оффер)."""
    if DEMO_ONLY and get_demo_invoice_count(telegram_id) >= 1:
        await _tg_send(chat_id,
            "Вы уже попробовали распознавание 👍\n\n"
            "Чтобы загрузить эту накладную к себе и открыть доступ к вашей аналитике на 24 часа — "
            "в распознанной накладной выше нажмите «📤 Отправить в iiko»: подключим ваш iiko прямо в чате.")
        return True
    return False
```

- [ ] **Step 3: Объяснение кнопки «Отправить в iiko» — явно про регистрацию**

В `_format_invoice_v2` (демо-блок объяснения кнопок) заменить строку про «📤 Отправить в iiko» на:
```python
                "📤 <b>Отправить в iiko</b> — здесь нужно подключить ваш iiko (быстрая регистрация "
                "в чате: сервер → логин → пароль). После этого накладная реально уйдёт к вам в учётку, "
                "и откроется доступ к вашей аналитике на 24 часа.\n"
```

- [ ] **Step 4: Текст оффера (пост-24ч) — переименовать `DEMO_UPSELL_TEXT` → `DEMO_OFFER_TEXT`**

Заменить определение `DEMO_UPSELL_TEXT = (...)` на:
```python
DEMO_OFFER_TEXT = (
    "⏳ Ваш 24-часовой доступ к данным закончился.\n\n"
    "Вы видели свои реальные цифры — выручку, фудкост, смены. Хотите оставить это навсегда, каждый день?\n\n"
    "💰 Разработка и настройка под ваше заведение — <b>200 000 ₸</b> (под вашу номенклатуру, "
    "поставщиков, сеть). Дальше подписка — <b>30 000 ₸/мес</b>.\n"
    "Не подойдёт за первый месяц — верну подключение полностью.\n\n"
    "👉 Напишите — подключу за день."
)
```

- [ ] **Step 5: Убрать мёртвый код**

`DEMO_UPSELL_TEXT`, `_send_demo_upsell`, `_delayed_demo_upsell` после правок выше становятся неиспользуемыми. Проверить и удалить, если нет других ссылок:
```bash
grep -n "DEMO_UPSELL_TEXT\|_send_demo_upsell\|_delayed_demo_upsell" api.py
```
Удалить определения, на которые больше нет ссылок (НЕ трогать `_demo_upsell_kb` — он переиспользуется как клавиатура оффера).

- [ ] **Step 6: Проверка**

Run: `python3 -c "import ast; ast.parse(open('api.py').read()); print('OK')"` → OK.
Run: `python3 test_demo_trial.py` → `ВСЕ ТЕСТЫ ОК` (не сломано).

- [ ] **Step 7: Коммит**
```bash
git add api.py
git commit -m "feat(demo-trial): воронка — убрать 10с-апселл, нудж на лимите, объяснение кнопки про регу, DEMO_OFFER_TEXT"
```

---

### Task 6: Backend — пуш оффера в бот через 24ч (планировщик)

**Files:**
- Modify: `database.py` (миграция `sales_sent` + хелперы рядом с `get_demo_trial`)
- Modify: `api.py` (импорт хелперов; `_demo_sales_scheduler`; регистрация в `startup`)
- Test: `test_demo_trial.py` (дополнить)

**Interfaces:**
- Consumes: `get_demo_trial`/`start_demo_trial` (Task 1), `DEMO_TRIAL_HOURS` (Task 2), `DEMO_OFFER_TEXT`/`_demo_upsell_kb` (Task 5), `_tg_send`.
- Produces: `get_trials_due_for_sales(now_ts, trial_seconds) -> List[int]`, `mark_trial_sales_sent(telegram_id) -> None`.

- [ ] **Step 1: Падающий тест** (дополнить `test_demo_trial.py` перед `if __name__`)
```python
def test_trials_due_for_sales():
    database.start_demo_trial(1001, "o", 1000)            # давно — должен попасть
    database.start_demo_trial(1002, "o", int(time.time()))  # только что — не должен
    due = database.get_trials_due_for_sales(int(time.time()), 24 * 3600)
    assert 1001 in due and 1002 not in due, due
    database.mark_trial_sales_sent(1001)
    due2 = database.get_trials_due_for_sales(int(time.time()), 24 * 3600)
    assert 1001 not in due2, "после mark_trial_sales_sent не должен повторяться"
    print("  [OK] get_trials_due_for_sales + mark_trial_sales_sent")
```
Добавить в раннер: `test_trials_due_for_sales`.

- [ ] **Step 2: Запустить — падает** (`get_trials_due_for_sales` нет)

Run: `python3 test_demo_trial.py` → ERROR.

- [ ] **Step 3: Миграция `sales_sent`**

В `database.py` в секции миграций `init_db` (рядом с другими `ALTER TABLE ... try/except`) добавить:
```python
    try:
        conn.execute("ALTER TABLE demo_trial ADD COLUMN sales_sent INTEGER DEFAULT 0")
        conn.commit()
    except Exception:
        pass
```

- [ ] **Step 4: DB-хелперы** (после `get_demo_trial`):
```python
def get_trials_due_for_sales(now_ts: int, trial_seconds: int):
    """Триалы, которым стукнуло trial_seconds и оффер ещё не слали."""
    conn = get_db()
    rows = conn.execute(
        "SELECT telegram_id FROM demo_trial "
        "WHERE started_ts + ? <= ? AND COALESCE(sales_sent, 0) = 0",
        (trial_seconds, now_ts)
    ).fetchall()
    conn.close()
    return [int(r["telegram_id"]) for r in rows]


def mark_trial_sales_sent(telegram_id: int) -> None:
    conn = get_db()
    conn.execute("UPDATE demo_trial SET sales_sent = 1 WHERE telegram_id = ?", (telegram_id,))
    conn.commit()
    conn.close()
```

- [ ] **Step 5: Планировщик в `api.py`**

Добавить `get_trials_due_for_sales, mark_trial_sales_sent` в `from database import (...)`. Рядом с `_weekly_report_scheduler` добавить:
```python
async def _demo_sales_scheduler():
    """Демо-бот: через DEMO_TRIAL_HOURS после подключения шлёт оффер в чат — один раз на юзера.
    В личке Telegram chat_id == telegram_id."""
    if not DEMO_ONLY:
        return
    while True:
        try:
            now = int(datetime.now(timezone.utc).timestamp())
            for tid in get_trials_due_for_sales(now, DEMO_TRIAL_HOURS * 3600):
                try:
                    await _tg_send(tid, DEMO_OFFER_TEXT, _demo_upsell_kb())
                    mark_trial_sales_sent(tid)
                except Exception as e:
                    logger.warning(f"[demo_sales] {tid}: {e}")
        except Exception as e:
            logger.warning(f"[demo_sales] loop: {e}")
        await asyncio.sleep(300)
```

- [ ] **Step 6: Регистрация в `startup`**

В `startup()` после существующих `asyncio.create_task(...)` добавить:
```python
    if DEMO_ONLY:
        asyncio.create_task(_demo_sales_scheduler())
```

- [ ] **Step 7: Проверка**

Run: `python3 test_demo_trial.py` → `ВСЕ ТЕСТЫ ОК`.
Run: `python3 -c "import ast; ast.parse(open('api.py').read()); print('OK')"`

- [ ] **Step 8: Коммит**
```bash
git add api.py database.py test_demo_trial.py
git commit -m "feat(demo-trial): пуш оффера в бот через 24ч (sales_sent + планировщик)"
```

---

### Task 7: Фронт — режим триала, замок + объяснения демо-вкладок

> Дополнительно к шагам ниже — добавить **короткое объяснение под заголовком каждой демо-вкладки** (видно на демо-боте: в `initApp` при `demoOnly` выставить `state.isDemoBot = true`; рендерить серую подпись под заголовком вкладки, если `state.isDemoBot`). Тексты (verbatim):
> - 🏠 Главная: «Сводка за период: сколько заработали, средний чек, сколько заказов — главные цифры заведения на одном экране.»
> - 🛒 Продажи: «Откуда выручка: каналы (зал/доставка/самовывоз), топ-блюда, кто приносит больше денег.»
> - 👥 Сотрудники: «Кто сколько продал и кто сейчас на смене — видно лучших и отстающих.»
> - 💰 Фудкост: «Сколько себестоимость продуктов съедает от выручки. Норма ~30%; выше — теряете маржу.»
> - 🧾 Накладные: «Приходы от поставщиков — те самые накладные, что бот грузит с фото.»
> - 🗑 Списания: «Что и на сколько списали (порча, брак) — где утекают продукты.»
> - 📈 Год/год: «Сравнение с прошлым годом по неделям/месяцам — растёте или падаете.»
> - 🧾 Смены: «Кассовые смены и расхождения — где в кассе недостача.»
> Закоммитить вместе с фронтом триала.

#### Базовая часть: ветвление initApp + режим триала + полноэкранный замок

**Files:**
- Modify: `index.html` (`initApp` демо-ветка ~строка где `if (demoOnly) { startDemo(); return; }`; новый экран-замок в HTML; новые JS-функции рядом с `startDemo`)

**Interfaces:**
- Consumes: `apiGet('/api/demo/trial')` → `{state, org_id?, seconds_left?, hours_left?}`; `checkExistingUser()`, `startDemo()`, `contactSupport()` (есть, ведёт на t.me/wiregroup).
- Produces: `enterTrialMode(trial)`, `showTrialPaywall()`, `startTrialCountdown(seconds)`.

- [ ] **Step 1: Заменить демо-ветку в `initApp`**

Заменить:
```javascript
  if (demoOnly) {
    startDemo();
    return;
  }
```
на:
```javascript
  if (demoOnly) {
    let trial = { state: 'none' };
    try { trial = await apiGet('/api/demo/trial'); } catch(e) {}
    if (trial.state === 'active') {
      await enterTrialMode(trial);
    } else if (trial.state === 'ended') {
      showTrialPaywall();
    } else {
      startDemo();
    }
    return;
  }
```

- [ ] **Step 2: Добавить HTML экрана-замка**

В `index.html` перед закрывающим `</body>` (или рядом с другими `.screen`-экранами) добавить:
```html
<div class="screen" id="screen-trial-end" style="display:none; position:fixed; inset:0; z-index:9999; background:var(--bg); overflow-y:auto; padding:24px 20px calc(24px + env(safe-area-inset-bottom));">
  <div style="max-width:520px; margin:0 auto;">
    <div style="font-size:40px; text-align:center; margin-top:24px;">⏳</div>
    <h2 style="text-align:center; margin:12px 0 4px;">Доступ к вашим данным закончился</h2>
    <p style="text-align:center; color:var(--text-secondary); margin-bottom:20px;">
      Вы сутки смотрели свои реальные цифры. Хотите оставить их навсегда — выручку, фудкост, смены, аналитику — каждый день?</p>
    <div class="card" style="padding:16px;">
      <div style="font-size:14px; line-height:1.6;">
        💰 Разработка и настройка под ваше заведение — <b>200 000 ₸</b><br>
        (под вашу номенклатуру, поставщиков, сеть)<br>
        Дальше подписка — <b>30 000 ₸/мес</b><br>
        <span style="color:var(--text-secondary)">Не подойдёт за первый месяц — верну подключение полностью.</span>
      </div>
    </div>
    <button onclick="contactSupport()" style="margin-top:18px; width:100%; padding:15px; background:var(--accent); color:var(--bg); border:none; border-radius:12px; font-weight:700; font-size:16px; cursor:pointer;">
      💬 Подключить — написать менеджеру</button>
  </div>
</div>
```

- [ ] **Step 3: Добавить JS-функции** сразу перед `async function startDemo()`:
```javascript
let _trialTimer = null;

async function enterTrialMode(trial) {
  // Ведём как обычного подключённого юзера: грузим реальный филиал и данные.
  document.querySelectorAll('.js-demo-btn').forEach(b => b.style.display = 'none');
  await checkExistingUser();
  // Баннер с обратным отсчётом поверх контента.
  let banner = document.getElementById('trial-banner');
  if (!banner) {
    banner = document.createElement('div');
    banner.id = 'trial-banner';
    banner.style.cssText = 'position:sticky; top:0; z-index:50; background:#1B3A6B; color:#fff; text-align:center; padding:8px 12px; font-size:13px; font-weight:600;';
    document.body.insertBefore(banner, document.body.firstChild);
  }
  banner.style.display = 'block';
  startTrialCountdown(trial.seconds_left || 0);
}

function startTrialCountdown(seconds) {
  const banner = document.getElementById('trial-banner');
  if (_trialTimer) clearInterval(_trialTimer);
  let left = seconds;
  const tick = () => {
    if (left <= 0) {
      clearInterval(_trialTimer);
      if (banner) banner.style.display = 'none';
      showTrialPaywall();
      return;
    }
    const h = Math.floor(left / 3600), m = Math.floor((left % 3600) / 60);
    if (banner) banner.textContent = `⏳ Демо-доступ к вашим данным: осталось ${h} ч ${m} мин`;
    left -= 1;
  };
  tick();
  _trialTimer = setInterval(tick, 1000);
}

function showTrialPaywall() {
  if (_trialTimer) clearInterval(_trialTimer);
  document.getElementById('navbar')?.classList.remove('visible');
  const tb = document.getElementById('trial-banner');
  if (tb) tb.style.display = 'none';
  document.getElementById('screen-trial-end').style.display = 'block';
}
```

- [ ] **Step 4: Проверка JS-синтаксиса**

Run:
```bash
python3 - <<'PY'
import re
html=open('index.html').read()
big=max(re.findall(r'<script>(.*?)</script>',html,re.S),key=len)
open('/tmp/c.js','w').write(big)
PY
node --check /tmp/c.js && echo "JS OK"; rm -f /tmp/c.js
```
Expected: `JS OK`.

- [ ] **Step 5: Ручная проверка флоу** (нет JS-харнесса)

Локально (демо-режим): `DEMO_ONLY=1 ANTHROPIC_API_KEY=... python3 api.py`. В мини-аппе под демо-юзером:
- Без триала: открывается демо-сэмпл (как раньше).
- Эмуляция активного триала (DevTools-консоль): временно `await apiGet('/api/demo/trial')` должно вернуть `{state:'none'}` для свежего юзера. Чтобы увидеть active/ended — проще проверить через бота: подключить iiko в чате (если есть тестовая учётка), затем открыть Mini App → должен показать реальные данные + синий баннер с отсчётом.
- Эмуляция замка: в консоли `showTrialPaywall()` → появляется полноэкранный экран с оффером и кнопкой менеджера, навбар скрыт.
Ожидаемо: нет JS-ошибок в консоли.

- [ ] **Step 6: Коммит**
```bash
git add index.html
git commit -m "feat(demo-trial): фронт — режим триала (реальные данные + отсчёт) и полноэкранный замок с оффером"
```

---

### Task 8: Деплой-конфигурация и прод-проверка

**Files:** нет кода — операционное.

- [ ] **Step 1: (опц.) env на демо-сервисе**

Render → `iiko-demo` → Environment: при желании `DEMO_TRIAL_HOURS` (дефолт 24 — можно не задавать). Других env не нужно (таблица создаётся миграцией в `init_db`).

- [ ] **Step 2: Прод-проверка после деплоя**

Под тестовым демо-аккаунтом: подключить реальный iiko в чате @wiredemobot → бот пишет про 24ч-доступ → открыть Mini App → видны реальные данные филиала + баннер-отсчёт. Дёрнуть `GET /api/demo/trial` (через мини-апп) → `state: active`. Для проверки замка — выставить `DEMO_TRIAL_HOURS=0` временно или подождать/подменить `started_ts` в БД → Mini App показывает полноэкранный замок.

- [ ] **Step 3: Слить ветку** (через `superpowers:finishing-a-development-branch`).

---

## Self-Review

**Spec coverage:**
- Триал с момента подключения, 24ч, env → Task 1 (таблица) + Task 2 (DEMO_TRIAL_HOURS, state) + Task 4 (старт при подключении). ✓
- Реальные данные во время триала через единый гейт → Task 2 (`_use_demo_data`) + Task 3 (`_get_org_id` + 26 гейтов). ✓
- Жёсткий замок после 24ч + бэк возвращает демо → Task 3 (ended → демо) + Task 6 (`showTrialPaywall`). ✓
- Один триал на клиента → Task 1 (`INSERT OR IGNORE`) + тест `test_trial_not_reset_on_second_connect`. ✓
- Подсказки в чате → Task 4 (DEMO_REG_PROMPTS). ✓
- Статус для фронта → Task 4 (`/api/demo/trial`). ✓
- Цена 200 000 + 30 000/мес → Task 5 (апселл) + Task 6 (экран замка). ✓
- Строгие гейты не тронуты → Task 3 меняет только строку `if _is_demo_user(user) or org_id == "demo-org-1":` (это демо-READ early-returns) и `_get_org_id`; зарплата/setup используют другой паттерн — не затронуты. ✓
- Основной бот не затронут → `_use_demo_data` на нём `_is_demo_user`=False → False без БД. ✓

**Placeholder scan:** весь код приведён дословно; ручная фронт-проверка вместо авто-теста — т.к. JS-харнесса в репо нет (как у прошлых фич). Без TBD/TODO.

**Type consistency:** `start_demo_trial(telegram_id, org_id, started_ts)` — сигнатура совпадает в Task 1 (def), Task 4 (вызов с 3 арг). `get_demo_trial` → `{org_id, started_ts}` используется в `_demo_trial_state` (Task 2). `_use_demo_data(user, org_id)` — определён в Task 2, применён в Task 3 (`_get_org_id` + 26 гейтов). `_demo_trial_state` ключи (`state/org_id/seconds_left`) совпадают между Task 2 (def), Task 4 (`/api/demo/trial`), Task 6 (фронт читает `state/seconds_left/org_id`). `/api/demo/trial` → имя функции `demo_trial` совпадает в Task 4 (def) и тесте.
