import importlib.util
import sqlite3
from pathlib import Path
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from cryptography.fernet import Fernet

spec=importlib.util.spec_from_file_location('push_routes',Path(__file__).with_name('push_routes.py'))
push=importlib.util.module_from_spec(spec);spec.loader.exec_module(push)

@pytest.fixture
def env(tmp_path, monkeypatch):
    path=tmp_path/'test.db'
    def db():
        c=sqlite3.connect(path);c.row_factory=sqlite3.Row;return c
    allowed={'a':('org-a',11),'b':('org-b',22)}
    def scope(token):
        if token not in allowed:return {'valid':False}
        return {'valid':True,'role':'manager','branches':[{'organization_id':allowed[token][0]}]}
    monkeypatch.setattr(push,'db',db);monkeypatch.setattr(push,'scope',scope)
    monkeypatch.setattr(push,'owner',lambda org: {'org-a':11,'org-b':22}.get(org,0))
    monkeypatch.setattr(push,'configured',lambda:True)
    monkeypatch.setenv('ENCRYPTION_KEY',Fernet.generate_key().decode())
    sent=[]
    monkeypatch.setattr(push,'fcm_send',lambda token,binding:sent.append((token,binding)) or 'sent')
    app=FastAPI();app.include_router(push.router)
    return TestClient(app),db,allowed,sent

def payload(letter='a'):
    return {'installation':letter*43,'secret':'s'*43,'binding':letter.upper()*43,'token':letter*60,'platform':'android'}

def register(client,letter='a'):
    return client.post('/api/push/devices',headers={'X-Site-Token':letter},json=payload(letter))

def test_no_auth_and_untrusted_branch_rejected(env):
    client,_,_,_=env
    assert client.post('/api/push/devices',json=payload()).status_code==401
    assert client.post('/api/push/devices',headers={'X-Site-Token':'forged'},json=payload()).status_code==403

def test_encrypted_storage_and_idempotent_registration(env):
    client,db,_,_=env
    assert register(client).status_code==200
    assert register(client).status_code==200
    with db() as conn:
        rows=conn.execute('SELECT * FROM native_push_devices').fetchall()
    assert len(rows)==1
    assert rows[0]['access_cipher']!='a'
    assert rows[0]['token_cipher']!=payload()['token']
    assert rows[0]['secret_hash']!=payload()['secret']

def test_cannot_overwrite_or_revoke_another_installation(env):
    client,db,_,_=env;register(client)
    attempt={**payload(),'secret':'z'*43}
    assert client.post('/api/push/devices',headers={'X-Site-Token':'b'},json=attempt).status_code==403
    assert client.post('/api/push/devices/revoke',json={'installation':attempt['installation'],'secret':attempt['secret']}).status_code==200
    with db() as conn: assert conn.execute('SELECT COUNT(*) FROM native_push_devices').fetchone()[0]==1

def test_only_current_owner_and_branch_receive_signal(env):
    client,_,_,sent=env;register(client,'a');register(client,'b')
    push.send_notice(11,['org-a','org-b'])
    assert sent==[('a'*60,'A'*43)]
    sent.clear();push.send_notice(11,['org-b']);assert sent==[]

def test_revoked_account_does_not_receive(env):
    client,db,allowed,sent=env;register(client);allowed.pop('a')
    push.send_notice(11,['org-a']);assert sent==[]
    with db() as conn:assert conn.execute('SELECT COUNT(*) FROM native_push_devices').fetchone()[0]==0

def test_valid_revoke_and_expired_lease(env):
    client,db,_,sent=env;register(client)
    assert client.post('/api/push/devices/revoke',json={'installation':'a'*43,'secret':'s'*43}).json()=={'ok':True}
    push.send_notice(11,['org-a']);assert sent==[]
    register(client)
    with db() as conn:conn.execute('UPDATE native_push_devices SET expires=0');conn.commit()
    push.send_notice(11,['org-a']);assert sent==[]

def test_known_device_token_cannot_be_stolen_by_new_installation(env):
    client,_,_,_=env;register(client)
    attempt={**payload('b'),'token':payload()['token']}
    assert client.post('/api/push/devices',headers={'X-Site-Token':'b'},json=attempt).status_code==409

def test_disabled_delivery_rejects_registration(env,monkeypatch):
    client,_,_,_=env;monkeypatch.setattr(push,'configured',lambda:False)
    assert client.get('/api/push/status',headers={'X-Site-Token':'a'}).json()=={'enabled':False}
    assert register(client).status_code==503
