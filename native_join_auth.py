"""Review-only native first staff binding. Explicit deployment is required.

A join QR locates a branch; it never identifies a person. Telegram's fresh
signed Mini App payload approves a device challenge, after which that device
may select one current unbound employee. No fabricated initData is used.
"""
from contextlib import closing
from datetime import datetime, timezone
import hmac
import html
import os
import re
import secrets
import time

from fastapi import APIRouter, Header, HTTPException, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
import database as D
import native_staff_auth as N

router = APIRouter()


def _enabled():
    N._enabled()
    if os.getenv('NATIVE_JOIN_ENABLED') != '1':
        raise HTTPException(503, 'Native staff registration is not enabled')


def _db():
    conn = N._db()
    conn.execute('''CREATE TABLE IF NOT EXISTS native_join_challenges (
        id TEXT PRIMARY KEY, secret_hash TEXT NOT NULL, org TEXT NOT NULL,
        join_hash TEXT NOT NULL, display_code TEXT NOT NULL,
        created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
        approved_by INTEGER, consumed_employee TEXT, consumed_code_hash TEXT
    )''')
    conn.commit()
    return conn


def _challenge(conn, challenge, secret=None):
    row = conn.execute('SELECT * FROM native_join_challenges WHERE id=?', (challenge,)).fetchone()
    if not row or row['expires_at'] <= int(time.time()):
        raise HTTPException(410, 'Registration request expired')
    if secret is not None and not hmac.compare_digest(row['secret_hash'], N._hash(secret)):
        raise HTTPException(401, 'Invalid registration secret')
    # Rotation invalidates every unfinished request, including approved ones.
    invite = conn.execute('SELECT code FROM branch_join WHERE organization_id=?', (row['org'],)).fetchone()
    if not invite or not hmac.compare_digest(N._hash(invite['code']), row['join_hash']):
        raise HTTPException(410, 'Branch invitation was replaced')
    return dict(row)


async def _employee_names(org):
    """Same iiko+schedule catalogue as api.join_list; identity stays server-side."""
    import api
    import mountain_routes as M
    info = api._get_restaurant_info(org, {'id': M._owner_of(org), 'username': 'join', 'first_name': 'Join'})
    client = api.get_client(info['api_login'], info.get('iiko_server'), info.get('api_password'))
    names = {}
    if hasattr(client, 'get_employees_map'):
        try:
            names = await client.get_employees_map()
        except Exception:
            # The existing join page also falls back to names from the schedule.
            names = {}
    counts = D.staff_shift_counts(org)
    return [dict(id=eid, name=names.get(eid) or eid[:8], shifts=counts.get(eid, 0))
            for eid in set(names) | set(counts)]


def _mine(conn, org, tid):
    return conn.execute('SELECT * FROM staff_access WHERE organization_id=? AND telegram_id=? AND active=1', (org, tid)).fetchone()


def _require_identity(row):
    if not row['approved_by']:
        raise HTTPException(401, 'Telegram identity has not been confirmed')
    return int(row['approved_by'])


def _session(conn, row, staff, tid):
    # Use precisely the existing employee-scoped session format. Never issue
    # an owner/manager site token and never rotate an active staff access code.
    code_hash = N._hash(staff['code'])
    conn.execute('INSERT OR IGNORE INTO native_staff_sessions VALUES (?,?,?,?,?,?)',
                 (row['secret_hash'], row['org'], staff['employee_id'], code_hash, tid, int(time.time()) + N.SESSION_TTL))
    conn.execute('UPDATE native_join_challenges SET consumed_employee=?, consumed_code_hash=? WHERE id=?',
                 (staff['employee_id'], code_hash, row['id']))


def _consumed_identity(conn, row, secret):
    if not row['consumed_employee']:
        return None
    # Logout/revocation cannot be undone by polling or replaying claim.
    session = conn.execute('SELECT * FROM native_staff_sessions WHERE secret_hash=?', (row['secret_hash'],)).fetchone()
    if not session or session['expires_at'] <= int(time.time()):
        raise HTTPException(401, 'Native staff session was ended')
    staff = N._staff_row(conn, row['org'], row['consumed_employee'], row['consumed_code_hash'])
    if int(staff['telegram_id'] or 0) != row['approved_by']:
        raise HTTPException(401, 'Telegram binding changed')
    return {'status': 'approved', 'name': staff['name'] or ''}


class Begin(BaseModel):
    join_token: str = Field(min_length=1, max_length=256, pattern=r'^[A-Za-z0-9_-]+$')


class Device(BaseModel):
    challenge: str = Field(pattern=r'^[A-Za-z0-9_-]{24}$')
    secret: str = Field(pattern=r'^[A-Za-z0-9_-]{43}$')


class Confirm(BaseModel):
    challenge: str = Field(pattern=r'^[A-Za-z0-9_-]{24}$')
    display_code: str = Field(pattern=r'^\d{6}$')


class Claim(Device):
    employee_id: str = Field(min_length=1, max_length=256)


@router.get('/api/native-join/config')
async def config(response: Response):
    import api
    response.headers['Cache-Control'] = 'no-store'
    try:
        _enabled()
        N._public_base()
    except HTTPException:
        return {'enabled': False}
    return {'enabled': True, 'bot_username': api.BOT_USERNAME}


@router.post('/api/native-join/begin')
async def begin(payload: Begin, response: Response):
    _enabled()
    import api
    N._public_base()
    org = await api._join_org(payload.join_token)
    now = int(time.time())
    challenge, secret = secrets.token_urlsafe(18), secrets.token_urlsafe(32)
    code = f'{secrets.randbelow(1000000):06d}'
    with closing(_db()) as conn:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('DELETE FROM native_join_challenges WHERE expires_at<=?', (now,))
        count = conn.execute('SELECT COUNT(*) FROM native_join_challenges WHERE org=?', (org,)).fetchone()[0]
        total = conn.execute('SELECT COUNT(*) FROM native_join_challenges').fetchone()[0]
        if count >= 50 or total >= 1000:
            raise HTTPException(429, 'Too many registration requests')
        # Recheck while holding the write lock; invite may have rotated during lookup.
        invite = conn.execute('SELECT code FROM branch_join WHERE organization_id=?', (org,)).fetchone()
        if not invite or not hmac.compare_digest(invite['code'], payload.join_token):
            raise HTTPException(410, 'Branch invitation was replaced')
        conn.execute('INSERT INTO native_join_challenges VALUES (?,?,?,?,?,?,?,NULL,NULL,NULL)',
                     (challenge, N._hash(secret), org, N._hash(payload.join_token), code, now, now + N.CHALLENGE_TTL))
        conn.commit()
    response.headers['Cache-Control'] = 'no-store'
    return {'challenge': challenge, 'secret': secret, 'display_code': code,
            'expires_in': N.CHALLENGE_TTL, 'telegram_url': f'https://t.me/{api.BOT_USERNAME}?start=nativejoin_{challenge}'}


@router.post('/api/native-join/confirm')
async def confirm(payload: Confirm, response: Response,
                  init_data: str | None = Header(None, alias='X-Telegram-Init-Data')):
    _enabled()
    import api
    tid = N._telegram_user(init_data)  # strict freshness and valid Telegram signature
    if api._join_tid(init_data) != tid:  # original join identity service, never synthetic data
        raise HTTPException(401, 'Telegram identity mismatch')
    with closing(_db()) as conn:
        conn.execute('BEGIN IMMEDIATE')
        row = _challenge(conn, payload.challenge)
        if not hmac.compare_digest(row['display_code'], payload.display_code):
            raise HTTPException(403, 'Confirmation code does not match')
        if row['approved_by'] and row['approved_by'] != tid:
            raise HTTPException(403, 'Request belongs to another Telegram account')
        conn.execute('UPDATE native_join_challenges SET approved_by=? WHERE id=?', (tid, row['id']))
        conn.commit()
    response.headers['Cache-Control'] = 'no-store'
    return {'ok': True}


@router.post('/api/native-join/status')
async def status(payload: Device, response: Response):
    _enabled()
    response.headers['Cache-Control'] = 'no-store'
    with closing(_db()) as conn:
        conn.execute('BEGIN IMMEDIATE')
        row = _challenge(conn, payload.challenge, payload.secret)
        if not row['approved_by']:
            return {'status': 'pending'}
        consumed = _consumed_identity(conn, row, payload.secret)
        if consumed:
            return consumed
        org, tid = row['org'], _require_identity(row)
        mine = _mine(conn, org, tid)
        if mine:
            _session(conn, row, mine, tid)
            conn.commit()
            return {'status': 'approved', 'name': mine['name'] or ''}
    employees = await _employee_names(org)
    with closing(_db()) as conn:
        conn.execute('BEGIN IMMEDIATE')
        row = _challenge(conn, payload.challenge, payload.secret)
        tid = _require_identity(row)
        consumed = _consumed_identity(conn, row, payload.secret)
        if consumed:
            return consumed
        mine = _mine(conn, org, tid)
        if mine:
            _session(conn, row, mine, tid)
            conn.commit()
            return {'status': 'approved', 'name': mine['name'] or ''}
        taken = {r['employee_id'] for r in conn.execute('SELECT employee_id FROM staff_access WHERE organization_id=? AND (telegram_id IS NOT NULL OR active=0)', (org,))}
    available = [e for e in employees if e['id'] not in taken]
    available.sort(key=lambda e: (-e['shifts'], e['name']))
    return {'status': 'choose', 'branch': D.branch_name(org), 'employees': available}


@router.post('/api/native-join/claim')
async def claim(payload: Claim, response: Response):
    _enabled()
    response.headers['Cache-Control'] = 'no-store'
    with closing(_db()) as conn:
        row = _challenge(conn, payload.challenge, payload.secret)
        _require_identity(row)
        consumed = _consumed_identity(conn, row, payload.secret)
        if consumed:
            if row['consumed_employee'] != payload.employee_id:
                raise HTTPException(409, 'Registration already completed')
            return consumed
        org = row['org']
    # Refresh eligibility on claim; do not trust IDs or employee names from a phone.
    available = {e['id']: e for e in await _employee_names(org)}
    with closing(_db()) as conn:
        conn.execute('BEGIN IMMEDIATE')
        row = _challenge(conn, payload.challenge, payload.secret)
        tid = _require_identity(row)
        consumed = _consumed_identity(conn, row, payload.secret)
        if consumed:
            if row['consumed_employee'] != payload.employee_id:
                raise HTTPException(409, 'Registration already completed')
            return consumed
        mine = _mine(conn, org, tid)
        if mine:
            _session(conn, row, mine, tid)
            conn.commit()
            return {'status': 'approved', 'name': mine['name'] or '', 'already': True}
        employee = available.get(payload.employee_id)
        if not employee:
            raise HTTPException(400, 'Choose an employee from the current branch list')
        existing = conn.execute('SELECT * FROM staff_access WHERE organization_id=? AND employee_id=?', (org, payload.employee_id)).fetchone()
        if existing and (not existing['active'] or existing['telegram_id']):
            raise HTTPException(409, 'Employee is already bound or access was revoked')
        now = datetime.now(timezone.utc).isoformat()
        if existing:
            conn.execute('UPDATE staff_access SET telegram_id=?, bound_at=?, name=? WHERE organization_id=? AND employee_id=? AND active=1 AND telegram_id IS NULL',
                         (tid, now, employee['name'], org, payload.employee_id))
        else:
            conn.execute('INSERT INTO staff_access (organization_id,employee_id,code,name,telegram_id,created_at,bound_at,active) VALUES (?,?,?,?,?,?,?,1)',
                         (org, payload.employee_id, secrets.token_urlsafe(12), employee['name'], tid, now, now))
        staff = conn.execute('SELECT * FROM staff_access WHERE organization_id=? AND employee_id=?', (org, payload.employee_id)).fetchone()
        if not staff or int(staff['telegram_id'] or 0) != tid or not staff['active']:
            raise HTTPException(409, 'Binding changed; refresh the employee list')
        _session(conn, row, staff, tid)
        conn.commit()
    return {'status': 'approved', 'name': staff['name'] or '', 'already': False}


@router.post('/api/native-join/cancel')
async def cancel(payload: Device, response: Response):
    _enabled()
    with closing(_db()) as conn:
        # Expired requests may still be cancelled with the device's secret.
        hashed = N._hash(payload.secret)
        conn.execute('DELETE FROM native_join_challenges WHERE id=? AND secret_hash=?', (payload.challenge, hashed))
        conn.execute('DELETE FROM native_staff_sessions WHERE secret_hash=?', (hashed,))
        conn.commit()
    response.headers['Cache-Control'] = 'no-store'
    return {'ok': True}


@router.get('/native-join/{challenge}', response_class=HTMLResponse)
async def confirmation_page(challenge: str):
    _enabled()
    with closing(_db()) as conn:
        row = _challenge(conn, challenge)
    nonce = secrets.token_urlsafe(18)
    code = html.escape(row['display_code'])
    branch = html.escape(D.branch_name(row['org']))
    body = f'''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Подключение сотрудника</title><style nonce="{nonce}">body{{font:17px system-ui;background:#f5f5f7;color:#1d1d1f;margin:24px}}main{{max-width:460px;margin:auto}}h1{{font-size:25px}}code{{font:700 40px system-ui;letter-spacing:8px}}button{{width:100%;border:0;border-radius:16px;background:#2f6bff;color:white;padding:16px;font:600 17px system-ui}}p{{line-height:1.5}}</style>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<main><h1>Подключение к «Финдиректору»</h1><p>{branch}</p><p>Сравните код с приложением на своём телефоне:</p><p><code>{code}</code></p><p>Подтверждайте только начатое вами подключение. Своё имя выберете в приложении.</p><button id="confirm">Код совпадает — подтвердить</button><p id="result" role="status"></p></main>
<script nonce="{nonce}">
const button=document.getElementById('confirm'),result=document.getElementById('result');
button.onclick=async()=>{{const tg=window.Telegram?.WebApp;if(!tg?.initData){{result.textContent='Откройте подтверждение через Telegram-бота.';return}}button.disabled=true;
try{{const response=await fetch('/api/native-join/confirm',{{method:'POST',headers:{{'Content-Type':'application/json','X-Telegram-Init-Data':tg.initData}},body:JSON.stringify({{challenge:'{html.escape(challenge)}',display_code:'{code}'}})}});if(!response.ok)throw Error();result.textContent='Личность подтверждена. Вернитесь в приложение и выберите себя.';button.textContent='Подтверждено';}}catch(_){{result.textContent='Запрос истёк или подтверждение недоступно. Начните подключение заново.';button.disabled=false}}}};
</script></html>'''
    return HTMLResponse(body, headers={'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer',
        'Content-Security-Policy': f"default-src 'none'; script-src 'nonce-{nonce}' https://telegram.org; style-src 'nonce-{nonce}'; connect-src 'self'; base-uri 'none'; form-action 'none'"})


async def handle_bot_start(source, chat_id, telegram_id, request):
    """Only offers Telegram's signed Mini App. A bot /start never authenticates."""
    if not source.startswith('nativejoin_'):
        return False
    if chat_id != telegram_id:
        return True
    import api
    try:
        _enabled()
        challenge = source[len('nativejoin_'):]
        if not re.fullmatch(r'[A-Za-z0-9_-]{24}', challenge):
            return True
        with closing(_db()) as conn:
            _challenge(conn, challenge)
        base = N._public_base()
        await api._tg_send(chat_id, 'Подтвердите только начатое вами подключение. Сравните код на телефоне с кодом на следующем экране.',
            {'inline_keyboard': [[{'text': 'Подтвердить подключение', 'web_app': {'url': f'{base}/native-join/{challenge}'}}]]})
    except HTTPException:
        await api._tg_send(chat_id, 'Запрос подключения истёк. Начните заново в приложении.')
    return True
