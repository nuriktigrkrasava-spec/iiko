"""«Гора» — задачи филиалам, баллы и уровень, плюс чек-листы из чата.

Доступ по личной подписанной ссылке, как у виджета и журналов: `/m/{token}`,
где токен = uid + подпись на общем ENCRYPTION_KEY. Владелец видит все свои
филиалы, управляющий — только свой. Отдельного входа не заводим.

Роли:
  • владелец   — ему принадлежат рестораны (`restaurants.telegram_id`);
                 ТОЛЬКО он ставит задачи (ИИ предлагает, он подтверждает);
  • управляющий — привязан к филиалу в `branch_managers`; задачу может закрыть,
                 создать — нет.

Баллы (согласовано с владельцем):
  задача  — быстро 10, средне 25, долго 50;
  чек-лист — +1 за сданный слот, −1 за пропущенный.
Уровень на горе — 40 отметок по 25 баллов: три закрытые задачи не поднимают на
вершину, подъём должен быть виден месяцами, а штрафы тянут вниз.
"""
import base64
import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import scoring as S
from database import (
    get_restaurants, get_owned_restaurants, get_branch_managers,
    add_branch_task, close_branch_task, get_branch_tasks, TASK_POINTS,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# ── Гора: 40 отметок по 10 баллов, вершина — 400 ─────────────────────────────
# Считано по потолку месяца: идеальные чек-листы дают 360 баллов, задачи ещё
# 100–400. При прежней вершине в 1000 её не достигал никто и никогда — цель, до
# которой нельзя дойти, азарта не создаёт. 400 берётся месяцем очень хорошей
# работы, но не даром.
STEP_POINTS = int(os.getenv("MOUNTAIN_STEP", "10"))
STEPS = int(os.getenv("MOUNTAIN_STEPS", "40"))

# Путь наверх — не сплошная линейка, а участки с именами: видно, где ты и что
# следующее. Порог — в баллах, подъём идёт слева направо змейкой (см. фронт).
STAGES = [
    (0,   "Подножие"),
    (80,  "Тропа"),
    (160, "Первый лагерь"),
    (240, "Скальный пояс"),
    (320, "Штурмовой лагерь"),
    (400, "Вершина"),
]


def _stage(points: int) -> Dict[str, Any]:
    """Участок пути и сколько до следующего — чтобы подъём читался этапами."""
    points = max(0, points)          # минус по баллам — это подножие, а не вершина
    cur = STAGES[0]
    nxt = STAGES[1] if len(STAGES) > 1 else None
    for i, (need, name) in enumerate(STAGES):
        if points >= need:
            cur = (need, name)
            nxt = STAGES[i + 1] if i + 1 < len(STAGES) else None
    return {"name": cur[1], "from": cur[0],
            "next": nxt[1] if nxt else None,
            "to_next": max(0, nxt[0] - points) if nxt else 0,
            "index": [n for n, _ in STAGES].index(cur[0]),
            "count": len(STAGES)}
CHECKLIST_POINT = 1        # сданный слот
CHECKLIST_PENALTY = -1     # пропущенный


def _secret() -> bytes:
    return (os.getenv("WIDGET_SECRET") or os.getenv("ENCRYPTION_KEY") or "iiko-widget-fallback").encode()


def _sign(uid: int) -> str:
    mac = hmac.new(_secret(), f"mountain:{uid}".encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode().rstrip("=")[:20]


def token_for(uid: int) -> str:
    """Ссылка ВЛАДЕЛЬЦА: подписанный telegram id. Одинакова локально и на
    проде — общий ENCRYPTION_KEY, без обращения к базе."""
    return f"{uid}.{_sign(uid)}"


def _sign_org(org_id: str) -> str:
    mac = hmac.new(_secret(), f"mountain-org:{org_id}".encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode().rstrip("=")[:20]


def token_for_org(org_id: str) -> str:
    """Ссылка ФИЛИАЛА — подписанный organization_id.

    Раньше ссылка выдавалась человеку: подписывался telegram id управляющего.
    Из-за этого филиал без управляющего в боте ссылку получить не мог (семь из
    двадцати трёх), а права на сайте зависели от таблиц бота. Сайт — это сайт:
    ссылка привязана к филиалу, телеграм для неё не нужен вообще.
    """
    return f"b{org_id}.{_sign_org(org_id)}"


def org_from_token(token: str) -> Optional[str]:
    """organization_id из ссылки филиала. None — это не ссылка филиала."""
    if not token or not token.startswith("b") or "." not in token:
        return None
    org, sig = token[1:].rsplit(".", 1)
    if not org:
        return None
    return org if hmac.compare_digest(sig.encode("utf-8", "ignore"),
                                      _sign_org(org).encode()) else None


def uid_from_token(token: str) -> Optional[int]:
    if not token or "." not in token:
        return None
    uid_s, sig = token.rsplit(".", 1)
    try:
        uid = int(uid_s)
    except ValueError:
        return None
    return uid if hmac.compare_digest(sig.encode("utf-8", "ignore"), _sign(uid).encode()) else None


# Какие филиалы участвуют. Служебные организации (КЦ, ЦЕХ, ОФИС, РОЯЛТИ) — не
# точки продаж: задачи и баллы по ним бессмысленны, а список раздувают до 30
# строк. Список настраивается: MOUNTAIN_ONLY — что оставить, MOUNTAIN_SKIP — что
# выкинуть; оба ищутся в названии филиала без учёта регистра.
ONLY = [x.strip().lower() for x in os.getenv("MOUNTAIN_ONLY", "астана").split(",") if x.strip()]
SKIP = [x.strip().lower() for x in os.getenv("MOUNTAIN_SKIP", "кц,цех,офис,роялти").split(",") if x.strip()]


def _is_branch(name: str) -> bool:
    n = (name or "").lower()
    if ONLY and not any(o in n for o in ONLY):
        return False
    # «кц»/«цех» проверяем как отдельные слова: иначе «Кцентр» и «Цеховая» тоже отпадут
    words = set(n.replace("(", " ").replace(")", " ").replace(",", " ").split())
    return not any(sk in words or (len(sk) > 4 and sk in n) for sk in SKIP)


def scope_of_token(token: str) -> Dict[str, Any]:
    """Что открывает эта ссылка. Единственная точка разбора доступа на сайте.

      • ссылка ФИЛИАЛА (`b{org}.{подпись}`) — ровно один филиал. Телеграм для
        неё не нужен: филиалу не обязательно иметь управляющего в боте;
      • ссылка ВЛАДЕЛЬЦА (`{uid}.{подпись}`) — вся его сеть.

    `org` — чем ограничен доступ (у владельца None), `uid` — от чьего имени
    ходить в iiko (у ссылки филиала это владелец филиала: своих кредов у
    управляющего нет, см. грабли из 234.md).
    """
    org = org_from_token(token)
    if org:
        from database import get_db
        conn = get_db()
        row = conn.execute("SELECT organization_name FROM restaurants "
                           "WHERE organization_id = ? ORDER BY id LIMIT 1", (org,)).fetchone()
        conn.close()
        if not row:
            return {"role": None, "branches": [], "org": None, "uid": 0, "valid": False}
        return {"role": "manager", "org": org, "uid": _owner_of(org), "valid": True,
                "branches": [{"organization_id": org, "name": row[0] or "Филиал"}]}
    uid = uid_from_token(token)
    if not uid:
        # подпись не сошлась — ссылки не существует
        return {"role": None, "branches": [], "org": None, "uid": 0, "valid": False}
    sc = _scope(uid)
    # valid = подпись верна. Роли при этом может не быть: uid, у которого нет
    # ни своих филиалов, ни назначения управляющим. Это «прав нет» (403), а не
    # «ссылки нет» (404) — счётчик прочтений отличает одно от другого.
    sc["org"], sc["uid"], sc["valid"] = None, uid, True
    return sc


def _scope(uid: int) -> Dict[str, Any]:
    """Что видит этот uid: владелец — свои филиалы, управляющий — свой."""
    # ВЛАДЕНИЕ, а не доступ. Две ловушки, обе живые:
    # 1. get_restaurants отдаёт и филиалы, где человек лишь управляющий;
    # 2. один филиал бывает заведён НЕСКОЛЬКО раз под разными telegram id —
    #    управляющему дали креды владельца, и он подключил через бота всю сеть.
    #    Из-за этого двое управляющих открывали доску как владельцы: видели все
    #    девять филиалов, могли ставить задачи любому и слать рассылку сети.
    # Владелец — тот, чья регистрация филиала ПЕРВАЯ.
    mine_orgs = _owned_org_ids(uid)
    own = [r for r in (get_owned_restaurants(uid) or [])
           if r.get("organization_id") in mine_orgs]
    if own:
        return {"role": "owner", "branches": [
            {"organization_id": r["organization_id"],
             "name": r.get("organization_name") or "Филиал"} for r in own
            if _is_branch(r.get("organization_name") or "")]}
    mine = [m for m in get_branch_managers() if int(m.get("telegram_id") or 0) == uid]
    if not mine:
        return {"role": None, "branches": []}
    # имя филиала берём из справочника ресторанов: у записи управляющего лежит
    # его собственное имя, и без этого филиал подписывался «Управляющий такой-то»
    from database import get_db
    conn = get_db()
    names = {r[0]: r[1] for r in conn.execute(
        "SELECT organization_id, organization_name FROM restaurants").fetchall()}
    conn.close()
    return {"role": "manager", "branches": [
        {"organization_id": m["organization_id"],
         "name": names.get(m["organization_id"]) or m.get("name") or "Филиал"} for m in mine]}


def _month_start() -> str:
    now = datetime.now()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()


def _level(points: int) -> Dict[str, Any]:
    """Баллы → отметка на горе. Ниже нуля не опускаемся, выше вершины не растём."""
    step = max(0, min(STEPS, points // STEP_POINTS))
    return {"step": step, "steps": STEPS,
            "height_pct": round(step / STEPS * 100, 1),
            "summit": STEPS * STEP_POINTS,
            "stage": _stage(points),
            "to_next": max(0, (step + 1) * STEP_POINTS - points) if step < STEPS else 0}


def _checklist_points_own(prog: Dict[str, Dict[str, int]], org: str) -> Dict[str, int]:
    """Баллы за чек-листы по НАШИМ сдачам: сдал слот +1, пропустил −1.
    Доску из чата больше не спрашиваем — бота не будет."""
    p = prog.get(org) or {}
    done, missed = int(p.get("done") or 0), abs(int(p.get("missed") or 0))
    return {"done": done, "missed": -missed, "expect": int(p.get("expect") or 0),
            "points": done * CHECKLIST_POINT - missed * abs(CHECKLIST_PENALTY)}


# Показатели для ОЦЕНКИ филиала доска собирает сама. Раньше она читала кэш
# ассистента: пока никто не нажал «Обновить», критериев не было, вес уходил на
# двух выживших — и филиал получал 100 из 100 по выручке и списаниям. Кэш на
# час: сбор по девяти филиалам идёт десятки секунд, на каждый заход его не гоняем.
SCORE_TTL = timedelta(hours=1)
_score_key = lambda uid: "mountain-score:%d" % int(uid)


async def _collect_score_signals(uid: int, branches: List[Dict[str, str]]) -> Dict[str, Dict[str, Any]]:
    """Динамика выручки и заказов, опоздания доставок и опоздания сотрудников —
    по каждому филиалу. Сбой одного филиала не роняет остальные."""
    import asyncio as _aio
    import api
    month_from = _month_start()[:10]
    today = datetime.now().date().isoformat()
    sem = _aio.Semaphore(4)

    async def one(b: Dict[str, str]):
        org = b["organization_id"]
        # Креды — ПО ФИЛИАЛУ: у управляющего своих ресторанов нет, и запрос от
        # его имени подставил бы демо-клиента (грабли из 234.md).
        owner = api._owner_user_of(org)
        if not owner:
            return b["name"], None
        sig: Dict[str, Any] = {}
        async with sem:
            try:
                sig["changes"] = await api._week_over_week(org, owner)
            except Exception as e:
                logger.warning(f"[score] дельты {b['name']}: {e!r}")
            try:
                sig["late"] = api._late_signal(
                    await api.late_deliveries(org, "month", None, None, 1, owner))
            except Exception as e:
                logger.warning(f"[score] опоздания заказов {b['name']}: {e!r}")
            try:
                sig["rating"] = api._rating_signal(await api.branch_reviews(org, owner))
            except Exception as e:
                logger.warning(f"[score] рейтинги {b['name']}: {e!r}")
            try:
                sig["shifts"] = api._shifts_signal(
                    await api.cashshifts_pending(org, 30, owner))
            except Exception as e:
                logger.warning(f"[score] непринятые смены {b['name']}: {e!r}")
            try:
                sig["plan"] = await api._plan_exec_signal(org, owner)
            except Exception as e:
                logger.warning(f"[score] выполнение плана {b['name']}: {e!r}")
            try:
                # Заодно наполняет staff_late в базе — экран и уведомления
                # читают уже посчитанное, а не ходят в iiko второй раз.
                sl = await api._staff_late_for(org, org, month_from, today, owner)
                # Филиал, который не задал свой старт смены, судим по общему
                # 09:00/16:00 — а он почти всегда не тот (Алиева открывается в
                # 11:00). Такой критерий не «ноль», а молчание: иначе оценка
                # падает не за опоздания, а за ненастроенность.
                if sl and sl["configured"] and sl["summary"]["total"]:
                    sig["staff_late"] = sl["summary"]
            except Exception as e:
                logger.warning(f"[score] опоздания сотрудников {b['name']}: {e!r}")
        return b["name"], sig

    out: Dict[str, Dict[str, Any]] = {}
    for name, sig in await _aio.gather(*(one(b) for b in branches)):
        if sig is not None:
            out[name] = sig
    api._set_cached(_score_key(uid), out, ttl=SCORE_TTL)
    return out


def _signals_by_branch(uid: int) -> Dict[str, Dict[str, Any]]:
    """Готовые показатели из кэша. Пусто — значит сбор ещё не проходил."""
    import api
    return api._get_cached(_score_key(uid), ttl=SCORE_TTL) or {}


def _owner_of(org_id: str) -> int:
    """Кому принадлежит филиал. Нужен, чтобы управляющий видел рейтинг СВОЕЙ
    сети, а не всех клиентов платформы.

    Владелец — тот, кто зарегистрировал филиал ПЕРВЫМ. Порядок задан явно:
    один и тот же филиал бывает заведён несколько раз под разными telegram id
    (управляющему дали креды владельца, и он подключил всю сеть через бота), а
    без ORDER BY «первый» зависел бы от того, как SQLite сегодня вернёт строки.
    """
    from database import get_db
    conn = get_db()
    row = conn.execute("SELECT telegram_id FROM restaurants WHERE organization_id = ? "
                       "ORDER BY id LIMIT 1", (org_id,)).fetchone()
    conn.close()
    return int(row[0]) if row and row[0] else 0


def _owned_org_ids(uid: int) -> set:
    """Филиалы, где uid — ПЕРВАЯ регистрация, то есть настоящий владелец.

    Одним запросом, а не _owner_of по каждому: филиалов два десятка.
    """
    from database import get_db
    conn = get_db()
    rows = conn.execute(
        "SELECT organization_id, telegram_id FROM restaurants r1 WHERE id = "
        "(SELECT MIN(id) FROM restaurants r2 WHERE r2.organization_id = r1.organization_id)"
    ).fetchall()
    conn.close()
    return {r[0] for r in rows if int(r[1] or 0) == int(uid)}


def _all_branches(owner_uid: int) -> List[Dict[str, str]]:
    """Точки сети ОДНОГО владельца (без служебных организаций).

    Раньше здесь был SELECT по всей таблице restaurants — она многоарендная, и
    в рейтинг попал бы чужой клиент, у которого филиал назван «Астана…».
    Дедуплицируем по organization_id: одна точка бывает заведена под разными
    аккаунтами и иначе появлялась на горе дважды.
    """
    from database import get_db
    conn = get_db()
    rows = conn.execute("SELECT organization_id, organization_name FROM restaurants "
                        "WHERE telegram_id = ?", (int(owner_uid),)).fetchall()
    conn.close()
    seen: Dict[str, str] = {}
    for org, name in rows:
        if org and org not in seen and _is_branch(name or ""):
            seen[org] = name or ""
    return [{"organization_id": o, "name": n} for o, n in seen.items()]


def _network_ranking(owner_uid: int) -> List[Dict[str, Any]]:
    """Место каждого филиала сети по баллам месяца. Считается по базе, без iiko."""
    from database import checklist_progress
    branches = _all_branches(owner_uid)
    orgs = [b["organization_id"] for b in branches]
    tasks = get_branch_tasks(orgs, since=_month_start())
    now_hm = datetime.now().strftime("%H:%M")
    passed = sum(1 for sl in SLOTS if sl <= now_hm)
    prog = checklist_progress(orgs, _month_start()[:10],
                              datetime.now().date().isoformat(), slots_passed_today=passed)
    out = []
    for b in branches:
        org = b["organization_id"]
        done = [t for t in tasks if t["organization_id"] == org and t["status"] == "done"]
        ch = _checklist_points_own(prog, org)
        pts = sum(int(t["points"] or 0) for t in done) + ch["points"]
        out.append({**b, "points": pts, "level": _level(pts), "tasks_done": len(done)})
    out.sort(key=lambda r: -r["points"])
    for i, r in enumerate(out):
        r["place"] = i + 1
    return out


def _ranking_with_scores(ranking: List[Dict[str, Any]],
                         signals: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Дописывает в рейтинг оценку каждого филиала.

    Управляющему нужен именно этот срез: сравнить себя с другими одним
    взглядом. Разбор по критериям в рейтинге не даём — чужие слабые места
    его не касаются, да и владелец их видит у себя.
    """
    from database import checklist_progress
    orgs = [r["organization_id"] for r in ranking]
    now_hm = datetime.now().strftime("%H:%M")
    passed = sum(1 for sl in SLOTS if sl <= now_hm)
    prog = checklist_progress(orgs, _month_start()[:10],
                              datetime.now().date().isoformat(), slots_passed_today=passed)
    out = []
    for r in ranking:
        ch = _checklist_points_own(prog, r["organization_id"])
        sc = S.score_branch(signals.get(r["name"]), ch)
        out.append({**r, "score": sc["score"], "counted": sc.get("counted")})
    return out


def _board_for(uid: int, journals: Optional[Dict[str, Any]] = None,
               signals: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    sc = _scope(uid)
    if not sc["role"]:
        return {"error": "нет доступа"}
    orgs = [b["organization_id"] for b in sc["branches"]]
    tasks = get_branch_tasks(orgs, since=_month_start())
    journals = journals or {}
    signals = _signals_by_branch(uid) if signals is None else signals
    from database import checklist_progress
    now_hm = datetime.now().strftime("%H:%M")
    passed = sum(1 for sl in SLOTS if sl <= now_hm)      # какие слоты уже прошли сегодня
    progress = checklist_progress(orgs, _month_start()[:10],
                                  datetime.now().date().isoformat(), slots_passed_today=passed)

    rows = []
    for b in sc["branches"]:
        org = b["organization_id"]
        mine = [t for t in tasks if t["organization_id"] == org]
        done = [t for t in mine if t["status"] == "done"]
        task_points = sum(int(t["points"] or 0) for t in done)
        ch = _checklist_points_own(progress, org)
        total = task_points + ch["points"]
        rows.append({
            **b,
            "tasks_open": [t for t in mine if t["status"] == "open"],
            "tasks_done": len(done),
            "task_points": task_points,
            "checklist": ch,
            "points": total,
            "level": _level(total),
            **S.score_branch(signals.get(b["name"]), ch),
        })
    rows.sort(key=lambda r: -r["points"])

    # Рейтинг сети виден ВСЕМ, включая управляющих: соревнование без чужих
    # результатов не работает. Задачи и чек-листы при этом остаются своими.
    owner_uid = uid if sc["role"] == "owner" else _owner_of(orgs[0] if orgs else "")
    ranking = _ranking_with_scores(_network_ranking(owner_uid), signals)
    return {"role": sc["role"], "month": datetime.now().strftime("%Y-%m"),
            "ranking": ranking,
            # true — показатели ещё собираются, оценка появится через минуту
            "score_pending": not signals,
            "scale": {"tasks": TASK_POINTS, "checklist_done": CHECKLIST_POINT,
                      "checklist_missed": CHECKLIST_PENALTY,
                      "step_points": STEP_POINTS, "steps": STEPS},
            "branches": rows}


async def recompute_all_scores() -> int:
    """Ночной пересчёт оценок по всем владельцам сети. Кладёт снимок дня в
    branch_scores — из него потом растут вторничная средняя и динамика.

    Считаем по владельцам, а не по филиалам: кэш показателей ключуется на uid,
    и один проход на владельца греет его же доску.
    """
    from database import get_db, save_branch_score
    import api
    conn = get_db()
    uids = [int(r[0]) for r in conn.execute(
        "SELECT DISTINCT telegram_id FROM restaurants WHERE telegram_id IS NOT NULL").fetchall()]
    conn.close()
    day = datetime.now().date().isoformat()
    saved = 0
    for uid in uids:
        sc = _scope(uid)
        if sc["role"] != "owner" or not sc["branches"]:
            continue
        try:
            signals = await _collect_score_signals(uid, sc["branches"])
        except Exception as e:
            logger.warning(f"[scores] сбор для {uid}: {e!r}")
            continue
        board = _board_for(uid, signals=signals)
        for b in board.get("branches") or []:
            save_branch_score(b["organization_id"], day, b.get("score"),
                              b.get("counted") or 0, b.get("criteria"))
            saved += 1
    return saved


def weekly_score_lines(orgs: List[Dict[str, str]]) -> List[str]:
    """Строки вторничной сводки: средняя за 7 дней, место и куда движется.

    Отдельной функцией, чтобы её можно было проверить тестом, не поднимая
    ни телеграма, ни планировщика.
    """
    from database import branch_score_average
    ids = [b["organization_id"] for b in orgs]
    today = datetime.now().date()
    cur = branch_score_average(ids, (today - timedelta(days=7)).isoformat(), today.isoformat())
    prev = branch_score_average(ids, (today - timedelta(days=14)).isoformat(),
                                (today - timedelta(days=8)).isoformat())
    rows = [(b["name"], cur[b["organization_id"]]) for b in orgs if b["organization_id"] in cur]
    rows.sort(key=lambda r: -r[1]["avg"])
    out = []
    for i, (name, c) in enumerate(rows, 1):
        org = next(b["organization_id"] for b in orgs if b["name"] == name)
        was = (prev.get(org) or {}).get("avg")
        delta = "" if was is None else (f" ({c['avg'] - was:+d} к прошлой неделе)" if c["avg"] != was
                                        else " (без изменений)")
        out.append(f"{i}. <b>{name}</b> — {c['avg']} из 100{delta}")
    return out


@router.get("/api/mountain/scores/{token}")
async def mountain_scores(token: str, days: int = 30):
    """История оценок: график динамики на доске. Управляющему — только его филиал."""
    from database import get_branch_scores
    sc = scope_of_token(token)
    uid = sc["uid"]
    if not sc["valid"]:
        return JSONResponse({"error": "bad token"}, status_code=404)
    if not sc["role"]:
        return JSONResponse({"error": "нет доступа"}, status_code=403)
    orgs = [b["organization_id"] for b in sc["branches"]]
    today = datetime.now().date()
    hist = get_branch_scores(orgs, (today - timedelta(days=max(1, days))).isoformat(),
                             today.isoformat())
    from database import branch_score_average
    avg = branch_score_average(orgs, (today - timedelta(days=7)).isoformat(), today.isoformat())
    return JSONResponse({"branches": [
        {**b, "history": hist.get(b["organization_id"]) or [],
         "week_avg": (avg.get(b["organization_id"]) or {}).get("avg")}
        for b in sc["branches"]]})


@router.get("/api/mountain/whoami/{token}")
async def whoami(token: str):
    """Кто пришёл по ссылке. Лёгкий запрос: шапке сайта нужна только роль,
    гонять ради неё всю доску (задачи, чек-листы, рейтинг) незачем."""
    sc = scope_of_token(token)
    uid = sc["uid"]
    if not sc["valid"]:
        return JSONResponse({"role": None}, status_code=404)
    return JSONResponse({"role": sc["role"],
                         "branch": sc["branches"][0]["name"] if sc["branches"] else ""})


@router.get("/api/mountain/data/{token}")
async def mountain_data(token: str, refresh: int = 0):
    """Доска. Оценка считается из кэша показателей; если его нет — доска
    отдаётся сразу, а сбор уходит в фон (score_pending=true). Ждать минуту с
    белым экраном ради числа в кружке нельзя. refresh=1 — считать сейчас."""
    import asyncio as _aio
    sc = scope_of_token(token)
    uid = sc["uid"]
    if not sc["valid"]:
        return JSONResponse({"error": "bad token"}, status_code=404)
    if not sc["role"]:
        return JSONResponse({"error": "нет доступа"}, status_code=403)
    orgs = [b["organization_id"] for b in sc["branches"]]
    # Показатели ключуем на ВЛАДЕЛЬЦА сети, а не на того, кто открыл ссылку.
    # Управляющему нужны оценки чужих филиалов (сравнить себя одним взглядом),
    # а его собственный кэш знал бы только про его точку. Заодно ночной
    # пересчёт греет кэш сразу и для управляющих.
    owner_uid = uid if sc["role"] == "owner" else _owner_of(orgs[0] if orgs else "")
    network = _all_branches(owner_uid) if owner_uid else sc["branches"]
    signals = _signals_by_branch(owner_uid or uid)
    if not signals and network:
        if refresh:
            signals = await _collect_score_signals(owner_uid or uid, network)
        else:
            _aio.create_task(_collect_score_signals(owner_uid or uid, network))
    return JSONResponse(_board_for(uid, signals=signals))


class AssignPayload(BaseModel):
    tasks: List[Dict[str, Any]]


@router.post("/api/mountain/assign/{token}")
async def mountain_assign(token: str, payload: AssignPayload):
    """Владелец подтверждает предложенные задачи. Управляющему сюда нельзя."""
    sc = scope_of_token(token)
    uid = sc["uid"]
    if not sc["valid"]:
        return JSONResponse({"error": "bad token"}, status_code=404)
    if sc["role"] != "owner":
        return JSONResponse({"error": "задачи ставит только владелец"}, status_code=403)
    allowed = {b["organization_id"]: b["name"] for b in sc["branches"]}
    created = 0
    for t in payload.tasks:
        org = str(t.get("organization_id") or "")
        title = str(t.get("title") or "").strip()
        if org not in allowed or not title:
            continue
        effort = t.get("effort") if t.get("effort") in TASK_POINTS else "средне"
        add_branch_task(org, allowed[org], title, detail=str(t.get("detail") or ""),
                        money=float(t.get("money") or 0), effort=effort,
                        task_key=str(t.get("task_key") or ""), created_by=uid)
        created += 1
    return JSONResponse({"ok": True, "created": created})


class ClosePayload(BaseModel):
    task_id: int


@router.post("/api/mountain/close/{token}")
async def mountain_close(token: str, payload: ClosePayload):
    """Закрыть задачу может и управляющий своего филиала, и владелец."""
    sc = scope_of_token(token)
    uid = sc["uid"]
    if not sc["valid"]:
        return JSONResponse({"error": "bad token"}, status_code=404)
    if not sc["role"]:
        return JSONResponse({"error": "нет доступа"}, status_code=403)
    orgs = {b["organization_id"] for b in sc["branches"]}
    task = next((t for t in get_branch_tasks(list(orgs)) if t["id"] == payload.task_id), None)
    if not task:
        return JSONResponse({"error": "задача не найдена"}, status_code=404)
    ok = close_branch_task(payload.task_id, done_by=uid)
    return JSONResponse({"ok": ok, "points": int(task["points"] or 0)})

# ── Акты разбора: П/Ф стейк → обрезки + нарезка ──────────────────────────────
# Экран живёт в той же вкладке и на тех же ссылках: владелец выбирает филиал,
# управляющий работает со своим. Цена входа берётся из накладных — руками её не
# вбивают, иначе себестоимость превращается в фантазию.
import acts as A


def _branch_or_403(sc: Dict[str, Any], org: Optional[str]) -> Optional[Dict[str, Any]]:
    """Филиал из уже разобранного доступа.

    Раньше принимал uid и сам звал _scope. Со ссылкой ФИЛИАЛА это стало дырой:
    uid у неё — владелец филиала (своих кредов у управляющего нет), и проверка
    пускала бы в любой филиал сети. Доступ разбирается один раз в
    scope_of_token, сюда приходит уже готовым.
    """
    if not sc.get("role"):
        return None
    branches = sc.get("branches") or []
    if not org:
        return branches[0] if branches else None
    return next((b for b in branches if b["organization_id"] == org), None)


def _rest_by_org(org_id: str) -> Dict[str, Any]:
    """Креды филиала — ПО ФИЛИАЛУ, а не по тому, кто открыл ссылку.

    Управляющий сам ресторанов не владеет: поиск по его uid возвращал пусто, и
    подставлялся демо-клиент (облачный, без складов и актов). Отсюда «акт не
    отправился» на ссылке филиала.
    """
    from database import get_db, decrypt_password
    conn = get_db()
    row = conn.execute(
        "SELECT api_login, api_password, iiko_server, organization_name FROM restaurants "
        "WHERE organization_id = ? AND COALESCE(iiko_server,'') != '' LIMIT 1", (org_id,)
    ).fetchone()
    if row is None:
        row = conn.execute("SELECT api_login, api_password, iiko_server, organization_name "
                           "FROM restaurants WHERE organization_id = ? LIMIT 1", (org_id,)).fetchone()
    conn.close()
    if not row:
        return {}
    return {"api_login": row["api_login"], "iiko_server": row["iiko_server"],
            "api_password": decrypt_password(row["api_password"] or ""),
            "org_name": row["organization_name"] or ""}


async def _salmon_context(sc: Dict[str, Any], org: Optional[str]) -> Dict[str, Any]:
    import api                                   # ленивый импорт: избегаем цикла
    b = _branch_or_403(sc, org)
    if not b:
        return {"error": "нет доступа к филиалу"}
    real_org = b["organization_id"]
    info = _rest_by_org(real_org)
    if not info:
        return {"error": "у филиала нет подключения к iiko"}
    client = api.get_client(info["api_login"], info.get("iiko_server"), info.get("api_password"))
    try:
        # П/Ф — тип PREPARED, а закупаемый каталог отфильтрован до GOODS,
        # поэтому здесь спрашиваем оба типа отдельным запросом.
        catalog = await client.search_nomenclature(real_org, "", limit=100000,
                                                   types=["GOODS", "PREPARED"])
    except Exception as e:
        logger.warning(f"[acts] номенклатура {real_org}: {e!r}")
        catalog = []
    prods = A.find_products(catalog)
    price, price_from = 0.0, ""

    async def _price_at(org_id: str, product_id: str):
        st = await api.price_stats(org_id, product_id, 60, {"id": uid})
        best = (st or {}).get("best") or {}
        return (float(best.get("price_per_unit") or 0),
                f'{best.get("supplier_name") or ""} · {best.get("date") or ""}'.strip(" ·"))

    if prods.get("raw"):
        try:
            price, price_from = await _price_at(real_org, prods["raw"]["id"])
        except Exception as e:
            logger.warning(f"[acts] цена входа {real_org}: {e!r}")
        # Бывает, что в этот филиал П/Ф не приходил (новый филиал, перерыв в
        # поставках) — тогда берём цену там, где его закупали: позиция общая.
        if price <= 0:
            others = [r for r in api.get_restaurants(uid)
                      if r["organization_id"] != real_org]
            others.sort(key=lambda r: 0 if "цех" in (r.get("organization_name") or "").lower() else 1)
            for r in others[:4]:
                try:
                    p2, from2 = await _price_at(r["organization_id"], prods["raw"]["id"])
                except Exception:
                    continue
                if p2 > 0:
                    price = p2
                    price_from = f'{from2} · закуп: {r.get("organization_name")}'
                    break
    return {"branch": b, "products": prods, "price_per_kg": price,
            "price_from": price_from, "trim_price": A.TRIM_PRICE}


@router.get("/api/acts/salmon/{token}")
async def acts_salmon_get(token: str, org: Optional[str] = None):
    sc = scope_of_token(token)
    uid = sc["uid"]
    if not sc["valid"]:
        return JSONResponse({"error": "bad token"}, status_code=404)
    # по ссылке филиала акт делается только по СВОЕМУ филиалу:
    # выбор из адреса игнорируем, иначе ссылка открыла бы чужой склад
    ctx = await _salmon_context(sc, sc["org"] or org)
    if ctx.get("error"):
        return JSONResponse(ctx, status_code=403)
    sc = _scope(uid)
    ctx["branches"] = sc["branches"]
    ctx["role"] = sc["role"]
    return JSONResponse(ctx)


class SalmonPayload(BaseModel):
    org: Optional[str] = None
    weight_raw: float                        # сколько П/Ф стейка пошло в разбор
    weight_trim: float                       # сколько вышло обрезков
    weight_waste: float = 0.0                # отход: кости и кожа, себестоимость 0 ₸
    price_per_kg: Optional[float] = None     # переопределение цены, если закуп разовый


@router.post("/api/acts/salmon/{token}")
async def acts_salmon_calc(token: str, payload: SalmonPayload):
    """Считает акт. В iiko пока не отправляет: схему productionDocument
    выясняем по ошибкам сервера, и отправлять «наугад» в учёт нельзя."""
    sc = scope_of_token(token)
    uid = sc["uid"]
    if not sc["valid"]:
        return JSONResponse({"error": "bad token"}, status_code=404)
    # по ссылке филиала акт делается только по СВОЕМУ филиалу:
    # выбор из адреса игнорируем, иначе ссылка открыла бы чужой склад
    ctx = await _salmon_context(sc, sc["org"] or payload.org)
    if ctx.get("error"):
        return JSONResponse(ctx, status_code=403)
    price = float(payload.price_per_kg or ctx["price_per_kg"] or 0)
    if price <= 0:
        return JSONResponse({"ok": False,
                             "error": "Нет цены П/Ф стейка: в накладных за 60 дней его не было. "
                                      "Впиши цену вручную."})
    res = A.split_salmon(price, payload.weight_raw, payload.weight_trim,
                         payload.weight_waste)
    res["products"] = ctx["products"]
    res["branch"] = ctx["branch"]
    return JSONResponse(res)


# ── Консоль владельца: сообщение управляющим ─────────────────────────────────
# Уведомление живёт на сайте, а не в чате: управляющий и так открывает «Гору»
# каждый день ради задач и чек-листов. Владелец видит, кто прочитал.
from database import (add_branch_notice, get_branch_notices, mark_notice_read,
                      notice_is_for, notice_read_stats)


class NoticePayload(BaseModel):
    text: str
    org: Optional[str] = None      # пусто = всем филиалам


@router.post("/api/mountain/notice/{token}")
async def notice_send(token: str, payload: NoticePayload):
    sc = scope_of_token(token)
    uid = sc["uid"]
    if not sc["valid"]:
        return JSONResponse({"error": "bad token"}, status_code=404)
    if sc["role"] != "owner":
        return JSONResponse({"error": "сообщения рассылает только владелец"}, status_code=403)
    text = (payload.text or "").strip()
    if not text:
        return JSONResponse({"error": "пустое сообщение"}, status_code=400)
    if len(text) > 2000:
        return JSONResponse({"error": "слишком длинно, до 2000 знаков"}, status_code=400)
    org = payload.org or ""
    if org and org not in {b["organization_id"] for b in sc["branches"]}:
        return JSONResponse({"error": "чужой филиал"}, status_code=403)
    nid = add_branch_notice(text, uid, org)
    return JSONResponse({"ok": True, "id": nid})


@router.get("/api/mountain/notices/{token}")
async def notices_list(token: str):
    sc = scope_of_token(token)
    uid = sc["uid"]
    if not sc["valid"]:
        return JSONResponse({"error": "bad token"}, status_code=404)
    if not sc["role"]:
        return JSONResponse({"error": "нет доступа"}, status_code=403)
    orgs = [b["organization_id"] for b in sc["branches"]]
    rows = get_branch_notices(orgs, reader=uid)
    if sc["role"] == "owner":
        names = {b["organization_id"]: b["name"] for b in sc["branches"]}
        for r in rows:
            r["read_by"] = notice_read_stats(r["id"])          # сколько прочитали
            r["branch"] = names.get(r.get("organization_id") or "", "все филиалы")
    return JSONResponse({"role": sc["role"], "notices": rows,
                         "unread": sum(1 for r in rows if not r.get("is_read"))})


@router.post("/api/mountain/notice/{token}/read/{notice_id}")
async def notice_read(token: str, notice_id: int):
    """Отметка «прочитал». Подписи токена мало: владелец по этой отметке судит,
    дошло ли сообщение до филиала. Раньше любой подписанный uid — в том числе
    без роли вообще — мог отметить ЛЮБОЕ сообщение, и счётчик «прочитали N»
    показывал больше, чем есть управляющих. Пускаем только адресата."""
    sc = scope_of_token(token)
    uid = sc["uid"]
    if not sc["valid"]:
        return JSONResponse({"error": "bad token"}, status_code=404)
    if not sc["role"]:
        return JSONResponse({"error": "нет доступа"}, status_code=403)
    orgs = [b["organization_id"] for b in sc["branches"]]
    if not notice_is_for(notice_id, orgs):
        return JSONResponse({"error": "сообщение не для вас"}, status_code=403)
    mark_notice_read(notice_id, uid)
    return JSONResponse({"ok": True})


class SalmonSendPayload(SalmonPayload):
    store_id: Optional[str] = None       # склад разбора; пусто — где лежит вход


@router.get("/api/acts/salmon/{token}/stores")
async def acts_salmon_stores(token: str, org: Optional[str] = None):
    """Склады филиала + подсказка, на каком реально лежит входной П/Ф."""
    import api
    sc = scope_of_token(token)
    uid = sc["uid"]
    if not sc["valid"]:
        return JSONResponse({"error": "bad token"}, status_code=404)
    # по ссылке филиала акт делается только по СВОЕМУ филиалу:
    # выбор из адреса игнорируем, иначе ссылка открыла бы чужой склад
    ctx = await _salmon_context(sc, sc["org"] or org)
    if ctx.get("error"):
        return JSONResponse(ctx, status_code=403)
    real_org = ctx["branch"]["organization_id"]
    info = _rest_by_org(real_org)
    client = api.get_client(info.get("api_login"), info.get("iiko_server"), info.get("api_password"))
    stores, suggest = [], ""
    try:
        stores = [{"id": s["id"], "name": s["name"]} for s in await client.get_stores(info.get("org_name", ""))]
    except Exception as e:
        logger.warning(f"[acts] склады {real_org}: {e!r}")
    raw = (ctx.get("products") or {}).get("raw") or {}
    if raw.get("id") and hasattr(client, "get_store_balances"):
        try:
            for b in await client.get_store_balances():
                if b.get("product") == raw["id"] and float(b.get("amount") or 0) > 0:
                    suggest = b.get("store") or ""
                    break
        except Exception:
            pass
    return JSONResponse({"stores": stores, "suggest": suggest})


@router.post("/api/acts/salmon/{token}/send")
async def acts_salmon_send(token: str, payload: SalmonSendPayload):
    """Отправка акта в iiko. Пишет в учёт, поэтому считаем здесь заново, а не
    доверяем числам из браузера: подменённый вес не должен попасть в документ."""
    import api
    sc = scope_of_token(token)
    uid = sc["uid"]
    if not sc["valid"]:
        return JSONResponse({"error": "bad token"}, status_code=404)
    # по ссылке филиала акт делается только по СВОЕМУ филиалу:
    # выбор из адреса игнорируем, иначе ссылка открыла бы чужой склад
    ctx = await _salmon_context(sc, sc["org"] or payload.org)
    if ctx.get("error"):
        return JSONResponse(ctx, status_code=403)
    prods = ctx["products"]
    if not (prods.get("raw") and prods.get("trim") and prods.get("slice")):
        return JSONResponse({"ok": False, "error": "В номенклатуре нет позиций разбора"})
    price = float(payload.price_per_kg or ctx["price_per_kg"] or 0)
    if price <= 0:
        return JSONResponse({"ok": False, "error": "Нет цены входа — впиши вручную"})
    calc = A.split_salmon(price, payload.weight_raw, payload.weight_trim,
                          payload.weight_waste)
    if not calc.get("ok"):
        return JSONResponse(calc)

    real_org = ctx["branch"]["organization_id"]
    info = _rest_by_org(real_org)
    client = api.get_client(info.get("api_login"), info.get("iiko_server"), info.get("api_password"))
    if not hasattr(client, "create_production_act"):
        return JSONResponse({"ok": False, "error": "Этот филиал на облачном iiko — акт недоступен"})
    store = payload.store_id
    if not store:
        try:
            stores = await client.get_stores(info.get("org_name", ""))
            store = stores[0]["id"] if stores else ""
        except Exception as e:
            return JSONResponse({"ok": False, "error": f"Не получил склады: {e}"})
    produced = [{"productId": prods["trim"]["id"], "amount": calc["trim"]["weight"]},
                {"productId": prods["slice"]["id"], "amount": calc["slice"]["weight"]}]
    # Отход кладём в документ, только если его взвесили и он есть в номенклатуре:
    # пустая строка с нулевым весом ломает проводку.
    if calc.get("waste", {}).get("weight") and (prods.get("waste") or {}).get("id"):
        produced.append({"productId": prods["waste"]["id"], "amount": calc["waste"]["weight"]})
    try:
        account = await client.get_account_for_production()
        resp = await client.create_production_act(
            store_from=store, store_to=store, account_to=account,
            consumed=[{"productId": prods["raw"]["id"], "amount": calc["raw"]["weight"]}],
            produced=produced,
        )
    except Exception as e:
        logger.warning(f"[acts] отправка {real_org}: {e!r}")
        return JSONResponse({"ok": False, "error": str(e)[:200]})
    return JSONResponse({**calc, "sent": resp.get("ok"), "number": resp.get("number"),
                         "send_error": resp.get("error")})


# ── Сдача чек-листа с сайта ──────────────────────────────────────────────────
# Раньше фото уходили только в чат бота. Управляющий и так открывает «Гору»
# каждый день — пусть сдаёт отсюда. Кадры сжимаем ДО отправки в браузере, а
# здесь ограничиваем размер: фотоконтроль не должен превращаться в файлопомойку.
import base64 as _b64
from database import (save_checklist_upload, get_checklist_uploads, checklist_dir)

ZONES = {"hall": "зал", "kitchen": "кухня", "wc": "санузел"}
SLOTS = ["10:45", "15:00", "20:45", "23:45"]
MAX_PHOTO_MB = 4
MAX_PHOTOS = 8


class ChecklistPayload(BaseModel):
    org: Optional[str] = None
    slot: str
    zone: str
    photos: List[str] = []          # base64, до MAX_PHOTOS штук
    note: Optional[str] = ""


@router.post("/api/mountain/checklist/{token}")
async def checklist_upload(token: str, payload: ChecklistPayload):
    sc = scope_of_token(token)
    uid = sc["uid"]
    if not sc["valid"]:
        return JSONResponse({"error": "bad token"}, status_code=404)
    b = _branch_or_403(sc, payload.org)
    if not b:
        return JSONResponse({"error": "нет доступа к филиалу"}, status_code=403)
    if payload.slot not in SLOTS:
        return JSONResponse({"error": f"слот должен быть одним из {', '.join(SLOTS)}"}, status_code=400)
    if payload.zone not in ZONES:
        return JSONResponse({"error": "зона: hall, kitchen или wc"}, status_code=400)
    if not payload.photos:
        return JSONResponse({"error": "нужно хотя бы одно фото"}, status_code=400)
    if len(payload.photos) > MAX_PHOTOS:
        return JSONResponse({"error": f"не больше {MAX_PHOTOS} кадров на зону"}, status_code=400)

    day = datetime.now().date().isoformat()
    folder = os.path.join(checklist_dir(), b["organization_id"], day)
    os.makedirs(folder, exist_ok=True)
    saved = []
    for i, raw in enumerate(payload.photos):
        try:
            data = _b64.b64decode((raw or "").split(",", 1)[-1], validate=False)
        except Exception:
            return JSONResponse({"error": "файл не читается"}, status_code=400)
        if len(data) > MAX_PHOTO_MB * 1024 * 1024:
            return JSONResponse({"error": f"кадр больше {MAX_PHOTO_MB} МБ — сожми"}, status_code=413)
        name = f"{payload.slot.replace(':', '')}_{payload.zone}_{int(datetime.now().timestamp())}_{i}.jpg"
        with open(os.path.join(folder, name), "wb") as f:
            f.write(data)
        saved.append(os.path.join(b["organization_id"], day, name))
    rid = save_checklist_upload(b["organization_id"], day, payload.slot, payload.zone,
                                saved, payload.note or "", uid)
    review = await _maybe_review(b["organization_id"], day, payload.slot)
    return JSONResponse({"ok": True, "id": rid, "photos": len(saved),
                         "slot": payload.slot, "zone": ZONES[payload.zone],
                         "review": review})


async def _maybe_review(org: str, day: str, slot: str) -> Dict[str, Any]:
    """Разбор фото моделью — со всеми предохранителями по деньгам.

    Гоняем не всё: только выборку и спорные случаи (см. checklist_ai). Один
    запрос на СЛОТ, а не на кадр: три зоны идут одним документом. Кадры
    ужимаются до 512 px, а по хешу стоит кэш — тот же снимок второй раз не
    оплачивается. Пока CHECKLIST_AI не включён, сюда вообще ничего не уходит.
    """
    import checklist_ai as C
    from database import (get_checklist_uploads, save_checklist_review,
                          photo_verdict_cache, save_photo_verdict, checklist_dir)
    ups = [u for u in get_checklist_uploads([org], day) if u["slot"] == slot]
    if not ups:
        return {"checked": False, "reason": "нет сдач"}

    # спорные случаи: сдано позже слота или кадров меньше трёх
    late = datetime.now().strftime("%H:%M") > slot
    photos_n = sum(len(u.get("photos") or []) for u in ups)
    do, why = C.should_review({"photos": [1] * photos_n}, late=late)
    if not do:
        return {"checked": False, "reason": why}

    blobs: List[Tuple[bytes, str]] = []
    hashes: List[str] = []
    for u in ups:
        for rel in (u.get("photos") or []):
            try:
                with open(os.path.join(checklist_dir(), rel), "rb") as f:
                    data = f.read()
            except Exception:
                continue
            blobs.append((data, ZONES.get(u["zone"], u["zone"])))
            hashes.append(C.photo_hash(data))
    if not blobs:
        return {"checked": False, "reason": "кадры не читаются"}

    cache = photo_verdict_cache(hashes)
    res = await C.review_slot(blobs, cache=cache)
    if res.get("checked"):
        save_checklist_review(org, day, slot, bool(res.get("ok")), res.get("issues") or [], why)
        for hsh in hashes:
            save_photo_verdict(hsh, {"ok": res.get("ok"), "issues": res.get("issues") or []})
    res["reason"] = why
    return res


@router.get("/api/mountain/checklist/{token}")
async def checklist_today(token: str):
    """Что сдано с сайта сегодня: слоты × зоны по каждому доступному филиалу."""
    sc = scope_of_token(token)
    uid = sc["uid"]
    if not sc["valid"]:
        return JSONResponse({"error": "bad token"}, status_code=404)
    if not sc["role"]:
        return JSONResponse({"error": "нет доступа"}, status_code=403)
    day = datetime.now().date().isoformat()
    orgs = [b["organization_id"] for b in sc["branches"]]
    rows = get_checklist_uploads(orgs, day)
    names = {b["organization_id"]: b["name"] for b in sc["branches"]}
    done: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        key = f'{r["organization_id"]}|{r["slot"]}|{r["zone"]}'
        done.setdefault(key, {"branch": names.get(r["organization_id"], ""),
                              "slot": r["slot"], "zone": ZONES.get(r["zone"], r["zone"]),
                              "photos": len(r["photos"]), "at": (r["created_at"] or "")[11:16]})
    from database import get_checklist_reviews
    reviews = [{"slot": r["slot"], "ok": bool(r["ok"]), "issues": r["issues"],
                "reason": r.get("reason") or "",
                "branch": names.get(r["organization_id"], "")}
               for r in get_checklist_reviews(orgs, day)]
    return JSONResponse({"day": day, "slots": SLOTS, "zones": ZONES,
                         "criteria": S.ZONE_CRITERIA,
                         "role": sc["role"], "done": list(done.values()),
                         "reviews": reviews})
