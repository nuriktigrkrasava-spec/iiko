"""ИИ-ассистент «Директор»: детерминированные сигналы → советы.

rules_advice — фоллбэк без сети (числа только из сигналов). advise — Claude
поверх тех же сигналов (грудинг), с деградацией на rules_advice.
Пo образцу claude_api.py."""
import json
import os
from typing import Any, Dict, List, Optional

from anthropic import AsyncAnthropic

MODEL = "claude-opus-5"  # по умолчанию (claude-api). insights_service использует opus-4-8.
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
        # техкарт нет → фудкост не считается: план
        elif b.get("has_recipes") is False:
            out.append(_adv(name, "med", "Фудкост не считается",
                            f"{name}: в iiko не заполнены техкарты — себестоимость взять неоткуда.",
                            None, {"type": "navigate", "tab": "fc", "hint": None}))
        # отмены/возвраты
        cn = b.get("cancels") or 0
        if cn > 0:
            out.append(_adv(name, "med", "Отмены и возвраты",
                            f"{name}: отмен и возвратов на {cn:,.0f} ₸ за период — разбери топ-причину.".replace(",", " "),
                            cn, {"type": "navigate", "tab": "supply", "hint": None}))
        # соцсети не подключены
        if b.get("has_socials") is False:
            out.append(_adv(name, "low", "Соцсети не подключены",
                            f"{name}: площадки отзывов (2ГИС/Wolt) не найдены — укажи бренд в «Подключить».",
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
    "Ты — ИИ-финдиректор сети ресторанов. Тебе дают УЖЕ ПОСЧИТАННЫЕ числа по филиалам "
    "(фудкост, выручка, отмены, списания, отзывы, час-пик). Используй ТОЛЬКО эти числа — "
    "ничего не выдумывай. Верни JSON-массив советов, отсортированный по деньгам убыв. "
    "Каждый совет: {id, branch, severity('high'|'med'|'low'), title, detail, money(число ₸/мес или null), "
    "action(null | {type:'navigate'|'showMetric', tab, hint})}. tab — один из: "
    "'fc'(фудкост),'supply'(склад),'rep'(соцсети),'sched'(расписание),'director'(директор). "
    "Пиши по-русски, конкретно: филиал, время, сумма. Не более 6 советов. Только JSON, без пояснений."
)


async def advise(signals: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Claude поверх сигналов; при любой проблеме — rules_advice."""
    if _client is None:
        return rules_advice(signals)
    try:
        msg = await _client.messages.create(
            model=MODEL,
            max_tokens=8000,
            output_config={"effort": "medium"},
            system=_SYSTEM,
            messages=[{"role": "user", "content": json.dumps(signals, ensure_ascii=False)}],
        )
        text = next((b.text for b in msg.content if b.type == "text"), "")
        parsed = _parse_advice(text)
        return parsed if parsed else rules_advice(signals)
    except Exception as e:  # сеть/квота/невалидный JSON → детерминированный фоллбэк
        print(f"[assistant] Claude недоступен, фоллбэк на правила: {e!r}")
        return rules_advice(signals)
