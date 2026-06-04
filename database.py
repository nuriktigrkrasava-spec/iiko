import sqlite3
import os
import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from cryptography.fernet import Fernet

DB_PATH = os.getenv("DB_PATH", "iiko_boss.db")

def _get_cipher() -> Optional[Fernet]:
    key = os.getenv("ENCRYPTION_KEY")
    if not key:
        return None
    return Fernet(key.encode())

def encrypt_password(password: str) -> str:
    cipher = _get_cipher()
    if not cipher or not password:
        return password
    return cipher.encrypt(password.encode()).decode()

def decrypt_password(encrypted: str) -> str:
    cipher = _get_cipher()
    if not cipher or not encrypted:
        return encrypted
    try:
        return cipher.decrypt(encrypted.encode()).decode()
    except Exception:
        return encrypted

def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        telegram_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        created_at TEXT,
        is_demo INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS restaurants (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id INTEGER,
        api_login TEXT,
        organization_id TEXT,
        organization_name TEXT,
        iiko_server TEXT DEFAULT NULL,
        api_password TEXT DEFAULT NULL,
        created_at TEXT
    );

    CREATE TABLE IF NOT EXISTS ai_cache (
        query_hash TEXT PRIMARY KEY,
        response TEXT,
        date TEXT,
        organization_id TEXT,
        created_at TEXT
    );

    CREATE TABLE IF NOT EXISTS bot_invoices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id INTEGER,
        telegram_user TEXT,
        raw_text TEXT,
        supplier TEXT,
        branch TEXT,
        items TEXT,
        total_amount REAL,
        date TEXT,
        status TEXT DEFAULT 'pending',
        created_at TEXT
    );

    CREATE TABLE IF NOT EXISTS expenses_manual (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        organization_id TEXT,
        name TEXT,
        category TEXT,
        amount REAL,
        kassa TEXT,
        date TEXT,
        created_at TEXT
    );

    CREATE TABLE IF NOT EXISTS pending_invoices (
        pending_id TEXT PRIMARY KEY,
        chat_id INTEGER,
        telegram_id INTEGER,
        data TEXT,
        updated_at TEXT
    );

    CREATE TABLE IF NOT EXISTS plan_links (
        organization_id TEXT PRIMARY KEY,
        url TEXT,
        updated_at TEXT
    );

    CREATE TABLE IF NOT EXISTS client_links (
        organization_id TEXT PRIMARY KEY,
        url TEXT,
        updated_at TEXT
    );
    """)
    conn.commit()
    # Миграция для существующих БД
    for col, definition in [("iiko_server", "TEXT DEFAULT NULL"), ("api_password", "TEXT DEFAULT NULL")]:
        try:
            conn.execute(f"ALTER TABLE restaurants ADD COLUMN {col} {definition}")
            conn.commit()
        except Exception:
            pass
    # Миграция bot_invoices: новые поля для интеграции с iiko
    for col, definition in [
        ("vat_amount", "REAL DEFAULT 0"),
        ("supplier_id", "TEXT"),
        ("organization_id", "TEXT"),
        ("iiko_doc_id", "TEXT"),
        ("iiko_doc_number", "TEXT"),
        ("dedup_hash", "TEXT"),
        ("photo_paths", "TEXT"),
        ("updated_at", "TEXT"),
    ]:
        try:
            conn.execute(f"ALTER TABLE bot_invoices ADD COLUMN {col} {definition}")
            conn.commit()
        except Exception:
            pass
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_bot_invoices_dedup ON bot_invoices(dedup_hash)")
        conn.commit()
    except Exception:
        pass
    conn.close()

def get_user(telegram_id: int) -> Optional[Dict[str, Any]]:
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None

def create_user(telegram_id: int, username: str = None, first_name: str = None):
    conn = get_db()
    conn.execute(
        "INSERT OR IGNORE INTO users (telegram_id, username, first_name, created_at) VALUES (?, ?, ?, ?)",
        (telegram_id, username, first_name, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

def set_demo_mode(telegram_id: int, is_demo: int):
    conn = get_db()
    conn.execute(
        "UPDATE users SET is_demo = ? WHERE telegram_id = ?",
        (is_demo, telegram_id)
    )
    conn.commit()
    conn.close()

def get_restaurants(telegram_id: int) -> List[Dict[str, Any]]:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM restaurants WHERE telegram_id = ? ORDER BY id", (telegram_id,)
    ).fetchall()
    conn.close()
    result = []
    seen_org_ids = set()
    for r in rows:
        d = dict(r)
        org_id = d.get("organization_id", "")
        if org_id in seen_org_ids:
            continue  # дедупликация по organization_id
        seen_org_ids.add(org_id)
        if d.get("api_password"):
            d["api_password"] = decrypt_password(d["api_password"])
        result.append(d)
    return result

def add_restaurant(telegram_id: int, api_login: str, org_id: str, org_name: str,
                   iiko_server: str = None, api_password: str = None):
    conn = get_db()
    conn.execute(
        """INSERT INTO restaurants
           (telegram_id, api_login, organization_id, organization_name, iiko_server, api_password, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (telegram_id, api_login, org_id, org_name, iiko_server,
         encrypt_password(api_password) if api_password else None,
         datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

def delete_restaurant(restaurant_id: int, telegram_id: int):
    conn = get_db()
    conn.execute(
        "DELETE FROM restaurants WHERE id = ? AND telegram_id = ?",
        (restaurant_id, telegram_id)
    )
    conn.commit()
    conn.close()

def delete_all_restaurants(telegram_id: int) -> int:
    """Удалить все рестораны пользователя. Возвращает кол-во удалённых строк."""
    conn = get_db()
    cur = conn.execute(
        "DELETE FROM restaurants WHERE telegram_id = ?",
        (telegram_id,)
    )
    conn.commit()
    n = cur.rowcount
    conn.close()
    return n

def get_ai_cache(query_hash: str, org_id: str, date_str: str) -> Optional[str]:
    conn = get_db()
    row = conn.execute(
        "SELECT response FROM ai_cache WHERE query_hash = ? AND organization_id = ? AND date = ?",
        (query_hash, org_id, date_str)
    ).fetchone()
    conn.close()
    return row["response"] if row else None

def set_ai_cache(query_hash: str, response: str, org_id: str, date_str: str):
    conn = get_db()
    conn.execute(
        """INSERT OR REPLACE INTO ai_cache (query_hash, response, date, organization_id, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (query_hash, response, date_str, org_id, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

def add_manual_expense(org_id: str, name: str, category: str, amount: float, kassa: str, date: str):
    conn = get_db()
    conn.execute(
        """INSERT INTO expenses_manual (organization_id, name, category, amount, kassa, date, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (org_id, name, category, amount, kassa, date, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

def get_manual_expenses(org_id: str, date_from: str, date_to: str) -> List[Dict[str, Any]]:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM expenses_manual WHERE organization_id = ? AND date >= ? AND date <= ? ORDER BY date DESC",
        (org_id, date_from, date_to)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def delete_manual_expense(expense_id: int, org_id: str):
    conn = get_db()
    conn.execute(
        "DELETE FROM expenses_manual WHERE id = ? AND organization_id = ?",
        (expense_id, org_id)
    )
    conn.commit()
    conn.close()


def save_bot_invoice(telegram_id: int, telegram_user: str, raw_text: str,
                     supplier: str, branch: str, items_json: str,
                     total_amount: float, date: str,
                     *,
                     vat_amount: float = 0.0,
                     supplier_id: Optional[str] = None,
                     organization_id: Optional[str] = None,
                     iiko_doc_id: Optional[str] = None,
                     iiko_doc_number: Optional[str] = None,
                     dedup_hash: Optional[str] = None,
                     photo_paths: Optional[str] = None,
                     status: str = "pending") -> int:
    now = datetime.now().isoformat()
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO bot_invoices
           (telegram_id, telegram_user, raw_text, supplier, branch, items, total_amount, date,
            vat_amount, supplier_id, organization_id, iiko_doc_id, iiko_doc_number,
            dedup_hash, photo_paths, status, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (telegram_id, telegram_user, raw_text, supplier, branch, items_json,
         total_amount, date, vat_amount, supplier_id, organization_id,
         iiko_doc_id, iiko_doc_number, dedup_hash, photo_paths, status, now, now)
    )
    conn.commit()
    inv_id = cur.lastrowid
    conn.close()
    return inv_id


def get_bot_invoices(limit: int = 50, organization_id: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = get_db()
    if organization_id:
        rows = conn.execute(
            "SELECT * FROM bot_invoices WHERE organization_id = ? ORDER BY created_at DESC LIMIT ?",
            (organization_id, limit)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM bot_invoices ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_bot_invoice(invoice_id: int) -> Optional[Dict[str, Any]]:
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM bot_invoices WHERE id = ?", (invoice_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def update_bot_invoice(invoice_id: int, **fields) -> None:
    """Обновляет произвольные поля накладной. updated_at выставляется автоматически."""
    if not fields:
        return
    allowed = {
        "supplier", "branch", "items", "total_amount", "date",
        "vat_amount", "supplier_id", "organization_id",
        "iiko_doc_id", "iiko_doc_number", "dedup_hash", "photo_paths", "status",
    }
    safe = {k: v for k, v in fields.items() if k in allowed}
    if not safe:
        return
    safe["updated_at"] = datetime.now().isoformat()
    set_clause = ", ".join(f"{k} = ?" for k in safe)
    params = list(safe.values()) + [invoice_id]
    conn = get_db()
    conn.execute(f"UPDATE bot_invoices SET {set_clause} WHERE id = ?", params)
    conn.commit()
    conn.close()


def find_invoice_by_dedup(dedup_hash: str, telegram_id: int,
                          days: int = 30) -> Optional[Dict[str, Any]]:
    """Ищет накладную с таким же хешем у того же пользователя за последние N дней."""
    if not dedup_hash:
        return None
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    conn = get_db()
    row = conn.execute(
        """SELECT * FROM bot_invoices
           WHERE dedup_hash = ? AND telegram_id = ? AND created_at >= ?
           ORDER BY created_at DESC LIMIT 1""",
        (dedup_hash, telegram_id, cutoff)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# ---- Pending invoices (живут в RAM бота, дублируются в БД чтобы пережить рестарт) ----

def save_pending_invoice(pending_id: str, chat_id: int, telegram_id: int,
                         data_json: str) -> None:
    """Сохраняет/обновляет pending-накладную (JSON без сырых байт фото)."""
    conn = get_db()
    conn.execute(
        """INSERT OR REPLACE INTO pending_invoices
           (pending_id, chat_id, telegram_id, data, updated_at)
           VALUES (?, ?, ?, ?, ?)""",
        (pending_id, chat_id, telegram_id, data_json, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()


def get_pending_invoice(pending_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM pending_invoices WHERE pending_id = ?", (pending_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_pending_invoice_by_chat(chat_id: int) -> Optional[Dict[str, Any]]:
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM pending_invoices WHERE chat_id = ? ORDER BY updated_at DESC LIMIT 1",
        (chat_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_pending_invoice_by_chat(chat_id: int) -> None:
    conn = get_db()
    conn.execute("DELETE FROM pending_invoices WHERE chat_id = ?", (chat_id,))
    conn.commit()
    conn.close()


def get_price_history(telegram_id: int, days: int = 90) -> List[Dict[str, Any]]:
    """Все позиции из сохранённых накладных пользователя за N дней.

    Возвращает плоский список: [{key, name, price_per_unit, supplier, date, unit}, ...]
    где key = iiko_product_id (если есть) или name.strip().lower().
    Используется для построения сравнения цен в боте (кнопка 📊 Сравнить цены).
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.execute(
        """SELECT items, supplier, date, created_at FROM bot_invoices
           WHERE telegram_id = ?
             AND date(COALESCE(date, substr(created_at, 1, 10))) >= date('now', ?)
             AND items IS NOT NULL AND items != ''""",
        (telegram_id, f"-{int(days)} days")
    )
    out: List[Dict[str, Any]] = []
    for row in cursor.fetchall():
        try:
            items = json.loads(row["items"]) or []
        except Exception:
            continue
        for it in items:
            name = (it.get("name") or "").strip()
            if not name:
                continue
            price = it.get("price_per_unit")
            if price is None or float(price) <= 0:
                continue
            key = it.get("iiko_product_id") or name.lower()
            out.append({
                "key": str(key),
                "name": name,
                "price_per_unit": float(price),
                "supplier": row["supplier"] or "—",
                "date": row["date"] or (row["created_at"] or "")[:10],
                "unit": it.get("unit") or "",
            })
    conn.close()
    return out


# ── План продаж (ссылка на Google-таблицу с планом по филиалу) ──────────────
def get_plan_url(organization_id: str) -> Optional[str]:
    conn = get_db()
    row = conn.execute(
        "SELECT url FROM plan_links WHERE organization_id = ?", (organization_id,)
    ).fetchone()
    conn.close()
    return row["url"] if row else None

def set_plan_url(organization_id: str, url: str):
    conn = get_db()
    conn.execute(
        "INSERT INTO plan_links (organization_id, url, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(organization_id) DO UPDATE SET url = excluded.url, updated_at = excluded.updated_at",
        (organization_id, url, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()


def get_client_url(organization_id: str) -> Optional[str]:
    conn = get_db()
    row = conn.execute(
        "SELECT url FROM client_links WHERE organization_id = ?", (organization_id,)
    ).fetchone()
    conn.close()
    return row["url"] if row else None

def set_client_url(organization_id: str, url: str):
    conn = get_db()
    conn.execute(
        "INSERT INTO client_links (organization_id, url, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(organization_id) DO UPDATE SET url = excluded.url, updated_at = excluded.updated_at",
        (organization_id, url, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()
