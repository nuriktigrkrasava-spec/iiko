"""Self-contained review tests: temporary SQLite, signed synthetic identity, no network.

The API/database adapters expose the existing join contracts; production api.py
is never imported (its startup jobs and credentials stay out of these tests).
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import time
import types
from urllib.parse import parse_qsl, urlencode

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

BOT = '123456:synthetic-join-test-token'


def signed(tid=111, age=0):
    values = {'auth_date': str(int(time.time()) - age),
              'user': json.dumps({'id': tid, 'first_name': 'Test'}, separators=(',', ':'))}
    key = hmac.new(b'WebAppData', BOT.encode(), hashlib.sha256).digest()
    values['hash'] = hmac.new(key, '\n'.join(f'{k}={v}' for k, v in sorted(values.items())).encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


@pytest.fixture
def env(tmp_path, monkeypatch):
    db_file = tmp_path / 'isolated-join.sqlite'
    def get_db():
        conn = sqlite3.connect(db_file, check_same_thread=False, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn
    with get_db() as conn:
        conn.executescript('''
        CREATE TABLE branch_join (organization_id TEXT PRIMARY KEY, code TEXT UNIQUE, created_at TEXT);
        CREATE TABLE staff_access (organization_id TEXT, employee_id TEXT, code TEXT UNIQUE,
          name TEXT, telegram_id INTEGER, created_at TEXT, bound_at TEXT, active INTEGER DEFAULT 1,
          PRIMARY KEY (organization_id, employee_id));
        INSERT INTO branch_join VALUES ('mine','join_mine','now'),('other','join_other','now');
        ''')
    database = types.ModuleType('database')
    database.get_db = get_db
    database.branch_name = lambda org: {'mine': 'Мой филиал', 'other': 'Другой филиал'}[org]
    monkeypatch.setitem(sys.modules, 'database', database)
    api = types.ModuleType('api')
    api.BOT_TOKEN, api.BOT_USERNAME = BOT, 'ExampleJoinBot'
    def validate(data):
        values = dict(parse_qsl(data, keep_blank_values=True))
        signature = values.pop('hash', '')
        key = hmac.new(b'WebAppData', BOT.encode(), hashlib.sha256).digest()
        expected = hmac.new(key, '\n'.join(f'{k}={v}' for k, v in sorted(values.items())).encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise HTTPException(403, 'Invalid Telegram init data')
        return json.loads(values.get('user', '{}'))
    async def join_org(token):
        with get_db() as conn:
            row = conn.execute('SELECT organization_id FROM branch_join WHERE code=?', (token,)).fetchone()
        if not row:
            raise HTTPException(404, 'Invalid invitation')
        return row[0]
    async def no_network(*args, **kwargs):
        raise AssertionError('External messages are forbidden in unit tests')
    api.validate_telegram_init_data = validate
    api._join_tid = lambda data: int(validate(data).get('id') or 0)
    api._join_org, api._tg_send = join_org, no_network
    monkeypatch.setitem(sys.modules, 'api', api)
    for name in ['native_staff_auth', 'native_join_auth']:
        spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + '.py'))
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
    N, J = sys.modules['native_staff_auth'], sys.modules['native_join_auth']
    async def names(org):
        return ([{'id': 'e1', 'name': 'Алия', 'shifts': 3}, {'id': 'e2', 'name': 'Бек', 'shifts': 1}]
                if org == 'mine' else [{'id': 'other1', 'name': 'Другой', 'shifts': 1}])
    monkeypatch.setattr(J, '_employee_names', names)
    monkeypatch.setenv('NATIVE_STAFF_ENABLED', '1')
    monkeypatch.setenv('NATIVE_JOIN_ENABLED', '1')
    monkeypatch.setenv('NATIVE_APP_ORIGIN', 'https://example.test')
    app = FastAPI()
    app.include_router(N.router)
    app.include_router(J.router)
    return types.SimpleNamespace(client=TestClient(app), db=get_db, N=N, J=J, api=api)


def begin(env, token='join_mine'):
    response = env.client.post('/api/native-join/begin', json={'join_token': token})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['secret'] not in data['telegram_url'] and token not in data['telegram_url']
    assert response.headers['cache-control'] == 'no-store'
    return data


def device(data):
    return {k: data[k] for k in ['challenge', 'secret']}


def confirm(env, data, tid=111, proof=None):
    return env.client.post('/api/native-join/confirm',
        json={k: data[k] for k in ['challenge', 'display_code']},
        headers={'X-Telegram-Init-Data': proof or signed(tid)})


def status(env, data):
    return env.client.post('/api/native-join/status', json=device(data))


def claim(env, data, employee='e1', **extra):
    return env.client.post('/api/native-join/claim', json={**device(data), 'employee_id': employee, **extra})


def test_no_employees_or_session_before_signed_confirmation(env):
    d = begin(env)
    assert status(env, d).json() == {'status': 'pending'}
    assert claim(env, d).status_code == 401
    with pytest.raises(HTTPException): env.N.authenticate(d['secret'])
    with env.db() as conn:
        row = dict(conn.execute('SELECT * FROM native_join_challenges').fetchone())
    assert d['secret'] not in json.dumps(row) and 'join_mine' not in json.dumps(row)


def test_unverified_device_never_reads_the_employee_catalog(env, monkeypatch):
    async def forbidden_catalog(org):
        raise AssertionError('Employee catalog read before identity verification')
    monkeypatch.setattr(env.J, '_employee_names', forbidden_catalog)
    data = begin(env)
    assert set(data) == {'challenge', 'secret', 'display_code', 'expires_in', 'telegram_url'}
    assert status(env, data).json() == {'status': 'pending'}
    assert claim(env, data).status_code == 401
    page = env.client.get('/native-join/' + data['challenge'])
    assert page.status_code == 200
    assert 'Алия' not in page.text and 'Бек' not in page.text
    assert data['secret'] not in page.text


def test_confirm_choose_claim_issues_only_matching_employee_session(env):
    d = begin(env)
    assert confirm(env, d).status_code == 200
    available = status(env, d).json()
    assert available['status'] == 'choose' and available['branch'] == 'Мой филиал'
    assert [e['id'] for e in available['employees']] == ['e1', 'e2']
    assert claim(env, d, name='Forged name', telegram_id=222).json()['status'] == 'approved'
    identity = env.N.authenticate(d['secret'])
    assert identity == {'org': 'mine', 'employee_id': 'e1', 'name': 'Алия', 'telegram_id': 111}
    assert status(env, d).json()['status'] == 'approved'
    assert claim(env, d, 'e2').status_code == 409


@pytest.mark.parametrize('proof', [signed(age=301), signed(age=-60), 'auth_date=1&user={"id":111}&hash=forged', signed(tid=0)])
def test_stale_future_forged_or_empty_identity_cannot_approve(env, proof):
    d = begin(env)
    assert confirm(env, d, proof=proof).status_code in (401, 403)
    assert status(env, d).json()['status'] == 'pending'


def test_wrong_code_and_second_person_cannot_approve_challenge(env):
    d = begin(env)
    bad = {**d, 'display_code': '000000' if d['display_code'] != '000000' else '111111'}
    assert confirm(env, bad).status_code == 403
    assert confirm(env, d, 111).status_code == 200
    assert confirm(env, d, 222).status_code == 403
    assert claim(env, d).status_code == 200
    assert env.N.authenticate(d['secret'])['telegram_id'] == 111


@pytest.mark.parametrize('step', ['before_confirm', 'before_claim'])
def test_qr_rotation_invalidates_unfinished_requests(env, step):
    d = begin(env)
    if step == 'before_claim': assert confirm(env, d).status_code == 200
    with env.db() as conn: conn.execute("UPDATE branch_join SET code='replacement' WHERE organization_id='mine'")
    assert confirm(env, d).status_code == 410
    assert status(env, d).status_code == 410
    assert claim(env, d).status_code == 410
    assert env.client.post('/api/native-join/begin', json={'join_token': 'join_mine'}).status_code == 404


def test_wrong_device_secret_does_not_list_or_claim(env):
    d = begin(env); assert confirm(env, d).status_code == 200
    bad = {**d, 'secret': 'x' * 43}
    assert status(env, bad).status_code == 401
    assert claim(env, bad).status_code == 401
    assert claim(env, d, 'other1').status_code == 400


def test_revoked_and_already_bound_employees_are_unavailable(env):
    with env.db() as conn:
        conn.execute("INSERT INTO staff_access VALUES ('mine','e1','code-one','Алия',222,'now','now',1)")
        conn.execute("INSERT INTO staff_access VALUES ('mine','e2','code-two','Бек',NULL,'now',NULL,0)")
    d = begin(env); assert confirm(env, d).status_code == 200
    assert status(env, d).json()['employees'] == []
    assert claim(env, d, 'e1').status_code == 409
    assert claim(env, d, 'e2').status_code == 409


def test_existing_binding_resumes_without_reissuing_code(env):
    with env.db() as conn:
        conn.execute("INSERT INTO staff_access VALUES ('mine','e1','existing-code','Алия',111,'now','now',1)")
    d = begin(env); assert confirm(env, d).status_code == 200
    assert status(env, d).json()['status'] == 'approved'
    assert env.N.authenticate(d['secret'])['employee_id'] == 'e1'
    with env.db() as conn: assert conn.execute('SELECT code FROM staff_access').fetchone()[0] == 'existing-code'


def test_unbound_personal_link_is_preserved_during_join(env):
    with env.db() as conn:
        conn.execute("INSERT INTO staff_access VALUES ('mine','e1','existing-code','Old name',NULL,'now',NULL,1)")
    d = begin(env); assert confirm(env, d).status_code == 200
    assert claim(env, d).status_code == 200
    with env.db() as conn: assert conn.execute('SELECT code FROM staff_access').fetchone()[0] == 'existing-code'


def test_racing_people_cannot_replace_each_other(env):
    a, b = begin(env), begin(env)
    assert confirm(env, a, 111).status_code == 200
    assert confirm(env, b, 222).status_code == 200
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda d: claim(env, d), [a, b]))
    assert sorted(r.status_code for r in responses) == [200, 409]
    with env.db() as conn:
        rows = conn.execute('SELECT * FROM staff_access').fetchall()
    assert len(rows) == 1 and rows[0]['telegram_id'] in (111, 222)
    losing = b if responses[0].status_code == 200 else a
    with pytest.raises(HTTPException): env.N.authenticate(losing['secret'])


def test_one_person_cannot_claim_two_names_in_parallel(env):
    a, b = begin(env), begin(env)
    assert confirm(env, a).status_code == 200 and confirm(env, b).status_code == 200
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda args: claim(env, *args), [(a, 'e1'), (b, 'e2')]))
    assert all(r.status_code == 200 for r in responses)
    with env.db() as conn: assert conn.execute('SELECT COUNT(*) FROM staff_access WHERE telegram_id=111').fetchone()[0] == 1
    assert env.N.authenticate(a['secret'])['employee_id'] == env.N.authenticate(b['secret'])['employee_id']


def test_cancel_and_logout_cannot_be_undone_by_replay(env):
    d = begin(env); assert confirm(env, d).status_code == 200
    assert claim(env, d).status_code == 200
    assert env.client.post('/api/native-staff/logout', headers={'X-Native-Session': d['secret']}).status_code == 200
    assert claim(env, d).status_code == 401
    assert status(env, d).status_code == 401
    e = begin(env); assert confirm(env, e).status_code == 200
    assert env.client.post('/api/native-join/cancel', json=device(e)).json()['ok']
    assert confirm(env, e).status_code == 410


def test_revoke_or_reissue_stops_join_session_and_replay(env):
    d = begin(env); assert confirm(env, d).status_code == 200; assert claim(env, d).status_code == 200
    with env.db() as conn: conn.execute("UPDATE staff_access SET code='replacement-code' WHERE employee_id='e1'")
    with pytest.raises(HTTPException): env.N.authenticate(d['secret'])
    assert status(env, d).status_code == 401
    assert claim(env, d).status_code == 401


def test_invitation_rotation_does_not_revoke_already_established_staff_session(env):
    d = begin(env); assert confirm(env, d).status_code == 200; assert claim(env, d).status_code == 200
    with env.db() as conn: conn.execute("UPDATE branch_join SET code='replacement' WHERE organization_id='mine'")
    assert env.N.authenticate(d['secret'])['employee_id'] == 'e1'


def test_confirmation_page_contains_no_device_secret_or_invitation(env):
    d = begin(env)
    page = env.client.get('/native-join/' + d['challenge'])
    assert page.status_code == 200
    assert d['secret'] not in page.text and 'join_mine' not in page.text
    assert d['display_code'] in page.text
    assert page.headers['cache-control'] == 'no-store'
    assert 'content-security-policy' in page.headers


def test_expiration_and_disabled_config_are_explicit(env, monkeypatch):
    d = begin(env)
    with env.db() as conn: conn.execute('UPDATE native_join_challenges SET expires_at=0')
    assert status(env, d).status_code == 410
    assert confirm(env, d).status_code == 410
    monkeypatch.delenv('NATIVE_JOIN_ENABLED')
    assert env.client.get('/api/native-join/config').json() == {'enabled': False}
    assert env.client.post('/api/native-join/begin', json={'join_token': 'join_mine'}).status_code == 503


def test_bot_start_in_group_does_not_message_or_authenticate(env):
    d = begin(env)
    assert asyncio.run(env.J.handle_bot_start('nativejoin_' + d['challenge'], -123, 111, None)) is True
    assert status(env, d).json() == {'status': 'pending'}


def test_disabled_bot_start_in_group_does_not_message_or_authenticate(env, monkeypatch):
    d = begin(env)
    for flag in ['NATIVE_JOIN_ENABLED', 'NATIVE_STAFF_ENABLED']:
        with monkeypatch.context() as disabled:
            disabled.setenv(flag, '0')
            assert asyncio.run(env.J.handle_bot_start('nativejoin_' + d['challenge'], -123, 111, None)) is True
    assert status(env, d).json() == {'status': 'pending'}
