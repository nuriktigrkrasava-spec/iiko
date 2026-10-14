"""Native staff sign-in security; isolated SQLite and no outbound messages."""
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient
import api
import database as D
import native_staff_auth as N

BOT = '123456:synthetic-test-bot-token'


def signed(tid=111, *, age=0, auth_date=True):
    values = {'user':json.dumps({'id':tid,'first_name':'Test'}, separators=(',',':'))}
    if auth_date:
        values['auth_date'] = str(int(time.time())-age)
    text = '\n'.join(f'{k}={v}' for k,v in sorted(values.items()))
    key = hmac.new(b'WebAppData', BOT.encode(), hashlib.sha256).digest()
    values['hash'] = hmac.new(key, text.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(D, 'DB_PATH', str(tmp_path/'native.db'))
    monkeypatch.setattr(api, 'BOT_TOKEN', BOT)
    monkeypatch.setenv('NATIVE_STAFF_ENABLED','1')
    monkeypatch.setenv('NATIVE_APP_ORIGIN','https://example.test')
    monkeypatch.setattr(api, 'get_client', lambda *a,**k: (_ for _ in ()).throw(AssertionError('No iiko access in auth tests')))
    async def no_messages(*a, **k):
        raise AssertionError('No external messages during auth tests')
    monkeypatch.setattr(api, '_tg_send', no_messages)
    D.init_db()
    D.add_restaurant(900, 'test', 'mine', 'Мой филиал', iiko_server='', api_password='')
    D.add_restaurant(901, 'test', 'other', 'Чужой филиал', iiko_server='', api_password='')
    code = D.issue_staff_access('mine','employee','Test Employee')
    client = TestClient(api.app, raise_server_exceptions=True)
    return client, code


def begin(client, code):
    r=client.post('/api/native-staff/begin',json={'code':code})
    assert r.status_code==200,r.text
    assert r.headers['cache-control']=='no-store'
    d=r.json()
    assert len(d['secret'])==43 and len(d['challenge'])==24
    assert d['secret'] not in d['telegram_url'] and code not in d['telegram_url']
    return d


def approve(client, d, tid=111, init=None):
    return client.post('/api/native-staff/confirm',json={'challenge':d['challenge'],'display_code':d['display_code']},headers={'X-Telegram-Init-Data':init or signed(tid)})


def test_pending_is_not_a_session_and_requires_device_secret(env):
    client, code=env;d=begin(client,code)
    assert client.get('/api/me',headers={'X-Native-Session':d['secret']}).status_code==401
    assert client.post('/api/native-staff/status',json={'challenge':d['challenge'],'secret':d['secret']}).json()=={'status':'pending'}
    assert client.post('/api/native-staff/status',json={'challenge':d['challenge'],'secret':'x'*43}).status_code==401
    with N._db() as conn:
        row=dict(conn.execute('SELECT * FROM native_staff_challenges').fetchone())
    assert d['secret'] not in json.dumps(row) and code not in json.dumps(row)


def test_signed_telegram_confirmation_yields_only_own_staff_access(env):
    client, code=env;d=begin(client,code)
    assert approve(client,d).status_code==200
    h={'X-Native-Session':d['secret']}
    assert client.get('/api/me',headers=h).json()['employee_id']=='employee'
    assert client.get('/api/me/week?org_id=other',headers=h).status_code==200
    assert client.get('/api/dashboard/other',headers=h).status_code==401
    assert client.get('/api/restaurants',headers=h).status_code==401
    assert client.post('/api/native-staff/status',json={'challenge':d['challenge'],'secret':d['secret']}).json()['status']=='approved'


@pytest.mark.parametrize('init',[signed(age=301),signed(age=-60),signed(auth_date=False),'auth_date=1&user=%7B%22id%22%3A111%7D&hash=invalid'])
def test_expired_future_missing_and_forged_telegram_proofs_fail(env,init):
    client,code=env;d=begin(client,code)
    assert approve(client,d,init=init).status_code in (401,403)
    assert client.get('/api/me',headers={'X-Native-Session':d['secret']}).status_code==401


def test_bound_link_cannot_be_approved_by_another_person(env):
    client,code=env;assert D.bind_staff_access(code,111)
    d=begin(client,code)
    assert approve(client,d,222).status_code==403
    assert approve(client,d,111).status_code==200


def test_wrong_display_code_is_rejected(env):
    client,code=env;d=begin(client,code);d['display_code']='000000' if d['display_code']!='000000' else '111111'
    assert approve(client,d).status_code==403


@pytest.mark.parametrize('action',['revoke','reissue'])
def test_revocation_and_reissue_invalidate_native_sessions(env,action):
    client,code=env;d=begin(client,code);assert approve(client,d).status_code==200
    if action=='revoke': D.revoke_staff_access('mine','employee')
    else: D.issue_staff_access('mine','employee','New phone')
    assert client.get('/api/me',headers={'X-Native-Session':d['secret']}).status_code==401


def test_expired_challenge_and_session_fail(env):
    client,code=env;d=begin(client,code);assert approve(client,d).status_code==200
    with N._db() as conn:
        conn.execute('UPDATE native_staff_sessions SET expires_at=0')
        conn.execute('UPDATE native_staff_challenges SET expires_at=0')
    assert client.get('/api/me',headers={'X-Native-Session':d['secret']}).status_code==401
    assert approve(client,d).status_code==410


def test_logout_cannot_be_undone_by_replaying_approval(env):
    client,code=env;d=begin(client,code);assert approve(client,d).status_code==200
    h={'X-Native-Session':d['secret']}
    assert client.post('/api/native-staff/logout',headers=h).json()['ok']
    assert client.get('/api/me',headers=h).status_code==401
    assert approve(client,d).status_code==410


def test_feature_disabled_and_confirmation_page_contains_no_secrets(env,monkeypatch):
    client,code=env;d=begin(client,code)
    page=client.get('/native-staff/'+d['challenge'])
    assert page.status_code==200
    assert d['secret'] not in page.text and code not in page.text
    assert 'no-store' in page.headers['cache-control']
    assert 'Content-Security-Policy' in page.headers
    monkeypatch.delenv('NATIVE_STAFF_ENABLED')
    assert client.post('/api/native-staff/begin',json={'code':code}).status_code==503
    assert approve(client,d).status_code==503


def test_rate_limit_is_scoped_and_no_owner_token_can_be_exchanged(env):
    client,code=env
    assert client.post('/api/native-staff/begin',json={'code':'not-a-staff-code'}).status_code==401
    for _ in range(5): begin(client,code)
    assert client.post('/api/native-staff/begin',json={'code':code}).status_code==429


def test_replaying_approval_does_not_extend_session(env):
    client,code=env;d=begin(client,code);assert approve(client,d).status_code==200
    with N._db() as conn: conn.execute('UPDATE native_staff_sessions SET expires_at=?',(int(time.time())+120,))
    assert approve(client,d).status_code==200
    with N._db() as conn: expires=conn.execute('SELECT expires_at FROM native_staff_sessions').fetchone()[0]
    assert expires<=int(time.time())+120


def test_configuration_requires_canonical_https_not_request_host(env,monkeypatch):
    client,code=env
    assert client.get('/api/native-staff/config').json()['enabled'] is True
    monkeypatch.setenv('NATIVE_APP_ORIGIN','http://unsafe.test')
    assert client.get('/api/native-staff/config').json()=={'enabled':False}
    assert client.post('/api/native-staff/begin',json={'code':code},headers={'host':'attacker.test'}).status_code==503
    for value in ['https://safe.test@attacker.test', 'https://safe.test/path', 'https://safe.test?x=1']:
        monkeypatch.setenv('NATIVE_APP_ORIGIN',value)
        assert client.get('/api/native-staff/config').json()=={'enabled':False}


@pytest.mark.parametrize('enabled', [True, False])
def test_native_deep_link_never_answers_a_group(env, monkeypatch, enabled):
    import asyncio
    client, code = env
    data = begin(client, code)
    if not enabled:
        monkeypatch.delenv('NATIVE_STAFF_ENABLED')
    # The fixture makes _tg_send fail, so even the disabled-path error is caught.
    assert asyncio.run(N.handle_bot_start('native_' + data['challenge'], -123, 111, None)) is True
    with N._db() as conn:
        assert conn.execute('SELECT approved_by FROM native_staff_challenges').fetchone()[0] is None
        assert conn.execute('SELECT COUNT(*) FROM native_staff_sessions').fetchone()[0] == 0


@pytest.mark.parametrize('enabled', [True, False])
def test_native_deep_link_never_answers_a_group(env, monkeypatch, enabled):
    import asyncio
    client, code = env
    data = begin(client, code)
    if not enabled:
        monkeypatch.delenv('NATIVE_STAFF_ENABLED')
    # The fixture makes _tg_send fail, so even the disabled-path error is caught.
    assert asyncio.run(N.handle_bot_start('native_' + data['challenge'], -123, 111, None)) is True
    with N._db() as conn:
        assert conn.execute('SELECT approved_by FROM native_staff_challenges').fetchone()[0] is None
        assert conn.execute('SELECT COUNT(*) FROM native_staff_sessions').fetchone()[0] == 0
