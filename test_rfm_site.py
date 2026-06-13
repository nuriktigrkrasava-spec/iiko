"""Локальные мини-тесты для сайта /rfm. Запуск: .venv/bin/python test_rfm_site.py
В iiko не ходим — get_all_restaurants и данные подменяются."""
import api
from datetime import date


def test_astana_filter():
    api.get_all_restaurants = lambda: [
        {"organization_name": "Астана, ул. Бокейхана 25а", "api_login": "x"},
        {"organization_name": "Астана, ул. Сыганак 11 (Жагалау)", "api_login": "x"},
        {"organization_name": "Актау, 12 микрорайон 30а", "api_login": "x"},
        {"organization_name": "Костанай, ул. Абая 153", "api_login": "x"},
    ]
    out = api._astana_restaurants()
    names = [r["organization_name"] for r in out]
    assert len(out) == 2, names
    assert all(n.lower().startswith("астана") for n in names), names


def test_aggregate_clients():
    today = date(2026, 6, 13)
    rows = [
        # phone A: заказ 5 дней назад + заказ 100 дней назад
        {"Delivery.CustomerPhone": "+7 701 000 0001", "OpenDate.Typed": "2026-06-08", "UniqOrderId.OrdersCount": 1, "DishDiscountSumInt": 5000},
        {"Delivery.CustomerPhone": "+7 701 000 0001", "OpenDate.Typed": "2026-03-05", "UniqOrderId.OrdersCount": 1, "DishDiscountSumInt": 3000},
        # phone B: пустой телефон — отбросить
        {"Delivery.CustomerPhone": "", "OpenDate.Typed": "2026-06-08", "UniqOrderId.OrdersCount": 1, "DishDiscountSumInt": 1000},
        # phone C: 0 заказов — отбросить строку
        {"Delivery.CustomerPhone": "+7 701 000 0003", "OpenDate.Typed": "2026-06-08", "UniqOrderId.OrdersCount": 0, "DishDiscountSumInt": 0},
    ]
    agg = api._aggregate_clients(rows, today)
    assert len(agg) == 1, list(agg)
    a = next(iter(agg.values()))
    assert a["orders_total"] == 2 and a["spend_total"] == 8000, a
    assert a["orders_90"] == 1 and a["spend_90"] == 5000, a   # только заказ 5 дней назад
    assert a["last_date"] == "2026-06-08", a


def _agg(orders_90, spend_90, orders_total, last_date):
    return {"orders_90": orders_90, "spend_90": spend_90,
            "orders_total": orders_total, "spend_total": spend_90, "last_date": last_date}

def test_rfm_segments():
    today = date(2026, 6, 13)
    agg = {
        "champ":   _agg(8, 90000, 12, "2026-06-12"),   # R~1, F7+, высокий M -> champions
        "loyal":   _agg(3, 12000, 5,  "2026-06-10"),   # R~3, F2-3 -> loyal
        "bigrare": _agg(1, 80000, 2,  "2026-05-20"),   # R~24, F=1, топ-M -> big_rare
        "new":     _agg(1, 1500,  1,  "2026-06-11"),   # R~2, F=1, низкий M -> new
        "atrisk":  _agg(0, 0.0,   5,  "2026-05-01"),   # R~43, был частый -> at_risk
        "lost":    _agg(0, 0.0,   1,  "2026-01-10"),   # R 90+ -> lost
    }
    out = api._rfm_by_thresholds(agg, today)
    got = {s["key"]: s["count"] for s in out["segments"]}
    assert out["total"] == 6, out
    for k in ("champions", "loyal", "big_rare", "new", "at_risk", "lost"):
        assert got.get(k) == 1, (k, got)
    # у каждого сегмента есть действие и пример
    for s in out["segments"]:
        assert s["action"] and s["example"], s


def test_branch_stats():
    today = date(2026, 6, 13)
    rows = [
        {"Delivery.CustomerPhone": "+7 701 000 0001", "OpenDate.Typed": "2026-06-10", "UniqOrderId.OrdersCount": 2, "DishDiscountSumInt": 10000},
        {"Delivery.CustomerPhone": "+7 701 000 0002", "OpenDate.Typed": "2026-06-09", "UniqOrderId.OrdersCount": 1, "DishDiscountSumInt": 4000},
    ]
    st = api._branch_stats(rows, today)
    assert st["clients"] == 2, st
    assert st["revenue"] == 14000, st
    assert st["repeat_pct"] == 50, st      # 1 из 2 клиентов с 2+ заказами
    assert st["ltv"] == 7000, st


def test_render_html():
    report = {
        "date": "2026-06-13",
        "kpi": {"clients": 1234, "revenue": 9000000, "ltv": 7300, "repeat_pct": 41},
        "rfm": {"total": 1234, "segments": [
            {"key": "champions", "emoji": "🏆", "label": "Чемпионы", "count": 142, "pct": 12,
             "revenue": 3000000, "action": "беречь, без скидок", "example": "Первыми пробуете новинку"},
        ]},
        "branches": [
            {"name": "Астана, ул. Бокейхана 25а", "clients": 300, "revenue": 2000000, "repeat_pct": 44, "ltv": 6600},
        ],
    }
    html = api._render_rfm_html(report)
    assert "<html" in html.lower()
    assert "RFM" in html and "Астана" in html
    assert "Чемпионы" in html and "беречь, без скидок" in html
    assert "Бокейхана" in html                       # таблица филиалов
    assert "Уснувшие VIP" in html                    # блок идей
    assert "Челлендж" in html or "челлендж" in html  # блок идей
    assert "приложени" in html                       # миграция в приложение


def test_cohort_retention():
    today = date(2026, 6, 13)
    rows = [
        # клиент 1: первый заказ янв, вернулся фев
        {"Delivery.CustomerPhone":"+7 700 000 0001","OpenDate.Typed":"2026-01-10","UniqOrderId.OrdersCount":1,"DishDiscountSumInt":1},
        {"Delivery.CustomerPhone":"+7 700 000 0001","OpenDate.Typed":"2026-02-15","UniqOrderId.OrdersCount":1,"DishDiscountSumInt":1},
        # клиент 2: только янв
        {"Delivery.CustomerPhone":"+7 700 000 0002","OpenDate.Typed":"2026-01-20","UniqOrderId.OrdersCount":1,"DishDiscountSumInt":1},
    ]
    c = api._cohort_retention(rows, today, max_m=2)
    jan = next(x for x in c["cohorts"] if x["month"] == "2026-01")
    assert jan["size"] == 2
    assert jan["ret"][0] == 100            # M0 — все
    assert jan["ret"][1] == 50             # M1 (фев) — вернулся 1 из 2
    assert jan["ret"][2] == 0              # M2 (мар) — никто


def test_render_edu():
    report = {"date":"2026-06-13","kpi":{"clients":1,"revenue":1,"ltv":1,"repeat_pct":1},
              "rfm":{"total":1,"segments":[]},"branches":[]}
    html = api._render_rfm_html(report)
    for s in ("Когортный анализ", "CLV", "+67%", "Прогноз оттока", "Dynamic Yield", "AI Factory"):
        assert s in html, s


def test_rfm_route_access():
    from fastapi.testclient import TestClient
    api.get_all_restaurants = lambda: []     # пустой список → роут не ходит в iiko
    client = TestClient(api.app)

    api.RFM_SITE_KEY = ""                     # ключ не задан → 404
    assert client.get("/rfm").status_code == 404
    assert client.get("/rfm?key=anything").status_code == 404

    api.RFM_SITE_KEY = "secret"
    assert client.get("/rfm").status_code == 403          # нет ключа
    assert client.get("/rfm?key=wrong").status_code == 403
    r = client.get("/rfm?key=secret")
    assert r.status_code == 200, r.status_code
    assert "RFM" in r.text and "Астаны" in r.text         # страница отрендерилась
    api.RFM_SITE_KEY = ""                                 # вернуть как было


if __name__ == "__main__":
    failed = 0
    for t in (test_astana_filter, test_aggregate_clients, test_rfm_segments, test_branch_stats, test_cohort_retention, test_render_html, test_render_edu, test_rfm_route_access):
        print(f"\n>>> {t.__name__}")
        try:
            t()
            print("  [OK]")
        except AssertionError as e:
            failed += 1; print(f"  [FAIL] {e}")
        except Exception as e:
            failed += 1; print(f"  [ERROR] {type(e).__name__}: {e}")
    print(f"\n{'='*50}\n{'ВСЕ ТЕСТЫ ОК' if not failed else f'ПРОВАЛЕНО: {failed}'}")
    raise SystemExit(1 if failed else 0)
