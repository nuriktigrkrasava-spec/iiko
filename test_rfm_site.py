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


if __name__ == "__main__":
    failed = 0
    for t in (test_astana_filter, test_aggregate_clients):
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
