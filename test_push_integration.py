from unittest.mock import AsyncMock, Mock
from fastapi.testclient import TestClient
import api
import mountain_routes as mountain
import push_routes


def test_persisted_notice_queues_only_authorized_branches(monkeypatch):
    scope = {'valid': True, 'role': 'owner', 'uid': 11,
             'branches': [{'organization_id': 'org-a'}, {'organization_id': 'org-b'}]}
    monkeypatch.setattr(mountain, 'scope_of_token', lambda _: scope)
    persist, deliver = Mock(return_value=42), Mock()
    monkeypatch.setattr(mountain, 'add_branch_notice', persist)
    monkeypatch.setattr(mountain, '_notice_to_telegram', AsyncMock(return_value=0))
    monkeypatch.setattr(push_routes, 'send_notice', deliver)
    client = TestClient(api.app)
    denied = client.post('/api/mountain/notice/test-token', json={'text': 'Hello', 'org': 'foreign'})
    assert denied.status_code == 403
    persist.assert_not_called()
    deliver.assert_not_called()
    result = client.post('/api/mountain/notice/test-token', json={'text': 'Hello', 'org': 'org-a'})
    assert result.status_code == 200
    deliver.assert_called_once_with(11, ['org-a'])


def test_unconfigured_push_status_is_disabled(monkeypatch):
    monkeypatch.setattr(push_routes, 'manager', lambda _: ('org-a', 11))
    monkeypatch.delenv('PUSH_ENABLED', raising=False)
    client = TestClient(api.app)
    response = client.get('/api/push/status', headers={'X-Site-Token': 'test-token'})
    assert response.status_code == 200
    assert response.json() == {'enabled': False}
