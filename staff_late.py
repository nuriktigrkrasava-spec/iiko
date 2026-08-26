"""Опоздания сотрудников: приход из явок iiko против эталона старта смены.

Эталон гибридный (решение владельца 25.08):
  • по умолчанию — время старта смены ФИЛИАЛА (утро/вечер), задаётся один раз;
  • если на сотрудника в этот день стоит плановая смена — она перебивает;
  • допуск grace минут: пришёл в его пределах — вовремя, а не «опоздал на 3».

Чего тут намеренно НЕТ:
  • прогулов. Отличить выходной от прогула по одним явкам нельзя, а ложный
    «прогул» в оценке филиала дороже пропущенного настоящего;
  • ухода раньше и переработок — это отдельный разговор про зарплату.

Модуль чистый: ни iiko, ни БД. Всё, что нужно, приходит аргументами — поэтому
логику можно проверить тестами, не поднимая ни сервера, ни базы.
"""
from typing import Any, Dict, Iterable, List, Optional, Tuple

DAY = 24 * 60
DEFAULT_GRACE_MIN = 10
# Больше этого — уже не опоздание, а смена, о которой мы не знаем. Проверено на
# живых явках Алиева: при одном старте 11:00 вечерние сотрудники (19:11, 21:47)
# получали «опоздание» на 8–10 часов и в одиночку топили оценку филиала. Три
# часа опоздания в ресторане не бывает — бывает вторая смена. Такие приходы
# помечаем «вне графика»: они видны на экране, но в знаменатель не идут.
# Лечится по-настоящему тем, что филиал заводит второй старт смены.
MAX_LATE_MIN = 120
# Время старта по умолчанию, пока филиал своё не задал. Утро — открытие кухни,
# вечер — пересменка. Оба перебиваются и настройкой филиала, и графиком.
DEFAULT_STARTS = ("09:00", "16:00")


def to_min(hhmm: str) -> Optional[int]:
    """'09:30' → 570. Мусор → None, а не исключение: явки приходят из чужой системы."""
    try:
        h, m = str(hhmm).strip().split(":")[:2]
        v = int(h) * 60 + int(m)
    except Exception:
        return None
    return v if 0 <= v < DAY else None


def _circle_gap(a: int, b: int) -> int:
    """Расстояние между временами по 24-часовому кругу: 23:50 и 00:10 — 20 минут,
    а не 1420. Иначе ночная смена всегда цеплялась бы к утреннему старту."""
    d = abs(a - b) % DAY
    return min(d, DAY - d)


def _lateness(arrival_m: int, planned_m: int) -> int:
    """На сколько минут позже плана. По кругу: план 23:00, приход 23:20 → 20;
    план 09:00, приход 08:50 → 0 (пришёл раньше — не опоздание)."""
    d = (arrival_m - planned_m) % DAY
    return d if d <= DAY // 2 else 0


def pick_planned(arrival: str,
                 shift_start: Optional[str] = None,
                 branch_starts: Iterable[str] = ()) -> Optional[str]:
    """Эталон для этого прихода: график сотрудника, иначе ближайший старт филиала.

    «Ближайший» — по кругу и по модулю: сотрудник вечерней смены, пришедший в
    15:40, сверяется с 16:00, а не с 09:00, и считается пришедшим вовремя.
    """
    if shift_start and to_min(shift_start) is not None:
        return shift_start
    a = to_min(arrival)
    if a is None:
        return None
    cands = [s for s in branch_starts if to_min(s) is not None]
    if not cands:
        return None
    return min(cands, key=lambda s: _circle_gap(a, to_min(s)))  # type: ignore[arg-type]


def late_rows(arrivals: List[Dict[str, Any]],
              schedule: Optional[Dict[Tuple[str, str], str]] = None,
              branch_starts: Iterable[str] = DEFAULT_STARTS,
              grace_min: int = DEFAULT_GRACE_MIN,
              max_late_min: int = MAX_LATE_MIN) -> List[Dict[str, Any]]:
    """Явки → строки «кто во сколько пришёл и опоздал ли».

    arrivals — строки _attendance_journal (employee_id, name, date, start).
    На сотрудника за день берём САМЫЙ РАННИЙ приход: терминал часто пишет
    несколько интервалов (разные роли), и поздний из них — не опоздание.
    schedule — {(employee_id, date): 'HH:MM'} плановое начало смены.
    """
    sched = schedule or {}
    starts = list(branch_starts or ())
    first: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for a in arrivals:
        eid, day, start = a.get("employee_id"), a.get("date"), a.get("start")
        if not eid or not day or to_min(start) is None:
            continue
        key = (eid, day)
        prev = first.get(key)
        if prev is None or to_min(start) < to_min(prev["start"]):  # type: ignore[operator]
            first[key] = a

    out: List[Dict[str, Any]] = []
    for (eid, day), a in first.items():
        arrival = a["start"]
        planned = pick_planned(arrival, sched.get((eid, day)), starts)
        if planned is None:
            # Эталона нет — не «вовремя» и не «опоздал»: критерий по этому
            # человеку молчит, а не выдумывает результат.
            out.append({"employee_id": eid, "name": a.get("name") or eid[:8], "date": day,
                        "arrival": arrival, "planned": None, "late_min": 0,
                        "status": "noplan"})
            continue
        late = _lateness(to_min(arrival), to_min(planned))  # type: ignore[arg-type]
        if late > max_late_min:
            # Ни к одному известному старту не подходит — молчим, а не выдумываем
            # опоздание в полсмены.
            out.append({"employee_id": eid, "name": a.get("name") or eid[:8], "date": day,
                        "arrival": arrival, "planned": None, "late_min": 0,
                        "status": "noplan"})
            continue
        out.append({"employee_id": eid, "name": a.get("name") or eid[:8], "date": day,
                    "arrival": arrival, "planned": planned,
                    "late_min": late if late > grace_min else 0,
                    "status": "late" if late > grace_min else "ontime"})
    out.sort(key=lambda r: (r["date"], r["arrival"], r["name"]))
    return out


def summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Сводка для экрана и для оценки филиала. Строки без эталона в знаменатель
    не идут: иначе филиал без заданного старта смены выглядел бы идеальным."""
    counted = [r for r in rows if r["status"] in ("late", "ontime")]
    late = [r for r in counted if r["status"] == "late"]
    return {
        "total": len(counted),
        "late": len(late),
        "late_pct": round(len(late) / len(counted) * 100, 1) if counted else None,
        "late_minutes": sum(r["late_min"] for r in late),
        "noplan": len(rows) - len(counted),
    }
