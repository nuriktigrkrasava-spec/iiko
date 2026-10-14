import asyncio
from unittest.mock import Mock,AsyncMock
import pytest
import api
from fastapi.testclient import TestClient

@pytest.fixture
def manager(monkeypatch):
    async def identity():return {'id':123,'only_org':'mine'}
    api.app.dependency_overrides[api.get_current_user]=identity
    spies={}
    for name in ['delete_restaurant','delete_all_restaurants','add_restaurant','set_app_state','create_user','set_demo_mode','_get_pending_by_id']:
        spies[name]=Mock(return_value=None);monkeypatch.setattr(api,name,spies[name])
    yield TestClient(api.app,raise_server_exceptions=False),spies
    api.app.dependency_overrides.clear()

@pytest.mark.parametrize('method,path,body',[
 ('DELETE','/api/restaurants/77',None),
 ('GET','/api/assistant',None),
 ('POST','/api/widget/token',{}),
 ('GET','/api/weekly-user-report/preview',None),
 ('GET','/api/admin/branches',None),
 ('GET','/api/chaspik',None),
 ('POST','/api/export-send',{'filename':'x.csv','content':'x'}),
 ('POST','/api/logout',{}),
 ('POST','/api/reviews/brand',{'brand':'foreign'}),
 ('GET','/api/invoice-edit/guessed-id',None),
 ('POST','/api/invoice-edit/guessed-id',{'items':[]}),
 ('POST','/api/setup/save',{'api_login':'l','organization_id':'other','organization_name':'Other'}),
])
def test_manager_cannot_mutate_network_or_open_owner_pending(manager,method,path,body):
    client,spies=manager
    response=client.request(method,path,json=body)
    assert response.status_code==403,(path,response.status_code)
    assert not any(s.called for s in spies.values()),path

def test_foreign_ocr_is_rejected_before_paid_processing(manager,monkeypatch):
    client,_=manager;recognize=AsyncMock(return_value={'items':[]})
    monkeypatch.setattr(api,'analyze_invoice_photos',recognize)
    response=client.post('/api/invoice/recognize/other',json={'images':[{'data':'YQ==','mime':'image/jpeg'}]})
    assert response.status_code==403
    recognize.assert_not_awaited()

def test_production_webhook_missing_secret_fails_closed(monkeypatch):
    monkeypatch.setattr(api,'IS_PROD',True);monkeypatch.setattr(api,'TELEGRAM_WEBHOOK_SECRET',None)
    response=TestClient(api.app,raise_server_exceptions=False).post('/telegram/webhook',json={})
    assert response.status_code==403

def test_prod_missing_bot_does_not_authenticate_dev(monkeypatch):
    monkeypatch.setattr(api,'IS_PROD',True);monkeypatch.setattr(api,'BOT_TOKEN','')
    with pytest.raises(api.HTTPException) as err:asyncio.run(api.get_current_user(None,None))
    assert err.value.status_code==401

def test_setup_cannot_grant_access_to_arbitrary_org(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(api,'DEMO_ONLY',False)
    writes=Mock()
    monkeypatch.setattr(api,'create_user',writes)
    monkeypatch.setattr(api,'add_restaurant',writes)
    monkeypatch.setattr(api,'get_client',lambda *a:SimpleNamespace(get_organizations=AsyncMock(return_value=[{'id':'mine','name':'Mine'}])))
    payload=api.SetupSave(api_login='fake',organization_id='victim',organization_name='Victim')
    with pytest.raises(api.HTTPException) as err:asyncio.run(api.setup_save(payload,{'id':321}))
    assert err.value.status_code==403
    writes.assert_not_called()

def test_setup_uses_verified_name(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(api,'DEMO_ONLY',False)
    write=Mock()
    monkeypatch.setattr(api,'create_user',Mock())
    monkeypatch.setattr(api,'set_demo_mode',Mock())
    monkeypatch.setattr(api,'add_restaurant',write)
    monkeypatch.setattr(api,'get_client',lambda *a:SimpleNamespace(get_organizations=AsyncMock(return_value=[{'id':'mine','name':'Verified'}])))
    payload=api.SetupSave(api_login='real',organization_id='mine',organization_name='Another branch')
    assert asyncio.run(api.setup_save(payload,{'id':321}))['success']
    assert write.call_args.args[3]=='Verified'
