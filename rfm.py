"""Витрина «RFM-клиенты · Астана».

Сбор данных по доставкам iiko всех филиалов Астаны, сегментация по правилам
заметки «Тактика» и рендер самодостаточной HTML-страницы. Роут `GET /rfm`
живёт в api.py и дёргает отсюда build_report() + render().

Дизайн страницы — в файле rfm_template.html (правится отдельно от Python).
"""
import asyncio
import logging
import os
import re
from datetime import date, timedelta

from database import get_all_restaurants, get_review_link, set_review_link
from claude_api import analyze_with_claude
from iiko import get_client

logger = logging.getLogger(__name__)

_TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "rfm_template.html")


def _norm_phone(s):
    """Нормализация телефона до 10 цифр (как в api._norm_phone)."""
    s = (s or "").split(",")[0]
    d = re.sub(r"\D", "", s)
    return d[-10:] if len(d) >= 10 else None


def _astana_restaurants():
    """Филиалы Астаны (по префиксу имени) из всех ресторанов с расшифрованными кредами."""
    out = []
    for r in get_all_restaurants():
        if (r.get("organization_name") or "").strip().lower().startswith("астана"):
            out.append(r)
    return out


def _aggregate_clients(rows, today):
    """Сырые строки olap_clients_rfm → {phone: {orders_90, spend_90, orders_total, spend_total, last_date}}.
    90д-окно считается относительно today."""
    cutoff = (today - timedelta(days=90)).isoformat()
    agg = {}
    for d in rows:
        ph = _norm_phone(d.get("Delivery.CustomerPhone") or "")
        if not ph:
            continue
        n = int(d.get("UniqOrderId.OrdersCount") or 0)
        if n <= 0:
            continue
        spend = float(d.get("DishDiscountSumInt") or 0)
        od = (d.get("OpenDate.Typed") or "")[:10]
        a = agg.setdefault(ph, {"orders_90": 0, "spend_90": 0.0,
                                "orders_total": 0, "spend_total": 0.0, "last_date": ""})
        a["orders_total"] += n
        a["spend_total"] += spend
        if od and od >= cutoff:
            a["orders_90"] += n
            a["spend_90"] += spend
        if od and od > a["last_date"]:
            a["last_date"] = od
    return agg


# (key, emoji, label, action, example) — действия/примеры из заметки «Тактика»/«Сегменты RFM»
_RFM_META = [
    ("champions", "🏆", "Чемпионы",      "беречь, без скидок — ранний доступ к новинкам",
     "Вы в числе первых пробуете новый сет 🔥"),
    ("loyal",     "💛", "Лояльные",      "апселл, поднимать чек",
     "К вашему сету — мисо-суп и напиток за полцены"),
    ("big_rare",  "💸", "Крупные редкие", "дать повод заходить чаще",
     "Подписка «Сет недели» — вкуснее и выгоднее"),
    ("new",       "🌱", "Новички",        "онбординг до 3-го заказа",
     "−15% на второй заказ, действует 7 дней"),
    ("at_risk",   "⚠️", "В зоне риска",    "win-back, окно ещё открыто",
     "Давно не виделись — собрали для вас сет −20%"),
    ("lost",      "⚰️", "Уснувшие",       "последний шанс или отпустить",
     "Последнее предложение: 1+1 на роллы"),
]


def _rfm_by_thresholds(agg, today):
    """agg → сегменты по фиксированным порогам заметки (R дни, F за 90д, M-квинтиль spend_90).
    Возвращает {total, segments:[{key,emoji,label,count,pct,revenue,action,example}]}."""
    custs = [(ph, a) for ph, a in agg.items() if a.get("orders_total", 0) > 0]
    total = len(custs)
    if not total:
        return {"total": 0, "segments": []}

    def rec_days(a):
        ld = a.get("last_date") or ""
        try:
            return (today - date.fromisoformat(ld[:10])).days
        except Exception:
            return 9999

    # M-квинтиль по spend_90 среди клиентов с заказами за 90д (5 = топ)
    spenders = sorted([(ph, a["spend_90"]) for ph, a in custs if a.get("orders_90", 0) >= 1],
                      key=lambda kv: kv[1], reverse=True)
    Lm = len(spenders)
    mq = {ph: 5 - (i * 5 // Lm) for i, (ph, _) in enumerate(spenders)} if Lm else {}

    def seg_of(ph, a):
        r = rec_days(a); f = a.get("orders_90", 0); m = mq.get(ph, 0); ot = a.get("orders_total", 0)
        if r <= 30 and f >= 4 and m >= 4:   return "champions"
        if r <= 30 and f >= 2:              return "loyal"
        if m >= 4 and f <= 2 and r <= 60:   return "big_rare"
        if r <= 30 and f == 1:              return "new"
        if 31 <= r <= 90 and ot >= 3:       return "at_risk"
        return "lost"

    buckets = {k: {"count": 0, "revenue": 0.0} for k, *_ in _RFM_META}
    for ph, a in custs:
        b = buckets[seg_of(ph, a)]
        b["count"] += 1
        b["revenue"] += a.get("spend_total", 0.0)
    segs = [{"key": k, "emoji": e, "label": lbl, "action": act, "example": ex,
             "count": buckets[k]["count"],
             "pct": round(buckets[k]["count"] / total * 100),
             "revenue": round(buckets[k]["revenue"])}
            for k, e, lbl, act, ex in _RFM_META if buckets[k]["count"] > 0]
    return {"total": total, "segments": segs}


def _branch_stats(rows, today):
    """Сводка по одному филиалу из его сырых строк olap_clients_rfm."""
    agg = _aggregate_clients(rows, today)
    total = len(agg)
    revenue = sum(a["spend_total"] for a in agg.values())
    repeat = sum(1 for a in agg.values() if a["orders_total"] >= 2)
    return {"clients": total, "revenue": round(revenue),
            "repeat_pct": round(repeat / total * 100) if total else 0,
            "ltv": round(revenue / total) if total else 0}


def _window_kpis(rows, lo, hi):
    """KPI (clients/revenue/ltv/repeat_pct) по строкам с датой заказа в [lo, hi] включительно."""
    agg = {}
    for d in rows:
        od = (d.get("OpenDate.Typed") or "")[:10]
        if not od or od < lo or od > hi:
            continue
        ph = _norm_phone(d.get("Delivery.CustomerPhone") or "")
        if not ph:
            continue
        n = int(d.get("UniqOrderId.OrdersCount") or 0)
        if n <= 0:
            continue
        a = agg.setdefault(ph, {"orders": 0, "spend": 0.0})
        a["orders"] += n
        a["spend"] += float(d.get("DishDiscountSumInt") or 0)
    total = len(agg)
    revenue = sum(a["spend"] for a in agg.values())
    repeat = sum(1 for a in agg.values() if a["orders"] >= 2)
    return {"clients": total, "revenue": round(revenue),
            "ltv": round(revenue / total) if total else 0,
            "repeat_pct": round(repeat / total * 100) if total else 0}


def _kpi_deltas(rows, today):
    """Динамика: последние 90 дней против предыдущих 90 (оба окна — из тех же данных).
    % изменения для clients/revenue/ltv; для repeat_pct — разница в пунктах (pp)."""
    cur = _window_kpis(rows, (today - timedelta(days=90)).isoformat(), today.isoformat())
    prev = _window_kpis(rows, (today - timedelta(days=180)).isoformat(),
                        (today - timedelta(days=91)).isoformat())

    def pct(c, p):
        return round((c - p) / p * 100) if p else None

    both = cur["clients"] and prev["clients"]
    return {
        "clients": pct(cur["clients"], prev["clients"]),
        "revenue": pct(cur["revenue"], prev["revenue"]),
        "ltv": pct(cur["ltv"], prev["ltv"]),
        "repeat_pp": (cur["repeat_pct"] - prev["repeat_pct"]) if both else None,
    }


def _cohort_retention(rows, today, max_m=4):
    """По сырым строкам olap_clients_rfm: когорты по месяцу первого заказа и
    удержание M0..max_m (% когорты с заказом в соответствующем месяце)."""
    by_phone = {}
    for d in rows:
        ph = _norm_phone(d.get("Delivery.CustomerPhone") or "")
        if not ph or int(d.get("UniqOrderId.OrdersCount") or 0) <= 0:
            continue
        m = (d.get("OpenDate.Typed") or "")[:7]
        if m:
            by_phone.setdefault(ph, set()).add(m)
    cohorts = {}
    for ph, months in by_phone.items():
        cohorts.setdefault(min(months), []).append(months)

    def month_add(ym, k):
        y, mo = int(ym[:4]), int(ym[5:7])
        mo += k; y += (mo - 1) // 12; mo = (mo - 1) % 12 + 1
        return f"{y:04d}-{mo:02d}"

    cur = today.strftime("%Y-%m")
    out = []
    for cm in sorted(cohorts):
        custs = cohorts[cm]; size = len(custs); ret = []
        for k in range(max_m + 1):
            mk = month_add(cm, k)
            ret.append(None if mk > cur else (round(sum(1 for s in custs if mk in s) / size * 100) if size else 0))
        out.append({"month": cm, "size": size, "ret": ret})
    return {"cohorts": out, "max_m": max_m}


async def _branch_top_products(client, dept, date_from, date_to, n=5):
    """Топ-n и анти-топ-n блюд филиала по количеству продаж (DishCount)."""
    fn = getattr(client, "olap_report", None)
    if not fn:
        return {"top": [], "bottom": []}
    try:
        res = await fn(dept, date_from, date_to, ["DishName"], ["DishCount"])
    except Exception:
        return {"top": [], "bottom": []}
    rows = [(str(r.get("DishName") or "").strip(), int(r.get("DishCount") or 0))
            for r in res.get("data", [])]
    rows = [(nm, c) for nm, c in rows if nm and c > 0]
    rows.sort(key=lambda x: x[1], reverse=True)
    top = [{"name": nm, "count": c} for nm, c in rows[:n]]
    bottom = [{"name": nm, "count": c} for nm, c in rows[-n:][::-1]] if len(rows) > n else []
    return {"top": top, "bottom": bottom}


async def _reviews_by_branch(rests):
    """По каждому филиалу: рейтинг 2ГИС + краткий разбор отзывов Claude
    (что хвалят / чем недовольны). Без отзывов/ошибке — филиал пропускается."""
    import reviews as rv

    async def one(r):
        org = r["organization_id"]; name = r["organization_name"]
        try:
            link = get_review_link(org, "2gis")
            if not link and name:
                found = await rv.discover_2gis(name, rv.BRAND_QUERY)
                if found:
                    set_review_link(org, "2gis", found["external_id"],
                                    found.get("title", ""), found.get("extra", ""))
                    link = get_review_link(org, "2gis")
            if not link:
                return None
            data = await rv.fetch_2gis(link["external_id"])
            texts = [x["text"] for x in (data or {}).get("reviews", []) if x.get("text")]
            if not texts:
                return None
            q = ("По этим отзывам одного филиала ответь ровно двумя строками: "
                 "'👍 Хвалят: <блюдо/за что чаще всего хвалят>' и "
                 "'👎 Недовольны: <главная причина недовольства>'. Коротко, без воды.")
            summary = await analyze_with_claude(q, {"reviews": texts, "branch": name}, org)
            return {"name": name, "rating": (data or {}).get("rating"), "summary": summary}
        except Exception as e:
            logger.warning(f"[rfm/reviews] {name}: {e}")
            return None

    res = await asyncio.gather(*(one(r) for r in rests))
    return [x for x in res if x]


async def build_report(today):
    """Собрать полный отчёт по филиалам Астаны за последние 180 дней."""
    date_to = today.isoformat()
    date_from = (today - timedelta(days=180)).isoformat()

    async def fetch(r):
        client = get_client(r["api_login"], r.get("iiko_server"), r.get("api_password"))
        fn = getattr(client, "olap_clients_rfm", None)
        if not fn:
            return (r, [])
        try:
            return (r, await fn(r["organization_name"], date_from, date_to))
        except Exception as e:
            logger.warning(f"[rfm] {r.get('organization_name')}: {e}")
            return (r, [])

    rests = _astana_restaurants()
    pairs = await asyncio.gather(*(fetch(r) for r in rests))
    all_rows, branches = [], []
    for r, rows in pairs:
        all_rows.extend(rows)
        client = get_client(r["api_login"], r.get("iiko_server"), r.get("api_password"))
        prods = await _branch_top_products(client, r["organization_name"], date_from, date_to)
        branches.append({"name": r["organization_name"], **_branch_stats(rows, today),
                         "top_products": prods["top"], "bottom_products": prods["bottom"]})

    agg = _aggregate_clients(all_rows, today)
    total = len(agg)
    revenue = round(sum(a["spend_total"] for a in agg.values()))
    repeat = sum(1 for a in agg.values() if a["orders_total"] >= 2)
    return {
        "date": date_to,
        "kpi": {"clients": total, "revenue": revenue,
                "ltv": round(revenue / total) if total else 0,
                "repeat_pct": round(repeat / total * 100) if total else 0},
        "rfm": _rfm_by_thresholds(agg, today),
        "delta": _kpi_deltas(all_rows, today),
        "branches": sorted(branches, key=lambda b: -b["revenue"]),
        "cohort": _cohort_retention(all_rows, today),
        "reviews": await _reviews_by_branch(rests),
    }


# ── Рендер ───────────────────────────────────────────────────────────────────

_IDEAS = '''
    <h2>💡 Идеи (из плейбука «Тактика»)</h2>

    <h3>😴 Уснувшие VIP — самое ценное</h3>
    <p>Бывший Чемпион с высоким чеком, но 60–90+ дней тишины. Правило: <b>персональный подход, НЕ массовая скидка</b> — его уводят вниманием.</p>
    <ul>
      <li>🤝 Личное касание «от менеджера», не безличная рассылка.</li>
      <li>🎁 Любимое блюдо в подарок (топ-ролл из истории iiko).</li>
      <li>👑 Вернуть статус/баллы: «сгорают через 7 дней — заберите».</li>
      <li>🚪 Эксклюзив: закрытая дегустация новинки.</li>
      <li>❓ Спросить, почему ушёл — часто причина в качестве/доставке.</li>
    </ul>
    <p class="tip"><b>Лестница возврата:</b> День 30 — мягко («скучаем» + маленький бонус) · День 45 — подарок-блюдо · День 60 — максимум (большой бонус + статус). Не давать максимум сразу — приучает уходить ради скидки.</p>

    <h3>🗂️ Что делать с каждым сегментом</h3>
    <div class="tablewrap"><table>
      <tr><th>Сегмент</th><th>Действие</th><th>Пример сообщения</th></tr>
      <tr><td>🏆 Активные VIP</td><td>беречь, без скидок</td><td>«Вы в числе первых пробуете новый сет 🔥»</td></tr>
      <tr><td>😴 Уснувшие VIP</td><td>персональный возврат</td><td>«Ваш любимый [ролл] — в подарок»</td></tr>
      <tr><td>💛 Лояльные</td><td>апселл, ↑ чек</td><td>«К вашему сету — мисо+напиток за полцены»</td></tr>
      <tr><td>🌱 Новички</td><td>онбординг до 3-го заказа</td><td>«−15% на 2-й заказ, 7 дней»</td></tr>
      <tr><td>⚠️ At-risk</td><td>win-back, окно открыто</td><td>«Давно не виделись — сет −20%»</td></tr>
      <tr><td>⚰️ Ушедшие</td><td>последний шанс или отпустить</td><td>«Последнее предложение: 1+1 на роллы»</td></tr>
      <tr><td>💸 Редкие крупные</td><td>повод заходить чаще</td><td>подписка «Сет недели»</td></tr>
      <tr><td>🌙 Спящие новички</td><td>не дать стать ушедшими</td><td>«Помните нас? Вот повод вернуться»</td></tr>
    </table></div>

    <h3>🎮 Челленджи в приложение</h3>
    <ul>
      <li>🔥 Стрик: 3 недели подряд заказ → бонусный ролл.</li>
      <li>📅 «Суши-пятница»: ×2 баллов в выбранный день.</li>
      <li>🏅 Коллекция: попробуй 5 авторских сетов → бейдж + подарок.</li>
      <li>🎯 Личный челлендж под сегмент: «2 заказа на неделе → бонус».</li>
      <li>👥 Реферальный: приведи друга → награда обоим.</li>
      <li>🎉 Сезонные: Наурыз, Новый год, день рождения сети (FOMO).</li>
      <li>🎰 Mystery box / колесо при заказе через приложение.</li>
      <li>🥉🥈🥇 Уровни: Бронза → Серебро → Золото, привилегии растут.</li>
    </ul>
    <p class="tip">Челлендж = ещё один заказ ради цели, без прямой скидки: маржа цела, частота растёт. Живут только в приложении → это и инструмент миграции.</p>

    <h3>📲 Перевести поток в приложение</h3>
    <p><b>Пряник:</b> лучшая цена только в приложении · баллы копятся только там · челленджи и уровни · новинки сначала в приложении · заказ в 1 клик (сохранённый адрес и любимый заказ).</p>
    <p><b>Каналы захода:</b> QR на коробках/чеках/столах → подарок за 1-й заказ · скрипт курьера/кассира · постепенный перенос лучших офферов из WhatsApp/Instagram в push.</p>
    <p class="tip">Экономика: push ≈ бесплатно, WhatsApp/SMS — деньги за каждое касание. Каждый переведённый клиент дешевле в обслуживании и даёт больше данных для RFM.</p>
    '''

_EDU = '''
    <h2>📊 Что ещё считаем (методы)</h2>

    <h3>Когортный анализ</h3>
    <p>Группируем клиентов по месяцу первого заказа и смотрим, как падает удержание со временем — видно, <b>на какой неделе теряем новичков</b>. Делают Sweetgreen, Starbucks. У нас: по iiko строим кривые удержания когорт → чиним онбординг. (см. таблицу когорт выше).</p>

    <h3>CLV / LTV (пожизненная ценность)</h3>
    <p>Сколько денег принесёт клиент за всё время (средний чек × частота × срок жизни). Задаёт <b>потолок бюджета</b> на удержание и привлечение — особенно для VIP.</p>
    <ul>
      <li>✅ Участники лояльности заходят <b>в 2 раза чаще</b> и тратят больше.</li>
      <li>✅ Повторные клиенты тратят <b>+67%</b> к новым — самый прибыльный сегмент.</li>
      <li>✅ Привлечь нового дороже, чем удержать; рост CLV прямо повышает прибыль.</li>
    </ul>

    <h3>Прогноз оттока (Churn)</h3>
    <p>Предсказываем, <b>кто вот-вот уйдёт</b>, ДО того как ушёл → опережающий win-back. Делают Dunkin, Starbucks (Deep Brew). У нас на старте — это сегменты «В зоне риска» и «Уснувшие» выше (R↓): триггерим их заранее, без сложной ML-модели.</p>

    <h3>Кейсы персонализации</h3>
    <p>🍟 <b>McDonald's — Dynamic Yield ($300 млн):</b> рекомендации на драйв-тру под <b>контекст</b> (погода, время, трафик, текущая корзина), а не личную историю. Подтолкнуло Starbucks создать Deep Brew.</p>
    <p>🍗 <b>Yum! (KFC/Taco Bell) — AI Factory:</b> связывает данные касс + цифровых меню + лояльности через AI для персональных промо по всем брендам.</p>
    '''

_SEG_LEAD = '''
    <h2>🎯 RFM-сегменты клиентов</h2>
    <p class="lead"><b>Что считаем.</b> Каждого клиента раскладываем по трём осям:
    <b>R</b>ecency — как давно был последний заказ, <b>F</b>requency — сколько заказов за 90 дней,
    <b>M</b>onetary — сколько потратил. По комбинации этих осей клиент попадает в один сегмент.</p>
    <p class="lead"><b>Зачем.</b> Один и тот же бюджет на маркетинг работает по-разному:
    Чемпионов нельзя приучать к скидкам, Уснувших — только персональный возврат, Новичков — довести до 3-го заказа.
    Карточка ниже: <b>число клиентов · доля</b>, выручка сегмента, <span style="color:var(--accent)">→ что делать</span> и пример сообщения.</p>
    '''

_BRANCHES_LEAD = '''
    <h2>🏪 Клиенты по филиалам</h2>
    <p class="lead"><b>Что в таблице.</b> <b>Клиентов</b> — уникальные телефоны с доставкой за 180 дней ·
    <b>Выручка</b> — сумма их заказов · <b>Повторных</b> — доля клиентов с 2+ заказами (лояльность точки) ·
    <b>LTV</b> — выручка ÷ клиентов (сколько в среднем приносит один клиент филиала).</p>
    <p class="lead">Низкий % повторных при высокой выручке = филиал «живёт» на новичках, удержание проседает.
    Ниже — <b>топ-5</b> блюд (что продвигать) и <b>анти-топ-5</b> (кандидаты убрать из меню или переработать).</p>
    '''

_COHORT_LEAD = '''
    <h2>📈 Удержание когорт</h2>
    <p class="lead"><b>Что считаем.</b> Клиентов группируем по месяцу первого заказа (когорта) и смотрим,
    какой % из них возвращался в следующие месяцы. <b>М0</b> всегда 100% (месяц первого заказа),
    <b>М1</b> — вернулись через месяц, и т.д. Прочерк — месяц ещё не наступил.</p>
    <p class="lead"><b>Как читать.</b> Чем медленнее падают числа по строке — тем лучше удержание.
    Резкий обвал на М1 = теряем новичков сразу после первого заказа → чинить онбординг (−15% на 2-й заказ, напоминание).</p>
    '''

_REVIEWS_LEAD = '''
    <h2>💬 Отзывы по филиалам (2ГИС)</h2>
    <p class="lead"><b>Что показываем.</b> Рейтинг филиала из 2ГИС + краткий разбор живых отзывов нейросетью:
    что чаще всего <b>хвалят</b> (усиливать и продвигать) и чем <b>недовольны</b> (главная причина — чинить в первую очередь).</p>
    '''

_EDU_LEAD = '<p class="lead">Кратко о методах, которые стоят за вкладками выше, и как их применяют большие сети.</p>'


def _delta_badge(pct, pp=False):
    """↑/↓-бейдж изменения. pct=None → пусто. pp=True → пункты вместо %."""
    if pct is None:
        return ""
    arrow = "↑" if pct > 0 else ("↓" if pct < 0 else "→")
    cls = "up" if pct > 0 else ("down" if pct < 0 else "flat")
    unit = " пп" if pp else "%"
    return f'<div class="d {cls}">{arrow} {abs(pct)}{unit} <span>vs пред. 90д</span></div>'


def _render_rfm_html(report):
    """report → самодостаточный HTML по шаблону rfm_template.html."""
    k = report["kpi"]
    d = report.get("delta") or {}
    nf = lambda v: f"{int(v):,}".replace(",", " ")

    seg_cards = "".join(
        f'''<div class="seg">
          <div class="seg-h">{s["emoji"]} {s["label"]}</div>
          <div class="seg-n">{nf(s["count"])} <span class="muted">· {s["pct"]}%</span></div>
          <div class="muted">{nf(s["revenue"])} ₸</div>
          <div class="act">→ {s["action"]}</div>
          <div class="ex">«{s["example"]}»</div>
        </div>'''
        for s in report["rfm"]["segments"]
    )
    branch_rows = "".join(
        f'<tr><td>{b["name"]}</td><td>{nf(b["clients"])}</td><td>{nf(b["revenue"])} ₸</td>'
        f'<td>{b["repeat_pct"]}%</td><td>{nf(b["ltv"])} ₸</td></tr>'
        for b in report["branches"]
    )

    cohort = report.get("cohort") or {"cohorts": [], "max_m": 4}
    if cohort["cohorts"]:
        head = "".join(f"<th>М{k}</th>" for k in range(cohort["max_m"] + 1))
        crows = "".join(
            f'<tr><td>{c["month"]}</td><td>{c["size"]}</td>' +
            "".join(f'<td>{"—" if v is None else str(v)+"%"}</td>' for v in c["ret"]) + "</tr>"
            for c in cohort["cohorts"])
        cohort_html = f'<div class="tablewrap"><table><tr><th>Когорта</th><th>Клиентов</th>{head}</tr>{crows}</table></div>'
    else:
        cohort_html = ""

    prod_html = ""
    for b in report["branches"]:
        if not b.get("top_products"):
            continue
        topl = "".join(f"<li>{p['name']} <span class='muted'>· {p['count']}</span></li>" for p in b["top_products"])
        botl = "".join(f"<li>{p['name']} <span class='muted'>· {p['count']}</span></li>" for p in b.get("bottom_products", []))
        prod_html += (f"<div class='seg'><div class='seg-h'>{b['name']}</div>"
                      f"<div class='muted'>👍 Топ-5</div><ol>{topl}</ol>"
                      + (f"<div class='muted'>👎 Анти-топ-5</div><ol>{botl}</ol>" if botl else "") + "</div>")
    products_block = f"<h2>🍣 Продукты по филиалам</h2><div class='segs'>{prod_html}</div>" if prod_html else ""

    rev_html = ""
    for rb in report.get("reviews", []):
        sm = (rb.get("summary") or "").replace("\n", "<br>")
        rt = f" · ⭐ {rb['rating']}" if rb.get("rating") is not None else ""
        rev_html += f"<div class='seg'><div class='seg-h'>{rb['name']}{rt}</div><div>{sm}</div></div>"
    reviews_block = f"<div class='segs'>{rev_html}</div>" if rev_html else ""

    branches_panel = (
        _BRANCHES_LEAD +
        '<div class="tablewrap"><table><tr><th>Филиал</th><th>Клиентов</th><th>Выручка</th><th>Повторных</th><th>LTV</th></tr>'
        f'{branch_rows}</table></div>{products_block}'
    )
    # (id, подпись вкладки, содержимое панели) — первая вкладка активна по умолчанию
    tabs = [
        ("seg", "🎯 Сегменты", f'{_SEG_LEAD}<div class="segs">{seg_cards}</div>'),
        ("br", "🏪 Филиалы", branches_panel),
    ]
    if cohort_html:
        tabs.append(("co", "📈 Когорты", _COHORT_LEAD + cohort_html))
    if reviews_block:
        tabs.append(("rv", "💬 Отзывы", _REVIEWS_LEAD + reviews_block))
    tabs.append(("id", "💡 Идеи", _IDEAS + _EDU_LEAD + _EDU))

    radios = "".join(
        f'<input type="radio" name="tab" id="t-{tid}" class="tabin"{" checked" if i == 0 else ""}>'
        for i, (tid, _l, _b) in enumerate(tabs))
    nav = "".join(f'<label for="t-{tid}">{lbl}</label>' for tid, lbl, _b in tabs)
    panels = "".join(f'<section class="panel" id="p-{tid}">{body}</section>'
                     for tid, _l, body in tabs)

    with open(_TEMPLATE_PATH, encoding="utf-8") as f:
        html = f.read()
    return (html
            .replace("@@DATE@@", str(report["date"]))
            .replace("@@CLIENTS@@", nf(k["clients"]))
            .replace("@@REVENUE@@", nf(k["revenue"]))
            .replace("@@LTV@@", nf(k["ltv"]))
            .replace("@@REPEAT@@", str(k["repeat_pct"]))
            .replace("@@DCLIENTS@@", _delta_badge(d.get("clients")))
            .replace("@@DREVENUE@@", _delta_badge(d.get("revenue")))
            .replace("@@DLTV@@", _delta_badge(d.get("ltv")))
            .replace("@@DREPEAT@@", _delta_badge(d.get("repeat_pp"), pp=True))
            .replace("@@RADIOS@@", radios)
            .replace("@@NAV@@", nav)
            .replace("@@PANELS@@", panels))


# Алиас для роута
render = _render_rfm_html
