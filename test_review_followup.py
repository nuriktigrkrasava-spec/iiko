"""Regression coverage for the second security review; no external calls."""
import asyncio
import base64
import io
import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient
from PIL import Image
import api
import database
import iiko
import checklist_ai as photos
import mountain_routes as mountain
import widget_routes as widget
from scripts.check_deployment import inspect_configuration


@pytest.fixture
def cached_victim(monkeypatch):
    monkeypatch.setattr(iiko, '_client_cache', {})
    monkeypatch.setattr(api, 'DEMO_ONLY', False)
    monkeypatch.setattr(api, 'get_client', iiko.get_client)
    async def organizations(self):
        if self.password != 'victim-test-password':
            raise ValueError('Wrong credentials')
        return [{'id': 'victim-org', 'name': 'Victim'}]
    monkeypatch.setattr(iiko.IikoWebClient, 'get_organizations', organizations)
    victim = iiko.get_client('shared-login', 'https://tenant.iiko.it', 'victim-test-password')
    assert asyncio.run(victim.get_organizations())
    writes = Mock()
    for name in ('create_user', 'add_restaurant', 'set_demo_mode'):
        monkeypatch.setattr(api, name, writes)
    monkeypatch.setattr(database, 'web_signup', writes)
    async def user():
        return {'id': 321}
    api.app.dependency_overrides[api.get_current_user] = user
    api.limiter.reset()
    yield TestClient(api.app), writes, victim
    api.app.dependency_overrides.clear()
    api.limiter.reset()


@pytest.mark.parametrize('password', [None, '', 'wrong-test-password'])
@pytest.mark.parametrize('endpoint', ['save', 'validate', 'signup'])
def test_missing_or_wrong_password_cannot_borrow_cached_owner(cached_victim, password, endpoint):
    client, writes, _ = cached_victim
    body = {'api_login': 'shared-login', 'iiko_server': 'https://tenant.iiko.it',
            'organization_id': 'victim-org', 'organization_name': 'Victim',
            'tg_username': 'attacker_test'}
    if password is not None:
        body['api_password'] = password
    path = '/api/signup' if endpoint == 'signup' else '/api/setup/' + endpoint
    response = client.post(path, json=body)
    if endpoint == 'validate':
        assert response.status_code == 200
        assert response.json()['valid'] is False
        assert 'organizations' not in response.json()
    else:
        assert response.status_code == 400
    writes.assert_not_called()


def test_password_reuse_and_returning_owner_are_correct(cached_victim):
    _, _, original = cached_victim
    assert iiko.get_client('shared-login', 'tenant.iiko.it/resto', 'victim-test-password') is original
    fallback = iiko.get_client('shared-login', 'tenant.iiko.it')
    assert fallback is not original and fallback.password == 'shared-login'
    assert iiko.get_client('shared-login', 'tenant.iiko.it', '') is fallback
    restored = iiko.get_client('shared-login', 'tenant.iiko.it', 'victim-test-password')
    assert restored is not fallback
    assert asyncio.run(restored.get_organizations())[0]['id'] == 'victim-org'


def test_verified_password_can_still_save(cached_victim):
    client, writes, _ = cached_victim
    response = client.post('/api/setup/save', json={
        'api_login': 'shared-login', 'iiko_server': 'https://tenant.iiko.it',
        'api_password': 'victim-test-password', 'organization_id': 'victim-org',
        'organization_name': 'User supplied name'})
    assert response.status_code == 200 and response.json()['success']
    assert writes.called


def test_proxy_chain_uses_first_untrusted_address(monkeypatch):
    from rate_limits import _client_ip
    from starlette.requests import Request
    monkeypatch.setenv('TRUSTED_PROXY_CIDRS', '10.0.0.7/32,10.0.0.8/32')
    def request(xff, peer='10.0.0.7'):
        return Request({'type': 'http', 'client': (peer, 1234),
                        'headers': [(b'x-forwarded-for', xff.encode())]})
    assert _client_ip(request('1.2.3.4, 203.0.113.5, 10.0.0.8')) == '203.0.113.5'
    assert _client_ip(request('1.2.3.4, 198.51.100.9, 10.0.0.8')) == '198.51.100.9'
    assert _client_ip(request('1.2.3.4', '198.51.100.9')) == '198.51.100.9'
    assert _client_ip(request('invalid')) == '10.0.0.7'


def test_database_comparisons_are_available_to_each_owner(monkeypatch, tmp_path):
    monkeypatch.setenv('DB_PATH', str(tmp_path/'snapshots.db'))
    monkeypatch.setenv('ASSISTANT_SNAPSHOT_OWNER_ID', '999')
    monkeypatch.setattr(api, 'get_restaurants', lambda uid: [
        {'organization_id': f'branch-{uid}', 'organization_name': 'Same name'}])
    monkeypatch.setattr(api, 'ASSISTANT_FOODCOST', False)
    monkeypatch.setattr(api, '_get_org_id', lambda org, user: org)
    for name in ('dashboard', '_week_over_week', '_weekplan_status', 'cancels',
                 'branch_reviews', 'late_deliveries', 'load_heatmap',
                 'get_stoplist', 'writeoffs'):
        monkeypatch.setattr(api, name, AsyncMock(return_value={}))
    database.save_signal_snapshot(101, 'Same name', {'revenue': 101})
    database.save_signal_snapshot(202, 'Same name', {'revenue': 202})
    for uid in (101, 202):
        result = asyncio.run(api._gather_assistant_signals({'id': uid}))
        assert result['branches'][0]['prev']['revenue'] == uid


def test_widget_revocation_is_per_owner_and_does_not_change_mobile_login(monkeypatch):
    monkeypatch.setenv('WIDGET_SECRET', 'test-widget-secret')
    monkeypatch.setenv('WIDGET_OWNER_VERSIONS', '{}')
    owner = widget.widget_token_for(101)
    branch = widget.widget_branch_token_for(101, 'branch-a')
    other = widget.widget_token_for(202)
    mobile = mountain.token_for(101)
    monkeypatch.setenv('WIDGET_OWNER_VERSIONS', '{"101":1}')
    assert widget._uid_from_token(owner) is None  # also protects journal routes
    assert widget._widget_scope(owner, 'branch-a') is None
    assert widget._widget_scope(branch) is None
    assert widget._uid_from_token(other) == 202
    assert mountain.uid_from_token(mobile) == 101
    new = widget.widget_branch_token_for(101, 'branch-a')
    assert widget._widget_scope(new) == (101, 'branch-a')
    assert widget._widget_scope(new, 'branch-b') is None
    assert widget._uid_from_token(widget.widget_token_for(101)) == 101


@pytest.mark.parametrize('value', ['not json', '[]', '{"101":true}', '{"101":-1}', '{"x":1}'])
def test_bad_widget_revocation_setting_never_falls_back(monkeypatch, value):
    monkeypatch.setenv('WIDGET_OWNER_VERSIONS', value)
    with pytest.raises(RuntimeError):
        widget.widget_token_for(101)


def test_prepared_photo_is_not_encoded_twice(monkeypatch):
    buf = io.BytesIO()
    Image.new('RGB', (32, 32), 'red').save(buf, 'PNG')
    prepared, mime = photos.shrink(buf.getvalue())
    messages = SimpleNamespace(create=AsyncMock(return_value=SimpleNamespace(
        content=[SimpleNamespace(text='{"ok":true,"criteria":[]}')])))
    monkeypatch.setattr(photos, '_client', SimpleNamespace(messages=messages))
    shrink = Mock(wraps=photos.shrink)
    monkeypatch.setattr(photos, 'shrink', shrink)
    assert asyncio.run(photos.review_slot([(prepared, 'hall')]))['checked']
    shrink.assert_not_called()
    sent = messages.create.call_args.kwargs['messages'][0]['content'][1]['source']
    assert base64.b64decode(sent['data']) == prepared and sent['media_type'] == mime
    with pytest.raises(ValueError):
        asyncio.run(photos.review_slot([(b'not a photo', 'hall')]))
    assert shrink.call_count == 1


def test_preflight_does_not_create_empty_database(monkeypatch, tmp_path):
    path = tmp_path/'missing.db'
    monkeypatch.setenv('DB_PATH', str(path))
    errors, _ = inspect_configuration()
    assert any('database is missing' in e for e in errors)
    assert not path.exists()


def test_preflight_flags_proxy_and_stored_insecure_server(monkeypatch, tmp_path):
    path = tmp_path/'existing.db'
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE restaurants(iiko_server TEXT)')
        conn.execute('INSERT INTO restaurants VALUES (?)', ('http://tenant.iiko.it/resto',))
    before = path.read_bytes()
    monkeypatch.setenv('DB_PATH', str(path))
    monkeypatch.setenv('RENDER', 'true')
    monkeypatch.delenv('TRUSTED_PROXY_CIDRS', raising=False)
    errors, _ = inspect_configuration()
    assert any('TRUSTED_PROXY_CIDRS' in e for e in errors)
    assert any('Stored iiko server' in e for e in errors)
    assert path.read_bytes() == before
