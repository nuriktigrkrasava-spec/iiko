"""Вкладка «План»: недели ISO, свёртка факта по дням недели, итоги и сводка сети.

Запуск:  python3 test_plan.py
"""
import os
import tempfile
from datetime import date, datetime

os.environ.setdefault("DB_PATH", tempfile.mktemp(suffix=".db"))
import api  # noqa: E402


def olap(day: str, order_type: str, n: int):
    return {"OpenDate.Typed": day + " 00:00:00", "OrderType.Name": order_type, "OrdersCount": n}


def test_iso_week_matches_the_owners_numbering():
    """«Неделя 35» в таблице владельца — это ISO-неделя, а не 35-я семидневка месяца."""
    assert api._iso_week_bounds("2026-W35") == (date(2026, 8, 24), date(2026, 8, 30))
    assert api._iso_week_of(date(2026, 8, 25)) == "2026-W35"
    assert api._iso_week_of(date(2026, 8, 30)) == "2026-W35", "воскресенье — тот же ISO-номер"
    assert api._iso_week_of(date(2026, 8, 31)) == "2026-W36"
    print("  [OK] неделя 35 = 24–30.08, воскресенье не уезжает в следующую")


def test_fact_folds_into_days_and_channels():
    rows = [olap("2026-08-24", "Доставка", 11), olap("2026-08-24", "Обычный заказ", 90),
            olap("2026-08-24", "Самовывоз", 8),
            olap("2026-08-24", "Wolt", 4), olap("2026-08-24", "Yandex Eda", 2),
            olap("2026-08-30", "Доставка", 15)]
    f = api._fold_by_dow(rows)["dow"]
    assert f["1"] == {"hall": 90, "pickup": 8, "delivery": 11, "agg": 6}, f["1"]
    assert f["7"]["delivery"] == 15 and f["7"]["hall"] == 0, f["7"]
    print("  [OK] понедельник: зал 90, вынос 8, доставка 11, агрегаторы 6")


def test_pickup_is_its_own_channel():
    """Вынос отделён от зала (решение владельца 26.08.2026): это разные
    процессы и разная нагрузка на кухню, смешивать их в одной колонке нельзя."""
    f = api._fold_by_dow([olap("2026-08-25", "Самовывоз", 7)])["dow"]
    assert f["2"] == {"hall": 0, "pickup": 7, "delivery": 0, "agg": 0}, f["2"]
    print("  [OK] самовывоз — отдельный канал, не зал")


def test_site_pickup_is_pickup_not_delivery():
    """«Сайт самовывоз» содержит слово «сайт», но это вынос. Проверяем порядок
    правил: самовывоз разбирается ДО доставки, иначе «Сайт самовывоз» мог бы
    уехать в доставку вместе с «Сайт доставка»."""
    assert api._classify_channel("Сайт самовывоз") == "pickup"
    assert api._classify_channel("Сайт доставка") == "delivery"
    assert api._classify_channel("Обычный заказ") == "hall"
    assert api._classify_channel("Wolt") == "agg"
    assert api._classify_channel("Яндекс Еда") == "agg"
    print("  [OK] все семь реальных типов заказа сети разложены верно")


def test_broken_dates_do_not_crash_the_week():
    f = api._fold_by_dow([{"OpenDate.Typed": "", "OrderType.Name": "Доставка", "OrdersCount": 5},
                          {"OpenDate.Typed": "не дата", "OrderType.Name": "Доставка", "OrdersCount": 5},
                          olap("2026-08-24", "Доставка", 3)])["dow"]
    assert sum(f[str(i)]["delivery"] for i in range(1, 8)) == 3, f
    print("  [OK] битые даты выброшены, живая строка посчитана")


NOW = {"kitchen": 18, "road": 12, "late_pct": 8.0, "rating": 4.5, "orders": 900}
PREV = {"kitchen": 24, "road": 12, "late_pct": 14.0, "rating": 4.2, "orders": 800}   # +12,5%


def test_wins_name_what_actually_got_better():
    """Поздравляем за улучшение, а не за «хорошо». Время меньше — победа,
    рейтинг больше — победа, а неизменившийся показатель молчит."""
    wins = api.plan_wins(NOW, PREV)
    keys = {w["key"] for w in wins}
    assert keys == {"kitchen", "late_pct", "rating", "orders"}, keys
    assert "road" not in keys, "не изменилось — не повод поздравлять"
    k = next(w for w in wins if w["key"] == "kitchen")
    assert k["from"] == 24 and k["to"] == 18 and k["better"] == 6, k
    print("  [OK] " + " · ".join(f'{w["label"]} {w["from"]}→{w["to"]}' for w in wins))


def test_getting_worse_is_never_a_win():
    wins = api.plan_wins(PREV, NOW)      # поменяли местами: стало хуже
    assert wins == [], wins
    print("  [OK] ухудшение поздравлением не притворяется")


def test_tiny_wobble_is_not_a_win():
    """Минута туда-сюда и 0,02 рейтинга — шум. Поздравлять за шум нельзя:
    поздравления обесценятся за неделю."""
    assert api.plan_wins({"kitchen": 18, "rating": 4.51, "late_pct": 7.6},
                         {"kitchen": 18.4, "rating": 4.50, "late_pct": 8.0}) == []
    print("  [OK] дрожь в пределах порога поздравлением не считается")


def test_seasonal_order_growth_does_not_congratulate_everyone():
    """Живой случай 25.08: порог заказов был в ШТУКАХ, и «плюс три заказа»
    прошло у всех девяти филиалов разом — открытку получила вся сеть просто
    за сезон. Порог сделан относительным."""
    assert api.plan_wins({"orders": 702}, {"orders": 671}) == [], "рост 4,6% — это сезон"
    win = api.plan_wins({"orders": 436}, {"orders": 355})
    assert [w["key"] for w in win] == ["orders"] and win[0]["pct"] == 23, win
    print("  [OK] +4,6% заказов молчит, +23% поздравляется")


def test_missing_metric_is_skipped_not_crashed():
    wins = api.plan_wins({"kitchen": 10}, {"kitchen": 20, "rating": 4.0})
    assert [w["key"] for w in wins] == ["kitchen"], wins
    assert api.plan_wins({}, {}) == []
    print("  [OK] отсутствующий показатель пропускается, а не роняет карточку")


def test_partial_week_compares_only_elapsed_days():
    """Живой случай 25.08: владелец проставил план на всю сеть на ТЕКУЩУЮ неделю,
    а критерий смотрел на завершённую — и «выполнение плана» молчало у восьми
    филиалов. Незавершённую неделю считаем пропорционально: план Пн–Ср против
    факта Пн–Ср, иначе филиал получает ноль просто за то, что сегодня среда."""
    plans = {d: {"hall": 100, "delivery": 10, "agg": 5} for d in range(1, 8)}
    assert api._plan_days_and_total(plans, 7) == 805, "неделя целиком"
    assert api._plan_days_and_total(plans, 3) == 345, "только Пн–Ср"
    assert api._plan_days_and_total(plans, 0) == 0
    print("  [OK] план недели 805, план трёх дней 345 — сравнивать есть с чем")


def test_partial_plan_ignores_days_that_have_not_happened():
    """Ключевое: дни, которых ещё не было, в знаменатель не идут."""
    plans = {1: {"hall": 90}, 2: {"hall": 90}, 6: {"hall": 200}, 7: {"hall": 200}}
    assert api._plan_days_and_total(plans, 2) == 180, "выходные не должны попасть"
    assert api._plan_days_and_total(plans, 7) == 580
    print("  [OK] пятничный и субботний план не тянет вниз оценку в понедельник")


def _grid(v):
    return {str(i): {t: v for t in api.PLAN_TYPES} for i in range(1, 8)}


def test_totals_and_network_row():
    rows = [{"organization_id": "a", "name": "Алиева", "plan": _grid(10), "fact": _grid(8), "base": _grid(9)},
            {"organization_id": "b", "name": "Достык", "plan": _grid(5), "fact": _grid(7), "base": _grid(6)}]
    r = api._plan_response("2026-W35", date(2026, 8, 24), date(2026, 8, 30), rows, demo=False)
    assert r["branches"][0]["total_plan"]["hall"] == 70, r["branches"][0]["total_plan"]
    assert r["branches"][0]["total_fact"]["hall"] == 56
    net = r["network"]
    assert net["name"] == "Итого сеть"
    assert net["plan"]["1"]["hall"] == 15 and net["total_fact"]["hall"] == 105, net
    print("  [OK] итог филиала 70 план / 56 факт, сеть по понедельнику 15")


def test_network_row_is_not_double_counted_into_branches():
    """Строка «Итого сеть» отдельная — в списке филиалов её быть не должно,
    иначе сумма сети удвоится при следующем сложении."""
    rows = [{"organization_id": "a", "name": "Алиева", "plan": _grid(10), "fact": _grid(8), "base": _grid(9)}]
    r = api._plan_response("2026-W35", date(2026, 8, 24), date(2026, 8, 30), rows, demo=False)
    assert [b["name"] for b in r["branches"]] == ["Алиева"], r["branches"]
    print("  [OK] «Итого сеть» отдельным полем, среди филиалов её нет")


def test_empty_week_has_full_grid():
    """Пустая неделя всё равно отдаёт 7 дней × 3 канала: таблица не должна
    рассыпаться на филиале, который ещё ничего не продал."""
    f = api._fold_by_dow([])["dow"]
    assert set(f) == {str(i) for i in range(1, 8)}
    assert all(set(f[d]) == set(api.PLAN_TYPES) for d in f), f
    print("  [OK] пустая неделя — полная сетка из нулей")


def test_day_plan_survives_a_round_trip():
    from database import set_day_plans, get_day_plans
    set_day_plans([{"org": "o1", "week": "2026-W35", "dow": 1, "ch_type": "hall", "planned": 90},
                   {"org": "o1", "week": "2026-W35", "dow": 5, "ch_type": "delivery", "planned": 22}])
    set_day_plans([{"org": "o1", "week": "2026-W35", "dow": 1, "ch_type": "hall", "planned": 97}])
    got = get_day_plans(["o1"], "2026-W35")
    assert got["o1"][1]["hall"] == 97, got      # перезапись, а не дубль
    assert got["o1"][5]["delivery"] == 22, got
    assert get_day_plans(["o1"], "2026-W36") == {}, "чужая неделя не подмешивается"
    print("  [OK] план сохраняется, перезаписывается и не течёт между неделями")


def test_done_days_counts_only_closed_days():
    """Сравнение с прошлой неделей идёт день в день, поэтому число закрытых
    дней считает сервер. Во вторник закрыт ровно один день — понедельник;
    сегодняшний ещё идёт и в сравнение не входит."""
    import api as A
    real_now = A.local_now

    def at(d: date):
        A.local_now = lambda: datetime(d.year, d.month, d.day, 14, 0)
        rows = [{"organization_id": "a", "name": "Алиева", "plan": _grid(10),
                 "fact": _grid(8), "base": _grid(9), "prev": _grid(7)}]
        return A._plan_response("2026-W35", date(2026, 8, 24), date(2026, 8, 30),
                                rows, demo=False)
    try:
        assert at(date(2026, 8, 24))["done_days"] == 0, "понедельник: закрытых дней нет"
        assert at(date(2026, 8, 25))["done_days"] == 1, "вторник: закрыт понедельник"
        assert at(date(2026, 8, 30))["done_days"] == 6, "воскресенье: шесть закрытых"
        past = at(date(2026, 9, 2))
        assert past["done_days"] == 7 and past["running"] is False, "прошедшая неделя — вся"
        future = at(date(2026, 8, 17))
        assert future["done_days"] == 0 and future["running"] is False
    finally:
        A.local_now = real_now
    print("  [OK] вторник = 1 закрытый день, закрытая неделя = 7, будущая = 0")


def test_previous_week_is_taken_from_the_base_window():
    """Прошлая неделя приходит рядом с фактом — иначе динамику не показать.
    Берётся из уже загруженного окна базы, отдельного запроса в iiko нет."""
    rows = [{"organization_id": "a", "name": "Алиева", "plan": _grid(10),
             "fact": _grid(8), "base": _grid(9), "prev": _grid(6)}]
    r = api._plan_response("2026-W35", date(2026, 8, 24), date(2026, 8, 30), rows, demo=False)
    assert r["branches"][0]["total_prev"]["hall"] == 42, r["branches"][0]["total_prev"]
    assert r["network"]["total_prev"]["hall"] == 42, r["network"]["total_prev"]
    print("  [OK] прошлая неделя в итогах филиала и сети: 42")


def test_row_without_previous_week_does_not_crash():
    """Филиал, по которому iiko промолчал, не должен ронять всю вкладку."""
    rows = [{"organization_id": "a", "name": "Алиева", "plan": _grid(10),
             "fact": _grid(8), "base": _grid(9)}]          # prev отсутствует
    r = api._plan_response("2026-W35", date(2026, 8, 24), date(2026, 8, 30), rows, demo=False)
    assert r["branches"][0]["total_prev"] == {t: 0 for t in api.PLAN_TYPES}
    print("  [OK] без прошлой недели итог нулевой, а не исключение")


def _cache_env(today: date, olap_rows, calls):
    """Подменяет часы и OLAP: тесты кэша не должны ходить в iiko."""
    import api as A

    async def fake_orders(real_org, d_from, d_to, user):
        calls.append((d_from.isoformat(), d_to.isoformat()))
        return [r for r in olap_rows
                if d_from.isoformat() <= r["OpenDate.Typed"][:10] <= d_to.isoformat()]

    A.local_now = lambda: datetime(today.year, today.month, today.day, 14, 0)
    A._orders_by_day = fake_orders


def test_closed_days_are_read_from_the_snapshot_not_from_iiko():
    """Второе открытие вкладки не должно стрелять в iiko: закрытый день уже
    лежит в базе. Ради этого весь кэш и заводился."""
    import api as A
    import asyncio as aio
    real_now, real_orders = A.local_now, A._orders_by_day
    calls = []
    rows = [olap("2026-08-24", "Обычный заказ", 90), olap("2026-08-25", "Доставка", 11)]
    try:
        _cache_env(date(2026, 8, 26), rows, calls)
        first = aio.run(A._orders_cached("org-cache-1", date(2026, 8, 24), date(2026, 8, 30), {"id": 1}))
        assert first["2026-08-24"]["hall"] == 90, first
        assert len(calls) == 1, f"первый заход — один запрос, было {calls}"
        second = aio.run(A._orders_cached("org-cache-1", date(2026, 8, 24), date(2026, 8, 30), {"id": 1}))
        assert second == first, (first, second)
        assert len(calls) == 1, f"второй заход не должен ходить в iiko, было {calls}"
    finally:
        A.local_now, A._orders_by_day = real_now, real_orders
    print("  [OK] второе открытие вкладки читает снимок, в iiko не идёт")


def test_today_is_never_returned_or_cached():
    """Сегодняшний день ещё идёт: положить его в снимок — значит навсегда
    зафиксировать половину дня и сравнивать её с целым днём прошлой недели."""
    import api as A
    import asyncio as aio
    real_now, real_orders = A.local_now, A._orders_by_day
    calls = []
    rows = [olap("2026-08-25", "Доставка", 11), olap("2026-08-26", "Доставка", 4)]
    try:
        _cache_env(date(2026, 8, 26), rows, calls)
        got = aio.run(A._orders_cached("org-cache-2", date(2026, 8, 24), date(2026, 8, 30), {"id": 1}))
        assert "2026-08-26" not in got, got
        assert got["2026-08-25"]["delivery"] == 11, got
        assert calls and calls[0][1] == "2026-08-25", f"в iiko не просим сегодняшний день: {calls}"
    finally:
        A.local_now, A._orders_by_day = real_now, real_orders
    print("  [OK] сегодняшний день не отдаётся и не кэшируется")


def test_day_without_orders_is_not_refetched_forever():
    """День, в который заказов не было, тоже закрыт. Не запиши мы нули —
    он считался бы «отсутствующим» и добирался при каждом открытии."""
    import api as A
    import asyncio as aio
    real_now, real_orders = A.local_now, A._orders_by_day
    calls = []
    try:
        _cache_env(date(2026, 8, 26), [], calls)          # iiko отдаёт пусто
        aio.run(A._orders_cached("org-cache-3", date(2026, 8, 24), date(2026, 8, 25), {"id": 1}))
        aio.run(A._orders_cached("org-cache-3", date(2026, 8, 24), date(2026, 8, 25), {"id": 1}))
        assert len(calls) == 1, f"нулевой день должен закрыться с первого раза, было {calls}"
    finally:
        A.local_now, A._orders_by_day = real_now, real_orders
    print("  [OK] день без заказов закрывается нулями, повторно не тянется")


def test_future_week_asks_iiko_for_nothing():
    """Неделя, которая ещё не наступила: закрытых дней нет, запросов тоже."""
    import api as A
    import asyncio as aio
    real_now, real_orders = A.local_now, A._orders_by_day
    calls = []
    try:
        _cache_env(date(2026, 8, 26), [], calls)
        got = aio.run(A._orders_cached("org-cache-4", date(2026, 9, 7), date(2026, 9, 13), {"id": 1}))
        assert got == {} and not calls, (got, calls)
    finally:
        A.local_now, A._orders_by_day = real_now, real_orders
    print("  [OK] будущая неделя: ни данных, ни запросов в iiko")


if __name__ == "__main__":
    failed = 0
    for t in (test_wins_name_what_actually_got_better, test_getting_worse_is_never_a_win,
              test_tiny_wobble_is_not_a_win, test_missing_metric_is_skipped_not_crashed,
              test_seasonal_order_growth_does_not_congratulate_everyone,
              test_partial_week_compares_only_elapsed_days,
              test_partial_plan_ignores_days_that_have_not_happened,
              test_iso_week_matches_the_owners_numbering, test_fact_folds_into_days_and_channels,
              test_pickup_is_its_own_channel, test_site_pickup_is_pickup_not_delivery,
              test_broken_dates_do_not_crash_the_week,
              test_totals_and_network_row, test_network_row_is_not_double_counted_into_branches,
              test_empty_week_has_full_grid, test_day_plan_survives_a_round_trip,
              test_done_days_counts_only_closed_days,
              test_previous_week_is_taken_from_the_base_window,
              test_row_without_previous_week_does_not_crash,
              test_closed_days_are_read_from_the_snapshot_not_from_iiko,
              test_today_is_never_returned_or_cached,
              test_day_without_orders_is_not_refetched_forever,
              test_future_week_asks_iiko_for_nothing):
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
