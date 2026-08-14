"""Панель контроля журналов: /j/{token} — личная ссылка владельца без пароля.

Отдельный модуль-роутер, как widget_routes: подключается одним include_router и
не конфликтует при слиянии веток. Токен переиспользуем от виджета — механизм
подписанного stateless-uid уже отлажен, второй заводить незачем.

Считаем всё на сервере и отдаём странице готовую структуру: страница только
рисует. Так одна и та же арифметика «сдано N из M» не разъедется между
графом, списком и утренним отчётом в боте.
"""
import html
import json
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

import journals as J
from database import (get_all_restaurants, get_branch_managers, get_journal_entries,
                      get_journal_range, save_journal_entry)
from widget_routes import _uid_from_token, widget_token_for

router = APIRouter()

def _esc(t: str) -> str:
    """Текст владельца уходит в Telegram с parse_mode=HTML — экранируем, иначе
    одна угловая скобка обрушит всю рассылку.

    После экранирования возвращаем ровно один приём разметки: **жирный**.
    Порядок важен — сначала escape, потом разметка, иначе через «**» можно
    было бы протащить произвольный тег.
    """
    s = html.escape(t or "")
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s, flags=re.S)


_RU_DOW = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
_RU_MON = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
           "августа", "сентября", "октября", "ноября", "декабря"]


def journal_link_for(uid: int, base: str = "") -> str:
    return f"{base}/j/{widget_token_for(uid)}"


def short_name(full: str) -> str:
    """«Астана, ул. Бухар Жырау 36» → «Бухар Жырау». Узлу графа нужна короткая
    подпись, иначе они наезжают друг на друга."""
    s = (full or "").strip()
    for city in ("Астана,", "Актобе,", "Актау,", "Атырау,", "Костанай,"):
        if s.startswith(city):
            rest = s[len(city):].strip()
            s = rest if city == "Астана," else city.rstrip(",")
            break
    for p in ("ул.", "мкр", "микрорайон"):
        if s.startswith(p):
            s = s[len(p):].strip()
    # Скобки: короткое уточнение — это и есть народное имя филиала («EXPO»),
    # длинное — историческая справка («бывш. Чубары»), её выкидываем.
    m = re.search(r"\(([^)]*)\)", s)
    if m:
        inner = m.group(1).strip()
        s = inner if len(inner) <= 6 else s[:m.start()].strip()
    # Номер дома в подписи узла не нужен: «Бухар Жырау 36» → «Бухар Жырау».
    parts = s.split()
    if len(parts) > 1 and re.fullmatch(r"\d+[А-Яа-яA-Za-z]?", parts[-1]):
        s = " ".join(parts[:-1])
    return s[:18] or (full or "Филиал")[:18]


# Журналы ведут только филиалы Астаны — так решил владелец. Регионы остаются в
# выручке и накладных, но чистоту, температуру и остатки не сдают.
JOURNAL_CITY = "Астана"
# Оба на Алпамыс 61: заготовочный цех и распредцентр. Это не гостевые точки —
# зала и санузла для гостей там нет, а в знаменателе «сдано N из M» они
# завышали план на две трети слота.
JOURNAL_SKIP = ("(КЦ)", "(ЦЕХ)")


def in_journals(full: str) -> bool:
    s = full or ""
    return s.startswith(JOURNAL_CITY) and not any(m in s for m in JOURNAL_SKIP)


def _payload(row) -> Dict[str, Any]:
    try:
        return json.loads(row.get("payload") or "{}")
    except Exception:
        return {}


def build_board(uid: int, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Состояние сети на текущий час: филиалы, что сдано, где дыры."""
    import api  # ленивый импорт: избегаем цикла на загрузке
    now = now or api.local_now()
    day = now.date().isoformat()

    rests = [r for r in api.get_restaurants(uid)     # владелец — все свои, управляющий — свои
             if in_journals(r.get("organization_name"))]
    orgs = {r["organization_id"]: r for r in rests}
    mgrs = {m["organization_id"]: m for m in get_branch_managers()}
    entries = [e for e in get_journal_entries(day) if e["organization_id"] in orgs]

    due = J.due_items(now)                            # [(kind, zone, slot)]
    due_n = len(due)

    # штрафы за 7 дней: сколько положенных позиций не сдано
    since = (now.date() - timedelta(days=7)).isoformat()
    past = [e for e in get_journal_range(since, day) if e["organization_id"] in orgs]
    full_day = len(J.due_items(now.replace(hour=23, minute=59)))
    done_by_day: Dict[str, int] = {}
    for e in past:
        if e["day"] != day:                           # текущий день ещё не закончился
            done_by_day[f'{e["organization_id"]}|{e["day"]}'] = \
                done_by_day.get(f'{e["organization_id"]}|{e["day"]}', 0) + 1
    days_past = sorted({e["day"] for e in past if e["day"] != day})

    branches, gaps = [], []
    for org_id, r in orgs.items():
        full = r.get("organization_name") or "Филиал"
        mine = [e for e in entries if e["organization_id"] == org_id]
        have = {(e["kind"], e["zone"], e["slot"]) for e in mine if e["status"] == "ok"}
        done = sum(1 for d in due if d in have)

        mgr = mgrs.get(org_id)
        connected = bool(mgr)

        # температура: последний сданный замер и его нарушения
        temp_rows = {e["slot"]: _payload(e) for e in mine if e["kind"] == "temp"}
        alarms: List[Dict[str, Any]] = []
        for slot, vals in temp_rows.items():
            for a in J.temp_alarms(vals or {}):
                a["slot"] = slot
                alarms.append(a)

        if not connected:
            st = "off"
        elif alarms:
            st = "bad"
        elif done >= due_n:
            st = "ok"
        elif done == 0:
            st = "bad"
        else:
            st = "part"

        pen = 0
        for d in days_past:
            pen += J.penalty_for(full_day - done_by_day.get(f"{org_id}|{d}", 0))

        clean: Dict[str, Dict[str, str]] = {}
        for kind, zone, slot in due:
            if kind != "clean":
                continue
            clean.setdefault(slot, {})[zone] = "ok" if ("clean", zone, slot) in have else "none"

        branches.append({
            "org": org_id, "n": short_name(full), "full": full,
            "done": done, "of": due_n, "st": st,
            "penalty": pen, "who": (f"@{mgr.get('name')}" if mgr and mgr.get("name") else None),
            "clean": clean,
            "temp": {s: v for s, v in temp_rows.items()},
            "temp_alarms": alarms,
            "stock": ("stock", "", J.STOCK_SLOT) in have,
            # уже введённые остатки — форма подставит их, чтобы не набивать заново
            "stock_counts": next((_payload(e) for e in mine if e["kind"] == "stock"), {}),
        })

        # дыры — то, ради чего экран открывают
        if not connected:
            gaps.append({"b": short_name(full), "st": "off",
                         "what": "Управляющий не подключён — ссылка исчерпана",
                         "since": "—"})
            continue
        for a in alarms:
            sign = "+" if a["value"] > 0 else ""
            gaps.append({"b": short_name(full), "st": "bad",
                         "what": f'{a["title"]}: {sign}{a["value"]:g} °C при норме {a["norm"]}',
                         "since": f'с {a["slot"]}'})
        for kind, zone, slot in due:
            if (kind, zone, slot) in have:
                continue
            if kind == "clean":
                what = f'Чистота · {J.ZONES[zone]["title"]}, слот {slot} — не сдана'
            elif kind == "temp":
                what = f"Температура · замер {slot} — не сдан"
            else:
                what = "Остатки не сданы"
            gaps.append({"b": short_name(full), "st": "part", "what": what,
                         "since": f"с {slot}"})

    rank = {"bad": 0, "off": 1, "part": 2}
    gaps.sort(key=lambda g: rank.get(g["st"], 3))

    slots = []
    for slot in sorted(set(J.CLEAN_SLOTS + J.TEMP_SLOTS), key=lambda s: J._hm(s)):
        items = [d for d in J.due_items(now.replace(hour=23, minute=59)) if d[2] == slot]
        of = len(items) * len(orgs)
        got = sum(1 for e in entries
                  if (e["kind"], e["zone"], e["slot"]) in {(i[0], i[1], i[2]) for i in items}
                  and e["status"] == "ok")
        is_due = J.slot_is_due(slot, now)
        what = []
        if slot in J.CLEAN_SLOTS:
            what.append("Чистота · зал, кухня, санузел")
        if slot in J.TEMP_SLOTS:
            what.append(f"Температура · {len(J.CAMERAS)} камер")
        slots.append({
            "t": slot, "what": " + ".join(what), "done": got, "of": of,
            "state": ("wait" if not is_due else ("done" if got >= of else "part")),
            "now": False,          # проставляется ниже: «сейчас» = последний наступивший
        })
    # «сейчас» — последний наступивший слот
    live = [s for s in slots if J.slot_is_due(s["t"], now)]
    for s in slots:
        s["now"] = bool(live) and s["t"] == live[-1]["t"]

    return {
        "day": day,
        "now": now.strftime("%H:%M"),
        "date_label": f"{_RU_DOW[now.weekday()]}, {now.day} {_RU_MON[now.month - 1]}",
        "due_n": due_n,
        "slots": slots,
        "branches": branches,
        "gaps": gaps,
        "cameras": J.CAMERAS,
        "norms": J.NORMS,
        "zones": {k: {"title": v["title"], "emoji": v["emoji"]} for k, v in J.ZONES.items()},
        "stock_places": [{"key": p["key"], "title": p["title"], "items": p["items"]}
                         for p in J.STOCK_PLACES],
    }


@router.get("/api/journals/data/{token}")
async def journals_data(token: str):
    uid = _uid_from_token(token)
    if not uid:
        return JSONResponse({"error": "bad token"}, status_code=404)
    try:
        return JSONResponse(build_board(uid))
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/api/journals/stock/{token}")
async def journals_stock(token: str, body: Dict[str, Any]):
    """Остатки вводятся на сайте: в чате 9 мест по 25 позиций никто не заполнит."""
    uid = _uid_from_token(token)
    if not uid:
        return JSONResponse({"error": "bad token"}, status_code=404)
    import api
    org = str(body.get("org") or "")
    allowed = {r["organization_id"] for r in api.get_restaurants(uid)}
    if org not in allowed:
        return JSONResponse({"error": "нет доступа к филиалу"}, status_code=403)
    day = api.local_now().date().isoformat()
    save_journal_entry(org, "stock", "", J.STOCK_SLOT, day, uid,
                       json.dumps(body.get("counts") or {}, ensure_ascii=False))
    return JSONResponse({"ok": True})


HELP = [
    "просто текст          — уйдёт всем управляющим в Telegram",
    "/кто                  — кто подключён к филиалам",
    "/напомнить            — повторить задание текущего слота тем, кто не сдал",
    "/филиал <часть> <текст> — написать одному филиалу",
    "/оживить <часть>      — сбросить счётчик исчерпанной ссылки",
    "/помощь               — этот список",
]


def _owner_orgs(uid: int) -> List[Dict[str, Any]]:
    """Филиалы, которыми человек распоряжается в консоли.

    Берём тот же источник, что и панель — get_restaurants(uid). Через
    get_all_restaurants() нельзя: она схлопывает дубли по организации, а на
    проде одна и та же точка заведена под несколькими аккаунтами, и владелец
    в отфильтрованном списке просто не находился.

    Область действия команд равна тому, что человек и так видит на экране:
    написать можно только управляющим своих филиалов.
    """
    import api
    return [r for r in api.get_restaurants(int(uid))
            if in_journals(r.get("organization_name"))]


def _managers_of(orgs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    keys = {r["organization_id"] for r in orgs}
    return [m for m in get_branch_managers() if m["organization_id"] in keys]


@router.post("/api/journals/say/{token}")
async def journals_say(token: str, body: Dict[str, Any]):
    """Командная строка панели: свободный текст — рассылка, «/» — команда.

    Пишет только владелец: у управляющего в restaurants своих строк нет, и
    список филиалов для него окажется пустым.
    """
    uid = _uid_from_token(token)
    if not uid:
        return JSONResponse({"error": "bad token"}, status_code=404)
    import api
    from database import set_app_state

    text = (body.get("text") or "").strip()
    if not text:
        return JSONResponse({"log": []})
    orgs = _owner_orgs(uid)
    if not orgs:
        # Показываем, что именно увидел сервер: «доступ запрещён» без цифр
        # заставляет гадать, а на проде и в копии базы данные разные.
        allr = api.get_all_restaurants()
        mine = [r for r in allr if str(r.get("telegram_id")) == str(uid)]
        return JSONResponse({"log": [
            ["err", "Команды доступны владельцу сети."],
            ["info", f"uid={uid} · всего точек {len(allr)} · ваших {len(mine)} · "
                     f"из них в журналах {sum(1 for r in mine if in_journals(r.get('organization_name')))}"],
        ]})

    by_org = {r["organization_id"]: r for r in orgs}
    mgrs = _managers_of(orgs)
    log: List[List[str]] = []

    async def send(tg_id: int, msg: str, kb: Optional[dict] = None) -> bool:
        try:
            await api._tg_send(int(tg_id), msg, kb)
            return True
        except Exception as e:
            log.append(["err", f"{tg_id}: {e!r}"[:160]])
            return False

    if not text.startswith("/"):
        if not mgrs:
            return JSONResponse({"log": [["err", "Ни один управляющий не подключён — писать некому."]]})
        # Без шапки: владелец пишет живым людям, а не рассылает циркуляр.
        # Приписка «Сообщение от руководства» к каждой строчке только мешает.
        head = ""
        sent = 0
        # Один человек может вести два филиала — шлём ему ОДНО сообщение,
        # а не по копии на каждый адрес.
        seen: set = set()
        for m in mgrs:
            tg = int(m["telegram_id"])
            if tg in seen:
                continue
            seen.add(tg)
            where = ", ".join(short_name(by_org[x["organization_id"]].get("organization_name"))
                              for x in mgrs if int(x["telegram_id"]) == tg)
            if await send(tg, head + _esc(text)):
                sent += 1
                log.append(["ok", f'→ {where} · @{m.get("name") or tg}'])
        log.append(["info", f"Отправлено получателям: {sent}"])
        return JSONResponse({"log": log})

    parts = text.split(maxsplit=1)
    cmd = parts[0].lower().lstrip("/")
    rest = parts[1].strip() if len(parts) > 1 else ""

    if cmd in ("помощь", "help", "?"):
        return JSONResponse({"log": [["info", h] for h in HELP]})

    if cmd in ("кто", "who"):
        for r in orgs:
            who = [m for m in mgrs if m["organization_id"] == r["organization_id"]]
            name = short_name(r.get("organization_name"))
            if who:
                log.append(["ok", f'{name} — ' + ", ".join(
                    f'@{m.get("name") or m["telegram_id"]}' for m in who)])
            else:
                log.append(["err", f"{name} — управляющий не подключён"])
        return JSONResponse({"log": log})

    if cmd in ("оживить", "ozhivit", "reset"):
        if not rest:
            return JSONResponse({"log": [["err", "Укажите филиал: /оживить кажымукана"]]})
        hit = [r for r in orgs if rest.lower() in (r.get("organization_name") or "").lower()]
        if len(hit) != 1:
            return JSONResponse({"log": [["err",
                "Не нашёл филиал" if not hit else "Под описание попало несколько — уточните"]]})
        set_app_state(f'invite_used:{hit[0]["organization_id"]}', "")
        return JSONResponse({"log": [
            ["ok", f'{short_name(hit[0].get("organization_name"))} — счётчик сброшен'],
            ["info", api.invite_link_for(hit[0]["organization_id"])]]})

    if cmd in ("филиал", "branch"):
        bits = rest.split(maxsplit=1)
        if len(bits) < 2:
            return JSONResponse({"log": [["err", "Формат: /филиал кажымукана текст сообщения"]]})
        hit = [r for r in orgs if bits[0].lower() in (r.get("organization_name") or "").lower()]
        if len(hit) != 1:
            return JSONResponse({"log": [["err",
                "Не нашёл филиал" if not hit else "Под описание попало несколько — уточните"]]})
        who = [m for m in mgrs if m["organization_id"] == hit[0]["organization_id"]]
        if not who:
            return JSONResponse({"log": [["err", "К этому филиалу никто не подключён"]]})
        for m in who:
            await send(m["telegram_id"], "📣 <b>Сообщение от руководства</b>\n\n" + _esc(bits[1]))
        log.append(["ok", f'{short_name(hit[0].get("organization_name"))} — отправлено'])
        return JSONResponse({"log": log})

    if cmd in ("напомнить", "remind"):
        now = api.local_now()
        due = J.due_items(now)
        if not due:
            return JSONResponse({"log": [["info", "Сейчас нечего напоминать — слоты ещё не наступили."]]})
        slot = max((d[2] for d in due), key=lambda s: J._hm(s))
        day = now.date().isoformat()
        entries = get_journal_entries(day)
        n = 0
        for m in mgrs:
            org = m["organization_id"]
            have = {(e["kind"], e["zone"], e["slot"]) for e in entries
                    if e["organization_id"] == org and e["status"] == "ok"}
            missing = [d for d in due if d[2] == slot and d not in have]
            if not missing:
                continue
            if await send(m["telegram_id"], api.journal_slot_message(slot, missing),
                          api._journal_kb(slot, missing, org)):
                n += 1
                log.append(["ok", f"→ {short_name(by_org[org].get('organization_name'))}"
                                  f" · не сдано {len(missing)}"])
        log.append(["info", f"Напоминание по слоту {slot}: {n} получателей"])
        return JSONResponse({"log": log})

    return JSONResponse({"log": [["err", f"Неизвестная команда «{cmd}». /помощь — список."]]})


@router.get("/j/{token}")
async def journals_page(token: str):
    if not _uid_from_token(token):
        return HTMLResponse("<h1>Ссылка недействительна</h1>", status_code=404)
    return HTMLResponse(PAGE.replace("__TOKEN__", token))


PAGE = r'''<!doctype html>
<html lang="ru"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Журналы">
<title>Журналы · Астана</title>
<style>

  /* Приборная панель. Хром обесцвечен полностью: цвет несёт только смысл —
     зелёный «сдано», красный «проблема», всё остальное серое. Полный набор
     токенов в :root, тёмная тема только переопределяет их. */
  :root{
    --ground:#EDEFF1; --surface:#FFFFFF; --surface-2:#F4F6F7; --inset:#E7EAEC;
    --line:#D2D7DB; --line-2:#E3E7EA;
    --ink:#101416; --ink-2:#4C555B; --ink-3:#79838A;
    --sel:#101416; --sel-bg:#E7EAEC;
    --ok:#1D7A48; --ok-bg:#DFEFE6;
    --crit:#B23A2B; --crit-bg:#F7E1DD; --idle:#A7B0B6;
    --mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,"Liberation Mono","DejaVu Sans Mono",monospace;
  }
  @media (prefers-color-scheme:dark){
    :root:not([data-theme="light"]){
      --ground:#0E1113; --surface:#161A1D; --surface-2:#1C2125; --inset:#101315;
      --line:#282E33; --line-2:#20262A;
      --ink:#E8ECEF; --ink-2:#97A1A9; --ink-3:#616B73;
      --sel:#E8ECEF; --sel-bg:#232A2E;
      --ok:#3FA76A; --ok-bg:#12271C;
      --crit:#E0503F; --crit-bg:#2B1512; --idle:#394248;
    }
  }
  :root[data-theme="dark"]{
    --ground:#0E1113; --surface:#161A1D; --surface-2:#1C2125; --inset:#101315;
    --line:#282E33; --line-2:#20262A;
    --ink:#E8ECEF; --ink-2:#97A1A9; --ink-3:#616B73;
    --sel:#E8ECEF; --sel-bg:#232A2E;
    --ok:#3FA76A; --ok-bg:#12271C;
    --crit:#E0503F; --crit-bg:#2B1512; --idle:#394248;
  }

  *{box-sizing:border-box}
  html{background:var(--ground)}
  body{
    margin:0;background:var(--ground);color:var(--ink);
    font-family:var(--mono);font-size:13px;line-height:1.5;
    -webkit-font-smoothing:antialiased;font-variant-numeric:tabular-nums;
    padding-bottom:34px;
  }
  .wrap{max-width:1160px;margin:0 auto;padding:16px 14px 22px;display:flex;flex-direction:column;gap:12px}

  /* ── рамка панели: острые углы + угловые засечки, как в TUI ── */
  .box{position:relative;background:var(--surface);border:1px solid var(--line)}
  .box::before,.box::after{
    content:"";position:absolute;width:7px;height:7px;border:1px solid var(--ink-3);opacity:.5;
  }
  .box::before{top:-1px;left:-1px;border-right:0;border-bottom:0}
  .box::after{bottom:-1px;right:-1px;border-left:0;border-top:0}
  .box-h{
    display:flex;align-items:center;justify-content:space-between;gap:10px;
    padding:7px 12px;border-bottom:1px solid var(--line-2);background:var(--surface-2);
  }
  .box-b{padding:12px}
  .tag{
    font-size:10.5px;letter-spacing:.16em;text-transform:uppercase;color:var(--ink-3);
  }
  .tag b{color:var(--ink);font-weight:500}

  /* ── шапка ── */
  header{display:flex;flex-wrap:wrap;align-items:flex-end;justify-content:space-between;gap:10px;
    padding:2px 2px 4px;border-bottom:1px solid var(--line)}
  h1{margin:0;font-size:clamp(15px,2.6vw,19px);font-weight:600;letter-spacing:.06em;text-transform:uppercase}
  .sub{color:var(--ink-3);font-size:11px;letter-spacing:.1em;text-transform:uppercase;margin-top:5px}
  .hdr-r{text-align:right;font-size:11.5px;color:var(--ink-2);letter-spacing:.06em}
  .hdr-r b{color:var(--ink);font-weight:600}

  /* ── лента слотов ── */
  .rail{display:grid;grid-template-columns:repeat(auto-fit,minmax(158px,1fr));gap:1px;background:var(--line-2)}
  .slot{background:var(--surface);padding:9px 11px;display:flex;flex-direction:column;gap:5px}
  .slot.now{background:var(--sel-bg);box-shadow:inset 2px 0 0 var(--ink)}
  .slot-t{font-size:14px;font-weight:600;letter-spacing:.04em}
  .slot.now .slot-t{color:var(--ink)}
  .slot-w{font-size:10.5px;color:var(--ink-3);line-height:1.35;min-height:2.7em}
  .meter{font-size:11px;letter-spacing:-.04em;white-space:nowrap;overflow:hidden}
  .meter .f{color:var(--ok)} .meter .p{color:var(--ink-2)} .meter .e{color:var(--line)}
  .slot-n{font-size:10.5px;color:var(--ink-2)}

  /* ── доска ── */
  .board{display:grid;grid-template-columns:minmax(0,1.5fr) minmax(0,1fr);gap:12px;align-items:start}
  @media (max-width:900px){.board{grid-template-columns:1fr}}

  .seg{display:flex;border:1px solid var(--line)}
  .seg button{
    font-family:var(--mono);font-size:10px;letter-spacing:.14em;text-transform:uppercase;
    border:0;background:transparent;color:var(--ink-3);padding:4px 10px;cursor:pointer;
  }
  .seg button+button{border-left:1px solid var(--line)}
  .seg button[aria-pressed="true"]{background:var(--ink);color:var(--surface)}
  .seg button:focus-visible{outline:2px solid var(--ink);outline-offset:2px}

  svg.graph{display:block;width:100%;height:auto;background:var(--inset)}
  .edge{stroke:var(--line);stroke-width:1;stroke-dasharray:2 4;fill:none}
  .edge.hot{stroke:var(--crit);opacity:.8;stroke-dasharray:3 3}
  .grid-l{stroke:var(--line-2);stroke-width:1}
  .node{cursor:pointer}
  .node:focus{outline:none}
  .node:focus-visible .hit{stroke:var(--ink);stroke-width:2}
  .nbg{fill:var(--surface);stroke:var(--line);stroke-width:1}
  .node.sel .nbg{stroke:var(--sel);stroke-width:2}
  .track{fill:none;stroke:var(--line-2);stroke-width:3}
  .arc{fill:none;stroke-width:3}
  .arc.ok{stroke:var(--ok)}.arc.part{stroke:var(--ink-2)}.arc.bad{stroke:var(--crit)}.arc.off{stroke:var(--idle)}
  .nnum{font-family:var(--mono);font-size:11.5px;font-weight:600;text-anchor:middle;fill:var(--ink)}
  .nname{font-family:var(--mono);font-size:9.5px;letter-spacing:.08em;text-anchor:middle;fill:var(--ink-2)}
  .cnum{font-family:var(--mono);font-size:18px;font-weight:600;text-anchor:middle;fill:var(--ink)}
  .ccap{font-family:var(--mono);font-size:8.5px;letter-spacing:.22em;text-anchor:middle;fill:var(--ink-3)}
  .halo{fill:none;stroke:var(--crit);stroke-width:1}
  @media (prefers-reduced-motion:no-preference){.node.alarm .halo{animation:ping 2.2s ease-out infinite}}
  @keyframes ping{0%{r:26;opacity:.6}100%{r:44;opacity:0}}

  .legend{display:flex;flex-wrap:wrap;gap:14px;padding:8px 12px;border-top:1px solid var(--line-2)}
  .lg{display:flex;align-items:center;gap:6px;font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--ink-3)}
  .sw{width:8px;height:8px;flex:none}

  table{width:100%;border-collapse:collapse;font-size:12px}
  th{text-align:left;font-size:9.5px;letter-spacing:.14em;text-transform:uppercase;color:var(--ink-3);
     font-weight:400;padding:0 8px 7px}
  td{padding:6px 8px;border-top:1px solid var(--line-2)}
  td.n{text-align:right}
  tr.row{cursor:pointer}
  tr.row:hover td{background:var(--surface-2)}
  tr.row.sel td{background:var(--sel-bg)}

  .st{display:inline-block;padding:1px 7px;font-size:10px;letter-spacing:.1em;text-transform:uppercase}
  .st.ok{background:var(--ok-bg);color:var(--ok)}
  .st.part{background:var(--surface-2);color:var(--ink-2)}
  .st.bad{background:var(--crit-bg);color:var(--crit)}
  .st.off{background:var(--surface-2);color:var(--ink-3)}

  /* ── панель филиала ── */
  .p-t{font-size:14px;font-weight:600;letter-spacing:.05em;text-transform:uppercase}
  .p-s{font-size:10.5px;color:var(--ink-3);letter-spacing:.08em;margin-top:3px}
  .grp{margin-top:13px;padding-top:10px;border-top:1px solid var(--line-2)}
  .grp:first-of-type{border-top:0}
  .grp-h{display:flex;align-items:baseline;justify-content:space-between;gap:8px;margin-bottom:7px}
  .grp-n{font-size:9.5px;letter-spacing:.18em;text-transform:uppercase;color:var(--ink-3)}
  .row2{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:2.5px 0;font-size:12px}
  .row2 .l{display:flex;align-items:center;gap:7px;min-width:0}
  .pip{width:6px;height:6px;flex:none}
  .pip.ok{background:var(--ok)}.pip.bad{background:var(--crit)}.pip.off{background:var(--idle)}
  .nm{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--ink-2)}
  .v{font-size:11.5px;color:var(--ink-3);white-space:nowrap}
  .v.bad{color:var(--crit);font-weight:600}.v.ok{color:var(--ok)}
  .empty{color:var(--ink-3);font-size:12px;padding:22px 0;text-align:center;line-height:1.7}
  kbd{background:var(--surface-2);border:1px solid var(--line);padding:1px 5px;color:var(--ink)}

  /* ── журнал событий ── */
  .log{display:flex;flex-direction:column}
  .le{display:flex;align-items:baseline;gap:10px;padding:6px 12px;border-top:1px solid var(--line-2);font-size:12px}
  .le:first-child{border-top:0}
  .lv{font-size:10px;letter-spacing:.1em;flex:none;width:52px}
  .lv.crit{color:var(--crit)}.lv.warn{color:var(--ink-2)}.lv.info{color:var(--ink-3)}
  .lb{flex:none;width:112px;color:var(--ink);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .lw{flex:1;color:var(--ink-2);min-width:0}
  .lt{flex:none;color:var(--ink-3);font-size:11px}
  @media (max-width:620px){.lb{width:auto}.le{flex-wrap:wrap}}

  /* ── статус-строка ── */
  .status{
    position:fixed;left:0;right:0;bottom:0;z-index:50;background:var(--surface-2);
    color:var(--ink-2);border-top:1px solid var(--line);
    font-size:10.5px;letter-spacing:.13em;text-transform:uppercase;
    display:flex;gap:18px;padding:6px 14px;overflow-x:auto;white-space:nowrap;
  }
  .status .sp{margin-left:auto}
  footer{color:var(--ink-3);font-size:11px;line-height:1.7;padding-top:10px;border-top:1px solid var(--line)}

  /* ── остатки ── */
let PLACE=0, COUNTS={};
function stockRender(){
  const b=DATA.branches.find(x=>x.org===CUR);
  document.getElementById("st-b").textContent=b?b.n:"—";
  const places=DATA.stock_places;
  document.getElementById("st-places").innerHTML=places.map((p,i)=>{
    const c=Object.keys(COUNTS[p.key]||{}).length;
    return '<button type="button" aria-pressed="'+(i===PLACE)+'" data-i="'+i+'">'+
      esc(p.title)+(c?' <span class="c">'+c+'</span>':'')+'</button>';}).join("");
  document.querySelectorAll("#st-places button").forEach(x=>x.addEventListener("click",()=>{
    PLACE=+x.dataset.i; stockRender();}));
  const p=places[PLACE], have=COUNTS[p.key]||{};
  document.getElementById("st-items").innerHTML=p.items.map(it=>{
    const v=have[it]??"";
    return '<div class="it'+(v!==""?" filled":"")+'"><label for="i-'+esc(it)+'">'+esc(it)+
      '</label><input id="i-'+esc(it)+'" type="number" step="any" inputmode="decimal" value="'+
      esc(v)+'" data-k="'+esc(it)+'"></div>';}).join("");
  document.querySelectorAll("#st-items input").forEach(inp=>inp.addEventListener("input",()=>{
    COUNTS[p.key]=COUNTS[p.key]||{};
    if(inp.value==="")delete COUNTS[p.key][inp.dataset.k];
    else COUNTS[p.key][inp.dataset.k]=parseFloat(inp.value);
    inp.parentElement.classList.toggle("filled",inp.value!=="");
    stockSum();
  }));
  stockSum();
}
function stockSum(){
  const total=DATA.stock_places.reduce((a,p)=>a+p.items.length,0);
  const done=Object.values(COUNTS).reduce((a,o)=>a+Object.keys(o).length,0);
  document.getElementById("st-sum").textContent="заполнено "+done+" из "+total;
}
document.getElementById("st-save").addEventListener("click",async()=>{
  if(!CUR){document.getElementById("st-msg").textContent="сначала выберите филиал";return;}
  const btn=document.getElementById("st-save"), msg=document.getElementById("st-msg");
  btn.disabled=true; msg.textContent="сохраняю…";
  try{
    const r=await fetch("/api/journals/stock/"+TOKEN,{method:"POST",
      headers:{"content-type":"application/json"},
      body:JSON.stringify({org:CUR,counts:COUNTS})});
    const j=await r.json();
    msg.textContent=j.ok?"сохранено в "+new Date().toLocaleTimeString("ru").slice(0,5):("ошибка: "+(j.error||""));
    if(j.ok)load();
  }catch(e){msg.textContent="сеть недоступна";}
  btn.disabled=false;
});

/* ── консоль ── */
  .con{display:flex;flex-direction:column;gap:0}
  .con-out{max-height:210px;overflow-y:auto;padding:8px 12px;display:flex;flex-direction:column;gap:2px}
  .cl{font-size:11.5px;display:flex;gap:8px}
  .cl .p{flex:none;color:var(--ink-3)}
  .cl.ok .t{color:var(--ok)} .cl.err .t{color:var(--crit)} .cl.info .t{color:var(--ink-2)}
  .cl.me .t{color:var(--ink)}
  .con-in{display:flex;align-items:center;gap:8px;border-top:1px solid var(--line-2);padding:8px 12px}
  .con-in span{color:var(--ink-3);flex:none}
  .con-in input{
    flex:1;min-width:0;background:transparent;border:0;outline:none;color:var(--ink);
    font-family:var(--mono);font-size:13px;
  }
  .con-in button{
    font-family:var(--mono);font-size:10px;letter-spacing:.14em;text-transform:uppercase;
    background:var(--ink);color:var(--surface);border:0;padding:5px 12px;cursor:pointer;flex:none;
  }
  .con-in button:disabled{opacity:.45;cursor:default}
  .hint{padding:0 12px 9px;font-size:10.5px;color:var(--ink-3);line-height:1.6}
  /* ── остатки ── */
  .pl{display:flex;flex-wrap:wrap;gap:1px;background:var(--line-2);border-bottom:1px solid var(--line-2)}
  .pl button{
    flex:1 1 auto;font-family:var(--mono);font-size:10px;letter-spacing:.08em;text-transform:uppercase;
    background:var(--surface);color:var(--ink-3);border:0;padding:7px 9px;cursor:pointer;text-align:left;
  }
  .pl button[aria-pressed="true"]{background:var(--sel-bg);color:var(--ink);box-shadow:inset 2px 0 0 var(--ink)}
  .pl button .c{color:var(--ok)}
  .items2{display:grid;grid-template-columns:repeat(auto-fill,minmax(232px,1fr));gap:1px;background:var(--line-2)}
  .it{display:flex;align-items:center;gap:8px;background:var(--surface);padding:6px 10px}
  .it label{flex:1;min-width:0;font-size:12px;color:var(--ink-2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .it input{
    width:74px;flex:none;background:var(--inset);border:1px solid var(--line);color:var(--ink);
    font-family:var(--mono);font-size:12.5px;padding:3px 6px;text-align:right;
  }
  .it input:focus{outline:1px solid var(--ink);border-color:var(--ink)}
  .it.filled input{border-color:var(--ok);color:var(--ok)}
  .save{display:flex;align-items:center;gap:12px;padding:9px 12px;border-top:1px solid var(--line-2)}
  .save button{
    font-family:var(--mono);font-size:10px;letter-spacing:.14em;text-transform:uppercase;
    background:var(--ink);color:var(--surface);border:0;padding:7px 16px;cursor:pointer;
  }
  .save button:disabled{opacity:.45;cursor:default}
  .save .msg{font-size:11px;color:var(--ink-3)}
  .load{padding:36px 0;text-align:center;color:var(--ink-3);font-size:12px;letter-spacing:.1em;text-transform:uppercase}
</style></head><body>
<div class="wrap">
  <header>
    <div><h1>Журналы · Астана</h1><div class="sub" id="sub">загрузка…</div></div>
    <div class="hdr-r" id="hdr"></div>
  </header>

  <div class="box">
    <div class="box-h"><span class="tag">Слоты <b>сегодня</b></span><span class="tag" id="slot-sum"></span></div>
    <div class="rail" id="rail"></div>
  </div>

  <div class="board">
    <div class="box">
      <div class="box-h"><span class="tag">Карта <b>сети</b></span>
        <div class="seg" role="group" aria-label="Вид">
          <button id="v-graph" aria-pressed="true">Граф</button>
          <button id="v-list" aria-pressed="false">Список</button>
        </div></div>
      <div id="view-graph"><svg class="graph" viewBox="0 0 720 530" role="img"
        aria-label="Граф филиалов со статусом сдачи журналов"><g id="g"></g></svg></div>
      <div id="view-list" class="box-b" hidden>
        <table><thead><tr><th>Филиал</th><th>Статус</th><th class="n">Сдано</th>
          <th class="n">Штраф 7д</th></tr></thead><tbody id="tbody"></tbody></table>
      </div>
      <div class="legend">
        <span class="lg"><span class="sw" style="background:var(--ok)"></span>сдано</span>
        <span class="lg"><span class="sw" style="background:var(--ink-2)"></span>частично</span>
        <span class="lg"><span class="sw" style="background:var(--crit)"></span>брак / просрочка</span>
        <span class="lg"><span class="sw" style="background:var(--idle)"></span>нет управляющего</span>
      </div>
    </div>
    <div class="box">
      <div class="box-h"><span class="tag">Филиал</span><span class="tag" id="pen"></span></div>
      <div class="box-b" id="panel"><div class="load">выберите узел</div></div>
    </div>
  </div>

  <div class="box">
    <div class="box-h"><span class="tag">Журнал <b>событий</b></span><span class="tag" id="log-sum"></span></div>
    <div class="log" id="log"></div>
  </div>

  <div class="box">
    <div class="box-h"><span class="tag">Остатки <b id="st-b">—</b></span>
      <span class="tag" id="st-sum"></span></div>
    <div class="pl" id="st-places"></div>
    <div class="items2" id="st-items"></div>
    <div class="save"><button id="st-save" type="button">Сохранить</button>
      <span class="msg" id="st-msg">заполняются раз в день, по местам хранения</span></div>
  </div>

  <div class="box con">
    <div class="box-h"><span class="tag">Связь <b>с филиалами</b></span>
      <span class="tag" id="con-n"></span></div>
    <div class="con-out" id="con-out"></div>
    <form class="con-in" id="con-form">
      <span>&gt;</span>
      <input id="con-inp" autocomplete="off" placeholder="сообщение всем управляющим или /команда"
             aria-label="Сообщение или команда">
      <button type="submit" id="con-btn">Отправить</button>
    </form>
    <div class="hint">Свободный текст уходит всем управляющим в Telegram.
      Команды: <b>/кто</b> · <b>/напомнить</b> · <b>/филиал</b> · <b>/оживить</b> · <b>/помощь</b></div>
  </div>
</div>
<div class="status"><span id="s1"></span><span id="s2"></span><span id="s3"></span>
  <span class="sp" id="s4"></span></div>

<script>
const TOKEN="__TOKEN__";
let DATA=null, CUR=null;
const NS="http://www.w3.org/2000/svg";
const el=(t,a={})=>{const n=document.createElementNS(NS,t);for(const k in a)n.setAttribute(k,a[k]);return n;};
const esc=s=>String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const bar=(d,o,w=14)=>{if(!o)return '<span class="e">'+"░".repeat(w)+'</span>';
  const f=Math.max(0,Math.min(w,Math.round(w*d/o)));
  return '<span class="'+(d>=o?"f":"p")+'">'+"█".repeat(f)+'</span><span class="e">'+"░".repeat(w-f)+'</span>';};

async function load(){
  const r=await fetch("/api/journals/data/"+TOKEN,{cache:"no-store"});
  DATA=await r.json();
  if(DATA.error){document.getElementById("sub").textContent="ошибка: "+DATA.error;return;}
  render();
}

function render(){
  const D=DATA, B=D.branches;
  document.getElementById("sub").textContent="Контроль сдачи · "+B.length+" филиалов";
  document.getElementById("hdr").innerHTML=esc(D.date_label)+"<br><b>"+esc(D.now)+"</b> · Астана UTC+5";
  const tot=B.reduce((a,b)=>a+b.done,0), of=B.length*D.due_n;
  document.getElementById("slot-sum").textContent="сдано "+tot+" из "+of;

  document.getElementById("rail").innerHTML=D.slots.map(s=>
    '<div class="slot'+(s.now?" now":"")+'"><div class="slot-t">'+esc(s.t)+'</div>'+
    '<div class="slot-w">'+esc(s.what)+'</div><div class="meter">'+
    (s.state==="wait"?bar(0,0):bar(s.done,s.of))+'</div><div class="slot-n">'+
    (s.state==="wait"?"ещё не время":s.done+" / "+s.of)+'</div></div>').join("");

  document.getElementById("tbody").innerHTML=B.map(b=>{
    const L={ok:"сдано",part:"частично",bad:"брак",off:"нет упр."}[b.st];
    return '<tr class="row" data-id="'+esc(b.org)+'"><td>'+esc(b.full)+'</td>'+
      '<td><span class="st '+b.st+'">'+L+'</span></td><td class="n">'+
      (b.st==="off"?"—":b.done+"/"+b.of)+'</td><td class="n">'+(b.penalty||"—")+'</td></tr>';}).join("");
  document.querySelectorAll("tr.row").forEach(r=>r.addEventListener("click",()=>sel(r.dataset.id)));

  drawGraph();
  document.getElementById("log").innerHTML=D.gaps.length?D.gaps.map(g=>{
    const lv=g.st==="bad"||g.st==="off"?"crit":"warn";
    return '<div class="le"><span class="lv '+lv+'">['+lv.toUpperCase()+']</span><span class="lb">'+
      esc(g.b)+'</span><span class="lw">'+esc(g.what)+'</span><span class="lt">'+esc(g.since)+'</span></div>';
  }).join(""):'<div class="load">всё сдано, отклонений нет</div>';
  document.getElementById("log-sum").textContent=D.gaps.length+" записей";

  const crit=D.gaps.filter(g=>g.st==="bad"||g.st==="off").length;
  document.getElementById("s1").textContent="Астана · "+B.length+" филиалов";
  document.getElementById("s2").textContent="сдано "+tot+"/"+of;
  document.getElementById("s3").textContent="crit "+crit+" · warn "+(D.gaps.length-crit);
  document.getElementById("s4").textContent="обновлено "+D.now;
  document.getElementById("con-n").textContent=B.filter(b=>b.who).length+" на связи";
  if(!CUR&&B.length) sel((B.find(b=>b.st==="bad")||B[0]).org);
}

const CX=360,CY=262,R=178;
function drawGraph(){
  const B=DATA.branches,g=document.getElementById("g");g.textContent="";
  const pts=B.map((b,i)=>{const a=(-90+i*(360/B.length))*Math.PI/180;
    return {b,x:CX+R*Math.cos(a),y:CY+R*Math.sin(a)};});
  [86,132,178].forEach(r=>g.appendChild(el("circle",{cx:CX,cy:CY,r,class:"grid-l",fill:"none"})));
  pts.forEach(p=>g.appendChild(el("path",{class:"edge"+(p.b.st==="bad"||p.b.st==="off"?" hot":""),
    d:"M"+CX+" "+CY+"L"+p.x+" "+p.y})));
  g.appendChild(el("circle",{cx:CX,cy:CY,r:42,class:"nbg"}));
  const tot=B.reduce((a,b)=>a+b.done,0);
  const t1=el("text",{x:CX,y:CY+1,class:"cnum"});t1.textContent=tot+"/"+(B.length*DATA.due_n);
  const t2=el("text",{x:CX,y:CY+18,class:"ccap"});t2.textContent="СДАНО";
  g.appendChild(t1);g.appendChild(t2);
  pts.forEach(p=>{
    const b=p.b,r=22,C=2*Math.PI*(r+4);
    const grp=el("g",{class:"node"+(b.st==="bad"?" alarm":"")+(b.org===CUR?" sel":""),
      tabindex:"0",role:"button","aria-label":b.full+": сдано "+b.done+" из "+b.of});
    grp.dataset.id=b.org;
    if(b.st==="bad")grp.appendChild(el("circle",{cx:p.x,cy:p.y,r:26,class:"halo"}));
    grp.appendChild(el("circle",{cx:p.x,cy:p.y,r,class:"nbg"}));
    grp.appendChild(el("circle",{cx:p.x,cy:p.y,r:r+4,class:"track"}));
    const f=b.of?b.done/b.of:0;
    if(f>0)grp.appendChild(el("circle",{cx:p.x,cy:p.y,r:r+4,class:"arc "+b.st,
      "stroke-dasharray":(C*f)+" "+C,transform:"rotate(-90 "+p.x+" "+p.y+")"}));
    grp.appendChild(el("circle",{cx:p.x,cy:p.y,r:r+4,class:"hit",fill:"none",stroke:"transparent"}));
    const n1=el("text",{x:p.x,y:p.y+4,class:"nnum"});n1.textContent=b.st==="off"?"—":b.done+"/"+b.of;
    const n2=el("text",{x:p.x,y:p.y+r+17,class:"nname"});n2.textContent=b.n.toUpperCase();
    grp.appendChild(n1);grp.appendChild(n2);
    grp.addEventListener("click",()=>sel(b.org));
    grp.addEventListener("keydown",e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();sel(b.org);}});
    g.appendChild(grp);
  });
}

function sel(org){
  CUR=org;
  const b=DATA.branches.find(x=>x.org===org); if(!b)return;
  COUNTS=JSON.parse(JSON.stringify(b.stock_counts||{})); stockRender();
  document.querySelectorAll(".node").forEach(n=>n.classList.toggle("sel",n.dataset.id===org));
  document.querySelectorAll("tr.row").forEach(r=>r.classList.toggle("sel",r.dataset.id===org));
  document.getElementById("pen").innerHTML=b.penalty?"штраф <b>"+b.penalty+"</b> за 7 дней":"штрафов нет";
  const P=document.getElementById("panel");
  if(b.st==="off"){
    P.innerHTML='<div class="p-t">'+esc(b.full)+'</div><div class="p-s">управляющий не подключён</div>'+
      '<div class="empty">Сдавать некому: ссылка-приглашение исчерпана.<br>'+
      'Наберите ниже <kbd>/оживить '+esc(b.n.split(" ")[0].toLowerCase())+'</kbd></div>';
    return;
  }
  let cl="";
  Object.keys(b.clean).sort().forEach(slot=>{
    const zs=b.clean[slot];
    Object.keys(zs).forEach(z=>{
      const ok=zs[z]==="ok", t=DATA.zones[z]?DATA.zones[z].title:z;
      cl+='<div class="row2"><div class="l"><span class="pip '+(ok?"ok":"bad")+'"></span>'+
        '<span class="nm">'+esc(t)+' · слот '+esc(slot)+'</span></div><span class="v '+
        (ok?"ok":"bad")+'">'+(ok?"сдано":"не сдано")+'</span></div>';
    });
  });
  const slots=Object.keys(b.temp);
  let cm="";
  if(!slots.length){cm='<div class="row2"><div class="l"><span class="pip bad"></span>'+
    '<span class="nm">Замер не сдан</span></div><span class="v bad">—</span></div>';}
  else{
    const vals=b.temp[slots[slots.length-1]]||{};
    DATA.cameras.forEach(c=>{
      const v=vals[c.key];
      if(v===undefined){cm+='<div class="row2"><div class="l"><span class="pip bad"></span>'+
        '<span class="nm">'+esc(c.title)+'</span></div><span class="v bad">нет</span></div>';return;}
      const n=DATA.norms[c.kind], bad=v<n.lo||v>n.hi;
      cm+='<div class="row2"><div class="l"><span class="pip '+(bad?"bad":"ok")+'"></span>'+
        '<span class="nm">'+esc(c.title)+'</span></div><span class="v '+(bad?"bad":"")+'">'+
        (v>0?"+":"")+v+' °C <span style="opacity:.5">'+esc(n.txt)+'</span></span></div>';
    });
  }
  P.innerHTML='<div class="p-t">'+esc(b.full)+'</div><div class="p-s">'+
    esc(b.who||"управляющий не назван")+' · сдано '+b.done+' из '+b.of+' к '+esc(DATA.now)+'</div>'+
    '<div class="grp"><div class="grp-h"><span class="grp-n">Чистота</span></div>'+(cl||'<div class="v">нет слотов</div>')+'</div>'+
    '<div class="grp"><div class="grp-h"><span class="grp-n">Температура</span>'+
      '<span class="st '+(b.temp_alarms.length?"bad":"ok")+'">'+
      (b.temp_alarms.length?b.temp_alarms.length+" вне нормы":"в норме")+'</span></div>'+cm+'</div>'+
    '<div class="grp"><div class="grp-h"><span class="grp-n">Остатки</span>'+
      '<span class="st '+(b.stock?"ok":"part")+'">'+(b.stock?"сданы":"не сданы")+'</span></div></div>';
}

/* ── остатки ── */
let PLACE=0, COUNTS={};
function stockRender(){
  const b=DATA.branches.find(x=>x.org===CUR);
  document.getElementById("st-b").textContent=b?b.n:"—";
  const places=DATA.stock_places;
  document.getElementById("st-places").innerHTML=places.map((p,i)=>{
    const c=Object.keys(COUNTS[p.key]||{}).length;
    return '<button type="button" aria-pressed="'+(i===PLACE)+'" data-i="'+i+'">'+
      esc(p.title)+(c?' <span class="c">'+c+'</span>':'')+'</button>';}).join("");
  document.querySelectorAll("#st-places button").forEach(x=>x.addEventListener("click",()=>{
    PLACE=+x.dataset.i; stockRender();}));
  const p=places[PLACE], have=COUNTS[p.key]||{};
  document.getElementById("st-items").innerHTML=p.items.map(it=>{
    const v=have[it]??"";
    return '<div class="it'+(v!==""?" filled":"")+'"><label for="i-'+esc(it)+'">'+esc(it)+
      '</label><input id="i-'+esc(it)+'" type="number" step="any" inputmode="decimal" value="'+
      esc(v)+'" data-k="'+esc(it)+'"></div>';}).join("");
  document.querySelectorAll("#st-items input").forEach(inp=>inp.addEventListener("input",()=>{
    COUNTS[p.key]=COUNTS[p.key]||{};
    if(inp.value==="")delete COUNTS[p.key][inp.dataset.k];
    else COUNTS[p.key][inp.dataset.k]=parseFloat(inp.value);
    inp.parentElement.classList.toggle("filled",inp.value!=="");
    stockSum();
  }));
  stockSum();
}
function stockSum(){
  const total=DATA.stock_places.reduce((a,p)=>a+p.items.length,0);
  const done=Object.values(COUNTS).reduce((a,o)=>a+Object.keys(o).length,0);
  document.getElementById("st-sum").textContent="заполнено "+done+" из "+total;
}
document.getElementById("st-save").addEventListener("click",async()=>{
  if(!CUR){document.getElementById("st-msg").textContent="сначала выберите филиал";return;}
  const btn=document.getElementById("st-save"), msg=document.getElementById("st-msg");
  btn.disabled=true; msg.textContent="сохраняю…";
  try{
    const r=await fetch("/api/journals/stock/"+TOKEN,{method:"POST",
      headers:{"content-type":"application/json"},
      body:JSON.stringify({org:CUR,counts:COUNTS})});
    const j=await r.json();
    msg.textContent=j.ok?"сохранено в "+new Date().toLocaleTimeString("ru").slice(0,5):("ошибка: "+(j.error||""));
    if(j.ok)load();
  }catch(e){msg.textContent="сеть недоступна";}
  btn.disabled=false;
});

/* ── консоль ── */
const out=document.getElementById("con-out");
function say(cls,txt){
  const d=document.createElement("div");
  d.className="cl "+cls;
  d.innerHTML='<span class="p">'+(cls==="me"?"&gt;":"·")+'</span><span class="t">'+esc(txt)+'</span>';
  out.appendChild(d); out.scrollTop=out.scrollHeight;
}
document.getElementById("con-form").addEventListener("submit",async e=>{
  e.preventDefault();
  const inp=document.getElementById("con-inp"), btn=document.getElementById("con-btn");
  const t=inp.value.trim(); if(!t)return;
  say("me",t); inp.value=""; btn.disabled=true;
  try{
    const r=await fetch("/api/journals/say/"+TOKEN,{method:"POST",
      headers:{"content-type":"application/json"},body:JSON.stringify({text:t})});
    const j=await r.json();
    (j.log||[]).forEach(([c,m])=>say(c,m));
    if(j.error)say("err",j.error);
  }catch(err){say("err","сеть недоступна: "+err);}
  btn.disabled=false; inp.focus();
  load();
});

const vg=document.getElementById("v-graph"),vl=document.getElementById("v-list");
const setView=x=>{vg.setAttribute("aria-pressed",x);vl.setAttribute("aria-pressed",!x);
  document.getElementById("view-graph").hidden=!x;document.getElementById("view-list").hidden=x;};
vg.addEventListener("click",()=>setView(true));
vl.addEventListener("click",()=>setView(false));

load();
setInterval(load,60000);
</script></body></html>
'''
