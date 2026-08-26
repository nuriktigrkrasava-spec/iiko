"""Акт разбора лосося: П/Ф стейк из ЦЕХа → обрезки + нарезка. Арифметика до копейки.

Запуск:  python3 test_acts.py
"""
import acts


def test_worked_example():
    """10 кг стейка по 9 300 (цена из накладной ЦЕХа), 2 кг обрезков."""
    r = acts.split_salmon(9300, 10, 2)
    assert r["ok"], r
    assert r["slice"]["weight"] == 8.0, r              # 10 − 2
    assert r["trim"]["sum"] == 17600.0, r              # 2 × 8800
    assert r["slice"]["price_per_kg"] == 9425.0, r     # (93 000 − 17 600) / 8
    print(f"  [OK] нарезка {r['slice']['price_per_kg']} ₸/кг, обрезки {r['trim']['sum']:.0f} ₸")


def test_money_does_not_leak():
    """Обрезки плюс нарезка равны стоимости входа — копейки не теряются."""
    for price, raw, trim in ((9300, 10, 2), (9990, 7.3, 1.85), (12000, 22.4, 6.15)):
        r = acts.split_salmon(price, raw, trim)
        assert r["ok"], r
        assert abs(r["check"] - r["raw"]["sum"]) < 0.01, (price, raw, r)
    print("  [OK] на трёх наборах сумма выходов сошлась со стоимостью входа")


def test_impossible_weights_are_refused():
    bad = acts.split_salmon(9300, 10, 12)              # обрезков больше, чем стейка
    assert not bad["ok"] and "тяжелее" in bad["error"], bad
    zero = acts.split_salmon(9300, 0, 0)
    assert not zero["ok"], zero
    neg = acts.split_salmon(9300, 10, -1)
    assert not neg["ok"], neg
    print("  [OK] нереальные веса не считаются, а объясняются")


def test_trim_more_expensive_than_input_is_refused():
    """Если стейк пришёл дешевле 8 800, обрезки съедают его целиком — это ошибка цены."""
    bad = acts.split_salmon(5000, 10, 8)               # 50 000 входа против 70 400 обрезков
    assert not bad["ok"] and "дороже" in bad["error"], bad
    print("  [OK] обрезки дороже входа → внятная ошибка, а не минус в себестоимости")


def test_no_trim_means_slice_costs_like_input():
    """Обрезков нет — нарезка стоит ровно столько же, сколько стоил стейк."""
    r = acts.split_salmon(9300, 10, 0)
    assert r["slice"]["weight"] == 10 and r["slice"]["price_per_kg"] == 9300.0, r
    print("  [OK] без обрезков себестоимость не меняется")


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
    assert p["raw"]["id"] == "1", p
    assert p["trim"]["id"] == "2" and p["slice"]["id"] == "3", p
    assert p["waste"]["id"] == "6", p
    print("  [OK] вход и два выхода найдены по имени, лишнее не подцепилось")


def test_waste_costs_nothing_and_only_takes_weight():
    """Отход по нулю: он уменьшает вес нарезки, но не её стоимость."""
    без = acts.split_salmon(9300, 10, 2)
    с = acts.split_salmon(9300, 10, 2, 1.5)
    assert с["waste"]["sum"] == 0 and с["waste"]["price_per_kg"] == 0, с
    assert с["slice"]["weight"] == 6.5 and без["slice"]["weight"] == 8.0, (с, без)
    assert с["slice"]["sum"] == без["slice"]["sum"], "деньги нарезки не меняются"
    assert с["slice"]["price_per_kg"] > без["slice"]["price_per_kg"], "цена за кг растёт"
    assert abs(с["check"] - с["raw"]["sum"]) < 0.01, с
    print(f"  [OK] отход 1.5 кг: нарезка {с['slice']['weight']} кг по {с['slice']['price_per_kg']} ₸/кг")


def test_waste_plus_trim_cannot_exceed_input():
    bad = acts.split_salmon(9300, 10, 6, 5)
    assert not bad["ok"] and "тяжелее" in bad["error"], bad
    print("  [OK] обрезки с отходом тяжелее стейка → отказ")


if __name__ == "__main__":
    failed = 0
    for t in (test_worked_example, test_money_does_not_leak, test_impossible_weights_are_refused,
              test_trim_more_expensive_than_input_is_refused, test_no_trim_means_slice_costs_like_input,
              test_products_found_by_name,
              test_waste_costs_nothing_and_only_takes_weight,
              test_waste_plus_trim_cannot_exceed_input):
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
