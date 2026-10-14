import asyncio
from unittest.mock import AsyncMock
import pytest
import widget_routes as widget
import api

@pytest.fixture
def scoped(monkeypatch):
    monkeypatch.setenv('WIDGET_SECRET','isolated-widget-test-secret')
    monkeypatch.setattr(api,'_get_cached',lambda *a,**k:None)
    monkeypatch.setattr(api,'_set_cached',lambda *a,**k:None)
    gather=AsyncMock(return_value={'connected':False})
    monkeypatch.setattr(widget,'_gather',gather)
    return widget.widget_branch_token_for(123,'mine'),gather

@pytest.mark.parametrize('path_org',[None,'mine'])
def test_branch_widget_cannot_expand_to_network(scoped,path_org):
    token,gather=scoped
    response=asyncio.run(widget._json_payload(token,path_org))
    assert response.status_code==200
    gather.assert_awaited_once_with(123,only_org='mine')
    assert response.headers['cache-control']=='private, no-store'

def test_branch_widget_foreign_org_denied_before_query(scoped):
    token,gather=scoped
    assert asyncio.run(widget._json_payload(token,'foreign')).status_code==404
    gather.assert_not_awaited()

def test_widget_branch_token_cannot_authorize_owner_journals(scoped):
    token,_=scoped
    assert widget._uid_from_token(token) is None

def test_tampered_branch_signature_rejected(scoped):
    token,_=scoped
    bad=token[:-1]+('0' if token[-1]!='0' else '1')
    assert widget._widget_scope(bad) is None

def test_html_link_without_branch_stays_scoped(scoped):
    token,gather=scoped
    assert asyncio.run(widget.widget_page(token)).status_code==200
    gather.assert_awaited_once_with(123,only_org='mine')


def test_restaurant_name_is_inert_text_in_html():
    payload='<img src=x onerror="alert(1)">'
    rendered=widget._render({'connected':True,'label':payload,'revenue':1,'spark':[]})
    assert payload not in rendered
    assert '&lt;img src=x onerror=&quot;alert(1)&quot;&gt;' in rendered


def test_widget_has_no_known_fallback_secret(monkeypatch):
    monkeypatch.delenv('WIDGET_SECRET', raising=False)
    monkeypatch.delenv('ENCRYPTION_KEY', raising=False)
    with pytest.raises(RuntimeError):
        widget.widget_token_for(123)
