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
    """Обрезки плюс нарезка равны стоимости входа — копейки не теряются.

    Сама по себе эта сумма тождественна входу (нарезка и есть остаток), и
    показывать её оператору как «сходимость» нельзя. Но как сторож она рабочая:
    поймает, если отход начнёт стоить денег. Поэтому рядом проверяем то, что
    тождеством НЕ является, — что каждая строка это свой вес на свою цену.
    """
    for price, raw, sl, trim in ((9300, 10, 8, 2), (9990, 7.3, 5.1, 1.85), (12000, 22.4, 15.2, 6.15)):
        r = acts.split_salmon(price, raw, sl, trim)
        assert r["ok"], r
        assert abs(r["check"] - r["raw"]["sum"]) < 0.01, (price, raw, r)
        assert r["waste"]["sum"] == 0.0, r
        for line in ("raw", "slice", "trim"):
            w, p, total = (r[line]["weight"], r[line]["price_per_kg"], r[line]["sum"])
            if w <= 0:
                continue
            # Цена в строке — это сумма, делённая на вес, и округлённая до копеек.
            # Обратно (вес × цену) сходится уже не до копейки: 5.1 × 11 107.25 это
            # 56 646.98 против 56 647.00 в сумме. Проверяем в ту сторону, в
            # которую считали, иначе тест ловит собственное округление.
            assert abs(round(total / w, 2) - p) <= 0.01, (line, r[line])
    print("  [OK] на трёх наборах цена строки = её сумма на её вес, отход по нулю")


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
        {"id": "4", "name": "П/Ф Лосось терияки", "unit": "кг"},     # передел, не выход
        {"id": "5", "name": "лосось туша", "unit": "кг"},            # сырьё ЦЕХа, не наш вход
    ]
    p = acts.find_products(catalog)
    assert p["raw"]["id"] == "1" and p["trim"]["id"] == "2", p
    assert p["slice"]["id"] == "3" and p["waste"]["id"] == "6", p
    assert "teriyaki" not in p and "sauce" not in p, p   # это уже не разбор
    print("  [OK] четыре позиции разбора нашлись, туша ЦЕХа не подхватилась")


# ── Угорь: другая рыба и другая форма разбора ───────────────────────────────
# В номенклатуре сети по угрю ровно две строки: «угорь» и «П/Ф угорь». Лососёвой
# тройки выходов у него нет ни на одном филиале, и разбор здесь двухпозиционный:
# что положили и что получилось, остальное — отход.

def test_eel_splits_into_one_output_and_waste():
    """Целый угорь → П/Ф угорь + отход. Обрезков в этой рыбе нет."""
    r = acts.split_act(14000, 10, 7.5, kind="eel")
    assert r["ok"] and r["kind"] == "eel", r
    assert r["waste"]["weight"] == 2.5 and r["waste_pct"] == 25.0, r
    assert r["trim"]["weight"] == 0.0 and r["trim"]["sum"] == 0.0, r
    assert r["slice"]["price_per_kg"] == round(140000 / 7.5, 2), r
    assert abs(r["check"] - r["raw"]["sum"]) < 0.01, r
    print(f"  [OK] угорь: выход {r['slice']['price_per_kg']} ₸/кг, отход {r['waste_pct']}%")


def test_eel_refuses_a_trim_weight_it_cannot_have():
    """Вес обрезков у угря взяться неоткуда — молча свалить его в отход нельзя.

    Отход у разбора — оценка разделки; подмешать в неё чужие килограммы значит
    соврать ровно той цифрой, ради которой экран и сделан.
    """
    bad = acts.split_act(14000, 10, 7.5, 1.5, kind="eel")
    assert not bad["ok"] and "обрезков нет" in bad["error"], bad
    print(f"  [OK] «{bad['error']}»")


def test_both_fish_count_waste_the_same_way():
    """Форма разная, а отход считается одинаково: вход минус то, что вышло.

    Проценты обеих рыб попадают в одну публичную таблицу по сети, и считаться
    они обязаны по одному правилу — иначе филиалы сравнивать нельзя.
    """
    sal = acts.split_act(9300, 10, 7.5, 1.5, trim_price=8800, kind="salmon")
    eel = acts.split_act(9300, 10, 9.0, kind="eel")
    assert sal["waste"]["weight"] == 1.0 and sal["waste_pct"] == 10.0, sal
    assert eel["waste"]["weight"] == 1.0 and eel["waste_pct"] == 10.0, eel
    for r in (sal, eel):
        assert abs(r["check"] - r["raw"]["sum"]) < 0.01, r
        assert r["waste"]["sum"] == 0.0, r
    assert sal["kind"] != eel["kind"], "вид разбора всё же разный"
    print("  [OK] у обеих рыб отход 1.0 кг и 10.0 % — правило одно")


def test_eel_error_speaks_about_the_eel():
    """Ошибка называет то, что человек держит в руках, — угря, а не стейк."""
    bad = acts.split_act(14000, 0, 0, kind="eel")
    assert not bad["ok"] and "угря" in bad["error"], bad
    print(f"  [OK] «{bad['error']}»")


def test_eel_products_found_by_name_or_by_words():
    """Имя из справочника, а если филиал назвал по-своему — по словам."""
    p = acts.find_products([
        {"id": "1", "name": "угорь", "unit": "кг"},
        {"id": "3", "name": "П/Ф угорь", "unit": "кг"},
        {"id": "4", "name": "Отход угря", "unit": "кг"},
        {"id": "5", "name": "П/Ф ЛОСОСЬ СТЕЙК", "unit": "кг"},     # чужая рыба
    ], kind="eel")
    assert p["raw"]["id"] == "1" and p["slice"]["id"] == "3", p
    assert p["waste"]["id"] == "4", p
    assert "trim" not in p and "teriyaki" not in p, p
    # филиал со старыми названиями: пласт — это тоже выход, а не вход
    other = acts.find_products([
        {"id": "9", "name": "Угорь унаги 1 кг", "unit": "кг"},
        {"id": "8", "name": "Пласт угря", "unit": "кг"},
    ], kind="eel")
    assert other["raw"]["id"] == "9" and other["slice"]["id"] == "8", other
    print("  [OK] позиции угря нашлись и по имени, и по словам")


# ── Передел: обрезки на сковороду ───────────────────────────────────────────
# Отдельный документ. Разбор о нём ничего не знает и знать не должен.

def test_frying_is_not_part_of_the_act():
    """Главное требование: в разборе жарки нет. Ни полей, ни строк, ни денег —
    иначе «плохо разделали рыбу» можно было бы замазать удачной сковородой."""
    r = acts.split_salmon(9300, 10, 8, 2)
    assert "teriyaki" not in r and "sauce" not in r, r
    assert abs(r["check"] - r["raw"]["sum"]) < 0.01, r
    print("  [OK] разбор считает только рыбу: вход = нарезка + обрезки + отход")


def test_weights_are_counted_even_when_no_price_is_known():
    """Отход — это вес, а не деньги, и цена на него не влияет.

    Пока расчёт упирался в ненайденную цену, экран не показывал НИЧЕГО: ни
    отхода, ни процентов, — при том что взвесили всё, что надо. Ноль ценой
    передаёт маршрут, когда себестоимости обрезков нет и константы учёта тоже.
    """
    r = acts.split_act(0, 10, 7, 2, trim_price=0, kind="salmon")
    assert r["ok"], r
    assert r["waste"]["weight"] == 1.0 and r["waste_pct"] == 10.0, r
    assert r["slice_pct"] == 70.0 and r["trim_pct"] == 20.0, r
    assert r["money"] is False, r
    print("  [OK] без цен: отход 1.0 кг, 10.0 % — веса считаются")


def test_money_is_not_invented_when_a_price_is_missing():
    """Ноль вместо ненайденной цены — не «бесплатно», а «неизвестно».

    Если посчитать обрезки по нулю, их деньги молча уедут в нарезку и она
    подорожает на ровном месте. Поэтому денег просто нет, пока нет цены.
    """
    r = acts.split_act(9300, 10, 7, 2, trim_price=0, kind="salmon")
    assert r["ok"] and r["money"] is False, r
    assert r["slice"]["price_per_kg"] is None and r["slice"]["sum"] is None, r
    assert r["trim"]["sum"] is None and r["check"] is None, r
    assert r["need"] == "trim_price", r
    # а с ценой обрезков — те же веса и уже деньги
    full = acts.split_act(9300, 10, 7, 2, trim_price=9000, kind="salmon")
    assert full["money"] is True and full["waste"]["weight"] == r["waste"]["weight"], full
    print("  [OK] нет цены обрезков — нет денег, но веса те же")


def test_input_price_alone_does_not_block_the_weights():
    """Цену входа тоже может не найтись — веса от этого не пропадают."""
    r = acts.split_act(0, 10, 8, 1.5)
    assert r["ok"] and r["money"] is False and r["need"] == "price", r
    assert r["waste"]["weight"] == 0.5 and r["waste_pct"] == 5.0, r
    print("  [OK] нет цены входа — отход 0.5 кг, 5.0 % на месте")


def test_eel_has_no_trim_at_all():
    """У угря разбор в две позиции: целый угорь → П/Ф угорь + отход.

    Обрезков угря нет ни в одном филиале сети — в номенклатуре только «угорь»
    и «П/Ф угорь». Пока у угря была лососёвая форма из трёх выходов, экран
    просил вес того, чего не существует, и упирался в цену несуществующих
    обрезков.
    """
    assert acts.roles_of(acts.KINDS["eel"]) == ["raw", "slice", "waste"], acts.KINDS["eel"]
    r = acts.split_act(9000, 10, 8, kind="eel")
    assert r["ok"] and r["money"] is True, r
    assert r["waste"]["weight"] == 2.0 and r["waste_pct"] == 20.0, r
    assert r["trim"]["weight"] == 0.0 and r["trim"]["sum"] == 0.0, r
    # вся стоимость входа легла на выход: обрезкам её отдавать некому
    assert r["slice"]["sum"] == 90000.0 and r["slice"]["price_per_kg"] == 11250.0, r
    print(f"  [OK] угорь: {r['slice']['price_per_kg']} ₸/кг, отход {r['waste_pct']}%")


def test_eel_does_not_ask_for_a_price_it_cannot_have():
    """Цена обрезков у угря не спрашивается: обрезков у него нет."""
    r = acts.split_act(9000, 10, 8, kind="eel")
    assert r["need"] == "" and r["money"] is True, r
    print("  [OK] угорь считается без цены обрезков")


def test_eel_input_is_the_whole_fish_not_the_prepared():
    """«угорь» — вход, «П/Ф угорь» — выход. Спутать их значит списать выход.

    В справочнике обе строки начинаются одинаково, и вход раньше выбирался по
    тому, какая попалась первой: на половине филиалов входом вставал П/Ф.
    """
    catalog = [
        {"id": "p", "name": "П/Ф угорь", "unit": "кг"},
        {"id": "g", "name": "угорь", "unit": "кг"},
    ]
    got = acts.find_products(catalog, "eel")
    assert got["raw"]["id"] == "g", got
    assert got["slice"]["id"] == "p", got
    # и в обратном порядке справочника — тот же ответ
    got2 = acts.find_products(list(reversed(catalog)), "eel")
    assert got2["raw"]["id"] == "g" and got2["slice"]["id"] == "p", got2
    assert "trim" not in got, got
    print("  [OK] вход «угорь», выход «П/Ф угорь» — в любом порядке справочника")


def test_frying_loss_is_paid_by_the_teriyaki():
    """2 кг обрезков положили, сняли 1.4 — деньги обрезков никуда не делись,
    значит килограмм терияки дороже килограмма обрезков ровно на ужарку."""
    r = acts.fry_teriyaki(2, 1.4)
    assert r["ok"], r
    assert r["teriyaki"]["shrink"] == 0.6 and r["yield_pct"] == 70.0, r
    assert r["teriyaki"]["sum"] == 17600.0, r              # 2 × 8800
    assert r["teriyaki"]["price_per_kg"] == 12571.43, r    # 17 600 / 1.4
    print(f"  [OK] ужарка {r['teriyaki']['shrink']} кг, терияки {r['teriyaki']['price_per_kg']} ₸/кг")


def test_sauce_makes_the_teriyaki_more_expensive():
    """200 г соуса по 4 000 ₸/кг — 800 ₸ сверху, и они ложатся на терияки."""
    dry = acts.fry_teriyaki(2, 1.4)
    r = acts.fry_teriyaki(2, 1.4, g_sauce=200, sauce_price=4000)
    assert r["sauce"]["grams"] == 200.0 and r["sauce"]["sum"] == 800.0, r
    assert r["teriyaki"]["sum"] == dry["teriyaki"]["sum"] + 800.0, r
    assert r["check"] == r["trim"]["sum"] + r["sauce"]["sum"], r
    print(f"  [OK] соус 800 ₸ → терияки {r['teriyaki']['price_per_kg']} ₸/кг "
          f"вместо {dry['teriyaki']['price_per_kg']}")


def test_shrink_is_counted_without_any_price():
    """Ужарка — разница двух весов, и цена обрезков к ней отношения не имеет."""
    r = acts.fry_teriyaki(2, 1.4, trim_price=0)
    assert r["ok"] and r["money"] is False, r
    assert r["teriyaki"]["shrink"] == 0.6 and r["yield_pct"] == 70.0, r
    assert r["shrink_pct"] == 30.0, r
    assert r["teriyaki"]["price_per_kg"] is None, r
    print("  [OK] без цены обрезков ужарка 0.6 кг, выход 70.0 %")


def test_sauce_per_kilo_is_the_number_that_catches_the_overpour():
    """Граммы сами по себе ни о чём: сравнивают «сколько на килограмм»."""
    r = acts.fry_teriyaki(2, 1.5, g_sauce=300, sauce_price=4000)
    assert r["sauce_g_per_kg"] == 200.0, r
    print(f"  [OK] {r['sauce_g_per_kg']} г соуса на килограмм терияки")


def test_impossible_frying_is_refused():
    """При жарке вес уходит. Привес и незаполненный выход — описка."""
    heavy = acts.fry_teriyaki(1.5, 1.8)
    assert not heavy["ok"] and "жарк" in heavy["error"], heavy
    empty = acts.fry_teriyaki(1.5, 0)
    assert not empty["ok"] and "сковород" in empty["error"], empty
    none = acts.fry_teriyaki(0, 0)
    assert not none["ok"] and "обрезк" in none["error"], none
    print("  [OK] привес, пустой выход и пустая сковорода объясняются")


def test_teriyaki_products_found_and_not_confused_with_the_fish():
    """«Соус Терияки» и «П/Ф Лосось терияки» — разные товары. Спутать их значит
    списать бутылку соуса вместо килограмма рыбы."""
    p = acts.find_products([
        {"id": "2", "name": "П/Ф ОБРЕЗКИ ЛОСОСЬ", "unit": "кг"},
        {"id": "7", "name": "Соус терияки", "unit": "кг"},
        {"id": "4", "name": "П/Ф Лосось терияки", "unit": "кг"},
        {"id": "3", "name": "П/Ф НАРЕЗКА ЛОСОСЬ", "unit": "кг"},   # чужая позиция
    ], kind="teriyaki")
    assert p["trim"]["id"] == "2" and p["teriyaki"]["id"] == "4", p
    assert p["sauce"]["id"] == "7", p
    assert "raw" not in p and "waste" not in p, p       # у передела их нет
    print("  [OK] обрезки, терияки и соус нашлись, нарезка не подхватилась")


def test_period_of_frying_is_its_own_summary():
    """Свод жарок — второй акт в iiko, и цены в нём те, что были в жарке."""
    rows = [{"weight_fry": 1.8, "weight_teriyaki": 1.2, "weight_sauce": 240,
             "trim_price": 8800, "sauce_price": 4000}]
    s = acts.summarize_teriyaki(rows)
    assert s["fry"] == 1.8 and s["teriyaki"] == 1.2 and s["shrink"] == 0.6, s
    assert s["sauce"] == 240.0 and s["sauce_sum"] == 960.0, s
    assert s["teriyaki_sum"] == 15840.0 + 960.0, s          # 1.8 × 8800 + соус
    assert s["teriyaki_price"] == 14000.0 and s["yield_pct"] == 66.7, s
    assert s["sauce_g_per_kg"] == 200.0, s
    assert acts.summarize_teriyaki([])["acts"] == 0, "пустой период не делит на ноль"
    print(f"  [OK] за период ужарилось {s['shrink']} кг, выход {s['yield_pct']}%, "
          f"соуса {s['sauce_g_per_kg']} г/кг")


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


def test_old_acts_do_not_lose_the_fried_trim():
    """Разборы, записанные ДО выноса жарки, хранят обрезки в двух колонках:
    weight_trim — остаток, weight_fry — то, что ушло на сковороду. Пока жарка
    считалась внутри акта, свод складывал обе. После выноса weight_fry перестал
    учитываться — и килограммы вместе с деньгами исчезали, а стоимость входа
    целиком ложилась на нарезку: 11 405 ₸/кг вместо 9 425.

    Обрезки есть обрезки: сколько их вышло из рыбы, столько и в своде. Что с
    ними сделали потом — вопрос другого документа.
    """
    old = {"organization_id": "A", "weight_raw": 10, "weight_slice": 8,
           "weight_trim": 0.2, "weight_fry": 1.8, "weight_teriyaki": 1.2,
           "weight_waste": 0.0, "price_per_kg": 9300, "trim_price": 8800}
    s = acts.summarize([old])
    assert s["trim"] == 2.0, s                          # 0.2 остатка + 1.8 со сковороды
    assert s["trim_sum"] == 17600.0, s                  # 2.0 × 8800
    assert s["slice_price"] == 9425.0, s                # (93 000 − 17 600) / 8

    # новый разбор пишет все обрезки одной колонкой — там прибавлять нечего
    new = {**old, "weight_trim": 2.0, "weight_fry": 0, "weight_teriyaki": 0}
    assert acts.summarize([new])["trim"] == 2.0, new
    assert acts.summarize([new])["slice_price"] == s["slice_price"], new
    print("  [OK] старый разбор не теряет обрезки со сковороды: "
          f"{s['trim']} кг, нарезка {s['slice_price']} ₸/кг")


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
