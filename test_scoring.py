"""Оценка филиала: критерии логичны, задачи на неё не влияют.

Запуск:  python3 test_scoring.py
"""
import scoring as S

GOOD = {
    "name": "Хороший", "revenue": 10_000_000,
    "changes": {"revenue_pct": 8},
    "foodcost": {"fact_pct": 29, "norm_pct": 30, "coverage": 85},
    "writeoffs": {"total": 100000, "pct": 3},
    "late": {"late_pct": 2},
}
BAD = {
    "name": "Плохой", "revenue": 10_000_000,
    "changes": {"revenue_pct": -12},
    "foodcost": {"fact_pct": 41, "norm_pct": 30, "coverage": 90},
    "writeoffs": {"total": 900000, "pct": 16},
    "late": {"late_pct": 20},
}
CH_OK = {"done": 24, "missed": 0}
CH_BAD = {"done": 6, "missed": -18}


def test_good_beats_bad():
    good = S.score_branch(GOOD, CH_OK)["score"]
    bad = S.score_branch(BAD, CH_BAD)["score"]
    assert good >= 90 and bad <= 15, (good, bad)
    print(f"  [OK] порядок в филиале {good} из 100, разруха {bad} из 100")


def test_tasks_do_not_affect_score():
    """Задачи в формулу не входят вовсе — закрыть их и «поднять оценку» нельзя."""
    a = S.score_branch(GOOD, CH_OK)["score"]
    b = S.score_branch({**GOOD}, CH_OK)["score"]
    assert a == b
    keys = {c["key"] for c in S.score_branch(GOOD, CH_OK)["criteria"]}
    assert "tasks" not in keys and keys == {"revenue", "foodcost", "writeoffs", "late", "checklist"}, keys
    print("  [OK] критериев пять, задач среди них нет")


def test_missing_data_is_not_a_penalty():
    """Нет отзывов и техкарт — не штраф: вес уходит на остальные критерии."""
    thin = {"name": "Без данных", "revenue": 5_000_000, "writeoffs": {"pct": 3},
            "changes": {"revenue_pct": 10}}      # рост на максимум шкалы
    r = S.score_branch(thin, CH_OK)
    counted = [c for c in r["criteria"] if c["counted"]]
    # три критерия из пяти, все на максимуме → 100: пустота не наказывается
    assert r["score"] == 100, r
    assert {c["key"] for c in counted} == {"revenue", "writeoffs", "checklist"}, counted
    print(f"  [OK] считано {len(counted)} критерия из 5, оценка {r['score']} — без наказания за пустоту")


def test_no_data_at_all_gives_none():
    r = S.score_branch({}, {})
    assert r["score"] is None and all(c["value"] is None for c in r["criteria"]), r
    print("  [OK] совсем без данных оценки нет — прочерк, а не ноль")


def test_criteria_have_weights_and_sum_to_100():
    assert sum(S.WEIGHTS.values()) == 100, S.WEIGHTS
    print(f"  [OK] веса критериев: {S.WEIGHTS}, сумма 100")


def test_foodcost_ignored_when_recipes_are_thin():
    """Покрытие техкарт ниже 60% — фудкост в оценку не идёт: цифра врёт."""
    thin = {**GOOD, "foodcost": {"fact_pct": 95, "norm_pct": 30, "coverage": 12}}
    crit = {c["key"]: c for c in S.score_branch(thin, CH_OK)["criteria"]}
    assert crit["foodcost"]["counted"] is False, crit["foodcost"]
    assert S.score_branch(thin, CH_OK)["score"] >= 85
    print("  [OK] фудкост с покрытием 12% не портит оценку")


def test_zone_criteria_are_short_and_specific():
    for zone, d in S.ZONE_CRITERIA.items():
        assert d["label"] and 3 <= len(d["items"]) <= 6, (zone, d)
        assert all(len(i) < 60 for i in d["items"]), zone
    print("  [OK] критерии зон: " + ", ".join(
        f'{d["label"]} — {len(d["items"])}' for d in S.ZONE_CRITERIA.values()))


def test_growth_and_lateness_are_directional():
    """Рост выручки поднимает, опоздания опускают — и наоборот."""
    up = S.score_branch({**GOOD, "changes": {"revenue_pct": 12}}, CH_OK)["score"]
    down = S.score_branch({**GOOD, "changes": {"revenue_pct": -12}}, CH_OK)["score"]
    fast = S.score_branch({**GOOD, "late": {"late_pct": 0}}, CH_OK)["score"]
    slow = S.score_branch({**GOOD, "late": {"late_pct": 18}}, CH_OK)["score"]
    assert up > down and fast > slow, (up, down, fast, slow)
    print(f"  [OK] выручка +12% → {up}, −12% → {down}; опозданий 0% → {fast}, 18% → {slow}")


if __name__ == "__main__":
    failed = 0
    for t in (test_good_beats_bad, test_tasks_do_not_affect_score,
              test_missing_data_is_not_a_penalty, test_no_data_at_all_gives_none,
              test_criteria_have_weights_and_sum_to_100,
              test_foodcost_ignored_when_recipes_are_thin,
              test_zone_criteria_are_short_and_specific,
              test_growth_and_lateness_are_directional):
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
