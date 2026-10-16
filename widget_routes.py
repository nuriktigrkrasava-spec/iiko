"""Виджет на домашний экран телефона: личная ссылка /w/{token} без Telegram-логина.

Отдельный модуль (APIRouter), чтобы подключаться и в редизайн-ветку, и в
прод-ветку деплоя одним `app.include_router(...)` без merge-конфликтов.
Токен — подписанный uid (общий ENCRYPTION_KEY) → одинаков локально и на проде,
хранилище не нужно. Тяжёлые расчёты берём из api.* ленивым импортом."""
import os
import hmac
import hashlib
import base64
import asyncio
import json
import html
from functools import lru_cache
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, Response
from fastapi.responses import HTMLResponse, JSONResponse

router = APIRouter()

_SITES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sites")


def _read_site(name: str) -> str:
    """HTML страниц лежит в sites/ отдельными файлами, а не строками в коде:
    так его видно подсветкой, диффы читаемы, и вёрстка правится без риска
    задеть логику роутера."""
    with open(os.path.join(_SITES_DIR, name), encoding="utf-8") as f:
        return f.read()
_WIDGET_BOT_URL = os.getenv("BOT_DEEPLINK", "https://t.me/iikoanalytics_bot")
_RU_MON = {1: "янв", 2: "фев", 3: "мар", 4: "апр", 5: "мая", 6: "июн",
           7: "июл", 8: "авг", 9: "сен", 10: "окт", 11: "ноя", 12: "дек"}

_WIDGET_TPL = _read_site("widget.html")


def _widget_secret() -> bytes:
    # ENCRYPTION_KEY одинаков на локали и на проде → токен совпадает везде, без БД.
    secret = os.getenv("WIDGET_SECRET") or os.getenv("ENCRYPTION_KEY")
    if not secret:
        raise RuntimeError("Configure WIDGET_SECRET or ENCRYPTION_KEY")
    return secret.encode()


@lru_cache(maxsize=8)
def _owner_versions(raw: str) -> Dict[str, int]:
    """Operator-controlled revocation epochs; malformed settings fail closed."""
    try:
        versions = json.loads(raw)
        if not isinstance(versions, dict) or any(
            not isinstance(uid, str) or str(int(uid)) != uid
            or type(version) is not int or version < 0
            for uid, version in versions.items()
        ):
            raise ValueError()
        return versions
    except (ValueError, TypeError):
        raise RuntimeError("Invalid WIDGET_OWNER_VERSIONS configuration") from None


def _owner_version(uid: int) -> int:
    return _owner_versions(os.getenv("WIDGET_OWNER_VERSIONS") or "{}").get(str(uid), 0)


def _widget_sign(uid: int) -> str:
    version = _owner_version(uid)
    message = f"widget:{uid}" + (f":v{version}" if version else "")
    mac = hmac.new(_widget_secret(), message.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode().rstrip("=")[:20]


def widget_token_for(uid: int) -> str:
    """Stateless подписанный токен: uid + подпись. Одинаков везде (общий ENCRYPTION_KEY)."""
    return f"{uid}.{_widget_sign(uid)}"


def _uid_from_token(token: str) -> Optional[int]:
    """Проверяет подпись и достаёт uid. None — если токен битый/подделан."""
    if not token or "." not in token:
        return None
    uid_s, sig = token.rsplit(".", 1)
    try:
        uid = int(uid_s)
    except ValueError:
        return None
    # bytes-сравнение: строковое compare_digest падает на не-ASCII подписи
    return uid if hmac.compare_digest(sig.encode("utf-8", "ignore"), _widget_sign(uid).encode()) else None


def widget_branch_token_for(uid: int, org_id: str) -> str:
    payload = base64.urlsafe_b64encode(json.dumps([uid, org_id], separators=(",", ":")).encode()).decode().rstrip("=")
    signature = _branch_sign(payload, uid)
    return f"b.{payload}.{signature}"


def _branch_sign(payload: str, uid: int) -> str:
    version = _owner_version(uid)
    message = "widget-branch:" + payload + (f":v{version}" if version else "")
    return hmac.new(_widget_secret(), message.encode(), hashlib.sha256).hexdigest()


def _widget_scope(token: str, requested_org: Optional[str] = None):
    if not token.startswith("b."):
        uid = _uid_from_token(token)
        return (uid, requested_org) if uid is not None else None
    try:
        prefix, payload, signature = token.split(".")
        if len(payload) > 2048:
            return None
        uid, org = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        if type(uid) is not int or not isinstance(org, str) or not org:
            return None
        expected = _branch_sign(payload, uid)
        if not hmac.compare_digest(signature.encode(), expected.encode()):
            return None
        if requested_org is not None and requested_org != org:
            return None
        return uid, org
    except (ValueError, TypeError, UnicodeError):
        return None


async def _gather(uid: int, only_org: Optional[str] = None) -> Dict[str, Any]:
    """Выручка сегодня (сумма по филиалам или один) + справка «вчера» + недельная искра."""
    import api  # ленивый импорт: избегаем циклической зависимости при загрузке
    user = {"id": uid, "username": "", "first_name": ""}
    orgs = api.get_restaurants(uid)
    if only_org:
        orgs = [o for o in orgs if o["organization_id"] == only_org]
    if not orgs:
        return {"connected": False}

    async def _rev(oid: str, period: str) -> float:
        try:
            d = await api.dashboard(oid, Response(), period, None, None, None, user=user)
            return float(d.get("revenue_today") or 0)
        except Exception:
            return 0.0

    ids = [o["organization_id"] for o in orgs]
    today_vals = await asyncio.gather(*(_rev(i, "today") for i in ids))
    yday_vals = await asyncio.gather(*(_rev(i, "yesterday") for i in ids))
    today, yday = sum(today_vals), sum(yday_vals)
    spark: List[float] = []
    try:
        dw = await api.dashboard(ids[0], Response(), "week", None, None, None, user=user)
        spark = [float(x) for x in ((dw.get("chart_7days") or {}).get("data") or [])]
    except Exception:
        spark = []
    label = orgs[0]["organization_name"] if len(orgs) == 1 else f"{len(orgs)} филиалов"
    return {"connected": True, "revenue": today, "yesterday": yday, "spark": spark, "label": label}


def _render(data: Dict[str, Any]) -> str:
    import api
    now = api.local_now()
    date_lbl = f"{now.day} {_RU_MON.get(now.month, '')}"
    time_lbl = now.strftime("%H:%M")

    if not data.get("connected"):
        rev_html = "—"; sub = "ресторан ещё не подключён"; delta_html = ""; spark_html = ""; label = "Виджет"
    else:
        rev = int(round(data.get("revenue") or 0))
        rev_html = f"{rev:,}".replace(",", " ")
        label = data.get("label") or "Выручка"
        sub = "за сегодня по всем филиалам" if "филиал" in label else "выручка за сегодня"
        yday = data.get("yesterday")
        if yday:
            yday_fmt = f"{int(round(yday)):,}".replace(",", " ")
            delta_html = f'<span class="ref">вчера {yday_fmt}&nbsp;₸</span>'
        else:
            delta_html = ""
        sp = data.get("spark") or []
        if sp:
            mx = max(sp) or 1
            bars = "".join(
                f'<span class="bar{" on" if i == len(sp) - 1 else ""}" style="height:{max(8, round(v / mx * 100))}%"></span>'
                for i, v in enumerate(sp))
            spark_html = f'<div class="spark" aria-hidden="true">{bars}</div>'
        else:
            spark_html = ""

    tpl = _WIDGET_TPL
    for k, v in {
        "__REV__": rev_html, "__CUR__": ("₸" if data.get("connected") else ""),
        "__SUB__": sub, "__DELTA__": delta_html, "__SPARK__": spark_html,
        "__LABEL__": html.escape(str(label)), "__DATE__": date_lbl, "__TIME__": time_lbl, "__BOT__": html.escape(_WIDGET_BOT_URL, quote=True),
    }.items():
        tpl = tpl.replace(k, v)
    return tpl


@router.get("/w/{token}")
async def widget_page(token: str):
    """Публичная страница-виджет (без Telegram-заголовка). Токен = авторизация."""
    import api
    scope = _widget_scope(token)
    if scope is None:
        return HTMLResponse(_render({"connected": False}), status_code=404)
    cache_key = f"widgetpage:{token}"
    data = api._get_cached(cache_key)
    if data is None:
        data = await _gather(scope[0], only_org=scope[1])
        api._set_cached(cache_key, data)
    return HTMLResponse(_render(data), headers={"Cache-Control": "private, no-store"})


@router.get("/w/{token}/{org_id}")
async def widget_page_branch(token: str, org_id: str):
    """То же, но по одному филиалу (org_id должен принадлежать владельцу токена)."""
    import api
    scope = _widget_scope(token, org_id)
    if scope is None:
        return HTMLResponse(_render({"connected": False}), status_code=404)
    cache_key = f"widgetpage:{token}:{org_id}"
    data = api._get_cached(cache_key)
    if data is None:
        data = await _gather(scope[0], only_org=scope[1])
        api._set_cached(cache_key, data)
    return HTMLResponse(_render(data), headers={"Cache-Control": "private, no-store"})


# ---- JSON для настоящего тайла (Scriptable / WidgetKit): виджет как «Погода» ----

async def _json_payload(token: str, only_org: Optional[str]):
    import api
    scope = _widget_scope(token, only_org)
    if scope is None:
        return JSONResponse({"connected": False}, status_code=404)
    ck = f"widgetjson:{token}:{only_org or 'all'}"
    data = api._get_cached(ck)
    if data is None:
        data = await _gather(scope[0], only_org=scope[1])
        api._set_cached(ck, data)
    return JSONResponse({**data, "bot": _WIDGET_BOT_URL},
                        headers={"Cache-Control": "private, no-store"})


@router.get("/api/widget/data/{token}")
async def widget_data(token: str):
    """Компактный JSON выручки (для Scriptable-виджета на домашний/локскрин)."""
    return await _json_payload(token, None)


@router.get("/api/widget/data/{token}/{org_id}")
async def widget_data_branch(token: str, org_id: str):
    return await _json_payload(token, org_id)
