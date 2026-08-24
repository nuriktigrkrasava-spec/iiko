"""Оценка филиала 0–100 и критерии сдачи чек-листа по зонам.

Принципы (по просьбе владельца):
  • оценка НЕ зависит от задач — иначе филиал поднимался бы, просто закрывая
    формулировки, а не наводя порядок;
  • каждый критерий логичен и проверяем: факт против нормы, а не «ощущение»;
  • чего нет в данных — не штрафуем: критерий выпадает, вес перераспределяется
    на остальные. Филиал без подключённых отзывов не должен быть «плохим»;
  • веса лежат тут, одним местом — менять оценку можно, не трогая экраны.
"""
from typing import Any, Dict, List, Optional, Tuple

# Что снимать в каждой зоне. Список короткий намеренно: длинный не выполняют.
ZONE_CRITERIA: Dict[str, Dict[str, Any]] = {
    "hall": {
        "label": "Зал",
        "items": ["Пол под столами и у входа", "Столы и стулья без липкости и крошек",
                  "Витрина и стекло без разводов", "Урна не переполнена"],
    },
    "kitchen": {
        "label": "Кухня",
        "items": ["Рабочие поверхности пустые и вытертые", "Плита и вытяжка без жира",
                  "Холодильник: продукты закрыты и подписаны", "Пол у линии и под столами",
                  "Раковина без посуды"],
    },
    "wc": {
        "label": "Санузел",
        "items": ["Унитаз и раковина чистые", "Пол сухой", "Есть мыло и бумага",
                  "Зеркало без разводов", "Урна не переполнена"],
    },
}

# Критерии оценки: вес и как считается. Меняются здесь и только здесь.
# Состав задан владельцем: деньги (фудкост, списания), рост выручки, скорость
# доставки и дисциплина по чек-листам. Задач тут нет намеренно — оценка не
# должна расти от того, что закрыли формулировку.
WEIGHTS = {
    "revenue": 25,      # рост выручки неделя к неделе
    "foodcost": 25,     # факт против нормы
    "writeoffs": 20,    # порча и списания
    "late": 20,         # опоздания доставки — за их снижение
    "checklist": 10,    # сдают ли чистоту вовремя
}


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def _revenue(b: Dict[str, Any]) -> Optional[float]:
    """Рост выручки неделя к неделе: −10% и хуже — ноль, +10% и лучше — единица."""
    ch = b.get("changes")
    if not isinstance(ch, dict) or ch.get("revenue_pct") is None:
        return None
    return _clamp((float(ch["revenue_pct"]) + 10) / 20)


def _late(b: Dict[str, Any]) -> Optional[float]:
    """Опоздания доставки: доля опоздавших заказов. 0% — единица, 15% — ноль."""
    lt = b.get("late")
    if not isinstance(lt, dict):
        return None
    pct = lt.get("late_pct")
    if pct is None:
        total, late_n = lt.get("total"), lt.get("late")
        if not total:
            return None
        pct = float(late_n or 0) / float(total) * 100
    return _clamp(1 - float(pct) / 15)


def _foodcost(b: Dict[str, Any]) -> Optional[float]:
    fc = b.get("foodcost")
    if not isinstance(fc, dict) or not fc.get("fact_pct") or not fc.get("norm_pct"):
        return None
    if float(fc.get("coverage") or 0) < 60:      # мало техкарт → цифра врёт
        return None
    over = float(fc["fact_pct"]) - float(fc["norm_pct"])
    return _clamp(1 - over / 10)


def _writeoffs(b: Dict[str, Any]) -> Optional[float]:
    wo = b.get("writeoffs")
    if not isinstance(wo, dict):
        return None
    pct = wo.get("pct")
    if pct is None:
        return None
    return _clamp(1 - (float(pct) - 5) / 10)


def _checklist(ch: Dict[str, Any]) -> Optional[float]:
    if not ch:
        return None
    done, missed = int(ch.get("done") or 0), abs(int(ch.get("missed") or 0))
    if done + missed == 0:
        return None
    return _clamp(done / (done + missed))


def score_branch(signals: Optional[Dict[str, Any]],
                 checklist: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Оценка филиала. Возвращает балл и разбор по критериям — чтобы владелец
    видел, из чего он сложился, а не верил числу на слово."""
    b = signals or {}
    parts: List[Tuple[str, str, Optional[float], int]] = [
        ("revenue", "Рост выручки", _revenue(b), WEIGHTS["revenue"]),
        ("foodcost", "Фудкост", _foodcost(b), WEIGHTS["foodcost"]),
        ("writeoffs", "Списания", _writeoffs(b), WEIGHTS["writeoffs"]),
        ("late", "Опоздания", _late(b), WEIGHTS["late"]),
        ("checklist", "Чек-листы", _checklist(checklist or {}), WEIGHTS["checklist"]),
    ]
    have = [(k, label, v, w) for k, label, v, w in parts if v is not None]
    if not have:
        return {"score": None, "criteria": [
            {"key": k, "label": label, "value": None, "weight": w} for k, label, _v, w in parts]}
    total_w = sum(w for _k, _l, _v, w in have)
    score = round(sum(v * w for _k, _l, v, w in have) / total_w * 100)
    return {
        "score": int(score),
        "criteria": [
            {"key": k, "label": label, "value": None if v is None else round(v * 100),
             "weight": w, "counted": v is not None}
            for k, label, v, w in parts
        ],
    }
