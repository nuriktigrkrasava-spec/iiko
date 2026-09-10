"""Акты разбора: П/Ф из ЦЕХа → нарезка + обрезки + отход. Лосось и угорь.

Разбор всегда одной формы, меняется только рыба:
  • ВХОД приходит в филиал накладной из ЦЕХа («П/Ф ЛОСОСЬ СТЕЙК» на Алиева
    9 300 ₸/кг, «Угорь целый»). Только его цена берётся из накладных;
  • «нарезка» — главный выход, на него ложится ВЕСЬ остаток стоимости;
  • «обрезки» по накладным не приходят ни разу — второй выход, оценивается
    фиксированной ценой учёта (trim_price);
  • «отход» — кости и кожа, себестоимость 0 ₸.

У лосося есть пятая позиция — «П/Ф ЛОСОСЬ ТЕРИЯКИ». Это те же обрезки,
обжаренные с соусом, поэтому он не отдельный выход разбора, а ПЕРЕДЕЛ обрезков:
сколько обрезков положили на сковороду, столько ушло из строки обрезков, а
деньги этих обрезков целиком легли на то, что со сковороды сняли. При жарке вес
уходит, деньги — нет: килограмм терияки поэтому дороже килограмма обрезков, и
именно ужарку этот акт и должен показывать. Отход разбора от жарки не меняется —
терияки берут не из стейка.

Оператор взвешивает то, что реально держит в руках: вход, нарезку и обрезки, а
у терияки — что положил жарить и что снял со сковороды. Отход не взвешивают: он
остаток веса, и именно он говорит, насколько аккуратно разобрали рыбу.
"""
from typing import Any, Dict, Iterable, List, Optional

TRIM_PRICE = 8800.0          # ₸/кг, себестоимость обрезков лосося — константа учёта
EEL_TRIM_PRICE = 0.0         # у угря цена обрезков ещё не назначена: 0 = спросим её
                             # в акте полем, чтобы разбор не ждал константы

# ── Виды разбора ─────────────────────────────────────────────────────────────
# names — как позиция называется в номенклатуре (проверено на сервере Алиева);
# words — по каким словам искать, если филиал назвал её по-своему: у каждого
# филиала свой сервер и свой справочник, а разбор один и тот же.
KINDS: Dict[str, Dict[str, Any]] = {
    "salmon": {
        "key": "salmon",
        "title": "Разбор лосося",
        "tab": "Лосось",                     # как рыба подписана в переключателе
        "raw_label": "Стейк в разбор",
        "raw_gen": "стейка",                 # «Вес стейка должен быть…»
        "raw_short": "стейк",                # «стейк − нарезка − обрезки»
        "trim_price": TRIM_PRICE,
        "teriyaki": True,
        "names": {
            "raw": ["П/Ф ЛОСОСЬ СТЕЙК"],
            "slice": ["П/Ф НАРЕЗКА ЛОСОСЬ"],
            "trim": ["П/Ф ОБРЕЗКИ ЛОСОСЬ"],
            "waste": ["Отход лосося"],
            "teriyaki": ["П/Ф ЛОСОСЬ ТЕРИЯКИ"],
        },
        "words": {
            "raw": [["лосос"], ["стейк"]],
            "slice": [["лосос"], ["нарезк"]],
            "trim": [["лосос"], ["обрезк"]],
            "waste": [["лосос"], ["отход"]],
            "teriyaki": [["лосос"], ["терияк"]],
        },
    },
    "eel": {
        "key": "eel",
        "title": "Разбор угря",
        "tab": "Угорь",
        "raw_label": "Угорь в разбор",
        "raw_gen": "угря",
        "raw_short": "угорь",
        "trim_price": EEL_TRIM_PRICE,
        "teriyaki": False,
        "names": {
            "raw": ["УГОРЬ ЦЕЛЫЙ", "П/Ф УГОРЬ ЦЕЛЫЙ"],
            "slice": ["П/Ф НАРЕЗКА УГОРЬ", "УГОРЬ НАРЕЗКА", "П/Ф УГОРЬ НАРЕЗКА"],
            "trim": ["П/Ф ОБРЕЗКИ УГОРЬ", "УГОРЬ ОБРЕЗКИ", "П/Ф УГОРЬ ОБРЕЗКИ"],
            "waste": ["Отход угря", "Отход угорь"],
        },
        "words": {
            "raw": [["угор", "угр"], ["цел"]],
            "slice": [["угор", "угр"], ["нарезк"]],
            "trim": [["угор", "угр"], ["обрезк"]],
            "waste": [["угор", "угр"], ["отход"]],
        },
    },
}

DEFAULT_KIND = "salmon"

# Совместимость с прежним кодом: разбор был только лососёвый.
RAW = KINDS["salmon"]["names"]["raw"][0]
TRIM = KINDS["salmon"]["names"]["trim"][0]
SLICE = KINDS["salmon"]["names"]["slice"][0]
WASTE = KINDS["salmon"]["names"]["waste"][0]
TERIYAKI = KINDS["salmon"]["names"]["teriyaki"][0]

# Слова выходов: по ним «просто рыба» отличается от нарезки и обрезков, когда
# вход назван не по шаблону («Угорь unagi 1 кг» вместо «Угорь целый»).
_OUTPUT_WORDS = ("нарезк", "обрезк", "отход", "терияк", "соус", "бонито")


def kind_spec(kind: Optional[str]) -> Dict[str, Any]:
    """Вид разбора по ключу. Неизвестный ключ — лосось: он был первым и он же
    остаётся тем, что открывается по старым ссылкам без ключа."""
    return KINDS.get((kind or "").strip().lower() or DEFAULT_KIND, KINDS[DEFAULT_KIND])


def roles_of(spec: Dict[str, Any]) -> List[str]:
    return ["raw", "slice", "trim", "waste"] + (["teriyaki"] if spec["teriyaki"] else [])


def _norm(s: str) -> str:
    return " ".join((s or "").lower().replace("ё", "е").split())


def _prod(p: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": p.get("id"), "name": p.get("name"), "unit": p.get("unit")}


def find_products(catalog: list, kind: str = DEFAULT_KIND) -> Dict[str, Optional[Dict[str, Any]]]:
    """Ищем позиции разбора по имени: id у каждого филиала свой (свой сервер).

    Три захода, от точного к терпимому: имя из справочника Алиева, затем набор
    слов в любом порядке («Угорь нарезка» и «П/Ф НАРЕЗКА УГОРЬ» — одно и то же),
    и только для входа — «рыба без слов выхода», иначе новый филиал с непривычным
    названием не соберёт акт вообще.
    """
    spec = kind_spec(kind)
    roles = roles_of(spec)
    out: Dict[str, Optional[Dict[str, Any]]] = {r: None for r in roles}
    items = [(_norm(p.get("name") or ""), p) for p in (catalog or [])]

    for role in roles:
        for n, p in items:
            if any(n.startswith(_norm(x)) for x in spec["names"].get(role, [])):
                out[role] = _prod(p)
                break

    for role in roles:
        if out[role] is not None:
            continue
        for n, p in items:
            if all(any(w in n for w in grp) for grp in spec["words"].get(role, [])):
                out[role] = _prod(p)
                break

    if out["raw"] is None:
        fish = spec["words"]["raw"][0]           # слова самой рыбы: «лосос», «угор»
        for n, p in items:
            if any(w in n for w in fish) and not any(b in n for b in _OUTPUT_WORDS):
                out["raw"] = _prod(p)
                break
    return out


def split_act(price_per_kg: float, w_raw: float, w_slice: float,
              w_trim: float = 0.0, trim_price: Optional[float] = None,
              w_teriyaki: float = 0.0, w_fry: float = 0.0,
              kind: str = DEFAULT_KIND) -> Dict[str, Any]:
    """Разбор в весах и деньгах. Только арифметика, в iiko не ходит.

    price_per_kg — цена входа из накладной;
    w_raw        — сколько входа пошло в разбор;
    w_slice      — сколько получилось нарезки (её и взвешивают);
    w_trim       — ВСЕ обрезки, включая те, что потом обжарят;
    w_fry        — сколько обрезков положили жарить;
    w_teriyaki   — сколько терияки сняли со сковороды. Разница с w_fry — ужарка:
                   вес ушёл, деньги остались, поэтому килограмм терияки дороже
                   килограмма обрезков ровно на ужарку. Пусто = жарки не было;
    отход        — остаток веса: вход − нарезка − обрезки. Себестоимость 0 ₸,
                   поэтому отход НЕ уменьшает стоимость нарезки — только вес.
    """
    spec = kind_spec(kind)
    trim_price = float(spec["trim_price"] if trim_price is None else trim_price or 0)
    price_per_kg = float(price_per_kg or 0)
    w_raw, w_slice, w_trim = float(w_raw or 0), float(w_slice or 0), float(w_trim or 0)
    w_ter, w_fry = float(w_teriyaki or 0), float(w_fry or 0)
    if not spec["teriyaki"]:
        w_ter = w_fry = 0.0
    # Жарку записали одним весом — значит, ужарку не мерили: считаем «сколько
    # положили, столько и сняли», это старая форма разбора и она честнее нуля.
    if w_ter > 0 and w_fry <= 0:
        w_fry = w_ter

    if w_raw <= 0:
        return {"ok": False, "error": f"Вес {spec['raw_gen']} должен быть больше нуля"}
    if w_slice < 0 or w_trim < 0 or w_ter < 0 or w_fry < 0:
        return {"ok": False, "error": "Вес не может быть отрицательным"}
    if w_fry > w_trim + 1e-9:
        # Терияки жарят ИЗ обрезков: больше, чем обрезков, туда не положить.
        return {"ok": False,
                "error": "В жарку ушло больше, чем было обрезков — терияки жарят из обрезков"}
    if w_fry > 0 and w_ter <= 0:
        return {"ok": False, "error": "Впиши, сколько терияки сняли со сковороды"}
    if w_ter > w_fry + 1e-9:
        return {"ok": False,
                "error": "Терияки тяжелее обрезков, что пошли в жарку — при жарке вес уходит"}
    w_waste = round(w_raw - w_slice - w_trim, 3)
    if w_waste < 0:
        return {"ok": False,
                "error": f"Нарезка и обрезки вместе тяжелее {spec['raw_gen']} — проверь весы"}

    w_trim_left = round(w_trim - w_fry, 3)          # обрезки, что остались обрезками
    w_shrink = round(w_fry - w_ter, 3)              # ужарка: вес ушёл, деньги нет
    raw_sum = round(price_per_kg * w_raw, 2)
    trim_sum = round(trim_price * w_trim_left, 2)
    ter_sum = round(trim_price * w_fry, 2)          # деньги обрезков, ушедших в жарку
    waste_sum = 0.0                       # отход по нулю: так ведётся учёт
    slice_sum = round(raw_sum - trim_sum - ter_sum, 2)
    if slice_sum < 0:
        return {"ok": False,
                "error": f"Обрезки по {trim_price:.0f} ₸ дороже всего {spec['raw_gen']} — проверь цену"}
    per_kg = round(slice_sum / w_slice, 2) if w_slice > 0 else 0.0
    ter_per_kg = round(ter_sum / w_ter, 2) if w_ter > 0 else 0.0

    return {
        "ok": True,
        "kind": spec["key"],
        "raw": {"weight": w_raw, "price_per_kg": price_per_kg, "sum": raw_sum},
        "slice": {"weight": w_slice, "price_per_kg": per_kg, "sum": slice_sum},
        "trim": {"weight": w_trim_left, "price_per_kg": trim_price, "sum": trim_sum},
        "teriyaki": {"weight": w_ter, "price_per_kg": ter_per_kg, "sum": ter_sum,
                     "from_trim": w_fry, "shrink": w_shrink},
        "waste": {"weight": w_waste, "price_per_kg": 0.0, "sum": waste_sum},
        "trim_price": trim_price,
        "slice_pct": round(w_slice / w_raw * 100, 1),
        "trim_pct": round(w_trim_left / w_raw * 100, 1),
        "teriyaki_pct": round(w_ter / w_raw * 100, 1),
        "fry_pct": round(w_fry / w_raw * 100, 1),
        # выход жарки: сколько процентов сковорода вернула. Ниже — больше ужарка
        "teriyaki_yield_pct": round(w_ter / w_fry * 100, 1) if w_fry > 0 else 0.0,
        "shrink_pct": round(w_shrink / w_fry * 100, 1) if w_fry > 0 else 0.0,
        "waste_pct": round(w_waste / w_raw * 100, 1),
        "check": round(trim_sum + ter_sum + waste_sum + slice_sum, 2),  # = стоимости входа
    }


# Разбор был только лососёвым — старое имя осталось рабочим.
split_salmon = split_act


# ── Свод за период ───────────────────────────────────────────────────────────
# Отдельно от split_act и без базы: складывать зафиксированные разборы —
# другая задача, и проверять её надо на голых числах.

def summarize(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Итог по пачке разборов — то, что администратор заносит в iiko одним актом.

    Проценты и себестоимость — средневзвешенные, а не среднее по актам: разбор
    на 40 кг и разбор на 2 кг не имеют одинакового веса в оценке филиала.
    """
    n = 0
    raw = slice_w = trim = waste = ter = fry = 0.0
    raw_sum = slice_sum = trim_sum = ter_sum = 0.0
    for r in rows:
        n += 1
        w_raw = float(r.get("weight_raw") or 0)
        w_slice = float(r.get("weight_slice") or 0)
        w_trim = float(r.get("weight_trim") or 0)
        w_ter = float(r.get("weight_teriyaki") or 0)
        # в старых разборах ужарку не писали: сколько сняли, столько и клали
        w_fry = float(r.get("weight_fry") or 0) or w_ter
        raw += w_raw
        slice_w += w_slice
        trim += w_trim
        ter += w_ter
        fry += w_fry
        waste += float(r.get("weight_waste") or 0)
        price = float(r.get("price_per_kg") or 0)
        tprice = float(r.get("trim_price") or TRIM_PRICE)
        raw_sum += price * w_raw
        trim_sum += tprice * w_trim
        ter_sum += tprice * w_fry
        # терияки оплачен обрезочной ценой того, что ушло в жарку, и на нарезку
        # не влияет: деньги переезжают внутри обрезков
        slice_sum += price * w_raw - tprice * w_trim - tprice * w_fry
    return {
        "acts": n,
        "raw": round(raw, 3), "slice": round(slice_w, 3),
        "trim": round(trim, 3), "waste": round(waste, 3),
        "teriyaki": round(ter, 3), "fry": round(fry, 3),
        "shrink": round(fry - ter, 3),
        "raw_sum": round(raw_sum, 2), "slice_sum": round(slice_sum, 2),
        "trim_sum": round(trim_sum, 2), "teriyaki_sum": round(ter_sum, 2),
        "slice_price": round(slice_sum / slice_w, 2) if slice_w > 0 else 0.0,
        "teriyaki_price": round(ter_sum / ter, 2) if ter > 0 else 0.0,
        "raw_price": round(raw_sum / raw, 2) if raw > 0 else 0.0,
        "slice_pct": round(slice_w / raw * 100, 1) if raw > 0 else 0.0,
        "trim_pct": round(trim / raw * 100, 1) if raw > 0 else 0.0,
        "teriyaki_pct": round(ter / raw * 100, 1) if raw > 0 else 0.0,
        "teriyaki_yield_pct": round(ter / fry * 100, 1) if fry > 0 else 0.0,
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
