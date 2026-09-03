"""Акт разбора лосося: П/Ф стейк из ЦЕХа → нарезка + обрезки + отход.

В разборе участвуют ровно четыре позиции — никакой туши, её режет ЦЕХ:
  • «П/Ф ЛОСОСЬ СТЕЙК (ЦЕХ)» приходит в филиал накладной из ЦЕХа (на Алиева
    9 300 ₸/кг). Это ВХОД разбора, и только его цена берётся из накладных;
  • «П/Ф НАРЕЗКА ЛОСОСЬ» — главный выход, на него ложится ВЕСЬ остаток стоимости;
  • «П/Ф ОБРЕЗКИ ЛОСОСЬ» по накладным не приходит ни разу — второй выход,
    оценивается фиксированно (TRIM_PRICE ₸/кг);
  • «Отход лосося» — кости и кожа, себестоимость 0 ₸.

Оператор взвешивает то, что реально держит в руках: стейк на входе, нарезку и
обрезки на выходе. Отход не взвешивают — он остаток веса, и именно он говорит,
насколько аккуратно разобрали рыбу.
"""
from typing import Any, Dict, Iterable, List, Optional

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


def split_salmon(price_per_kg: float, w_raw: float, w_slice: float,
                 w_trim: float = 0.0, trim_price: float = TRIM_PRICE) -> Dict[str, Any]:
    """Разбор в весах и деньгах. Только арифметика, в iiko не ходит.

    price_per_kg — цена входящего П/Ф стейка из накладной;
    w_raw        — сколько стейка пошло в разбор;
    w_slice      — сколько получилось нарезки (её и взвешивают);
    w_trim       — обрезки (оцениваются по trim_price);
    отход        — остаток веса: стейк − нарезка − обрезки. Себестоимость 0 ₸,
                   поэтому отход НЕ уменьшает стоимость нарезки — только вес.
    """
    price_per_kg = float(price_per_kg or 0)
    w_raw, w_slice, w_trim = float(w_raw or 0), float(w_slice or 0), float(w_trim or 0)
    if w_raw <= 0:
        return {"ok": False, "error": "Вес стейка должен быть больше нуля"}
    if w_slice < 0 or w_trim < 0:
        return {"ok": False, "error": "Вес не может быть отрицательным"}
    w_waste = round(w_raw - w_slice - w_trim, 3)
    if w_waste < 0:
        return {"ok": False,
                "error": "Нарезка и обрезки вместе тяжелее стейка — проверь весы"}

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
        "slice": {"weight": w_slice, "price_per_kg": per_kg, "sum": slice_sum},
        "trim": {"weight": w_trim, "price_per_kg": trim_price, "sum": trim_sum},
        "waste": {"weight": w_waste, "price_per_kg": 0.0, "sum": waste_sum},
        "slice_pct": round(w_slice / w_raw * 100, 1),
        "trim_pct": round(w_trim / w_raw * 100, 1),
        "waste_pct": round(w_waste / w_raw * 100, 1),
        "check": round(trim_sum + waste_sum + slice_sum, 2),   # = стоимости входа
    }


# ── Свод за период ───────────────────────────────────────────────────────────
# Отдельно от split_salmon и без базы: складывать зафиксированные разборы —
# другая задача, и проверять её надо на голых числах.

def summarize(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Итог по пачке разборов — то, что администратор заносит в iiko одним актом.

    Проценты и себестоимость — средневзвешенные, а не среднее по актам: разбор
    на 40 кг и разбор на 2 кг не имеют одинакового веса в оценке филиала.
    """
    n = 0
    raw = slice_w = trim = waste = 0.0
    raw_sum = slice_sum = trim_sum = 0.0
    for r in rows:
        n += 1
        w_raw = float(r.get("weight_raw") or 0)
        w_slice = float(r.get("weight_slice") or 0)
        w_trim = float(r.get("weight_trim") or 0)
        raw += w_raw
        slice_w += w_slice
        trim += w_trim
        waste += float(r.get("weight_waste") or 0)
        price = float(r.get("price_per_kg") or 0)
        tprice = float(r.get("trim_price") or TRIM_PRICE)
        raw_sum += price * w_raw
        trim_sum += tprice * w_trim
        slice_sum += price * w_raw - tprice * w_trim
    return {
        "acts": n,
        "raw": round(raw, 3), "slice": round(slice_w, 3),
        "trim": round(trim, 3), "waste": round(waste, 3),
        "raw_sum": round(raw_sum, 2), "slice_sum": round(slice_sum, 2),
        "trim_sum": round(trim_sum, 2),
        "slice_price": round(slice_sum / slice_w, 2) if slice_w > 0 else 0.0,
        "raw_price": round(raw_sum / raw, 2) if raw > 0 else 0.0,
        "slice_pct": round(slice_w / raw * 100, 1) if raw > 0 else 0.0,
        "trim_pct": round(trim / raw * 100, 1) if raw > 0 else 0.0,
        "waste_pct": round(waste / raw * 100, 1) if raw > 0 else 0.0,
    }


def by_branch(rows: Iterable[Dict[str, Any]],
              names: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """Свод по филиалам — публичная таблица «где нарезка дешевле и отхода меньше».

    Сортируем по % отхода: у кого рыба уходит в кости меньше всех, тот и наверху.
    """
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        groups.setdefault(r.get("organization_id") or "", []).append(r)
    out = []
    for org, rs in groups.items():
        s = summarize(rs)
        s["organization_id"] = org
        s["name"] = (names or {}).get(org, org)
        out.append(s)
    out.sort(key=lambda s: (s["waste_pct"], s["slice_price"]))
    return out
