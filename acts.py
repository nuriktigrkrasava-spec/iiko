"""Акт разбора лосося: П/Ф стейк из ЦЕХа → обрезки + нарезка.

В разборе участвуют ровно три позиции — никакой туши, её режет ЦЕХ:
  • «П/Ф ЛОСОСЬ СТЕЙК (ЦЕХ)» приходит в филиал накладной из ЦЕХа (на Алиева
    9 300 ₸/кг). Это ВХОД разбора, и только его цена берётся из накладных;
  • «П/Ф ОБРЕЗКИ ЛОСОСЬ» по накладным не приходит ни разу — это ВЫХОД,
    оценивается фиксированно (TRIM_PRICE ₸/кг);
  • «П/Ф НАРЕЗКА ЛОСОСЬ» — второй выход, на него ложится ВЕСЬ остаток стоимости.

Оператор вводит два веса: сколько стейка пошло в разбор и сколько получилось
обрезков. Нарезка не взвешивается — это остаток веса.
"""
from typing import Any, Dict, Optional

TRIM_PRICE = 8800.0          # ₸/кг, себестоимость обрезков — константа учёта

# Как позиции называются в номенклатуре (проверено на сервере Алиева).
RAW = "П/Ф ЛОСОСЬ СТЕЙК"      # вход: приходит накладной из ЦЕХа
TRIM = "П/Ф ОБРЕЗКИ ЛОСОСЬ"   # выход по фиксированной цене
SLICE = "П/Ф НАРЕЗКА ЛОСОСЬ"  # выход, забирает остаток стоимости
WASTE = "Отход лосося"        # выход по нулю: кости и кожа денег не стоят


def _norm(s: str) -> str:
    return " ".join((s or "").lower().replace("ё", "е").split())


def find_products(catalog: list) -> Dict[str, Optional[Dict[str, Any]]]:
    """Ищем четыре позиции по имени: id у каждого филиала свой (свой сервер)."""
    want = {"raw": _norm(RAW), "trim": _norm(TRIM), "slice": _norm(SLICE),
            "waste": _norm(WASTE)}
    out: Dict[str, Optional[Dict[str, Any]]] = {k: None for k in want}
    for p in catalog or []:
        n = _norm(p.get("name") or "")
        for key, w in want.items():
            if out[key] is None and n.startswith(w):
                out[key] = {"id": p.get("id"), "name": p.get("name"), "unit": p.get("unit")}
    return out


def split_salmon(price_per_kg: float, w_raw: float, w_trim: float,
                 w_waste: float = 0.0, trim_price: float = TRIM_PRICE) -> Dict[str, Any]:
    """Разбор в весах и деньгах. Только арифметика, в iiko не ходит.

    price_per_kg — цена входящего П/Ф стейка из накладной;
    w_raw        — сколько стейка пошло в разбор;
    w_trim       — обрезки (оцениваются по trim_price);
    w_waste      — отход: кости и кожа. Вес вводится руками, себестоимость 0 ₸,
                   поэтому отход НЕ уменьшает стоимость нарезки — только вес;
    нарезка      — остаток веса, на неё ложится весь остаток стоимости.
    """
    price_per_kg = float(price_per_kg or 0)
    w_raw, w_trim, w_waste = float(w_raw or 0), float(w_trim or 0), float(w_waste or 0)
    if w_raw <= 0:
        return {"ok": False, "error": "Вес стейка должен быть больше нуля"}
    if w_trim < 0 or w_waste < 0:
        return {"ok": False, "error": "Вес не может быть отрицательным"}
    w_slice = round(w_raw - w_trim - w_waste, 3)
    if w_slice < 0:
        return {"ok": False, "error": "Обрезки и отход вместе тяжелее стейка — проверь весы"}

    raw_sum = round(price_per_kg * w_raw, 2)
    trim_sum = round(trim_price * w_trim, 2)
    waste_sum = 0.0                       # отход по нулю: так ведётся учёт
    slice_sum = round(raw_sum - trim_sum, 2)
    if slice_sum < 0:
        return {"ok": False,
                "error": f"Обрезки по {trim_price:.0f} ₸ дороже всего стейка — проверь цену"}
    per_kg = round(slice_sum / w_slice, 2) if w_slice > 0 else 0.0

    return {
        "ok": True,
        "raw": {"weight": w_raw, "price_per_kg": price_per_kg, "sum": raw_sum},
        "trim": {"weight": w_trim, "price_per_kg": trim_price, "sum": trim_sum},
        "waste": {"weight": w_waste, "price_per_kg": 0.0, "sum": waste_sum},
        "slice": {"weight": w_slice, "price_per_kg": per_kg, "sum": slice_sum},
        "trim_pct": round(w_trim / w_raw * 100, 1),
        "waste_pct": round(w_waste / w_raw * 100, 1),
        "check": round(trim_sum + waste_sum + slice_sum, 2),   # = стоимости входа
    }
