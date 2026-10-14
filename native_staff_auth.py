"""Opt-in native staff sessions, confirmed with signed Telegram Mini App data.

No owner/manager credentials are issued. Revoking/reissuing a staff link
invalidates its native sessions on their next request. Production stays disabled
until NATIVE_STAFF_ENABLED=1 is explicitly configured by the operator.
"""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import hmac
import html
import os
import re
import secrets
import time
from urllib.parse import parse_qsl, urlsplit

from fastapi import APIRouter, Header, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
import database as D

router = APIRouter()
CHALLENGE_TTL = 300
SESSION_TTL = 30 * 86400


def _enabled():
    import api
    if os.getenv('NATIVE_STAFF_ENABLED') != '1' or not api.BOT_TOKEN:
        raise HTTPException(503, 'Native staff sign-in is not enabled')


def _public_base():
    # Never use a request Host header to construct an identity confirmation URL.
    value = (os.getenv('NATIVE_APP_ORIGIN') or os.getenv('RENDER_EXTERNAL_URL') or os.getenv('MINIAPP_URL') or '').rstrip('/')
    try:
        uri = urlsplit(value)
        valid = (uri.scheme == 'https' and bool(uri.hostname) and not uri.username
                 and not uri.password and not uri.path and not uri.query
                 and not uri.fragment and uri.port in (None, 443))
    except ValueError:
        valid = False
    if not valid:
        raise HTTPException(503, 'Canonical HTTPS origin is not configured')
    return value


@router.get('/api/native-staff/config')
async def config(response: Response):
    import api
    response.headers['Cache-Control'] = 'no-store'
    try:
        _enabled()
        _public_base()
    except HTTPException:
        return {'enabled':False}
    return {'enabled':True, 'bot_username':api.BOT_USERNAME}


def _hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _db():
    conn = D.get_db()
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS native_staff_challenges (
      id TEXT PRIMARY KEY, secret_hash TEXT NOT NULL,
      org TEXT NOT NULL, employee_id TEXT NOT NULL, code_hash TEXT NOT NULL,
      display_code TEXT NOT NULL, created_at INTEGER NOT NULL,
      expires_at INTEGER NOT NULL, approved_by INTEGER
    );
    CREATE TABLE IF NOT EXISTS native_staff_sessions (
      secret_hash TEXT PRIMARY KEY, org TEXT NOT NULL,
      employee_id TEXT NOT NULL, code_hash TEXT NOT NULL,
      telegram_id INTEGER NOT NULL, expires_at INTEGER NOT NULL
    );
    ''')
    return conn


def _staff_row(conn, org, employee_id, code_hash):
    row = conn.execute('SELECT * FROM staff_access WHERE organization_id=? AND employee_id=? AND active=1', (org, employee_id)).fetchone()
    if not row or not hmac.compare_digest(_hash(row['code']), code_hash):
        raise HTTPException(401, 'Staff access was revoked or replaced')
    return dict(row)


def _challenge(conn, challenge):
    row = conn.execute('SELECT * FROM native_staff_challenges WHERE id=?', (challenge,)).fetchone()
    if not row or row['expires_at'] <= int(time.time()):
        raise HTTPException(410, 'Sign-in request expired')
    return dict(row)


def authenticate(secret):
    """Called only by get_staff, never by get_current_user."""
    _enabled()
    if not isinstance(secret, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', secret):
        raise HTTPException(401, 'Native staff session required')
    with closing(_db()) as conn:
        session = conn.execute('SELECT * FROM native_staff_sessions WHERE secret_hash=?', (_hash(secret),)).fetchone()
        if not session or session['expires_at'] <= int(time.time()):
            raise HTTPException(401, 'Native staff session expired')
        row = _staff_row(conn, session['org'], session['employee_id'], session['code_hash'])
        if int(row['telegram_id'] or 0) != session['telegram_id']:
            raise HTTPException(401, 'Telegram binding changed')
        return {'org':row['organization_id'], 'employee_id':row['employee_id'],
                'name':row['name'] or '', 'telegram_id':session['telegram_id']}


class Begin(BaseModel):
    code: str = Field(min_length=1, max_length=256)


class Poll(BaseModel):
    challenge: str = Field(min_length=24, max_length=24)
    secret: str = Field(min_length=43, max_length=43)


class Confirm(BaseModel):
    challenge: str = Field(min_length=24, max_length=24)
    display_code: str = Field(pattern=r'^\d{6}$')


@router.post('/api/native-staff/begin')
async def begin(payload: Begin, request: Request, response: Response):
    _enabled()
    import api
    _public_base()
    row = D.staff_access_by_code(payload.code)
    if not row:
        raise HTTPException(401, 'Staff link is invalid')
    now = int(time.time())
    secret, challenge = secrets.token_urlsafe(32), secrets.token_urlsafe(18)
    display_code = f'{secrets.randbelow(1000000):06d}'
    with closing(_db()) as conn:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('DELETE FROM native_staff_challenges WHERE expires_at<=?', (now,))
        conn.execute('DELETE FROM native_staff_sessions WHERE expires_at<=?', (now,))
        count = conn.execute('SELECT COUNT(*) FROM native_staff_challenges WHERE code_hash=? AND created_at>?', (_hash(payload.code), now-CHALLENGE_TTL)).fetchone()[0]
        total = conn.execute('SELECT COUNT(*) FROM native_staff_challenges').fetchone()[0]
        if count >= 5 or total >= 1000:
            conn.rollback()
            raise HTTPException(429, 'Too many sign-in requests')
        conn.execute('INSERT INTO native_staff_challenges VALUES (?,?,?,?,?,?,?,?,NULL)',
                     (challenge, _hash(secret), row['organization_id'], row['employee_id'], _hash(payload.code), display_code, now, now+CHALLENGE_TTL))
        conn.commit()
    response.headers['Cache-Control'] = 'no-store'
    return {'challenge':challenge, 'secret':secret, 'display_code':display_code,
            'expires_in':CHALLENGE_TTL, 'telegram_url':f'https://t.me/{api.BOT_USERNAME}?start=native_{challenge}'}


@router.post('/api/native-staff/status')
async def status(payload: Poll, response: Response):
    _enabled()
    response.headers['Cache-Control'] = 'no-store'
    with closing(_db()) as conn:
        row = _challenge(conn, payload.challenge)
        if not hmac.compare_digest(row['secret_hash'], _hash(payload.secret)):
            raise HTTPException(401, 'Invalid sign-in secret')
        if not row['approved_by']:
            return {'status':'pending'}
    identity = authenticate(payload.secret)
    return {'status':'approved', 'name':identity['name']}


def _telegram_user(init_data):
    import api
    if not init_data:
        raise HTTPException(401, 'Open confirmation in Telegram')
    # Reject missing/future auth_date as well as expired data; the old mini-app
    # validator remains unchanged for backwards compatibility.
    try:
        auth_date = int(dict(parse_qsl(init_data)).get('auth_date', '0'))
    except (ValueError, TypeError):
        auth_date = 0
    age = time.time()-auth_date
    if not auth_date or age < -30 or age > CHALLENGE_TTL:
        raise HTTPException(401, 'Telegram confirmation expired')
    user = api.validate_telegram_init_data(init_data)
    tid = int(user.get('id') or 0)
    if not tid:
        raise HTTPException(401, 'Telegram identity required')
    return tid


@router.post('/api/native-staff/confirm')
async def confirm(payload: Confirm, response: Response,
                  init_data: str | None = Header(None, alias='X-Telegram-Init-Data')):
    _enabled()
    tid = _telegram_user(init_data)
    with closing(_db()) as conn:
        conn.execute('BEGIN IMMEDIATE')
        challenge = _challenge(conn, payload.challenge)
        if not hmac.compare_digest(challenge['display_code'], payload.display_code):
            raise HTTPException(403, 'Confirmation code does not match')
        row = _staff_row(conn, challenge['org'], challenge['employee_id'], challenge['code_hash'])
        if row['telegram_id'] and int(row['telegram_id']) != tid:
            raise HTTPException(403, 'Staff link belongs to another Telegram account')
        if challenge['approved_by'] and challenge['approved_by'] != tid:
            raise HTTPException(403, 'Sign-in was already confirmed')
        conn.execute('UPDATE staff_access SET telegram_id=?, bound_at=COALESCE(bound_at,?) WHERE code=? AND (telegram_id IS NULL OR telegram_id=?)', (tid, datetime.now(timezone.utc).isoformat(), row['code'], tid))
        conn.execute('UPDATE native_staff_challenges SET approved_by=? WHERE id=?', (tid, challenge['id']))
        # INSERT OR IGNORE means replaying a signed approval never extends TTL.
        conn.execute('INSERT OR IGNORE INTO native_staff_sessions VALUES (?,?,?,?,?,?)',
                     (challenge['secret_hash'], row['organization_id'], row['employee_id'], challenge['code_hash'], tid, int(time.time())+SESSION_TTL))
        conn.commit()
    response.headers['Cache-Control'] = 'no-store'
    return {'ok':True}


@router.post('/api/native-staff/logout')
async def logout(response: Response, secret: str | None = Header(None, alias='X-Native-Session')):
    _enabled()
    if not secret:
        raise HTTPException(401, 'Native session required')
    with closing(_db()) as conn:
        hashed = _hash(secret)
        conn.execute('DELETE FROM native_staff_sessions WHERE secret_hash=?', (hashed,))
        conn.execute('DELETE FROM native_staff_challenges WHERE secret_hash=?', (hashed,))
        conn.commit()
    response.headers['Cache-Control'] = 'no-store'
    return {'ok':True}


@router.get('/native-staff/{challenge}', response_class=HTMLResponse)
async def confirmation_page(challenge: str):
    _enabled()
    with closing(_db()) as conn:
        row = _challenge(conn, challenge)
        staff = _staff_row(conn, row['org'], row['employee_id'], row['code_hash'])
    # Only the public request ID is present in Telegram. The phone's secret is
    # never included in a URL, confirmation page, bot message or redirect.
    nonce = secrets.token_urlsafe(18)
    code = html.escape(row['display_code'])
    name = html.escape(staff['name'] or 'Сотрудник')
    body = f'''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Подтверждение входа</title><style nonce="{nonce}">body{{font:17px system-ui;background:#f5f5f7;color:#1d1d1f;margin:24px}}main{{max-width:460px;margin:auto}}h1{{font-size:25px}}code{{font:700 40px system-ui;letter-spacing:8px}}button{{width:100%;border:0;border-radius:16px;background:#2f6bff;color:white;padding:16px;font:600 17px system-ui}}p{{line-height:1.5}}</style>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<main><h1>Вход в приложение «Финдиректор»</h1><p>{name}</p><p>Сравните код с кодом в приложении на своём телефоне:</p><p><code>{code}</code></p><p>Подтверждайте только вход, который начали сами. Если коды различаются, закройте эту страницу.</p><button id="confirm">Код совпадает — войти</button><p id="result" role="status"></p></main>
<script nonce="{nonce}">
const button=document.getElementById('confirm'),result=document.getElementById('result');
button.onclick=async()=>{{
 const tg=window.Telegram?.WebApp;
 if(!tg?.initData){{result.textContent='Откройте эту кнопку через Telegram-бота.';return}}
 button.disabled=true;
 try{{const response=await fetch('/api/native-staff/confirm',{{method:'POST',headers:{{'Content-Type':'application/json','X-Telegram-Init-Data':tg.initData}},body:JSON.stringify({{challenge:'{html.escape(challenge)}',display_code:'{code}'}})}});
 if(!response.ok)throw Error();
 result.textContent='Вход подтверждён. Вернитесь в приложение «Финдиректор».';
 button.textContent='Подтверждено';
 }}catch(_){{result.textContent='Не удалось подтвердить вход. Проверьте срок запроса и учётную запись Telegram.';button.disabled=false}}
}};
</script></html>'''
    return HTMLResponse(body, headers={
        'Cache-Control':'no-store', 'Referrer-Policy':'no-referrer',
        'Content-Security-Policy':f"default-src 'none'; script-src 'nonce-{nonce}' https://telegram.org; style-src 'nonce-{nonce}'; connect-src 'self'; base-uri 'none'; form-action 'none'",
    })


async def handle_bot_start(source, chat_id, telegram_id, request):
    """Called by existing webhook; only offers a Mini App, never authenticates."""
    if not source.startswith('native_'):
        return False
    # Never answer a native-login deep link in a group, including disabled mode.
    if chat_id != telegram_id:
        return True
    import api
    try:
        _enabled()
        challenge = source[len('native_'):]
        with closing(_db()) as conn:
            _challenge(conn, challenge)
        base = _public_base()
        await api._tg_send(chat_id, 'Подтвердите вход в приложение только если начали его сами. Сравните код на телефоне с кодом на следующем экране.',
                           {'inline_keyboard':[[{'text':'Подтвердить вход в приложение','web_app':{'url':f'{base}/native-staff/{challenge}'}}]]})
    except HTTPException:
        await api._tg_send(chat_id, 'Запрос входа недоступен или истёк. Начните вход заново в приложении.')
    return True
