# Счётчик юзеров демо-бота + лимит накладных — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить демо-боту счётчик новых юзеров с атрибуцией источника и пушем владельцу, а основному боту — месячный лимит распознавания накладных с докупкой и пушем о достижении лимита.

**Architecture:** Один FastAPI-апп (`api.py`) + SQLite (`database.py`), два деплоя по флагу `DEMO_ONLY`. Фича 1 (счётчик) активна на демо-боте, Фича 2 (лимит) — на основном; БД общая, поэтому `/stats` и ежедневный пуш агрегируют обе. Новые данные — две таблицы (`user_acquisition`, `invoice_quota`) и хелперы в `database.py`; бизнес-логика — в webhook-обработчике и одном фоновом цикле.

**Tech Stack:** Python 3.12, FastAPI, SQLite (sqlite3 + Row factory), Telegram Bot API через существующие `_tg_send`/`_tg_edit`, Claude Sonnet 4.6 для распознавания (без изменений).

## Global Constraints

- **Модель распознавания не меняем:** `claude-sonnet-4-6` (`claude_api.py:131,160`). A/B подтвердил: Haiku врёт на плохих фото.
- **Базовый месячный лимит:** 130 накладных на аккаунт (`base_limit` default 130).
- **Пакеты докупки:** +50 (4 000 ₸) и +100 (8 000 ₸); докупленный `extra` **не сгорает**.
- **Расход:** сперва месячный лимит (`used`), по исчерпании — `extra`.
- **Рубильник:** `QUOTA_ENFORCE` (env, дефолт `0`). При `0` лимит только считается, распознавание НЕ блокируется; при `1` — блокирует и шлёт пуш о лимите. Расход (`consume_quota`) считается всегда, независимо от рубильника.
- **Владелец:** `OWNER_CHAT_ID = 8727082281` (через env, дефолт этот id).
- **Без платёжного шлюза.** Докупка — вручную через менеджера + `/addquota`.
- **БД:** только через `get_db()` (Row factory); новые таблицы — в `init_db()` (`CREATE TABLE IF NOT EXISTS` + `ALTER ... ADD COLUMN` в try/except). Фреймворка миграций нет.
- **Сообщения в Telegram:** только через `await _tg_send(chat_id, text, kb=None)` (возвращает message_id).
- **Тестов в проекте нет** (pytest не установлен). Для чистых функций БД — standalone verify-скрипты на временной БД через `DB_PATH=...`. Для бот-логики — `python3 -m py_compile` + ручная проверка в Telegram.

Спека: `docs/superpowers/specs/2026-06-30-demo-user-counter-and-invoice-quota-design.md`.

---

### Task 1: Таблицы и хелперы в database.py

**Files:**
- Modify: `database.py:140` (добавить 2 таблицы в `executescript` `init_db`)
- Modify: `database.py:175` (добавить идемпотентный ALTER для `limit_notified_ts`)
- Modify: `database.py` (новые функции после `inc_demo_invoice_count`, ~`database.py:226`)
- Verify: `scratchpad/verify_db.py` (временный скрипт)

**Interfaces:**
- Produces (для api.py):
  - `record_acquisition(telegram_id:int, username:str, source:str) -> bool` (True, если строка создана)
  - `acquisition_stats() -> dict` ключи: `total, today, week, by_source:list[(str,int)]`
  - `get_quota(telegram_id:int) -> dict` ключи: `telegram_id, period_start_ts, used, base_limit, extra, plan_active, limit_notified_ts`
  - `quota_available(telegram_id:int) -> int`
  - `consume_quota(telegram_id:int) -> None`
  - `add_quota_extra(telegram_id:int, n:int) -> int` (новый `extra`)
  - `reset_quota_if_due(telegram_id:int) -> None`
  - `should_notify_limit(telegram_id:int) -> bool`
  - `quota_stats() -> dict` ключи: `accounts, used, extra, at_limit`

- [ ] **Step 1: Добавить таблицы в `init_db` executescript**

В `database.py`, внутри `conn.executescript("""...""")` (`init_db`), перед закрывающими `""")` (после блока `demo_trial`, `database.py:139`) добавить:

```sql

    -- Атрибуция: первый контакт юзера с демо-ботом и источник (deep-link ?start=)
    CREATE TABLE IF NOT EXISTS user_acquisition (
        telegram_id   INTEGER PRIMARY KEY,
        username      TEXT,
        source        TEXT,
        first_seen_ts INTEGER
    );

    -- Лимит распознавания накладных (основной бот).
    -- extra — несгораемый докупленный баланс; used — расход месячного лимита.
    CREATE TABLE IF NOT EXISTS invoice_quota (
        telegram_id       INTEGER PRIMARY KEY,
        period_start_ts   INTEGER,
        used              INTEGER DEFAULT 0,
        base_limit        INTEGER DEFAULT 130,
        extra             INTEGER DEFAULT 0,
        plan_active       INTEGER DEFAULT 0,
        limit_notified_ts INTEGER DEFAULT 0
    );
```

- [ ] **Step 2: Добавить идемпотентный ALTER (на случай старой таблицы)**

После блока ALTER для `demo_trial` (`database.py:171-175`) добавить:

```python
    try:
        conn.execute("ALTER TABLE invoice_quota ADD COLUMN limit_notified_ts INTEGER DEFAULT 0")
        conn.commit()
    except Exception:
        pass
```

- [ ] **Step 3: Добавить хелперы**

После `inc_demo_invoice_count` (после `database.py:226`) добавить:

```python

# === Атрибуция юзеров демо-бота ===

def record_acquisition(telegram_id: int, username: str, source: str) -> bool:
    """Фиксирует первый контакт юзера с демо-ботом. True, если строка создана (новый юзер)."""
    conn = get_db()
    cur = conn.execute(
        "INSERT OR IGNORE INTO user_acquisition (telegram_id, username, source, first_seen_ts) "
        "VALUES (?, ?, ?, ?)",
        (telegram_id, username, source, int(datetime.now().timestamp()))
    )
    conn.commit()
    created = cur.rowcount > 0
    conn.close()
    return created


def acquisition_stats() -> dict:
    conn = get_db()
    now = int(datetime.now().timestamp())
    total = conn.execute("SELECT COUNT(*) c FROM user_acquisition").fetchone()["c"]
    today = conn.execute("SELECT COUNT(*) c FROM user_acquisition WHERE first_seen_ts >= ?",
                         (now - 86400,)).fetchone()["c"]
    week = conn.execute("SELECT COUNT(*) c FROM user_acquisition WHERE first_seen_ts >= ?",
                        (now - 7 * 86400,)).fetchone()["c"]
    rows = conn.execute(
        "SELECT source, COUNT(*) c FROM user_acquisition GROUP BY source ORDER BY c DESC"
    ).fetchall()
    conn.close()
    return {"total": int(total), "today": int(today), "week": int(week),
            "by_source": [(r["source"] or "direct", int(r["c"])) for r in rows]}


# === Квота накладных (основной бот) ===

def get_quota(telegram_id: int) -> dict:
    """Возвращает квоту аккаунта, создавая строку с дефолтами при первом обращении."""
    conn = get_db()
    row = conn.execute("SELECT * FROM invoice_quota WHERE telegram_id = ?", (telegram_id,)).fetchone()
    if not row:
        conn.execute(
            "INSERT OR IGNORE INTO invoice_quota (telegram_id, period_start_ts) VALUES (?, ?)",
            (telegram_id, int(datetime.now().timestamp()))
        )
        conn.commit()
        row = conn.execute("SELECT * FROM invoice_quota WHERE telegram_id = ?", (telegram_id,)).fetchone()
    conn.close()
    return {"telegram_id": telegram_id, "period_start_ts": int(row["period_start_ts"]),
            "used": int(row["used"]), "base_limit": int(row["base_limit"]),
            "extra": int(row["extra"]), "plan_active": int(row["plan_active"]),
            "limit_notified_ts": int(row["limit_notified_ts"])}


def reset_quota_if_due(telegram_id: int) -> None:
    """Ленивый месячный сброс: обнуляет used и сдвигает период. extra НЕ трогаем."""
    q = get_quota(telegram_id)
    now = int(datetime.now().timestamp())
    if now > q["period_start_ts"] + 30 * 86400:
        conn = get_db()
        conn.execute(
            "UPDATE invoice_quota SET used = 0, period_start_ts = ?, limit_notified_ts = 0 "
            "WHERE telegram_id = ?",
            (now, telegram_id)
        )
        conn.commit()
        conn.close()


def quota_available(telegram_id: int) -> int:
    q = get_quota(telegram_id)
    return (q["base_limit"] - q["used"]) + q["extra"]


def consume_quota(telegram_id: int) -> None:
    """Списывает 1 накладную: сперва месячный лимит (used), по исчерпании — extra."""
    get_quota(telegram_id)  # гарантирует наличие строки
    conn = get_db()
    row = conn.execute("SELECT used, base_limit, extra FROM invoice_quota WHERE telegram_id = ?",
                       (telegram_id,)).fetchone()
    used, base, extra = int(row["used"]), int(row["base_limit"]), int(row["extra"])
    if used < base:
        conn.execute("UPDATE invoice_quota SET used = used + 1 WHERE telegram_id = ?", (telegram_id,))
    elif extra > 0:
        conn.execute("UPDATE invoice_quota SET extra = extra - 1 WHERE telegram_id = ?", (telegram_id,))
    conn.commit()
    conn.close()


def add_quota_extra(telegram_id: int, n: int) -> int:
    """Начисляет n накладных в несгораемый extra. Возвращает новый extra."""
    get_quota(telegram_id)
    conn = get_db()
    conn.execute("UPDATE invoice_quota SET extra = extra + ? WHERE telegram_id = ?", (n, telegram_id))
    conn.commit()
    row = conn.execute("SELECT extra FROM invoice_quota WHERE telegram_id = ?", (telegram_id,)).fetchone()
    conn.close()
    return int(row["extra"])


def should_notify_limit(telegram_id: int) -> bool:
    """True, если владельцу не слали пуш о лимите последние 24ч; помечает время отправки."""
    get_quota(telegram_id)
    conn = get_db()
    row = conn.execute("SELECT limit_notified_ts FROM invoice_quota WHERE telegram_id = ?",
                       (telegram_id,)).fetchone()
    now = int(datetime.now().timestamp())
    if row and now - int(row["limit_notified_ts"]) < 86400:
        conn.close()
        return False
    conn.execute("UPDATE invoice_quota SET limit_notified_ts = ? WHERE telegram_id = ?", (now, telegram_id))
    conn.commit()
    conn.close()
    return True


def quota_stats() -> dict:
    conn = get_db()
    accounts = conn.execute("SELECT COUNT(*) c FROM invoice_quota").fetchone()["c"]
    used = conn.execute("SELECT COALESCE(SUM(used),0) s FROM invoice_quota").fetchone()["s"]
    extra = conn.execute("SELECT COALESCE(SUM(extra),0) s FROM invoice_quota").fetchone()["s"]
    at_limit = conn.execute(
        "SELECT COUNT(*) c FROM invoice_quota WHERE (base_limit - used) + extra <= 0"
    ).fetchone()["c"]
    conn.close()
    return {"accounts": int(accounts), "used": int(used), "extra": int(extra), "at_limit": int(at_limit)}
```

- [ ] **Step 4: Написать verify-скрипт**

Создать `scratchpad/verify_db.py` (путь scratchpad из окружения):

```python
import os, tempfile
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "q.db")
import database as db
db.init_db()

# атрибуция
assert db.record_acquisition(1, "alice", "whatsapp") is True
assert db.record_acquisition(1, "alice", "whatsapp") is False   # идемпотентно
assert db.record_acquisition(2, "bob", "instagram") is True
st = db.acquisition_stats()
assert st["total"] == 2 and st["today"] == 2, st
assert ("whatsapp", 1) in st["by_source"]

# квота
q = db.get_quota(100)
assert q["base_limit"] == 130 and q["used"] == 0 and q["extra"] == 0, q
assert db.quota_available(100) == 130
for _ in range(130):
    db.consume_quota(100)
assert db.quota_available(100) == 0, db.quota_available(100)
db.consume_quota(100)                       # сверх лимита без extra — не уходит в минус
assert db.quota_available(100) == 0
assert db.add_quota_extra(100, 100) == 100
assert db.quota_available(100) == 100
db.consume_quota(100)                        # тратит extra
assert db.quota_available(100) == 99, db.quota_available(100)

# пуш о лимите — антиспам
db2 = db.get_quota(200)
for _ in range(130):
    db.consume_quota(200)
assert db.quota_available(200) == 0
assert db.should_notify_limit(200) is True   # первый раз — да
assert db.should_notify_limit(200) is False  # в течение суток — нет

qs = db.quota_stats()
assert qs["accounts"] >= 2 and qs["at_limit"] >= 1, qs
print("OK verify_db")
```

- [ ] **Step 5: Запустить verify**

Run: `python3 scratchpad/verify_db.py`
Expected: `OK verify_db` (без AssertionError)

- [ ] **Step 6: Smoke-проверка синтаксиса**

Run: `python3 -c "import database; database  # import ok"`
Expected: без ошибок

- [ ] **Step 7: Commit**

```bash
git add database.py
git commit -m "feat(quota): таблицы user_acquisition/invoice_quota + хелперы (атрибуция, квота 130, несгораемый extra)"
```

---

### Task 2: Константы и импорты в api.py

**Files:**
- Modify: `api.py:28-43` (импорт из database — добавить новые имена)
- Modify: `api.py:109` (рядом с `DEMO_ONLY` — `OWNER_CHAT_ID`)
- Modify: `api.py:500` (`DEMO_PLAN_INVOICES = 300` → `130`)
- Modify: `api.py` (рядом, тексты пакета и клавиатура менеджера)

**Interfaces:**
- Produces: константы `OWNER_CHAT_ID`, `DEMO_PLAN_INVOICES` (=130), `LIMIT_REACHED_TEXT`, функция `_wiregroup_kb()`; импортированные хелперы БД.

- [ ] **Step 1: Расширить импорт из database**

В `api.py:28-43` в блок `from database import (...)` добавить строку перед закрывающей `)`:

```python
    record_acquisition, acquisition_stats,
    get_quota, quota_available, consume_quota, add_quota_extra,
    reset_quota_if_due, should_notify_limit, quota_stats,
```

- [ ] **Step 2: Добавить OWNER_CHAT_ID**

После `api.py:109` (`DEMO_ONLY = ...`) добавить:

```python
OWNER_CHAT_ID = int(os.getenv("OWNER_CHAT_ID", "8727082281"))  # владелец — пуши и /stats
```

- [ ] **Step 3: Лимит → 130**

В `api.py:500` заменить:

```python
DEMO_PLAN_INVOICES = 300
```
на
```python
DEMO_PLAN_INVOICES = 130  # базовый месячный лимит накладных на аккаунт (default base_limit)
```

- [ ] **Step 4: Текст лимита и клавиатура менеджера**

После `_demo_upsell_kb` (`api.py:510-513`) добавить:

```python
LIMIT_REACHED_TEXT = (
    "📦 Лимит {limit} накладных в этом месяце исчерпан.\n"
    "Докупить: +50 за 4 000 ₸ или +100 за 8 000 ₸ — напишите менеджеру.\n"
    "Остаток докупленного переносится на следующий месяц."
)

def _wiregroup_kb() -> dict:
    return {"inline_keyboard": [
        [{"text": "💬 Написать менеджеру — докупить", "url": "https://t.me/wiregroup"}],
    ]}
```

- [ ] **Step 5: Smoke-проверка синтаксиса**

Run: `python3 -m py_compile api.py`
Expected: без вывода (успех)

- [ ] **Step 6: Commit**

```bash
git add api.py
git commit -m "feat(quota): OWNER_CHAT_ID, лимит 130, текст докупки, импорт хелперов"
```

---

### Task 3: Фича 1 — захват источника, пуш о новом юзере, /stats

**Files:**
- Modify: `api.py:4789-4796` (обработчик `/start` — парсинг параметра + атрибуция + пуш)
- Modify: `api.py` (хелпер `_build_stats_text`, рядом со схемой текстов, напр. после `LIMIT_REACHED_TEXT`)
- Modify: `api.py:4797` (вставить обработчики `/stats` перед catch-all `/`-команд)

**Interfaces:**
- Consumes: `record_acquisition`, `acquisition_stats`, `quota_stats` (Task 1), `OWNER_CHAT_ID` (Task 2), `_tg_send`.
- Produces: `_build_stats_text() -> str` (используется здесь и в Task 4).

- [ ] **Step 1: Хелпер сводки**

После `LIMIT_REACHED_TEXT`/`_wiregroup_kb` добавить:

```python
def _build_stats_text() -> str:
    a = acquisition_stats()
    q = quota_stats()
    src = " · ".join(f"{s} {c}" for s, c in a["by_source"]) or "—"
    return (
        f"👥 Юзеры демо-бота\n"
        f"Всего: {a['total']} · сегодня: {a['today']} · за неделю: {a['week']}\n"
        f"Источники: {src}\n\n"
        f"📦 Накладные (платные аккаунты)\n"
        f"Активных аккаунтов: {q['accounts']}\n"
        f"Распознано в этом месяце: {q['used']}\n"
        f"Докуплено (баланс): {q['extra']}\n"
        f"Упёрлись в лимит: {q['at_limit']} аккаунтов"
    )
```

- [ ] **Step 2: Парсинг `/start` + атрибуция + пуш**

В `api.py:4790-4796` заменить:

```python
        text = message.get("text") or ""
        if text == "/start":
            if DEMO_ONLY:
                await _tg_send(chat_id, DEMO_WELCOME_TEXT, _demo_start_kb())
            else:
                await _tg_send(chat_id, WELCOME_TEXT, _start_kb())
            return {"ok": True}
```
на
```python
        text = message.get("text") or ""
        if text.startswith("/start"):
            parts = text.split(maxsplit=1)
            source = parts[1].strip() if len(parts) > 1 else "direct"
            if DEMO_ONLY:
                if record_acquisition(telegram_id, username, source):
                    try:
                        ts = datetime.now().strftime("%d.%m.%Y %H:%M")
                        uname = f"@{username}" if username else "(без username)"
                        await _tg_send(OWNER_CHAT_ID,
                                       f"🆕 Новый юзер {uname}\nИсточник: {source}\n{ts}")
                    except Exception as e:
                        logger.warning(f"[acq] owner notify {telegram_id}: {e}")
                await _tg_send(chat_id, DEMO_WELCOME_TEXT, _demo_start_kb())
            else:
                await _tg_send(chat_id, WELCOME_TEXT, _start_kb())
            return {"ok": True}
```

- [ ] **Step 3: Обработчик /stats**

После блока `/faq` `/help` (`api.py:4797-4799`), перед `if text.startswith("/")` добавить:

```python
        if text == "/stats" and chat_id == OWNER_CHAT_ID:
            await _tg_send(chat_id, _build_stats_text())
            return {"ok": True}
```

- [ ] **Step 4: Smoke-проверка синтаксиса**

Run: `python3 -m py_compile api.py`
Expected: без вывода

- [ ] **Step 5: Ручная проверка**

В демо-боте (`DEMO_ONLY=true`) открыть ссылку `t.me/<bot>?start=whatsapp` новым юзером →
- владелец (`8727082281`) получает «🆕 Новый юзер … Источник: whatsapp …»;
- повторный `/start` тем же юзером пуш НЕ шлёт.
Команда `/stats` от владельца → приходит сводка. От не-владельца — игнор.

- [ ] **Step 6: Commit**

```bash
git add api.py
git commit -m "feat(demo): источник из ?start=, пуш владельцу о новом юзере, /stats (юзеры+накладные)"
```

---

### Task 4: Фича 1 — ежедневный пуш-сводка

**Files:**
- Modify: `api.py` (новый цикл `_daily_stats_scheduler` рядом с `_demo_sales_scheduler` `api.py:3635`)
- Modify: `api.py:783-796` (запуск цикла в startup-хуке)

**Interfaces:**
- Consumes: `_build_stats_text` (Task 3), `OWNER_CHAT_ID`, `_tg_send`.

- [ ] **Step 1: Цикл планировщика**

После `_demo_sales_scheduler` (`api.py:3651`, перед `_weekly_report_scheduler`) добавить:

```python
async def _daily_stats_scheduler():
    """Раз в сутки шлёт владельцу сводку: юзеры демо-бота + расход накладных."""
    while True:
        await asyncio.sleep(86400)
        try:
            await _tg_send(OWNER_CHAT_ID, _build_stats_text())
        except Exception as e:
            logger.warning(f"[daily_stats] {e}")
```

- [ ] **Step 2: Запуск в startup**

В startup-хуке (`api.py:792-796`), рядом с `asyncio.create_task(_weekly_report_scheduler())`, добавить:

```python
    asyncio.create_task(_daily_stats_scheduler())
```

- [ ] **Step 3: Smoke-проверка синтаксиса**

Run: `python3 -m py_compile api.py`
Expected: без вывода

- [ ] **Step 4: Ручная проверка**

Временно заменить `await asyncio.sleep(86400)` на `await asyncio.sleep(15)` локально, запустить апп, убедиться что через 15с владельцу пришла сводка; вернуть 86400 обратно.

- [ ] **Step 5: Commit**

```bash
git add api.py
git commit -m "feat(demo): ежедневный пуш-сводка владельцу (юзеры + накладные)"
```

---

### Task 5: Фича 2 — гейт лимита, списание, пуш о лимите

**Files:**
- Modify: `api.py:4387-4392` (рядом с `_demo_after_recognition` — новые `_invoice_gate`, `_quota_gate`, `_after_recognition`)
- Modify: `api.py:4408-4409` (в `_recognize_invoice_and_create_pending` — заменить вызов гейта)
- Modify: `api.py:4445` (в `_recognize_...` — заменить пост-обработку)
- Modify: `api.py:4810-4811` (текстовый путь — заменить гейт)
- Modify: `api.py` (текстовый путь после создания pending — добавить пост-обработку)

**Interfaces:**
- Consumes: `reset_quota_if_due`, `quota_available`, `consume_quota`, `should_notify_limit` (Task 1), `OWNER_CHAT_ID`, `LIMIT_REACHED_TEXT`, `_wiregroup_kb`, `DEMO_PLAN_INVOICES` (Task 2), существующие `_demo_block_if_used`, `_demo_after_recognition`.
- Produces: `_invoice_gate(chat_id, telegram_id, username) -> bool`, `_after_recognition(chat_id, telegram_id) -> None`.

- [ ] **Step 0: Добавить рубильник `QUOTA_ENFORCE`**

Рядом с `OWNER_CHAT_ID` (`api.py:113`) добавить константу:

```python
# Рубильник блокировки по лимиту. По умолчанию 0 — лимит только считается
# (кнопка «Лимит»/статистика показывают расход), но распознавание НЕ блокируется.
# Поставить 1, когда владелец убедится в корректности цифр — тогда лимит блокирует.
QUOTA_ENFORCE = os.getenv("QUOTA_ENFORCE", "0").strip().lower() in ("1", "true", "yes", "on")
```

- [ ] **Step 1: Добавить гейт и пост-обработку**

После `_demo_after_recognition` (`api.py:4392`) добавить:

```python
async def _quota_gate(chat_id: int, telegram_id: int, username: str) -> bool:
    """Основной бот: месячный лимит накладных. True если распознавание блокировано."""
    if DEMO_ONLY:
        return False  # на демо-боте свой лимит — _demo_block_if_used
    reset_quota_if_due(telegram_id)
    if quota_available(telegram_id) > 0:
        return False
    if not QUOTA_ENFORCE:
        return False  # рубильник выключен: лимит только считается, не блокируем
    await _tg_send(chat_id, LIMIT_REACHED_TEXT.format(limit=DEMO_PLAN_INVOICES), _wiregroup_kb())
    if should_notify_limit(telegram_id):
        uname = f"@{username}" if username else "(без username)"
        try:
            await _tg_send(OWNER_CHAT_ID, f"🚫 Аккаунт упёрся в лимит\nid: {telegram_id} · {uname}")
        except Exception as e:
            logger.warning(f"[quota] owner notify {telegram_id}: {e}")
    return True


async def _invoice_gate(chat_id: int, telegram_id: int, username: str) -> bool:
    """Единый гейт перед распознаванием: демо-лимит ИЛИ месячный лимит основного бота."""
    if await _demo_block_if_used(chat_id, telegram_id):
        return True
    if await _quota_gate(chat_id, telegram_id, username):
        return True
    return False


async def _after_recognition(chat_id: int, telegram_id: int) -> None:
    """После успешного распознавания: демо-счётчик ИЛИ списание месячной квоты."""
    await _demo_after_recognition(chat_id, telegram_id)
    if not DEMO_ONLY:
        consume_quota(telegram_id)
```

- [ ] **Step 2: Подключить гейт в `_recognize_invoice_and_create_pending`**

В `api.py:4407-4409` заменить:

```python
    # Демо-бот: лимит — 1 распознавание, дальше только продающее сообщение.
    if await _demo_block_if_used(chat_id, telegram_id):
        return
```
на
```python
    # Гейт: демо-лимит ИЛИ месячный лимит накладных основного бота.
    if await _invoice_gate(chat_id, telegram_id, username):
        return
```

- [ ] **Step 3: Подключить списание в `_recognize_invoice_and_create_pending`**

В `api.py:4445` заменить:

```python
    await _demo_after_recognition(chat_id, telegram_id)
```
на
```python
    await _after_recognition(chat_id, telegram_id)
```

- [ ] **Step 4: Подключить гейт в текстовом пути**

В `api.py:4809-4811` заменить:

```python
            # Демо-бот: лимит — 1 распознавание, дальше только продающее сообщение.
            if await _demo_block_if_used(chat_id, telegram_id):
                return {"ok": True}
```
на
```python
            # Гейт: демо-лимит ИЛИ месячный лимит накладных основного бота.
            if await _invoice_gate(chat_id, telegram_id, username):
                return {"ok": True}
```

- [ ] **Step 5: Подключить списание в текстовом пути**

В текстовом пути pending создаётся и отрисовывается ниже `api.py:4823`. Найти конец этого блока — строку, где после `_persist_pending`/отправки превью обработчик делает `return {"ok": True}` (завершение успешной ветки текстового распознавания). Непосредственно ПЕРЕД этим `return {"ok": True}` добавить:

```python
            await _after_recognition(chat_id, telegram_id)
```

(Если в текстовой ветке несколько точек выхода — добавить только в успешную, после фактического создания `pending`, не в ветку ошибки `api.py:4815-4820`.)

- [ ] **Step 6: Smoke-проверка синтаксиса**

Run: `python3 -m py_compile api.py`
Expected: без вывода

- [ ] **Step 7: Ручная проверка**

На основном боте (`DEMO_ONLY` не задан): через `/addquota` (Task 6) или вручную в БД выставить аккаунту `used = base_limit`, прислать фото накладной →
- бот отвечает «📦 Лимит 130 … исчерпан …» с кнопкой менеджера;
- владелец получает «🚫 Аккаунт упёрся в лимит … id … @username»;
- повторная попытка в тот же день владельцу пуш НЕ шлёт.
До лимита — распознавание работает как раньше, `used` растёт на 1 за документ (проверить `/limit` из Task 6).

- [ ] **Step 8: Commit**

```bash
git add api.py
git commit -m "feat(quota): гейт лимита накладных на основном боте, списание по документам, пуш владельцу о лимите"
```

---

### Task 6: Фича 2 — кнопка «Лимит» и /addquota

**Files:**
- Modify: `api.py:3346-3354` (`_start_kb` — добавить кнопку «📦 Лимит»)
- Modify: `api.py:4588-4590` (callback-секция — ветка `limit:show`)
- Modify: `api.py:4797` (текстовые команды `/limit` и `/addquota` перед catch-all `/`)

**Interfaces:**
- Consumes: `get_quota`, `reset_quota_if_due`, `add_quota_extra` (Task 1), `OWNER_CHAT_ID` (Task 2), `_tg_send`.
- Produces: `_limit_text(telegram_id) -> str`.

- [ ] **Step 1: Хелпер текста лимита**

Рядом с `_build_stats_text` (Task 3) добавить:

```python
def _limit_text(telegram_id: int) -> str:
    reset_quota_if_due(telegram_id)
    q = get_quota(telegram_id)
    base_left = max(0, q["base_limit"] - q["used"])
    avail = base_left + q["extra"]
    reset_date = datetime.fromtimestamp(q["period_start_ts"] + 30 * 86400).strftime("%d.%m.%Y")
    return (
        f"📦 Накладные\n"
        f"По подписке в этом месяце: {base_left} из {q['base_limit']}\n"
        f"Докуплено (баланс): {q['extra']}\n"
        f"Доступно всего: {avail}\n"
        f"Лимит обновится: {reset_date}"
    )
```

- [ ] **Step 2: Кнопка «📦 Лимит» в стартовой клавиатуре основного бота**

В `_start_kb` (`api.py:3347-3353`) в список `inline_keyboard` добавить строку (после Mini App):

```python
            [{"text": "📦 Лимит накладных", "callback_data": "limit:show"}],
```

- [ ] **Step 3: Обработка callback `limit:show`**

В callback-секции после ветки `info:faq` (`api.py:4588-4590`), перед `if action.startswith("info:faq:")`, добавить:

```python
            if action == "limit:show":
                tg_id = cb.get("from", {}).get("id", 0)
                await _tg_send(chat_id, _limit_text(tg_id))
                return {"ok": True}
```

- [ ] **Step 4: Команды /limit и /addquota**

После обработчика `/stats` (Task 3, `api.py:~4800`), перед `if text.startswith("/")`, добавить:

```python
        if text in ("/limit", "📦 Лимит накладных") and not DEMO_ONLY:
            await _tg_send(chat_id, _limit_text(telegram_id))
            return {"ok": True}
        if text.startswith("/addquota") and chat_id == OWNER_CHAT_ID:
            parts = text.split()
            if len(parts) == 3 and parts[1].isdigit() and parts[2].lstrip("-").isdigit():
                tid, n = int(parts[1]), int(parts[2])
                new_extra = add_quota_extra(tid, n)
                await _tg_send(chat_id,
                               f"✅ Аккаунту {tid} начислено {n}. Баланс докупленного: {new_extra}.")
            else:
                await _tg_send(chat_id, "Формат: /addquota <telegram_id> <кол-во>")
            return {"ok": True}
```

- [ ] **Step 5: Smoke-проверка синтаксиса**

Run: `python3 -m py_compile api.py`
Expected: без вывода

- [ ] **Step 6: Ручная проверка**

На основном боте: `/start` → есть кнопка «📦 Лимит накладных», тап → показывает «по подписке / докуплено / доступно всего / дата». Команда `/limit` — то же. Владелец: `/addquota <свой_id> 50` → «✅ … начислено 50 …», затем `/limit` показывает баланс докупленного 50. `/addquota` от не-владельца — игнор.

- [ ] **Step 7: Commit**

```bash
git add api.py
git commit -m "feat(quota): кнопка/команда Лимит (остаток+баланс), админ-команда /addquota"
```

---

## Self-Review

**Spec coverage:**
- Фича 1: источник из `?start=` (Task 3 Step 2) ✓; таблица `user_acquisition` (Task 1) ✓; пуш о новом юзере (Task 3 Step 2) ✓; `/stats` (Task 3 Step 3) ✓; ежедневный пуш (Task 4) ✓.
- Фича 2: таблица `invoice_quota` + хелперы (Task 1) ✓; лимит 130, гейт, счёт по документам (Task 5) ✓; несгораемый `extra`, расход base→extra (Task 1 `consume_quota`, verify) ✓; два пакета в тексте (Task 2 `LIMIT_REACHED_TEXT`) ✓; пуш о лимите с id+username и антиспам (Task 5 + Task 1 `should_notify_limit`) ✓; кнопка «Лимит» (Task 6) ✓; `/addquota` (Task 6) ✓; «бот = платный» — гейт не требует `plan_active` (Task 5) ✓.
- Не входит: Robokassa — нигде не упоминается ✓. Фраза про возврат — уже удалена (отдельный коммит) ✓.

**Type consistency:** имена хелперов идентичны в Task 1 (определение), Task 2 (импорт) и Task 5/6 (вызовы): `record_acquisition`, `acquisition_stats`, `get_quota`, `quota_available`, `consume_quota`, `add_quota_extra`, `reset_quota_if_due`, `should_notify_limit`, `quota_stats`. `_build_stats_text`/`_limit_text`/`_invoice_gate`/`_after_recognition`/`_quota_gate`/`_wiregroup_kb`/`LIMIT_REACHED_TEXT`/`OWNER_CHAT_ID`/`DEMO_PLAN_INVOICES` — согласованы между задачами.

**Открытый момент реализации:** в Task 5 Step 5 точная строка `return {"ok": True}` успешной текстовой ветки определяется при чтении `api.py` ~4830-4845 (после создания и отрисовки pending). Это единственное место, где нужен взгляд на конкретные строки во время исполнения — логика однозначна (списать после успешного создания pending).
