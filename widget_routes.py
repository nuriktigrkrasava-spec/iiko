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
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, Response
from fastapi.responses import HTMLResponse, JSONResponse

router = APIRouter()

_WIDGET_BOT_URL = os.getenv("BOT_DEEPLINK", "https://t.me/iikoanalytics_bot")
_RU_MON = {1: "янв", 2: "фев", 3: "мар", 4: "апр", 5: "мая", 6: "июн",
           7: "июл", 8: "авг", 9: "сен", 10: "окт", 11: "ноя", 12: "дек"}

_WIDGET_TPL = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta name="apple-mobile-web-app-title" content="Saya">
<meta name="theme-color" content="#e9ecf7" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#0c0e13" media="(prefers-color-scheme: dark)">
<title>Saya · выручка</title>
<style>
  :root {
    --ground:#e9ecf7; --glass:linear-gradient(135deg, rgba(255,255,255,.66), rgba(255,255,255,.44));
    --glass-2:rgba(255,255,255,.5);
    --hair:rgba(20,26,44,.10); --hi:#0a0b12; --lo:#43485a; --mute:#8a90a2;
    --acc:#2f6bff; --acc-2:#5a8cff; --acc-glow:rgba(47,107,255,.24);
    --grn:#1faa53; --red:#ff3b30;
    --shadow:0 1px 2px rgba(20,30,60,.05), 0 18px 44px -22px rgba(20,30,60,.30);
    --blob-a:rgba(47,107,255,.18); --blob-b:rgba(120,150,255,.14);
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --ground:#0c0e13; --glass:linear-gradient(135deg, rgba(255,255,255,.11), rgba(255,255,255,.04));
      --glass-2:rgba(255,255,255,.055);
      --hair:rgba(255,255,255,.10); --hi:#f2f4fa; --lo:#c6cee1; --mute:#98a3c0;
      --acc:#4f6ef7; --acc-2:#6b86ff; --acc-glow:rgba(79,110,247,.42);
      --grn:#3ecf8e; --red:#e5484d;
      --shadow:0 10px 28px -18px rgba(0,0,0,.75);
      --blob-a:rgba(79,110,247,.30); --blob-b:rgba(60,90,220,.20);
    }
  }
  * { box-sizing:border-box; }
  body {
    margin:0; min-height:100vh; display:grid; place-items:center; padding:40px 20px;
    color:var(--hi);
    background:radial-gradient(60% 40% at 18% 8%, var(--blob-a), transparent 60%),
               radial-gradient(55% 45% at 88% 22%, var(--blob-b), transparent 62%), var(--ground);
    font-family:"Inter",-apple-system,BlinkMacSystemFont,"SF Pro Text",system-ui,"Segoe UI",Roboto,sans-serif;
    -webkit-font-smoothing:antialiased;
  }
  .stage { width:100%; max-width:384px; }
  .card {
    position:relative; background:var(--glass);
    -webkit-backdrop-filter:blur(16px) saturate(1.6); backdrop-filter:blur(16px) saturate(1.6);
    border:1px solid var(--hair); border-radius:26px; padding:26px 24px 24px; box-shadow:var(--shadow);
  }
  .eyebrow { display:flex; align-items:center; gap:8px; font-size:11px; font-weight:650;
    letter-spacing:.07em; text-transform:uppercase; color:var(--mute); }
  .eyebrow .live { width:7px; height:7px; border-radius:50%; background:var(--grn);
    box-shadow:0 0 8px color-mix(in srgb, var(--grn) 70%, transparent); }
  .eyebrow .hint { margin-left:auto; letter-spacing:0; text-transform:none; font-weight:450; font-size:12px; }
  .rev { margin-top:16px; font-weight:750; font-size:56px; line-height:1; letter-spacing:-.038em;
    font-variant-numeric:tabular-nums; display:flex; align-items:baseline; gap:8px; color:var(--hi); }
  .rev .cur { font-size:21px; font-weight:650; letter-spacing:-.02em; color:var(--mute); }
  .revsub { margin-top:13px; display:flex; align-items:center; gap:11px; flex-wrap:wrap; font-size:13px; color:var(--lo); }
  .delta { display:inline-flex; align-items:center; gap:4px; font-size:12.5px; font-weight:700; color:var(--grn);
    background:color-mix(in srgb, var(--grn) 14%, transparent); padding:4px 9px; border-radius:999px; font-variant-numeric:tabular-nums; }
  .delta.dn { color:var(--red); background:color-mix(in srgb, var(--red) 14%, transparent); }
  .ref { display:inline-flex; align-items:center; font-size:12px; font-weight:600; color:var(--lo);
    background:var(--glass-2, rgba(255,255,255,.5)); border:1px solid var(--hair);
    padding:4px 9px; border-radius:999px; font-variant-numeric:tabular-nums; }
  .spark { margin-top:20px; display:flex; align-items:flex-end; gap:7px; height:44px; }
  .spark .bar { flex:1; border-radius:5px;
    background:linear-gradient(180deg, color-mix(in srgb, var(--acc) 24%, transparent), color-mix(in srgb, var(--acc) 9%, transparent));
    border:1px solid color-mix(in srgb, var(--acc) 18%, transparent);
    box-shadow:inset 0 1px 0 rgba(255,255,255,.45);
    -webkit-backdrop-filter:blur(6px); backdrop-filter:blur(6px); }
  .spark .bar.on { background:linear-gradient(180deg, color-mix(in srgb, var(--acc-2) 88%, white), var(--acc));
    border-color:color-mix(in srgb, var(--acc) 55%, transparent);
    box-shadow:inset 0 1px 0 rgba(255,255,255,.55), 0 8px 18px -8px var(--acc-glow); }
  .rule { margin:22px 0; height:1px; background:var(--hair); }
  .cta { display:flex; align-items:center; justify-content:center; gap:11px; width:100%; text-decoration:none;
    background:linear-gradient(135deg, var(--acc), var(--acc-2)); color:#fff; font-size:15.5px; font-weight:650;
    letter-spacing:-.01em; padding:15px 18px; border-radius:16px; box-shadow:0 12px 28px -10px var(--acc-glow);
    transition:transform .16s cubic-bezier(.34,1.4,.5,1), filter .16s ease; }
  .cta:hover { filter:brightness(1.05); }
  .cta:active { transform:scale(.985); }
  .cta:focus-visible { outline:2px solid var(--acc); outline-offset:3px; }
  .cta svg { width:21px; height:21px; flex:none; }
  .ctacap { margin-top:11px; text-align:center; font-size:12px; color:var(--mute); line-height:1.5; }
  @media (prefers-reduced-motion: reduce) { .cta { transition:none; } }
</style>
</head>
<body>
  <div class="stage">
    <div class="card">
      <div class="eyebrow"><span class="live"></span>__LABEL__<span class="hint">__DATE__ · __TIME__</span></div>
      <div class="rev">__REV__<span class="cur">__CUR__</span></div>
      <div class="revsub"><span>__SUB__</span>__DELTA__</div>
      __SPARK__
      <div class="rule"></div>
      <a class="cta" href="__BOT__">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <path d="M4 8V6a2 2 0 0 1 2-2h2M16 4h2a2 2 0 0 1 2 2v2M20 16v2a2 2 0 0 1-2 2h-2M8 20H6a2 2 0 0 1-2-2v-2"/>
          <path d="M8 12h8M8 9h5M8 15h6"/>
        </svg>
        <span>Распознать накладную</span>
      </a>
      <div class="ctacap">откроется чат бота — пришли фото накладной</div>
    </div>
  </div>
</body>
</html>"""


def _widget_secret() -> bytes:
    # ENCRYPTION_KEY одинаков на локали и на проде → токен совпадает везде, без БД.
    return (os.getenv("WIDGET_SECRET") or os.getenv("ENCRYPTION_KEY") or "iiko-widget-fallback").encode()


def _widget_sign(uid: int) -> str:
    mac = hmac.new(_widget_secret(), f"widget:{uid}".encode(), hashlib.sha256).digest()
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
        "__LABEL__": label, "__DATE__": date_lbl, "__TIME__": time_lbl, "__BOT__": _WIDGET_BOT_URL,
    }.items():
        tpl = tpl.replace(k, v)
    return tpl


@router.get("/w/{token}")
async def widget_page(token: str):
    """Публичная страница-виджет (без Telegram-заголовка). Токен = авторизация."""
    import api
    uid = _uid_from_token(token)
    if uid is None:
        return HTMLResponse(_render({"connected": False}), status_code=404)
    cache_key = f"widgetpage:{token}"
    data = api._get_cached(cache_key)
    if data is None:
        data = await _gather(uid)
        api._set_cached(cache_key, data)
    return HTMLResponse(_render(data), headers={"Cache-Control": "max-age=120"})


@router.get("/w/{token}/{org_id}")
async def widget_page_branch(token: str, org_id: str):
    """То же, но по одному филиалу (org_id должен принадлежать владельцу токена)."""
    import api
    uid = _uid_from_token(token)
    if uid is None:
        return HTMLResponse(_render({"connected": False}), status_code=404)
    cache_key = f"widgetpage:{token}:{org_id}"
    data = api._get_cached(cache_key)
    if data is None:
        data = await _gather(uid, only_org=org_id)
        api._set_cached(cache_key, data)
    return HTMLResponse(_render(data), headers={"Cache-Control": "max-age=120"})


# ---- JSON для настоящего тайла (Scriptable / WidgetKit): виджет как «Погода» ----

async def _json_payload(token: str, only_org: Optional[str]):
    import api
    uid = _uid_from_token(token)
    if uid is None:
        return JSONResponse({"connected": False}, status_code=404)
    ck = f"widgetjson:{token}:{only_org or 'all'}"
    data = api._get_cached(ck)
    if data is None:
        data = await _gather(uid, only_org=only_org)
        api._set_cached(ck, data)
    return JSONResponse({**data, "bot": _WIDGET_BOT_URL},
                        headers={"Cache-Control": "max-age=120"})


@router.get("/api/widget/data/{token}")
async def widget_data(token: str):
    """Компактный JSON выручки (для Scriptable-виджета на домашний/локскрин)."""
    return await _json_payload(token, None)


@router.get("/api/widget/data/{token}/{org_id}")
async def widget_data_branch(token: str, org_id: str):
    return await _json_payload(token, org_id)
