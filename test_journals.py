"""Журналы: разбор показаний, нормы камер, сборка панели, штрафы.

Проверяем то, что ломается тихо: минус набранный типографским тире, замер
вне нормы, «сдано N из M» до наступления слота и филиал не из Астаны,
который в журналы попадать не должен.
"""
import json
import os
import sys
from datetime import datetime

import pytest

os.environ.setdefault("ENCRYPTION_KEY", "test-key-journals")
sys.path.insert(0, os.path.dirname(__file__))

import journals as J  # noqa: E402

OWNER = 8727082281
MGR = 777

ORG_A = "aaaaaaaa-0000-0000-0000-000000000001"
ORG_B = "bbbbbbbb-0000-0000-0000-000000000002"
ORG_REG = "cccccccc-0000-0000-0000-000000000003"

RESTS = [
    {"organization_id": ORG_A, "organization_name": "Астана, ул. Бухар Жырау 36",
     "telegram_id": OWNER},
    {"organization_id": ORG_B, "organization_name": "Астана, ул. Кажымукана 16",
     "telegram_id": OWNER},
    {"organization_id": ORG_REG, "organization_name": "Актобе, ул. Локомотивная 7",
     "telegram_id": OWNER},
]

AFTERNOON = datetime(2026, 8, 14, 15, 40)


# ── разбор показаний ────────────────────────────────────────────────────────

def test_parses_nine_numbers():
    vals, err = J.parse_temps("-20 4 -19 3 5 4 3 6 -21")
    assert err is None
    assert vals["fish_fr"] == -20 and vals["snack_fr"] == -21


def test_typographic_minus_is_accepted():
    """Телефон подставляет «−» вместо дефиса — это не должно ломать сдачу."""
    vals, err = J.parse_temps("−20 4 −19 3 5 4 3 6 −21")
    assert err is None and vals["fish_fr"] == -20


def test_newlines_and_degree_signs_ok():
    vals, err = J.parse_temps("-20°C\n4\n-19\n3\n5\n4\n3\n6\n-21")
    assert err is None and len(vals) == 9


def test_wrong_count_rejected():
    _, err = J.parse_temps("-20 4 -19")
    assert err and "9" in err


def test_garbage_rejected():
    _, err = J.parse_temps("холодно тепло -19 3 5 4 3 6 -21")
    assert err and "не число" in err


def test_absurd_value_rejected():
    _, err = J.parse_temps("-20 4 -19 3 5 4 3 6 -900")
    assert err and "опечатк" in err


# ── нормы ───────────────────────────────────────────────────────────────────

def test_freezer_norm():
    assert J.temp_status("fish_fr", -20) == "ok"
    assert J.temp_status("fish_fr", -9) == "bad"      # разморозился


def test_fridge_norm():
    assert J.temp_status("veg", 4) == "ok"
    assert J.temp_status("veg", 12) == "bad"
    assert J.temp_status("veg", -5) == "bad"          # подморозил овощи


def test_alarms_list_only_violations():
    vals = {c["key"]: (-20 if c["kind"] == "fr" else 4) for c in J.CAMERAS}
    assert J.temp_alarms(vals) == []
    vals["snack_fr"] = -9
    al = J.temp_alarms(vals)
    assert len(al) == 1 and al[0]["key"] == "snack_fr"


# ── что положено сдать ──────────────────────────────────────────────────────

def test_due_grows_through_the_day():
    morning = J.due_items(datetime(2026, 8, 14, 9, 0))
    noon = J.due_items(AFTERNOON)
    night = J.due_items(datetime(2026, 8, 14, 23, 59))
    assert len(morning) == 0                      # до 10:45 ещё ничего не горит
    assert 0 < len(noon) < len(night)


def test_due_counts_zones_separately():
    """Зал, кухня и санузел — три отдельные сдачи, а не одна «чистота»."""
    at1100 = J.due_items(datetime(2026, 8, 14, 11, 0))
    clean = [d for d in at1100 if d[0] == "clean"]
    assert len(clean) == len(J.ZONE_ORDER)


def test_task_text_carries_criteria():
    t = J.clean_task_text("hall", "10:45")
    assert "коврик" in t.lower() and "разводов" in t


def test_temp_task_lists_all_cameras():
    t = J.temp_task_text("11:00")
    for c in J.CAMERAS:
        assert c["title"] in t


# ── сборка панели ───────────────────────────────────────────────────────────

@pytest.fixture()
def board(monkeypatch, tmp_path):
    import database
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "j.db"))
    database.init_db()
    import api
    import journal_routes
    monkeypatch.setattr(api, "get_restaurants", lambda uid: RESTS)
    monkeypatch.setattr(api, "get_all_restaurants", lambda: RESTS)
    monkeypatch.setattr(api, "local_now", lambda: AFTERNOON)
    monkeypatch.setattr(database, "get_branch_managers",
                        lambda org_id=None: [{"organization_id": ORG_A,
                                              "telegram_id": MGR, "name": "albina"}])
    monkeypatch.setattr(journal_routes, "get_branch_managers",
                        lambda org_id=None: [{"organization_id": ORG_A,
                                              "telegram_id": MGR, "name": "albina"}])
    return journal_routes, database


def test_regions_are_excluded(board):
    jr, _ = board
    b = jr.build_board(OWNER, AFTERNOON)
    names = {x["full"] for x in b["branches"]}
    assert "Актобе, ул. Локомотивная 7" not in names
    assert len(b["branches"]) == 2


def test_branch_without_manager_is_off(board):
    jr, _ = board
    b = jr.build_board(OWNER, AFTERNOON)
    kazh = next(x for x in b["branches"] if "Кажымукана" in x["full"])
    assert kazh["st"] == "off"
    assert any(g["st"] == "off" for g in b["gaps"])


def test_submitted_zone_counts_as_done(board):
    jr, db = board
    day = AFTERNOON.date().isoformat()
    db.save_journal_entry(ORG_A, "clean", "hall", "10:45", day, MGR,
                          json.dumps({"photos": [1, 2, 3]}))
    b = jr.build_board(OWNER, AFTERNOON)
    buh = next(x for x in b["branches"] if "Бухар" in x["full"])
    assert buh["done"] == 1
    assert not any("Зал" in g["what"] and "10:45" in g["what"] for g in b["gaps"])


def test_temperature_out_of_norm_turns_branch_red(board):
    jr, db = board
    day = AFTERNOON.date().isoformat()
    vals = {c["key"]: (-20 if c["kind"] == "fr" else 4) for c in J.CAMERAS}
    vals["snack_fr"] = -9
    db.save_journal_entry(ORG_A, "temp", "", "11:00", day, MGR, json.dumps(vals))
    b = jr.build_board(OWNER, AFTERNOON)
    buh = next(x for x in b["branches"] if "Бухар" in x["full"])
    assert buh["st"] == "bad"
    assert any("−9" in g["what"] or "-9" in g["what"] for g in b["gaps"])


def test_resubmission_replaces_not_duplicates(board):
    jr, db = board
    day = AFTERNOON.date().isoformat()
    db.save_journal_entry(ORG_A, "clean", "hall", "10:45", day, MGR, json.dumps({"photos": [1]}))
    db.save_journal_entry(ORG_A, "clean", "hall", "10:45", day, MGR, json.dumps({"photos": [1, 2]}))
    rows = [e for e in db.get_journal_entries(day)
            if e["organization_id"] == ORG_A and e["kind"] == "clean"]
    assert len(rows) == 1
    assert len(json.loads(rows[0]["payload"])["photos"]) == 2


def test_photo_hash_is_remembered(board):
    _, db = board
    db.remember_photo("abc123", ORG_A, "hall", "2026-08-13", "file1")
    assert db.seen_photo("abc123", ORG_A)["day"] == "2026-08-13"
    assert db.seen_photo("abc123", ORG_B) is None      # хэши не текут между филиалами


def test_short_name_shortens_astana_addresses(board):
    jr, _ = board
    assert jr.short_name("Астана, ул. Бухар Жырау 36") == "Бухар Жырау"
    assert jr.short_name("Астана, ул. Кажымукана 16") == "Кажымукана"


def test_workshop_and_hub_excluded(board):
    """Цех и распредцентр на Алпамыс 61 — не гостевые точки, журналы не ведут."""
    jr, _ = board
    assert not jr.in_journals("Астана, ул. Алпамыс 61 (КЦ)")
    assert not jr.in_journals("Астана, ул. Алпамыс 61 (ЦЕХ)")
    assert jr.in_journals("Астана, ул. Бухар Жырау 36")
    assert not jr.in_journals("Актобе, ул. Локомотивная 7")
