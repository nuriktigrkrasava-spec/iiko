"""Уведомления управляющим: утренний дайджест и триггеры.

До этой правки рассылка группировалась по restaurants.telegram_id, то есть
уходила только владельцу. Проверяем, что управляющий получает свои филиалы,
владелец — по-прежнему все свои, и что филиал считается один раз на всех.
"""
import asyncio
import os
import sys

import pytest

os.environ.setdefault("ENCRYPTION_KEY", "test-key-for-notifications")

OWNER = 1
ALBINA = 777          # управляющая двух филиалов
KANAT = 888           # управляющий одного

ORG_A = "org-buhar"
ORG_B = "org-bokey"
ORG_C = "org-expo"

RESTS = [
    {"organization_id": ORG_A, "organization_name": "Бухар Жырау 36", "telegram_id": OWNER},
    {"organization_id": ORG_B, "organization_name": "Бокейхана 25а", "telegram_id": OWNER},
    {"organization_id": ORG_C, "organization_name": "EXPO", "telegram_id": OWNER},
]


@pytest.fixture()
def api(monkeypatch):
    sys.path.insert(0, os.path.dirname(__file__))
    import api as api_module
    import database
    monkeypatch.setattr(api_module, "get_all_restaurants", lambda: RESTS)
    monkeypatch.setattr(database, "get_all_restaurants", lambda: RESTS, raising=False)
    return api_module


def _managers(monkeypatch, rows):
    import database
    monkeypatch.setattr(database, "get_branch_managers", lambda org_id=None: rows)


def orgs_for(recipients, tg_id):
    return {r["organization_id"] for r in recipients.get(tg_id, [])}


def test_manager_of_two_branches_gets_both(api, monkeypatch):
    _managers(monkeypatch, [
        {"organization_id": ORG_A, "telegram_id": ALBINA, "name": "albina"},
        {"organization_id": ORG_B, "telegram_id": ALBINA, "name": "albina"},
    ])
    rec = api._report_recipients(RESTS)
    assert orgs_for(rec, ALBINA) == {ORG_A, ORG_B}


def test_manager_does_not_get_other_branches(api, monkeypatch):
    _managers(monkeypatch, [
        {"organization_id": ORG_A, "telegram_id": ALBINA, "name": "albina"},
        {"organization_id": ORG_C, "telegram_id": KANAT, "name": "kanat"},
    ])
    rec = api._report_recipients(RESTS)
    assert orgs_for(rec, ALBINA) == {ORG_A}
    assert orgs_for(rec, KANAT) == {ORG_C}


def test_owner_still_gets_everything(api, monkeypatch):
    _managers(monkeypatch, [
        {"organization_id": ORG_A, "telegram_id": ALBINA, "name": "albina"},
    ])
    rec = api._report_recipients(RESTS)
    assert orgs_for(rec, OWNER) == {ORG_A, ORG_B, ORG_C}


def test_no_managers_changes_nothing(api, monkeypatch):
    _managers(monkeypatch, [])
    rec = api._report_recipients(RESTS)
    assert list(rec) == [OWNER]
    assert orgs_for(rec, OWNER) == {ORG_A, ORG_B, ORG_C}


def test_owner_as_own_manager_gets_no_duplicate(api, monkeypatch):
    """Владелец, назначенный управляющим сам себе, не должен получить филиал дважды."""
    _managers(monkeypatch, [
        {"organization_id": ORG_A, "telegram_id": OWNER, "name": "owner"},
    ])
    rec = api._report_recipients(RESTS)
    assert len(rec[OWNER]) == 3


def test_manager_of_unknown_branch_ignored(api, monkeypatch):
    """Отвязанный филиал в branch_managers не должен ломать рассылку."""
    _managers(monkeypatch, [
        {"organization_id": "org-удалён", "telegram_id": ALBINA, "name": "albina"},
    ])
    rec = api._report_recipients(RESTS)
    assert ALBINA not in rec


# ── филиал считается один раз на всех получателей ───────────────────────────

def _run_morning(api, monkeypatch, calls=None):
    """Гоняет утреннюю рассылку на фейковых цифрах. Возвращает [(chat_id, text)]."""
    async def fake_branch(r, yd):
        if calls is not None:
            calls.append(r["organization_id"])
        return {"name": r["organization_name"], "org": r["organization_id"],
                "rev": 100.0, "prev_day": 90.0, "prev_week": 80.0,
                "mtd": 1000.0, "forecast": 2000.0, "typical": 95.0,
                "stops": [], "lows": []}

    sends = []

    class FakeResp:
        def json(self):
            return {"ok": True}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, **kw):
            sends.append((json["chat_id"], json["text"]))
            return FakeResp()

    monkeypatch.setattr(api, "_branch_morning", fake_branch)
    monkeypatch.setattr(api, "BOT_TOKEN", "test-token")
    monkeypatch.setattr(api.httpx, "AsyncClient", lambda *a, **kw: FakeClient())

    assert asyncio.run(api._send_morning_report()) is True
    return sends


def test_branch_computed_once_for_owner_and_manager(api, monkeypatch):
    """Точка с владельцем и управляющим не должна дёргать OLAP дважды."""
    _managers(monkeypatch, [
        {"organization_id": ORG_A, "telegram_id": ALBINA, "name": "albina"},
        {"organization_id": ORG_B, "telegram_id": ALBINA, "name": "albina"},
    ])
    calls = []
    sends = _run_morning(api, monkeypatch, calls)
    assert sorted(calls) == sorted([ORG_A, ORG_B, ORG_C])   # ровно по одному разу
    assert sorted(c for c, _ in sends) == sorted([OWNER, ALBINA])  # оба получили письмо


def test_invoice_hint_only_for_managers(api, monkeypatch):
    """Про накладные напоминаем управляющему; владельцу эта строка не нужна."""
    _managers(monkeypatch, [
        {"organization_id": ORG_A, "telegram_id": ALBINA, "name": "albina"},
    ])
    sends = _run_morning(api, monkeypatch)
    by_id = dict(sends)
    assert "Накладные можно пробивать прямо здесь" in by_id[ALBINA]
    assert "Накладные можно пробивать прямо здесь" not in by_id[OWNER]


def test_morning_hour_is_11_local(api):
    """Владелец просил 11:00 по Казахстану; local_now — UTC+5."""
    assert api.MORNING_HOUR_LOCAL == 11
    assert api.local_now().utcoffset().total_seconds() == 5 * 3600
