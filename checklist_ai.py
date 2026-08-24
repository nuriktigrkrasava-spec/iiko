"""Разбор фото чек-листов моделью — с четырьмя предохранителями по деньгам.

Слепой прогон стоил бы около миллиона токенов в день: 4 слота × 3 зоны ×
до 8 кадров × 9 филиалов, кадр 1024×768 в vision ≈ 1 050 токенов. Поэтому:

  1. КАДР ДО 512 px по длинной стороне — vision считает по площади,
     512×384 это ≈ 260 токенов вместо 1 050. Грязь на полу видно так же.
  2. ОДИН ЗАПРОС НА СЛОТ, а не на кадр: три зоны идут одним документом, и
     системный промпт оплачивается один раз вместо трёх.
  3. ВЫБОРОЧНЫЙ КОНТРОЛЬ: через модель идут не все сдачи, а доля (SAMPLE_PCT)
     плюс все спорные — сдано с опозданием, вчера было нарушение, мало кадров.
     Остальное просто лежит: человек посмотрит, если понадобится.
  4. КЭШ ПО ХЕШУ: тот же кадр второй раз не оплачивается.

Рубильник свой — CHECKLIST_AI. По умолчанию ВЫКЛЮЧЕН: пока владелец не сказал
«включай», ни один кадр в модель не уходит.
"""
import hashlib
import io
import json
import os
from typing import Any, Dict, List, Optional, Tuple

AI_ENABLED = os.getenv("CHECKLIST_AI", "0") == "1"
MODEL = os.getenv("CHECKLIST_MODEL", "claude-sonnet-5")
MAX_SIDE = int(os.getenv("CHECKLIST_MAX_SIDE", "512"))
SAMPLE_PCT = int(os.getenv("CHECKLIST_SAMPLE_PCT", "20"))
MAX_TOKENS = int(os.getenv("CHECKLIST_MAX_TOKENS", "700"))
MAX_PHOTOS_PER_SLOT = int(os.getenv("CHECKLIST_MAX_PHOTOS", "6"))

_client = None
if AI_ENABLED and os.getenv("ANTHROPIC_API_KEY"):
    try:
        from anthropic import AsyncAnthropic
        _client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    except Exception:
        _client = None

PROMPT = (
    "Ты проверяешь чистоту в ресторане по фото. На вход — кадры одной сдачи "
    "чек-листа: зал, кухня, санузел.\n"
    "Верни СТРОГО JSON: "
    '{"ok":true|false,"issues":[{"zone":"зал|кухня|санузел","what":"<что не так, до 80 знаков>"}]}\n'
    "Отмечай только видимое: грязный пол, мусор, разводы, немытая посуда, "
    "открытые продукты, беспорядок на полках. Не выдумывай и не придирайся к "
    "мелочам — задача поймать реальную грязь, а не идеальный порядок."
)


def photo_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:32]


def shrink(data: bytes, max_side: int = MAX_SIDE) -> Tuple[bytes, str]:
    """Кадр → JPEG не длиннее max_side. Без Pillow отдаём как есть."""
    try:
        from PIL import Image
    except Exception:
        return data, "image/jpeg"
    try:
        im = Image.open(io.BytesIO(data))
        im = im.convert("RGB")
        k = min(1.0, max_side / max(im.size))
        if k < 1.0:
            im = im.resize((int(im.width * k), int(im.height * k)), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=72, optimize=True)
        return buf.getvalue(), "image/jpeg"
    except Exception:
        return data, "image/jpeg"


def tokens_for(width: int, height: int) -> int:
    """Оценка стоимости кадра в токенах — по площади (примерно w*h/750)."""
    return int(width * height / 750)


def should_review(upload: Dict[str, Any], *, late: bool = False,
                  had_issue_yesterday: bool = False,
                  rnd: Optional[float] = None) -> Tuple[bool, str]:
    """Гнать ли эту сдачу через модель. Возвращает (да/нет, причина).

    Спорные случаи проверяем всегда, остальное — выборочно: смысл не в тотальном
    контроле, а в том, чтобы管 знал, что могут проверить.
    """
    if late:
        return True, "сдано с опозданием"
    if had_issue_yesterday:
        return True, "вчера было нарушение"
    photos = upload.get("photos") or []
    if len(photos) < 3:
        return True, "меньше трёх кадров"
    import random
    r = rnd if rnd is not None else random.random()
    if r * 100 < SAMPLE_PCT:
        return True, "выборочный контроль"
    return False, "не проверяем"


async def review_slot(photos: List[Tuple[bytes, str]],
                      cache: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Один запрос на слот: все зоны одним документом.

    cache — {хеш кадра: результат}; повторный кадр не оплачивается.
    Без ключа или с выключенным рубильником возвращает «не проверяли».
    """
    if not photos:
        return {"checked": False, "reason": "нет кадров"}
    cache = cache if cache is not None else {}
    keys = [photo_hash(d) for d, _ in photos]
    if keys and all(k in cache for k in keys):
        return {"checked": True, "cached": True, **cache[keys[0]]}
    if _client is None:
        return {"checked": False, "reason": "разбор фото выключен (CHECKLIST_AI)"}

    content: List[Dict[str, Any]] = []
    for data, zone in photos[:MAX_PHOTOS_PER_SLOT]:
        small, mime = shrink(data)
        import base64
        content.append({"type": "text", "text": f"Зона: {zone}"})
        content.append({"type": "image", "source": {
            "type": "base64", "media_type": mime,
            "data": base64.b64encode(small).decode()}})
    try:
        resp = await _client.messages.create(
            model=MODEL, max_tokens=MAX_TOKENS, system=PROMPT,
            messages=[{"role": "user", "content": content}])
        txt = "".join(getattr(c, "text", "") for c in resp.content).strip()
        start, end = txt.find("{"), txt.rfind("}")
        data = json.loads(txt[start:end + 1]) if start >= 0 and end > start else {}
        out = {"checked": True, "ok": bool(data.get("ok")), "issues": data.get("issues") or []}
    except Exception as e:
        return {"checked": False, "reason": f"модель не ответила: {e!r}"[:160]}
    for k in keys:
        cache[k] = {"ok": out["ok"], "issues": out["issues"]}
    return out
