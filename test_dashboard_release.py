import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from fastapi import Response
import api

@pytest.fixture
def dashboard(monkeypatch):
    monkeypatch.setattr(api,'_use_demo_data',lambda *a:False)
    monkeypatch.setattr(api,'_parse_org_ids',lambda *a:['a','b'])
    monkeypatch.setattr(api,'_get_cached',lambda *a,**kw:None)
    monkeypatch.setattr(api,'_set_cached',lambda *a,**kw:None)
    monkeypatch.setattr(api,'local_now',lambda:datetime(2026,9,3,12))
    monkeypatch.setattr(api,'get_period_dates',lambda *a:('2026-09-03','2026-09-03'))
    monkeypatch.setattr(api,'_get_restaurant_info',lambda org,user:{'api_login':org})
    monkeypatch.setattr(api,'_olap_dept',lambda org,info:org)
    clients={k:SimpleNamespace(olap_report=AsyncMock(return_value={'data':[{'OpenDate.Typed':'2026-09-03','DishDiscountSumInt':0,'DishAmountSum':100,'GuestNum':1,'OrdersCount':1}]}),get_cashshifts=True) for k in ['a','b']}
    monkeypatch.setattr(api,'get_client',lambda login,*a:clients[login])
    return clients

def run():
    return asyncio.run(api.dashboard('a',Response(),period='today',from_=None,to=None,org_ids=None,user={'id':123}))

def test_forecast_uses_closed_days_excluding_today(dashboard,monkeypatch):
    sessions=[{'openDate':'2026-09-01','payOrders':100},{'openDate':'2026-09-02','payOrders':200},{'openDate':'2026-09-03','payOrders':9999}]
    monkeypatch.setattr(api,'branch_shift_sessions',AsyncMock(return_value=(sessions,{})))
    result=run()
    assert result['forecast']==9000 # 2 branches * 300 / 2 completed days * 30
    assert result['forecast_method']=='monthly_closed_days'
    assert result['revenue_today']==19998

def test_partial_cash_uses_same_net_olap_for_card_and_chart(dashboard,monkeypatch):
    async def shifts(client,org,*a):
        if org=='b':raise RuntimeError('unavailable')
        return ([{'openDate':'2026-09-03','payOrders':999}],{})
    monkeypatch.setattr(api,'branch_shift_sessions',shifts)
    result=run()
    assert result['revenue_today']==0 # Fully discounted is zero, not gross 200
    assert sum(result['chart_7days']['data'])==0
    assert result['forecast'] is None

def test_failed_branch_does_not_become_plausible_zero(dashboard,monkeypatch):
    dashboard['b'].olap_report.side_effect=RuntimeError('unavailable')
    monkeypatch.setattr(api,'branch_shift_sessions',AsyncMock(return_value=([],{})))
    result=run()
    assert '_iiko_error' in result
