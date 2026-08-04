"""ИИ-ассистент «Директор»: детерминированные сигналы → советы.

rules_advice — фоллбэк без сети (числа только из сигналов). advise — Claude
поверх тех же сигналов (грудинг), с деградацией на rules_advice.
Пo образцу claude_api.py."""
import json
import os
from typing import Any, Dict, List, Optional

from anthropic import AsyncAnthropic

MODEL = "claude-haiku-4-5"  # дешёвая модель по просьбе владельца (бюджет). Поднять при желании.
_client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY")) if os.getenv("ANTHROPIC_API_KEY") else None

DOW_RU = {0: "Пн", 1: "Вт", 2: "Ср", 3: "Чт", 4: "Пт", 5: "Сб", 6: "Вс"}


def _adv(branch, severity, title, detail, money, action=None) -> Dict[str, Any]:
    return {"id": f"{branch}:{title}"[:80], "branch": branch, "severity": severity,
            "title": title, "detail": detail, "money": money, "action": action}


def rules_advice(signals: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Детерминированный фоллбэк. Все числа берутся из signals, ничего не выдумываем."""
    out: List[Dict[str, Any]] = []
    for b in signals.get("branches", []):
        name = b.get("name") or "Филиал"
        fc = b.get("foodcost")
        rev = b.get("revenue") or 0
        # фудкост выше нормы → деньги = перерасход к норме
        if fc and fc.get("fact_pct") is not None and fc.get("fact_pct") > fc.get("norm_pct", 30):
            over = (fc["fact_pct"] - fc["norm_pct"]) / 100 * (fc.get("fact_sum", 0) / (fc["fact_pct"] / 100) if fc["fact_pct"] else 0)
            out.append(_adv(name, "high", "Фудкост выше нормы",
                            f"{name}: фудкост {fc['fact_pct']:.0f}% при норме {fc['norm_pct']}%. "
                            f"Пересобери техкарты топ-блюд и передоговорись с поставщиками.",
                            round(over) if over > 0 else None,
                            {"type": "navigate", "tab": "fc", "hint": None}))
        # техкарт нет → фудкост не считается: план (во вкладку Директор)
        if b.get("has_recipes") is False:
            out.append(_adv(name, "med", "Техкарты не заведены",
                            f"{name}: заполни техкарты в iiko, чтобы считать фудкост.",
                            None, {"type": "navigate", "tab": "director", "hint": None}))
        # техкарты есть, но покрывают мало выручки → фудкост неполный
        elif b.get("has_recipes") is True and fc and fc.get("coverage") is not None and fc["coverage"] < 70:
            cov = fc["coverage"]
            out.append(_adv(name, "med", "Техкарты неполные",
                            f"{name}: техкарты покрывают {cov}% выручки — заполни остальные "
                            f"во вкладке Директор, чтобы фудкост считался полностью.",
                            None, {"type": "navigate", "tab": "director", "hint": None}))
        # отмены/возвраты
        cn = b.get("cancels") or 0
        if cn > 0:
            out.append(_adv(name, "med", "Отмены и возвраты",
                            f"{name}: отмен и возвратов на {cn:,.0f} ₸ за период — разбери топ-причину.".replace(",", " "),
                            cn, {"type": "navigate", "tab": "supply", "hint": None}))
        # стоп-лист: ходовые позиции с 0 в остатке = упущенная выручка
        sc = b.get("stop_count") or 0
        if sc > 0:
            top = ", ".join(b.get("stop_items") or [])
            out.append(_adv(name, "med", "Стоп-лист — упущенная выручка",
                            f"{name}: {sc} позиций в стоп-листе (0 в остатке){f' — {top}' if top else ''}. "
                            f"Гости не могут заказать ходовое — дозакажи, вернёшь выручку.",
                            None, {"type": "navigate", "tab": "supply", "hint": None}))
        # списания / порча
        wo = b.get("writeoffs")
        if wo and (wo.get("pct") or 0) > 5:
            out.append(_adv(name, "med", "Списания выше нормы",
                            f"{name}: списано {wo.get('total'):,.0f} ₸ ({wo.get('pct')}% закупа) — порча/перезаказ, деньги в мусор.".replace(",", " "),
                            wo.get("total"), {"type": "navigate", "tab": "supply", "hint": None}))
        # соцсети не подключены
        if b.get("has_socials") is False:
            out.append(_adv(name, "low", "Соцсети не подключены",
                            f"{name}: площадки отзывов (2ГИС/Wolt) не найдены — укажи бренд в «Подключить».",
                            None, {"type": "navigate", "tab": "rep", "hint": None}))
        # слабые отзывы → одна карточка на филиал (худшая площадка)
        worst = None
        for p in (b.get("reviews") or []):
            rating = p.get("rating")
            if rating is None:
                continue
            delta = p.get("delta")
            low = rating < 4 if rating <= 5 else rating < 8
            neg = isinstance(delta, (int, float)) and delta < 0
            if (low or neg) and (worst is None or rating < worst.get("rating", 1e9)):
                worst = p
        if worst is not None:
            wr, wl = worst.get("rating"), worst.get("label")
            wd = worst.get("delta")
            falling = " (падает)" if isinstance(wd, (int, float)) and wd < 0 else ""
            out.append(_adv(name, "med", f"Слабый отзыв · {wl}",
                            f"{name}: {wl} рейтинг {wr}{falling} — разбери свежие жалобы.",
                            None, {"type": "navigate", "tab": "rep", "hint": None}))
        # час-пик → штат
        peak = b.get("peak")
        if peak:
            out.append(_adv(name, "low", "Час-пик — усилить смену",
                            f"{name}: пик нагрузки {peak.get('day')} около {peak.get('hour')}:00 — "
                            f"добавь официантов на этот слот.",
                            None, {"type": "navigate", "tab": "sched", "hint": None}))
    out.sort(key=lambda a: (a["money"] or 0), reverse=True)
    return out


def _parse_advice(raw_text: str) -> List[Dict[str, Any]]:
    """Снимает markdown-обёртку и парсит JSON-массив советов. Бросает при мусоре."""
    t = raw_text.strip()
    if t.startswith("```"):
        t = t.split("```", 2)[1]
        if t.startswith("json"):
            t = t[4:]
        t = t.strip("`").strip()
    data = json.loads(t)
    if isinstance(data, dict) and "advice" in data:
        data = data["advice"]
    if not isinstance(data, list):
        raise ValueError("advice не массив")
    # оставляем только корректные объекты: не-dict элемент (null/строка/число)
    # уронил бы рендер фронта (a.id/a.severity на не-объекте) — защищаемся тут.
    return [x for x in data if isinstance(x, dict)]


_SYSTEM = (
    "Ты — опытный операционный директор сети ресторанов, который лично отвечает за прибыль. "
    "Говоришь как живой практик-управленец, а не как бот: коротко, по делу, с цифрой и конкретным действием. "
    "Тебе дают УЖЕ ПОСЧИТАННЫЕ числа по каждому филиалу (фудкост, выручка, отмены, списания, отзывы, час-пик). "
    "Используй ТОЛЬКО эти числа — ничего не выдумывай, проценты и суммы бери из данных.\n"
    "ТВОЯ ЗАДАЧА — замечать ВСЁ, что вредит ПРИБЫЛИ, КАЧЕСТВУ и РЕПУТАЦИИ ресторана, и говорить об этом. "
    "Смотри на весь набор: отмены/возвраты, СТОП-ЛИСТ (ходовые позиции с 0 в остатке = упущенная выручка), "
    "СПИСАНИЯ/порча (деньги в мусор), слабый отзыв/низкий рейтинг (уводит гостей — репутация), час-пик без штата, "
    "падение выручки/среднего чека, неполные техкарты, высокий фудкост. "
    "ГЛАВНОЕ — НЕ ШАБЛОНЬ: у разных филиалов РАЗНЫЕ боли, показывай именно их, а не одно и то же.\n"
    "ВАЖНО про фудкост: если у филиала foodcost.coverage < 70% — процент фудкоста ПОСЧИТАН НА НЕПОЛНЫХ "
    "ТЕХКАРТАХ и НЕНАДЁЖЕН. Тогда НЕ пиши 'фудкост X%' как проблему (это кривая цифра) — вместо этого дай совет "
    "'заполни техкарты, покрытие только Y%' (tab 'director') и разбери ДРУГИЕ, надёжные проблемы филиала "
    "(отмены, отзыв, час-пик). Процент фудкоста подавай как проблему ТОЛЬКО если coverage >= 70%.\n"
    "Дай на филиал 1–2 совета: его главная надёжная боль + при желании вторая по деньгам — чтобы картина была "
    "живой и разной, а не 'у всех фудкост'. Если реально всё ок — не выдумывай.\n"
    "Верни JSON-массив советов, отсортированный по деньгам убыв. Каждый совет: "
    "{id, branch, severity('high'|'med'|'low'), title, detail, money(число ₸/мес или null), "
    "action(null | {type:'navigate'|'showMetric', tab, hint})}. tab — один из: "
    "'fc'(фудкост),'supply'(склад),'rep'(соцсети),'sched'(расписание),'director'(директор). "
    "Пиши по-русски, конкретно: филиал, время, сумма, один шаг (не общими словами). До 14 советов. "
    "Только JSON, без пояснений."
)


async def advise(signals: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Claude поверх сигналов; при любой проблеме — rules_advice."""
    if _client is None:
        return rules_advice(signals)
    try:
        msg = await _client.messages.create(
            model=MODEL,
            max_tokens=4000,
            system=_SYSTEM,
            messages=[{"role": "user", "content": json.dumps(signals, ensure_ascii=False)}],
        )
        text = next((b.text for b in msg.content if b.type == "text"), "")
        parsed = _parse_advice(text)
        return parsed if parsed else rules_advice(signals)
    except Exception as e:  # сеть/квота/невалидный JSON → детерминированный фоллбэк
        print(f"[assistant] Claude недоступен, фоллбэк на правила: {e!r}")
        return rules_advice(signals)
