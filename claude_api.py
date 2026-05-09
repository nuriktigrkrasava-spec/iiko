import os
import hashlib
import json
import base64
from typing import Dict, Any, Optional
from anthropic import AsyncAnthropic
from database import get_ai_cache, set_ai_cache

client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY")) if os.getenv("ANTHROPIC_API_KEY") else None

async def analyze_with_claude(
    question: str,
    context: Dict[str, Any],
    org_id: str
) -> str:
    if not client:
        return "🤖 AI помощник временно недоступен. Попробуйте позже."
    
    date_str = context.get("date", "unknown")
    context_json = json.dumps(context, ensure_ascii=False, default=str)
    query_hash = hashlib.sha256(f"{question}:{context_json}".encode()).hexdigest()[:32]
    
    cached = get_ai_cache(query_hash, org_id, date_str)
    if cached:
        return cached
    
    system_prompt = (
        "Ты — аналитик ресторана. Отвечай на русском языке, кратко и по делу. "
        "Используй эмодзи где уместно. Давай конкретные рекомендации на основе предоставленных метрик. "
        "Не придумывай данных, которых нет в контексте."
    )
    
    user_prompt = f"""Контекст ресторана (JSON):
{context_json}

Вопрос менеджера: {question}

Дай развёрнутый, но лаконичный ответ с конкретными цифрами из контекста."""

    try:
        message = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}]
        )
        response = message.content[0].text
        set_ai_cache(query_hash, response, org_id, date_str)
        return response
    except Exception as e:
        return f"⚠️ Ошибка AI: {str(e)}"


INVOICE_PROMPT = """Ты помощник по распознаванию накладных и товарных чеков казахстанских ресторанов.
Извлеки структурированные данные и верни ТОЛЬКО JSON без пояснений:
{
  "supplier": "название поставщика или null",
  "branch": "название филиала/ресторана если указан или null",
  "date": "дата в формате YYYY-MM-DD или null",
  "items": [
    {"name": "название товара", "quantity": 0.0, "unit": "кг/шт/л/уп", "price_per_unit": 0.0, "total": 0.0}
  ],
  "total_amount": 0.0,
  "notes": "любые важные заметки или null"
}
Если значение не найдено — null. Quantity и цены — числа, не строки."""


async def analyze_invoice_photo(image_bytes: bytes, mime_type: str = "image/jpeg") -> Dict[str, Any]:
    """Распознаёт накладную из фото через Claude Vision."""
    if not client:
        return {"error": "AI недоступен"}
    try:
        image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
        message = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2048,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": mime_type, "data": image_b64}
                    },
                    {"type": "text", "text": INVOICE_PROMPT}
                ]
            }]
        )
        raw = message.content[0].text.strip()
        # Убираем markdown-обёртку если есть
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw.strip())
    except json.JSONDecodeError:
        return {"error": "Не удалось распарсить ответ", "raw": message.content[0].text[:500]}
    except Exception as e:
        return {"error": str(e)}


async def analyze_invoice_text(text: str) -> Dict[str, Any]:
    """Распознаёт накладную из текстового сообщения."""
    if not client:
        return {"error": "AI недоступен"}
    try:
        message = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2048,
            messages=[{
                "role": "user",
                "content": f"{INVOICE_PROMPT}\n\nТекст накладной:\n{text}"
            }]
        )
        raw = message.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw.strip())
    except json.JSONDecodeError:
        return {"error": "Не удалось распарсить", "raw": message.content[0].text[:500]}
    except Exception as e:
        return {"error": str(e)}
