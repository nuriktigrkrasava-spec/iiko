"""Тесты 24ч-триала демо-бота.
Запуск: python3 test_demo_trial.py
"""
import os, tempfile, asyncio, time
os.environ.setdefault("DB_PATH", tempfile.mktemp(suffix="_trial_test.db"))
os.environ["DEMO_ONLY"] = "1"  # триал живёт только на демо-боте

import database; database.init_db()
import api
from fastapi import HTTPException


def test_trial_insert_and_get():
    database.start_demo_trial(111, "org-A", 1_000_000)
    row = database.get_demo_trial(111)
    assert row and row["org_id"] == "org-A" and row["started_ts"] == 1_000_000, row
    print("  [OK] start_demo_trial + get_demo_trial")


def test_trial_not_reset_on_second_connect():
    database.start_demo_trial(222, "org-X", 5_000)
    database.start_demo_trial(222, "org-Y", 9_999)  # повтор не должен перезаписать
    row = database.get_demo_trial(222)
    assert row["org_id"] == "org-X" and row["started_ts"] == 5_000, row
    print("  [OK] повторное подключение не перезапускает триал")


def test_get_trial_none():
    assert database.get_demo_trial(999999) is None
    print("  [OK] нет триала → None")


def test_use_demo_data_active_trial():
    tid = 333
    database.start_demo_trial(tid, "org-real", int(time.time()))  # только что
    user = {"id": tid}
    # активный триал + реальный org → НЕ демо
    assert api._use_demo_data(user, "org-real") is False
    # но demo-org-1 всегда демо
    assert api._use_demo_data(user, "demo-org-1") is True
    print("  [OK] активный триал → реальные данные, demo-org-1 всё равно демо")


def test_use_demo_data_ended_trial():
    tid = 444
    database.start_demo_trial(tid, "org-real", int(time.time()) - 26 * 3600)  # сутки прошли
    assert api._use_demo_data({"id": tid}, "org-real") is True  # ended → демо
    st = api._demo_trial_state(tid)
    assert st["state"] == "ended", st
    print("  [OK] истёкший триал → демо-сэмпл, state=ended")


def test_use_demo_data_no_trial():
    assert api._use_demo_data({"id": 555}, "whatever") is True  # демо-юзер без триала
    assert api._demo_trial_state(555)["state"] == "none"
    print("  [OK] нет триала → демо")


if __name__ == "__main__":
    tests = [test_trial_insert_and_get, test_trial_not_reset_on_second_connect, test_get_trial_none,
             test_use_demo_data_active_trial, test_use_demo_data_ended_trial, test_use_demo_data_no_trial]
    failed = 0
    for t in tests:
        print(f"\n>>> {t.__name__}")
        try:
            t()
        except AssertionError as e:
            failed += 1; print(f"  [FAIL] {e}")
        except Exception as e:
            failed += 1; print(f"  [ERROR] {type(e).__name__}: {e}")
    try:
        os.remove(os.environ["DB_PATH"])
    except OSError:
        pass
    print(f"\n{'='*50}\n{'ВСЕ ТЕСТЫ ОК' if not failed else f'ПРОВАЛЕНО: {failed}'}")
