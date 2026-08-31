"""Журнал явок: свёртка XML-явок iiko в строки приход/уход по дню.
Задвоенные роли (пересекающиеся интервалы) не должны удваивать часы, а явка без
dateTo (смена ещё идёт) обязана попадать в журнал — иначе весь день «явок нет»."""
import database; database.init_db()
import api


def test_single_attendance_becomes_one_row():
    att = [{"employeeId": "e1", "dateFrom": "2026-07-20T10:00:00",
            "dateTo": "2026-07-20T18:00:00", "departmentName": "Демо"}]
    rows = api._attendance_journal(att, {"e1": "Виктория Ким"}, "Демо")
    assert rows == [{"employee_id": "e1", "name": "Виктория Ким",
                     "date": "2026-07-20", "start": "10:00", "end": "18:00",
                     "hours": 8.0, "open": False}]


def test_doubled_roles_do_not_double_hours():
    att = [
        {"employeeId": "e1", "dateFrom": "2026-07-20T10:00:00",
         "dateTo": "2026-07-20T18:00:00", "departmentName": "Демо"},
        {"employeeId": "e1", "dateFrom": "2026-07-20T12:00:00",
         "dateTo": "2026-07-20T16:00:00", "departmentName": "Демо"},
    ]
    rows = api._attendance_journal(att, {"e1": "Ким"}, "Демо")
    assert len(rows) == 1
    assert rows[0]["hours"] == 8.0
    assert rows[0]["start"] == "10:00" and rows[0]["end"] == "18:00"


def test_filters_by_department():
    att = [
        {"employeeId": "e1", "dateFrom": "2026-07-20T10:00:00",
         "dateTo": "2026-07-20T18:00:00", "departmentName": "Демо"},
        {"employeeId": "e2", "dateFrom": "2026-07-20T09:00:00",
         "dateTo": "2026-07-20T17:00:00", "departmentName": "Другой филиал"},
    ]
    rows = api._attendance_journal(att, {"e1": "Ким", "e2": "Иванов"}, "Демо")
    assert [r["employee_id"] for r in rows] == ["e1"]


def test_open_attendance_counts_as_on_shift():
    """Смена ещё идёт: dateTo нет. Раньше строка выпадала и экран весь день
    показывал «за этот день явок нет»."""
    today = api.local_now().date().isoformat()
    att = [{"employeeId": "e1", "dateFrom": f"{today}T11:10:00", "dateTo": None,
            "departmentName": "Демо"}]
    rows = api._attendance_journal(att, {"e1": "Ким"}, "Демо", today, today)
    assert len(rows) == 1
    assert rows[0]["start"] == "11:10" and rows[0]["open"] is True


def test_stale_open_attendance_from_other_day_dropped():
    """Незакрытые явки iiko отдаёт на любой период — двухлетний «висяк» не должен
    показываться как «человек на смене»."""
    today = api.local_now().date().isoformat()
    att = [{"employeeId": "e9", "dateFrom": "2024-06-26T15:46:00", "dateTo": None,
            "departmentName": "Демо"},
           {"employeeId": "e1", "dateFrom": f"{today}T11:10:00", "dateTo": None,
            "departmentName": "Демо"}]
    rows = api._attendance_journal(att, {}, "Демо", today, today)
    assert [r["employee_id"] for r in rows] == ["e1"]


def test_open_interval_extends_closed_one():
    """Задвоенные роли: одна закрыта, вторая ещё идёт — человек всё ещё на смене."""
    today = api.local_now().date().isoformat()
    att = [{"employeeId": "e1", "dateFrom": f"{today}T11:00:00",
            "dateTo": f"{today}T12:00:00", "departmentName": "Демо"},
           {"employeeId": "e1", "dateFrom": f"{today}T11:10:00", "dateTo": None,
            "departmentName": "Демо"}]
    rows = api._attendance_journal(att, {}, "Демо", today, today)
    assert len(rows) == 1 and rows[0]["open"] is True


def test_range_filter_drops_neighbour_day():
    """iiko на запрос одного дня отдаёт и смену, начавшуюся накануне вечером."""
    att = [{"employeeId": "e1", "dateFrom": "2026-07-19T22:00:00",
            "dateTo": "2026-07-20T02:00:00", "departmentName": "Демо"},
           {"employeeId": "e2", "dateFrom": "2026-07-20T10:00:00",
            "dateTo": "2026-07-20T18:00:00", "departmentName": "Демо"}]
    rows = api._attendance_journal(att, {}, "Демо", "2026-07-20", "2026-07-20")
    assert [r["employee_id"] for r in rows] == ["e2"]


def test_open_shift_survives_a_longer_closed_record():
    """Флаг «на смене» брался у интервала, который кончается позже. Утром, когда
    открытая явка ещё короче закрытой, сотрудник числился ушедшим со смены.
    Незакрытая явка означает «на смене» независимо от соседей."""
    today = api.local_now().date().isoformat()
    att = [{"employeeId": "e1", "dateFrom": f"{today}T11:00:00",
            "dateTo": f"{today}T23:00:00", "departmentName": "Демо"},
           {"employeeId": "e1", "dateFrom": f"{today}T11:10:00", "dateTo": None,
            "departmentName": "Демо"}]
    rows = api._attendance_journal(att, {}, "Демо", today, today)
    assert len(rows) == 1 and rows[0]["open"] is True, rows


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print(f"  [OK] {name}")
            except AssertionError as e:
                failed += 1; print(f"  [FAIL] {name}: {e}")
            except Exception as e:
                failed += 1; print(f"  [ERROR] {name}: {type(e).__name__}: {e}")
    print(f"\n{'ВСЕ ТЕСТЫ ОК' if not failed else f'ПРОВАЛЕНО: {failed}'}")
