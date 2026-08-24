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
    get_restaurants, get_branch_managers, add_branch_task, close_branch_task,
    get_branch_tasks, TASK_POINTS,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# ── Гора: 40 отметок по 25 баллов ────────────────────────────────────────────
STEP_POINTS = int(os.getenv("MOUNTAIN_STEP", "25"))
STEPS = int(os.getenv("MOUNTAIN_STEPS", "40"))
CHECKLIST_POINT = 1        # сданный слот
CHECKLIST_PENALTY = -1     # пропущенный


def _secret() -> bytes:
    return (os.getenv("WIDGET_SECRET") or os.getenv("ENCRYPTION_KEY") or "iiko-widget-fallback").encode()


def _sign(uid: int) -> str:
    mac = hmac.new(_secret(), f"mountain:{uid}".encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode().rstrip("=")[:20]


def token_for(uid: int) -> str:
    """Ссылка одинакова локально и на проде — общий ENCRYPTION_KEY, без БД."""
    return f"{uid}.{_sign(uid)}"


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


def _scope(uid: int) -> Dict[str, Any]:
    """Что видит этот uid: владелец — свои филиалы, управляющий — свой."""
    own = get_restaurants(uid) or []
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
            "to_next": max(0, (step + 1) * STEP_POINTS - points) if step < STEPS else 0}


def _checklist_points_own(prog: Dict[str, Dict[str, int]], org: str) -> Dict[str, int]:
    """Баллы за чек-листы по НАШИМ сдачам: сдал слот +1, пропустил −1.
    Доску из чата больше не спрашиваем — бота не будет."""
    p = prog.get(org) or {}
    done, missed = int(p.get("done") or 0), abs(int(p.get("missed") or 0))
    return {"done": done, "missed": -missed, "expect": int(p.get("expect") or 0),
            "points": done * CHECKLIST_POINT - missed * abs(CHECKLIST_PENALTY)}


def _signals_by_branch(uid: int) -> Dict[str, Dict[str, Any]]:
    """Показатели филиалов из кэша ассистента. Только из кэша: сбор идёт по всем
    филиалам и стоит минуты, доска не должна его запускать. Кэш наполняет кнопка
    «Предложить задачи» и живёт 12 часов."""
    import api
    cached = api._get_cached(api._cache_key(uid, "mountain-signals", "all", "month"),
                             ttl=api.ASSISTANT_TTL)
    if not cached:
        return {}
    return {b.get("name"): b for b in (cached.get("branches") or []) if b.get("name")}


def _board_for(uid: int, journals: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    sc = _scope(uid)
    if not sc["role"]:
        return {"error": "нет доступа"}
    orgs = [b["organization_id"] for b in sc["branches"]]
    tasks = get_branch_tasks(orgs, since=_month_start())
    journals = journals or {}
    signals = _signals_by_branch(uid)      # пусто, пока не считали задачи — это нормально
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
    return {"role": sc["role"], "month": datetime.now().strftime("%Y-%m"),
            "scale": {"tasks": TASK_POINTS, "checklist_done": CHECKLIST_POINT,
                      "checklist_missed": CHECKLIST_PENALTY,
                      "step_points": STEP_POINTS, "steps": STEPS},
            "branches": rows}


@router.get("/api/mountain/data/{token}")
async def mountain_data(token: str):
    uid = uid_from_token(token)
    if not uid:
        return JSONResponse({"error": "bad token"}, status_code=404)
    return JSONResponse(_board_for(uid))


class AssignPayload(BaseModel):
    tasks: List[Dict[str, Any]]


@router.post("/api/mountain/assign/{token}")
async def mountain_assign(token: str, payload: AssignPayload):
    """Владелец подтверждает предложенные задачи. Управляющему сюда нельзя."""
    uid = uid_from_token(token)
    if not uid:
        return JSONResponse({"error": "bad token"}, status_code=404)
    sc = _scope(uid)
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
    uid = uid_from_token(token)
    if not uid:
        return JSONResponse({"error": "bad token"}, status_code=404)
    sc = _scope(uid)
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


def _branch_or_403(uid: int, org: Optional[str]) -> Optional[Dict[str, Any]]:
    sc = _scope(uid)
    if not sc["role"]:
        return None
    if not org:
        return sc["branches"][0] if sc["branches"] else None
    return next((b for b in sc["branches"] if b["organization_id"] == org), None)


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


async def _salmon_context(uid: int, org: Optional[str]) -> Dict[str, Any]:
    import api                                   # ленивый импорт: избегаем цикла
    b = _branch_or_403(uid, org)
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
    uid = uid_from_token(token)
    if not uid:
        return JSONResponse({"error": "bad token"}, status_code=404)
    ctx = await _salmon_context(uid, org)
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
    uid = uid_from_token(token)
    if not uid:
        return JSONResponse({"error": "bad token"}, status_code=404)
    ctx = await _salmon_context(uid, payload.org)
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
                      notice_read_stats)


class NoticePayload(BaseModel):
    text: str
    org: Optional[str] = None      # пусто = всем филиалам


@router.post("/api/mountain/notice/{token}")
async def notice_send(token: str, payload: NoticePayload):
    uid = uid_from_token(token)
    if not uid:
        return JSONResponse({"error": "bad token"}, status_code=404)
    sc = _scope(uid)
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
    uid = uid_from_token(token)
    if not uid:
        return JSONResponse({"error": "bad token"}, status_code=404)
    sc = _scope(uid)
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
    uid = uid_from_token(token)
    if not uid:
        return JSONResponse({"error": "bad token"}, status_code=404)
    mark_notice_read(notice_id, uid)
    return JSONResponse({"ok": True})


class SalmonSendPayload(SalmonPayload):
    store_id: Optional[str] = None       # склад разбора; пусто — где лежит вход


@router.get("/api/acts/salmon/{token}/stores")
async def acts_salmon_stores(token: str, org: Optional[str] = None):
    """Склады филиала + подсказка, на каком реально лежит входной П/Ф."""
    import api
    uid = uid_from_token(token)
    if not uid:
        return JSONResponse({"error": "bad token"}, status_code=404)
    ctx = await _salmon_context(uid, org)
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
    uid = uid_from_token(token)
    if not uid:
        return JSONResponse({"error": "bad token"}, status_code=404)
    ctx = await _salmon_context(uid, payload.org)
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
    uid = uid_from_token(token)
    if not uid:
        return JSONResponse({"error": "bad token"}, status_code=404)
    b = _branch_or_403(uid, payload.org)
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
    uid = uid_from_token(token)
    if not uid:
        return JSONResponse({"error": "bad token"}, status_code=404)
    sc = _scope(uid)
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
