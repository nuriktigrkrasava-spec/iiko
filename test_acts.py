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


# ── Терияки: те же обрезки, обжаренные с соусом ──────────────────────────────

def test_teriyaki_is_taken_out_of_the_trim():
    """Вписали, сколько вышло терияки, — ровно столько ушло из обрезков."""
    r = acts.split_salmon(9300, 10, 8, 2, w_teriyaki=1.5)
    assert r["ok"], r
    assert r["trim"]["weight"] == 0.5, r               # 2 − 1.5 осталось обрезками
    assert r["teriyaki"]["weight"] == 1.5, r
    assert r["teriyaki"]["price_per_kg"] == 8800.0, r  # цена обрезочная: это они и есть
    assert r["teriyaki"]["sum"] == 13200.0, r          # 1.5 × 8800
    print(f"  [OK] из 2 кг обрезков 1.5 ушло в терияки, обрезков осталось {r['trim']['weight']}")


def test_teriyaki_moves_money_but_does_not_create_it():
    """Терияки стоит как обрезки, поэтому деньги переезжают из строки в строку:
    ни нарезка, ни отход, ни сумма акта не двигаются."""
    plain = acts.split_salmon(9300, 10, 7, 2)
    with_ter = acts.split_salmon(9300, 10, 7, 2, w_teriyaki=1.2)
    assert with_ter["slice"] == plain["slice"], (plain["slice"], with_ter["slice"])
    assert with_ter["waste"] == plain["waste"], (plain["waste"], with_ter["waste"])
    assert abs(with_ter["check"] - with_ter["raw"]["sum"]) < 0.01, with_ter
    assert with_ter["trim"]["sum"] + with_ter["teriyaki"]["sum"] == plain["trim"]["sum"], with_ter
    print("  [OK] нарезка, отход и сумма акта не изменились — деньги только переехали")


def test_teriyaki_does_not_touch_the_waste_percent():
    """Отход считается от стейка, а терияки берут из обрезков: процент отхода —
    оценка того, как разобрали рыбу, и жарка не должна его улучшать."""
    r = acts.split_salmon(9300, 10, 7, 2, w_teriyaki=2)
    assert r["waste"]["weight"] == 1.0 and r["waste_pct"] == 10.0, r
    assert r["trim_pct"] == 0.0 and r["teriyaki_pct"] == 20.0, r
    print("  [OK] все обрезки ушли в терияки, отход остался прежним")


def test_teriyaki_cannot_exceed_the_trim():
    """Больше, чем было обрезков, нажарить нельзя — это описка в весах."""
    bad = acts.split_salmon(9300, 10, 8, 2, w_teriyaki=2.5)
    assert not bad["ok"] and "обрезк" in bad["error"], bad
    neg = acts.split_salmon(9300, 10, 8, 2, w_teriyaki=-1)
    assert not neg["ok"], neg
    print("  [OK] терияки больше обрезков — внятная ошибка")


def test_products_found_by_name():
    catalog = [
        {"id": "1", "name": "П/Ф ЛОСОСЬ СТЕЙК (ЦЕХ)", "unit": "кг"},
        {"id": "2", "name": "П/Ф ОБРЕЗКИ ЛОСОСЬ", "unit": "кг"},
        {"id": "3", "name": "П/Ф НАРЕЗКА ЛОСОСЬ", "unit": "кг"},
        {"id": "6", "name": "Отход лосося", "unit": "кг"},
        {"id": "4", "name": "П/Ф Лосось терияки", "unit": "кг"},
        {"id": "5", "name": "лосось туша", "unit": "кг"},            # сырьё ЦЕХа, не наш вход
    ]
    p = acts.find_products(catalog)
    assert p["raw"]["id"] == "1" and p["trim"]["id"] == "2", p
    assert p["slice"]["id"] == "3" and p["waste"]["id"] == "6", p
    assert p["teriyaki"]["id"] == "4", p
    print("  [OK] пять позиций разбора нашлись, туша ЦЕХа не подхватилась")


# ── Ужарка: терияки дороже обрезков ровно на то, что ушло со сковороды ───────

def test_frying_loss_is_paid_by_the_teriyaki():
    """2 кг обрезков положили жарить, сняли 1.4 — деньги обрезков никуда не
    делись, значит килограмм терияки стоит дороже килограмма обрезков."""
    r = acts.split_salmon(9300, 10, 8, 2, w_fry=2, w_teriyaki=1.4)
    assert r["ok"], r
    assert r["teriyaki"]["from_trim"] == 2.0 and r["teriyaki"]["weight"] == 1.4, r
    assert r["teriyaki"]["shrink"] == 0.6, r
    assert r["teriyaki"]["sum"] == 17600.0, r              # 2 × 8800, как и было
    assert r["teriyaki"]["price_per_kg"] == 12571.43, r    # 17 600 / 1.4
    assert r["teriyaki_yield_pct"] == 70.0, r
    print(f"  [OK] ужарка {r['teriyaki']['shrink']} кг, терияки {r['teriyaki']['price_per_kg']} ₸/кг")


def test_frying_loss_does_not_change_the_slice_or_the_act():
    """Ужарка происходит ПОСЛЕ разбора: ни нарезка, ни отход, ни сумма акта от
    неё не двигаются — иначе жаркой можно было бы улучшить разбор рыбы."""
    plain = acts.split_salmon(9300, 10, 7, 2)
    fried = acts.split_salmon(9300, 10, 7, 2, w_fry=2, w_teriyaki=1.1)
    assert fried["slice"] == plain["slice"], (plain["slice"], fried["slice"])
    assert fried["waste"] == plain["waste"], (plain["waste"], fried["waste"])
    assert abs(fried["check"] - fried["raw"]["sum"]) < 0.01, fried
    assert fried["trim"]["sum"] + fried["teriyaki"]["sum"] == plain["trim"]["sum"], fried
    print("  [OK] сумма акта сошлась со входом, нарезка и отход на месте")


def test_frying_more_than_there_was_is_refused():
    """В жарку нельзя положить больше, чем вышло обрезков."""
    bad = acts.split_salmon(9300, 10, 8, 2, w_fry=2.5, w_teriyaki=2)
    assert not bad["ok"] and "обрезк" in bad["error"], bad
    print("  [OK] в жарку больше обрезков — внятная ошибка")


def test_teriyaki_heavier_than_the_pan_is_refused():
    """При жарке вес уходит. Терияки тяжелее того, что положили, — описка."""
    bad = acts.split_salmon(9300, 10, 8, 2, w_fry=1.5, w_teriyaki=1.8)
    assert not bad["ok"] and "жарк" in bad["error"], bad
    empty = acts.split_salmon(9300, 10, 8, 2, w_fry=1.5)     # положили и не взвесили
    assert not empty["ok"] and "сковород" in empty["error"], empty
    print("  [OK] привес после жарки и незаполненный выход не считаются")


# ── Соус терияки: граммы свои, деньги со стороны ────────────────────────────

def test_sauce_makes_the_teriyaki_more_expensive():
    """200 г соуса по 4 000 ₸/кг — это 800 ₸ сверху, и они ложатся на терияки."""
    dry = acts.split_salmon(9300, 10, 8, 2, w_fry=2, w_teriyaki=1.4)
    r = acts.split_salmon(9300, 10, 8, 2, w_fry=2, w_teriyaki=1.4,
                          g_sauce=200, sauce_price=4000)
    assert r["ok"], r
    assert r["sauce"]["grams"] == 200.0 and r["sauce"]["sum"] == 800.0, r
    assert r["teriyaki"]["sum"] == dry["teriyaki"]["sum"] + 800.0, r
    assert r["teriyaki"]["price_per_kg"] == round(18400 / 1.4, 2), r
    print(f"  [OK] соус 800 ₸ → терияки {r['teriyaki']['price_per_kg']} ₸/кг вместо "
          f"{dry['teriyaki']['price_per_kg']}")


def test_sauce_does_not_touch_the_fish_money():
    """Соус пришёл своей накладной. Нарезка, отход и сходимость акта — по рыбе,
    иначе акт на 93 000 ₸ входа перестал бы сходиться."""
    dry = acts.split_salmon(9300, 10, 7, 2, w_fry=2, w_teriyaki=1.2)
    wet = acts.split_salmon(9300, 10, 7, 2, w_fry=2, w_teriyaki=1.2,
                            g_sauce=350, sauce_price=5200)
    assert wet["slice"] == dry["slice"], (dry["slice"], wet["slice"])
    assert wet["waste"] == dry["waste"] and wet["waste_pct"] == dry["waste_pct"], wet
    assert wet["check"] == dry["check"], (dry["check"], wet["check"])
    assert abs(wet["check"] - wet["raw"]["sum"]) < 0.01, wet
    print("  [OK] соус дорожает только терияки: акт сошёлся со входом")


def test_sauce_per_kilo_is_the_number_that_catches_the_overpour():
    """Граммы соуса сами по себе ни о чём: сравнивают «сколько на килограмм»."""
    r = acts.split_salmon(9300, 10, 8, 2, w_fry=2, w_teriyaki=1.5,
                          g_sauce=300, sauce_price=4000)
    assert r["sauce_g_per_kg"] == 200.0, r              # 300 г на 1.5 кг
    print(f"  [OK] {r['sauce_g_per_kg']} г соуса на килограмм терияки")


def test_sauce_without_teriyaki_is_refused():
    """Соус льют на сковороду. Граммы без выхода — промах полем, а не разбор."""
    bad = acts.split_salmon(9300, 10, 8, 2, g_sauce=200, sauce_price=4000)
    assert not bad["ok"] and "соус" in bad["error"].lower(), bad
    print("  [OK] соус без терияки не считается, а объясняется")


def test_eel_has_no_sauce():
    """У угря жарки нет — соус в его разбор не заедет даже полем."""
    r = acts.split_act(14000, 10, 7.5, 1.5, trim_price=12000, kind="eel",
                       g_sauce=500, sauce_price=4000)
    assert r["ok"] and r["sauce"]["grams"] == 0.0 and r["sauce"]["sum"] == 0.0, r
    print("  [OK] угорь считается без соуса")


def test_sauce_found_in_the_catalog_and_not_confused_with_the_fish():
    """«Соус Терияки» и «П/Ф Лосось терияки» — разные товары. Спутать их значит
    списать бутылку соуса вместо килограмма рыбы."""
    catalog = [
        {"id": "1", "name": "П/Ф ЛОСОСЬ СТЕЙК", "unit": "кг"},
        {"id": "2", "name": "П/Ф ОБРЕЗКИ ЛОСОСЬ", "unit": "кг"},
        {"id": "3", "name": "П/Ф НАРЕЗКА ЛОСОСЬ", "unit": "кг"},
        {"id": "6", "name": "Отход лосося", "unit": "кг"},
        {"id": "7", "name": "Соус Терияки", "unit": "кг"},      # раньше П/Ф
        {"id": "4", "name": "П/Ф Лосось терияки", "unit": "кг"},
    ]
    p = acts.find_products(catalog)
    assert p["teriyaki"]["id"] == "4", p
    assert p["sauce"]["id"] == "7", p
    print("  [OK] соус нашёлся отдельно от П/Ф терияки")


def test_period_counts_the_sauce_with_its_own_price():
    """В своде соус — свои граммы и свои деньги: цену берём ту, что была в
    разборе, иначе занесённый в iiko свод поехал бы от новой накладной."""
    rows = [{"organization_id": "A", "weight_raw": 10, "weight_slice": 8,
             "weight_trim": 0.0, "weight_fry": 1.8, "weight_teriyaki": 1.2,
             "weight_waste": 0.2, "price_per_kg": 9300, "trim_price": 8800,
             "weight_sauce": 240, "sauce_price": 4000}]
    s = acts.summarize(rows)
    assert s["sauce"] == 240.0 and s["sauce_sum"] == 960.0, s
    assert s["sauce_g_per_kg"] == 200.0, s
    assert s["teriyaki_sum"] == 15840.0 + 960.0, s          # 1.8 × 8800 + соус
    assert s["teriyaki_price"] == round(16800 / 1.2, 2), s
    dry = acts.summarize([{**rows[0], "weight_sauce": 0, "sauce_price": 0}])
    assert s["slice_price"] == dry["slice_price"], (s, dry)
    print(f"  [OK] за период {s['sauce']} г соуса на {s['sauce_sum']} ₸, "
          f"нарезка не сдвинулась")


def test_period_counts_the_frying_loss():
    """В своде терияки — своим весом, а деньгами он остаётся обрезками, что
    ушли в жарку: себестоимость нарезки от ужарки не двигается."""
    rows = [{"organization_id": "A", "weight_raw": 10, "weight_slice": 8,
             "weight_trim": 0.0, "weight_fry": 1.8, "weight_teriyaki": 1.2,
             "weight_waste": 0.2, "price_per_kg": 9300, "trim_price": 8800}]
    s = acts.summarize(rows)
    assert s["teriyaki"] == 1.2 and s["fry"] == 1.8 and s["shrink"] == 0.6, s
    assert s["teriyaki_sum"] == 15840.0, s                  # 1.8 × 8800
    assert s["teriyaki_price"] == 13200.0, s                # 15 840 / 1.2
    assert s["teriyaki_yield_pct"] == 66.7, s
    same = acts.summarize([{**rows[0], "weight_trim": 1.8, "weight_fry": 0,
                            "weight_teriyaki": 0}])
    assert abs(s["slice_price"] - same["slice_price"]) < 0.01, (s, same)
    print(f"  [OK] за период ужарилось {s['shrink']} кг, выход жарки {s['teriyaki_yield_pct']}%")


# ── Угорь: тот же разбор, другая рыба ────────────────────────────────────────

def test_eel_splits_like_salmon():
    """Целый угорь → нарезка + обрезки + отход. Цена обрезков у угря своя, и
    пока она не назначена — приходит полем в акт."""
    r = acts.split_act(14000, 10, 7.5, 1.5, trim_price=12000, kind="eel")
    assert r["ok"] and r["kind"] == "eel", r
    assert r["waste"]["weight"] == 1.0 and r["waste_pct"] == 10.0, r
    assert r["trim"]["sum"] == 18000.0, r                   # 1.5 × 12 000
    assert r["slice"]["price_per_kg"] == round((140000 - 18000) / 7.5, 2), r
    assert abs(r["check"] - r["raw"]["sum"]) < 0.01, r
    print(f"  [OK] угорь: нарезка {r['slice']['price_per_kg']} ₸/кг, отход {r['waste_pct']}%")


def test_eel_has_no_teriyaki():
    """Терияки жарят из лососёвых обрезков. Угрю его передали по ошибке — акт
    не должен молча посчитать несуществующий передел."""
    r = acts.split_act(14000, 10, 7.5, 1.5, trim_price=12000, w_fry=1, w_teriyaki=0.7, kind="eel")
    assert r["ok"], r
    assert r["teriyaki"]["weight"] == 0 and r["trim"]["weight"] == 1.5, r
    print("  [OK] у угря жарка не считается, обрезки остались обрезками")


def test_eel_error_speaks_about_the_eel():
    bad = acts.split_act(14000, 0, 0, kind="eel")
    assert not bad["ok"] and "угря" in bad["error"], bad
    print(f"  [OK] «{bad['error']}»")


def test_eel_products_found_by_name_or_by_words():
    """Имя из справочника Алиева, а если филиал назвал по-своему — по словам."""
    p = acts.find_products([
        {"id": "1", "name": "Угорь целый", "unit": "кг"},
        {"id": "2", "name": "П/Ф ОБРЕЗКИ УГОРЬ", "unit": "кг"},
        {"id": "3", "name": "П/Ф НАРЕЗКА УГОРЬ", "unit": "кг"},
        {"id": "4", "name": "Отход угря", "unit": "кг"},
        {"id": "5", "name": "П/Ф ЛОСОСЬ СТЕЙК", "unit": "кг"},     # чужая рыба
    ], kind="eel")
    assert p["raw"]["id"] == "1" and p["trim"]["id"] == "2", p
    assert p["slice"]["id"] == "3" and p["waste"]["id"] == "4", p
    assert "teriyaki" not in p, p
    other = acts.find_products([
        {"id": "9", "name": "Угорь унаги 1 кг", "unit": "кг"},      # вход без «целый»
        {"id": "8", "name": "Угорь нарезка", "unit": "кг"},
    ], kind="eel")
    assert other["raw"]["id"] == "9" and other["slice"]["id"] == "8", other
    print("  [OK] позиции угря нашлись и по имени, и по словам")


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

# те же разборы, но часть обрезков ушла в терияки (в базе обрезки хранятся уже
# остатком, терияки — отдельным весом)
ROWS_TER = [
    {"organization_id": "A", "weight_raw": 10, "weight_slice": 8, "weight_trim": 0.8,
     "weight_teriyaki": 1.0, "weight_waste": 0.2, "price_per_kg": 9300, "trim_price": 8800},
]


def test_period_counts_teriyaki_as_part_of_the_trim():
    """В своде терияки виден отдельной цифрой, но деньгами он остаётся обрезками:
    себестоимость нарезки такая же, как если бы его не жарили."""
    s = acts.summarize(ROWS_TER)
    assert s["teriyaki"] == 1.0 and s["trim"] == 0.8, s
    assert s["teriyaki_sum"] == 8800.0, s
    same = acts.summarize([{**ROWS_TER[0], "weight_trim": 1.8, "weight_teriyaki": 0}])
    assert abs(s["slice_price"] - same["slice_price"]) < 0.01, (s, same)
    print(f"  [OK] терияки {s['teriyaki']} кг в своде, нарезка {s['slice_price']} ₸/кг не поехала")


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
    import sys
    here = sys.modules[__name__]
    tests = [v for k, v in vars(here).items() if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
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
