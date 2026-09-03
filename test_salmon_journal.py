"""Журнал разборов: фиксация, период, «занёс в iiko вручную», чужой филиал.

База — временная: тесты не должны трогать рабочий iiko_boss.db.
Запуск:  python3 test_salmon_journal.py
"""
import os
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_salmon.db")

import acts
import database as D

A, B = "org-astana", "org-almaty"
D.init_db()


def _act(org, raw, sl, trim, uid=1):
    calc = acts.split_salmon(9300, raw, sl, trim)
    assert calc["ok"], calc
    return D.add_salmon_act(org, uid, calc, 9300, acts.TRIM_PRICE)


def test_saved_act_comes_back_with_all_weights():
    aid = _act(A, 10, 8, 1.8)
    row = [r for r in D.get_salmon_acts([A]) if r["id"] == aid][0]
    assert row["weight_raw"] == 10 and row["weight_slice"] == 8, row
    assert row["weight_trim"] == 1.8 and abs(row["weight_waste"] - 0.2) < 1e-6, row
    assert row["slice_price"] > 9300, row        # обрезки дешевле — нарезка дороже входа
    assert not row["posted_at"], row
    print(f"  [OK] разбор #{aid} записан: отход {row['weight_waste']} кг, "
          f"нарезка {row['slice_price']} ₸/кг")


def test_period_filters_by_date_and_branch():
    _act(B, 10, 6, 2)
    today = D.datetime.now().date().isoformat()
    mine = D.get_salmon_acts([A], today, today)
    assert mine and all(r["organization_id"] == A for r in mine), mine
    assert D.get_salmon_acts([A], "2000-01-01", "2000-01-02") == []
    print(f"  [OK] за сегодня по своему филиалу {len(mine)} разбор(ов), чужие не попали")


def test_summary_matches_what_admin_types_into_iiko():
    rows = D.get_salmon_acts([A, B])
    s = acts.summarize(rows)
    assert abs(s["raw"] - (s["slice"] + s["trim"] + s["waste"])) < 1e-6, s
    assert s["acts"] == len(rows), s
    print(f"  [OK] свод по двум филиалам: стейк {s['raw']} → нарезка {s['slice']}, "
          f"обрезки {s['trim']}, отход {s['waste']}")


def test_posting_closes_only_the_acts_you_saw():
    open_before = D.get_salmon_acts([A], only_open=True)
    fresh = _act(A, 5, 4, 0.8)            # добавился, пока админ переписывал числа
    n = D.mark_salmon_posted([r["id"] for r in open_before], [A], by=1)
    assert n == len(open_before), (n, open_before)
    still_open = [r["id"] for r in D.get_salmon_acts([A], only_open=True)]
    assert still_open == [fresh], still_open
    print(f"  [OK] закрыто {n}, разбор #{fresh} остался в следующей пачке")


def test_posting_twice_changes_nothing():
    ids = [r["id"] for r in D.get_salmon_acts([A]) if r["posted_at"]]
    assert D.mark_salmon_posted(ids, [A], by=2) == 0, ids
    print("  [OK] повторное «занёс в iiko» ничего не переписывает")


def test_foreign_branch_cannot_close_or_delete():
    other = D.get_salmon_acts([B], only_open=True)
    assert other, other
    assert D.mark_salmon_posted([r["id"] for r in other], [A], by=1) == 0
    assert D.delete_salmon_act(other[0]["id"], [A]) is False
    assert D.delete_salmon_act(other[0]["id"], [B]) is True
    print("  [OK] чужой разбор ни закрыть, ни удалить")


def test_posted_act_cannot_be_deleted():
    posted = [r for r in D.get_salmon_acts([A]) if r["posted_at"]]
    assert posted, posted
    assert D.delete_salmon_act(posted[0]["id"], [A]) is False
    print("  [OK] занесённый в iiko разбор удалить нельзя — свод бы разошёлся")


def test_network_table_lists_every_branch_that_worked():
    _act(B, 12, 7, 2.5)                   # у Алматы разбор грубее — он и будет ниже
    orgs = D.all_salmon_orgs()
    assert set(orgs) >= {A, B}, orgs
    rows = acts.by_branch(D.get_salmon_acts(orgs), {A: "Астана", B: "Алматы"})
    assert {r["name"] for r in rows} == {"Астана", "Алматы"}, rows
    assert rows[0]["waste_pct"] <= rows[-1]["waste_pct"], rows
    print("  [OK] публичная таблица: " + ", ".join(
        f"{r['name']} {r['waste_pct']}% / {r['slice_price']:.0f} ₸" for r in rows))


if __name__ == "__main__":
    failed = 0
    for t in (test_saved_act_comes_back_with_all_weights, test_period_filters_by_date_and_branch,
              test_summary_matches_what_admin_types_into_iiko,
              test_posting_closes_only_the_acts_you_saw, test_posting_twice_changes_nothing,
              test_foreign_branch_cannot_close_or_delete, test_posted_act_cannot_be_deleted,
              test_network_table_lists_every_branch_that_worked):
        print(f"\n>>> {t.__name__}")
        try:
            t()
        except AssertionError as e:
            failed += 1
            print(f"  [FAIL] {e}")
        except Exception as e:
            failed += 1
            print(f"  [ERROR] {type(e).__name__}: {e}")
    print(f"\n{'='*50}\n{'ВСЕ ТЕСТЫ ОК' if not failed else f'ПРОВАЛЕНО: {failed}'}")
    raise SystemExit(1 if failed else 0)
