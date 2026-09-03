"""Акт разбора лосося: П/Ф стейк → нарезка + обрезки + отход. Арифметика до копейки.

Запуск:  python3 test_acts.py
"""
import acts


def test_worked_example():
    """10 кг стейка по 9 300 (цена из накладной ЦЕХа), 8 кг нарезки, 2 кг обрезков."""
    r = acts.split_salmon(9300, 10, 8, 2)
    assert r["ok"], r
    assert r["waste"]["weight"] == 0.0, r              # 10 − 8 − 2
    assert r["trim"]["sum"] == 17600.0, r              # 2 × 8800
    assert r["slice"]["price_per_kg"] == 9425.0, r     # (93 000 − 17 600) / 8
    print(f"  [OK] нарезка {r['slice']['price_per_kg']} ₸/кг, обрезки {r['trim']['sum']:.0f} ₸")


def test_waste_is_what_is_left():
    """Отход не вводят — он остаток веса, и на нём же считается процент."""
    r = acts.split_salmon(9300, 10, 7, 2)
    assert r["ok"], r
    assert r["waste"]["weight"] == 1.0, r              # 10 − 7 − 2
    assert r["waste_pct"] == 10.0, r
    assert r["slice_pct"] == 70.0 and r["trim_pct"] == 20.0, r
    print("  [OK] отход = стейк − нарезка − обрезки, % отхода 10.0")


def test_waste_costs_nothing_and_only_takes_weight():
    """Кости и кожа стоят 0 ₸: деньги входа полностью уходят в нарезку и обрезки."""
    r = acts.split_salmon(9300, 10, 7, 2)
    assert r["waste"]["sum"] == 0.0, r
    assert abs(r["check"] - r["raw"]["sum"]) < 0.01, r
    # нарезки меньше, а денег на ней столько же — значит, кг дороже
    assert r["slice"]["price_per_kg"] > acts.split_salmon(9300, 10, 8, 2)["slice"]["price_per_kg"]
    print("  [OK] отход дорожает нарезку, а не съедает стоимость")


def test_money_does_not_leak():
    """Обрезки плюс нарезка равны стоимости входа — копейки не теряются."""
    for price, raw, sl, trim in ((9300, 10, 8, 2), (9990, 7.3, 5.1, 1.85), (12000, 22.4, 15.2, 6.15)):
        r = acts.split_salmon(price, raw, sl, trim)
        assert r["ok"], r
        assert abs(r["check"] - r["raw"]["sum"]) < 0.01, (price, raw, r)
    print("  [OK] на трёх наборах сумма выходов сошлась со стоимостью входа")


def test_impossible_weights_are_refused():
    bad = acts.split_salmon(9300, 10, 9, 2)            # нарезка с обрезками тяжелее стейка
    assert not bad["ok"] and "тяжелее" in bad["error"], bad
    zero = acts.split_salmon(9300, 0, 0)
    assert not zero["ok"], zero
    neg = acts.split_salmon(9300, 10, -1)
    assert not neg["ok"], neg
    print("  [OK] нереальные веса не считаются, а объясняются")


def test_trim_more_expensive_than_input_is_refused():
    """Если стейк пришёл дешевле 8 800, обрезки съедают его целиком — это ошибка цены."""
    bad = acts.split_salmon(5000, 10, 2, 8)            # 50 000 входа против 70 400 обрезков
    assert not bad["ok"] and "дороже" in bad["error"], bad
    print("  [OK] обрезки дороже входа → внятная ошибка, а не минус в себестоимости")


def test_no_trim_means_slice_costs_like_input():
    """Обрезков и отхода нет — нарезка стоит ровно столько же, сколько стоил стейк."""
    r = acts.split_salmon(9300, 10, 10, 0)
    assert r["slice"]["weight"] == 10 and r["slice"]["price_per_kg"] == 9300.0, r
    assert r["waste_pct"] == 0.0, r
    print("  [OK] без потерь себестоимость не меняется")


def test_products_found_by_name():
    catalog = [
        {"id": "1", "name": "П/Ф ЛОСОСЬ СТЕЙК (ЦЕХ)", "unit": "кг"},
        {"id": "2", "name": "П/Ф ОБРЕЗКИ ЛОСОСЬ", "unit": "кг"},
        {"id": "3", "name": "П/Ф НАРЕЗКА ЛОСОСЬ", "unit": "кг"},
        {"id": "6", "name": "Отход лосося", "unit": "кг"},
        {"id": "4", "name": "П/Ф Лосось терияки", "unit": "кг"},     # не про разбор
        {"id": "5", "name": "лосось туша", "unit": "кг"},            # сырьё ЦЕХа, не наш вход
    ]
    p = acts.find_products(catalog)
    assert p["raw"]["id"] == "1" and p["trim"]["id"] == "2", p
    assert p["slice"]["id"] == "3" and p["waste"]["id"] == "6", p
    print("  [OK] четыре позиции разбора нашлись, лишние не подхватились")


# ── Свод за период ───────────────────────────────────────────────────────────

ROWS = [
    # филиал А: разбор аккуратный, отхода почти нет
    {"organization_id": "A", "weight_raw": 10, "weight_slice": 8, "weight_trim": 1.8,
     "weight_waste": 0.2, "price_per_kg": 9300, "trim_price": 8800},
    {"organization_id": "A", "weight_raw": 20, "weight_slice": 16, "weight_trim": 3.6,
     "weight_waste": 0.4, "price_per_kg": 9300, "trim_price": 8800},
    # филиал Б: тот же вход, но нарезки меньше — отход больше
    {"organization_id": "B", "weight_raw": 10, "weight_slice": 6, "weight_trim": 2,
     "weight_waste": 2, "price_per_kg": 9300, "trim_price": 8800},
]


def test_period_totals_are_sums():
    """Свод — это то, что администратор занесёт одним актом: веса складываются."""
    s = acts.summarize(ROWS)
    assert s["acts"] == 3, s
    assert s["raw"] == 40.0 and s["slice"] == 30.0, s
    assert s["trim"] == 7.4 and s["waste"] == 2.6, s
    assert abs(s["raw"] - (s["slice"] + s["trim"] + s["waste"])) < 1e-6, s
    print(f"  [OK] за период: стейк {s['raw']} → нарезка {s['slice']}, обрезки {s['trim']}, отход {s['waste']}")


def test_period_averages_are_weighted():
    """Большой разбор весит в среднем больше маленького — иначе филиал можно
    «вылечить» одним удачным килограммом."""
    s = acts.summarize(ROWS)
    assert s["waste_pct"] == 6.5, s                    # 2.6 / 40
    # себестоимость нарезки = (вся стоимость входа − обрезки) / вес нарезки
    money = 40 * 9300 - 7.4 * 8800
    assert abs(s["slice_price"] - money / 30) < 0.01, s
    small = acts.summarize([ROWS[0]])
    assert small["waste_pct"] == 2.0, small
    print(f"  [OK] средний отход {s['waste_pct']}%, нарезка {s['slice_price']} ₸/кг — по весу")


def test_branches_are_ranked_by_waste():
    """Публичная таблица: наверху тот, у кого отхода меньше."""
    rows = acts.by_branch(ROWS, {"A": "Астана", "B": "Алматы"})
    assert [r["name"] for r in rows] == ["Астана", "Алматы"], rows
    assert rows[0]["waste_pct"] == 2.0 and rows[1]["waste_pct"] == 20.0, rows
    assert rows[0]["slice_price"] < rows[1]["slice_price"], rows
    print(f"  [OK] {rows[0]['name']} {rows[0]['waste_pct']}% впереди {rows[1]['name']} {rows[1]['waste_pct']}%")


def test_empty_period_does_not_divide_by_zero():
    s = acts.summarize([])
    assert s["acts"] == 0 and s["waste_pct"] == 0.0 and s["slice_price"] == 0.0, s
    assert acts.by_branch([]) == []
    print("  [OK] пустой период — нули, а не падение")


if __name__ == "__main__":
    failed = 0
    for t in (test_worked_example, test_waste_is_what_is_left,
              test_waste_costs_nothing_and_only_takes_weight, test_money_does_not_leak,
              test_impossible_weights_are_refused,
              test_trim_more_expensive_than_input_is_refused,
              test_no_trim_means_slice_costs_like_input, test_products_found_by_name,
              test_period_totals_are_sums, test_period_averages_are_weighted,
              test_branches_are_ranked_by_waste, test_empty_period_does_not_divide_by_zero):
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
