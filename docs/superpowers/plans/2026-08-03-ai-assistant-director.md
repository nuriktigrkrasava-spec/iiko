# ИИ-ассистент «Директор» — Implementation Plan (Фаза 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Заменить демо-агента (`web/src/lg/Agent.tsx`) на проактивного ИИ-советника: бэкенд собирает реальные сигналы по всем филиалам, Claude превращает их в приоритезированные советы «проблема → деньги → что сделать» с опциональными действиями (открыть вкладку / показать динамику); при недоступности Claude — детерминированный фоллбэк на правила.

**Architecture:** Новый эндпоинт `GET /api/assistant` в `api.py` собирает компактные сигналы по филиалам **залогиненного клиента** (`get_restaurants(user.id)`, 1..N — продукт мультитенантный, число филиалов нигде не захардкожено), переиспользуя существующие route-функции, передаёт их модулю `assistant_ai.py` (по образцу `claude_api.py`), который вызывает Claude и парсит структурированный список советов. `Agent.tsx` тянет `/api/assistant`, проактивно всплывает 1–2 карточками и показывает список с кнопками-действиями. Действия исполняются через существующий механизм `window.dispatchEvent('lg:go', ...)`.

**Tech Stack:** Python 3 / FastAPI (`api.py`), `anthropic` AsyncAnthropic (уже в `requirements.txt`, 0.97.0). React + Vite + TS (`web/src/lg`). Тесты: pytest (Python), `npx tsc -b` (типы фронта).

## Global Constraints

- **Модель Claude:** `claude-opus-5` (значение по умолчанию по правилам claude-api). Существующий `insights_service.py` использует `claude-opus-4-8` — если владелец предпочтёт единообразие, заменить константу; не менять без явного решения.
- **Грудинг:** Claude получает уже посчитанные нами числа и обязан использовать их. Никаких выдуманных сумм/процентов. Системный промпт это фиксирует.
- **Деградация:** при отсутствии `ANTHROPIC_API_KEY`, таймауте, ошибке или невалидном JSON — детерминированный фоллбэк `rules_advice(signals)`. Фича всегда что-то возвращает.
- **Демо:** при `_use_demo_data` — вернуть демо-советы (не звать Claude, не палить ключ).
- **Мультитенант:** филиалы всегда = `get_restaurants(user.id)` залогиненного клиента (1..N), не захардкоженное число. В совете указывается филиал.
- **Масштаб (большие сети):** сбор сигналов дросселируется семафором (не более 5–6 параллельных вызовов iiko), чтобы не хаммерить сервер клиента с десятками филиалов. Факт-пейлоад в Claude — только агрегаты (проценты/суммы/топ-1), не сырые списки.
- **Действия — белый список:** фронт исполняет только `navigate` и `showMetric`; неизвестные типы игнорируются. (Действие `proposeShift` — Фаза 2, вне этого плана.)
- **Без чата:** текстовый ввод и `reply()` удаляются полностью.

## File Structure

- **Create `assistant_ai.py`** (корень репо, рядом с `claude_api.py`): чистая логика «сигналы → советы». Экспортирует `rules_advice(signals) -> list[dict]` (детерминированно, без сети) и `async def advise(signals) -> list[dict]` (Claude + парсинг, фоллбэк на правила). Не знает про FastAPI/HTTP — тестируется изолированно.
- **Modify `api.py`**: добавить `_gather_assistant_signals(user) -> dict` и route `GET /api/assistant`. Route — тонкий: собрать сигналы → `await assistant_ai.advise(...)` → вернуть.
- **Create `web/src/lg/assistant.ts`**: типы (`Advice`, `AdviceAction`) + `runAction(a)` (навигация/подсветка через `lg:go`). Изолирует логику действий от компонента.
- **Rewrite `web/src/lg/Agent.tsx`**: убрать чат/`reply`/`TIPS`; тянуть `/api/assistant`; проактивные тосты + панель советов с кнопками-действиями.
- **Create `web/src/lg/assistant.test.ts`**: юнит на `runAction` (диспатчит правильное событие).
- **Create `tests/test_assistant_ai.py`** (или рядом с прочими py-тестами, если есть каталог): юниты на `rules_advice` и парсер.

---

### Task 1: `assistant_ai.py` — правила-фоллбэк + парсер

**Files:**
- Create: `assistant_ai.py`
- Test: `tests/test_assistant_ai.py`

**Interfaces:**
- Produces: `rules_advice(signals: dict) -> list[dict]` — детерминированные советы из сигналов, отсортированы по `money` убыв.; `_parse_advice(raw_text: str) -> list[dict]` — парсит JSON-массив советов из ответа Claude (снимает markdown-обёртку), бросает при мусоре.
- Advice-словарь: `{"id": str, "branch": str, "severity": "high"|"med"|"low", "title": str, "detail": str, "money": float|None, "action": dict|None}`. `action` (если есть): `{"type": "navigate"|"showMetric", "tab": str, "hint": str|None}`.
- Signals-словарь (вход): `{"branches": [{"name": str, "foodcost": {...}|None, "revenue": float|None, "cancels": float|None, "writeoffs_pct": float|None, "reviews": [...], "peak": {"day": str, "hour": int}|None, "has_recipes": bool, "has_socials": bool}]}`.

- [ ] **Step 1: Write the failing test для rules_advice**

```python
# tests/test_assistant_ai.py
from assistant_ai import rules_advice, _parse_advice

def test_rules_advice_flags_high_foodcost_with_money_and_sorts():
    signals = {"branches": [
        {"name": "Актобе", "foodcost": {"fact_pct": 56.0, "norm_pct": 30, "fact_sum": 500000},
         "revenue": 900000, "cancels": 40000, "writeoffs_pct": 3.0,
         "reviews": [], "peak": None, "has_recipes": True, "has_socials": False},
    ]}
    out = rules_advice(signals)
    # фудкост 56% при норме 30% и отмены 40k → минимум два совета, самый денежный первым
    assert len(out) >= 2
    assert out[0]["money"] >= out[1]["money"]
    fc = next(a for a in out if "удкост" in a["title"] or "удкост" in a["detail"])
    assert fc["branch"] == "Актобе"
    assert fc["action"] == {"type": "navigate", "tab": "fc", "hint": None}

def test_rules_advice_socials_plan_when_not_connected():
    signals = {"branches": [
        {"name": "Актау", "foodcost": None, "revenue": 800000, "cancels": 0,
         "writeoffs_pct": 0, "reviews": [], "peak": None,
         "has_recipes": False, "has_socials": False},
    ]}
    out = rules_advice(signals)
    assert any(a["action"] == {"type": "navigate", "tab": "rep", "hint": None} for a in out)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_assistant_ai.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'assistant_ai'`.

- [ ] **Step 3: Write `assistant_ai.py` (rules + parser + advise)**

```python
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
    return data
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_assistant_ai.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Add parser test + `advise()` with fallback**

Add test:

```python
def test_parse_advice_strips_markdown():
    raw = '```json\n[{"branch":"X","title":"t","detail":"d","money":10,"severity":"low"}]\n```'
    out = _parse_advice(raw)
    assert out[0]["branch"] == "X"
```

Append to `assistant_ai.py`:

```python
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
```

- [ ] **Step 6: Run tests + commit**

Run: `.venv/bin/python -m pytest tests/test_assistant_ai.py -q` → PASS (3 passed).

```bash
git add assistant_ai.py tests/test_assistant_ai.py
git commit -m "feat(assistant): движок советов (правила + Claude) для ИИ-ассистента"
```

---

### Task 2: `_gather_assistant_signals` в `api.py`

**Files:**
- Modify: `api.py` (добавить функцию рядом с другими хелперами, напр. после `_attendance_journal`)
- Test: ручная проверка через curl в Task 3 (сбор зависит от живого iiko; юнит-мок избыточен для Ф1).

**Interfaces:**
- Produces: `async def _gather_assistant_signals(user: Dict) -> Dict[str, Any]` — по каждому филиалу владельца собирает компактные сигналы (см. форму в Task 1). Устойчив к сбою отдельного филиала (try/except на филиал).

- [ ] **Step 1: Реализовать сбор сигналов**

Route-функции в `api.py` — обычные async-функции; вызываем их напрямую, передавая `user` и, где нужно, throwaway `Response`. Собираем дёшево: `foodcost(compute=1)`, `dashboard`, `cancels`, `reviews`, `load-heatmap`. Флаги наполненности берём из результатов (cost_available, platforms).

```python
async def _gather_assistant_signals(user: Dict[str, Any]) -> Dict[str, Any]:
    """Компактные сигналы по всем филиалам ЗАЛОГИНЕННОГО клиента (1..N) для ИИ-ассистента.
    Сбой одного филиала не роняет остальные. Семафор ограничивает нагрузку на iiko
    у больших сетей (десятки филиалов)."""
    from fastapi import Response as _Resp
    rests = get_restaurants(user.get("id", 0))
    out_branches: List[Dict[str, Any]] = []
    sem = asyncio.Semaphore(6)  # не более 6 филиалов одновременно → не хаммерим сервер клиента

    async def one(r: Dict[str, Any]) -> Dict[str, Any]:
        org = r.get("organization_id")
        name = r.get("organization_name") or "Филиал"
        b: Dict[str, Any] = {"name": name, "foodcost": None, "revenue": None,
                             "cancels": None, "writeoffs_pct": None, "reviews": [],
                             "peak": None, "has_recipes": None, "has_socials": None}
        try:
            fc = await foodcost(org, "month", 1, user)
            b["has_recipes"] = fc.get("fact_pct") is not None
            if fc.get("fact_pct") is not None:
                b["foodcost"] = {"fact_pct": fc["fact_pct"], "norm_pct": fc.get("norm_pct", 30),
                                 "fact_sum": fc.get("fact_sum")}
        except Exception as e:
            logger.warning(f"[assistant] foodcost {name}: {e!r}")
        try:
            d = await dashboard(org, _Resp(), "month", user=user)
            b["revenue"] = d.get("revenue_today")  # revenue_today = выручка периода
        except Exception as e:
            logger.warning(f"[assistant] dashboard {name}: {e!r}")
        try:
            cn = await cancels(org, "month", user)
            b["cancels"] = cn.get("total_amount")
        except Exception as e:
            logger.warning(f"[assistant] cancels {name}: {e!r}")
        try:
            rv = await branch_reviews(org, user)
            b["has_socials"] = bool(rv.get("platforms"))
            b["reviews"] = [{"label": p.get("label"), "rating": p.get("rating"),
                             "delta": p.get("delta")} for p in rv.get("platforms", [])]
        except Exception as e:
            logger.warning(f"[assistant] reviews {name}: {e!r}")
        return b

    async def throttled(r: Dict[str, Any]) -> Dict[str, Any]:
        async with sem:  # семафор ограничивает число одновременных обращений к iiko
            return await one(r)

    results = await asyncio.gather(*(throttled(r) for r in rests), return_exceptions=True)
    for r in results:
        if isinstance(r, dict):
            out_branches.append(r)
    return {"branches": out_branches}
```

Проверить точные сигнатуры перед вызовом (`grep -n "async def dashboard\|async def cancels\|async def foodcost\|async def branch_reviews" api.py`) и подставить фактические имена/параметры (напр. `dashboard(org_id, response, period="today", ...)` — передать `_Resp()` и `period="month"`, `user=user`). Если у `cancels`/`dashboard` иная арность — привести вызовы в соответствие.

- [ ] **Step 2: Синтаксис-проверка**

Run: `.venv/bin/python -c "import ast; ast.parse(open('api.py').read()); print('OK')"`
Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add api.py
git commit -m "feat(assistant): сбор компактных сигналов по всем филиалам"
```

---

### Task 3: Эндпоинт `GET /api/assistant`

**Files:**
- Modify: `api.py` (добавить route рядом с прочими, напр. после `_gather_assistant_signals`)

**Interfaces:**
- Consumes: `_gather_assistant_signals` (Task 2), `assistant_ai.advise` (Task 1).
- Produces: `GET /api/assistant` → `{"advice": [Advice], "count": int, "demo": bool}`.

- [ ] **Step 1: Добавить импорт и route**

Вверху `api.py` (рядом с `from claude_api import ...`):

```python
import assistant_ai
```

Route:

```python
_DEMO_ADVICE = [
    {"id": "demo:fc", "branch": "Демо-ресторан", "severity": "high",
     "title": "Фудкост выше нормы", "detail": "Фудкост 36% при норме 30% — теряешь ≈ 2,9 млн/мес. Начни с техкарт топ-блюд.",
     "money": 2900000, "action": {"type": "navigate", "tab": "fc", "hint": None}},
    {"id": "demo:cn", "branch": "Демо-ресторан", "severity": "med",
     "title": "Отмены и возвраты", "detail": "Отмены на 52 тыс/мес — разбери топ-причину.",
     "money": 52000, "action": {"type": "navigate", "tab": "supply", "hint": None}},
]

@app.get("/api/assistant")
async def assistant(user: Dict = Depends(get_current_user)):
    """Проактивные советы ИИ-ассистента по всем филиалам залогиненного клиента."""
    # демо-режим: не зовём Claude, отдаём демо-советы
    rests = get_restaurants(user.get("id", 0))
    if not rests or _use_demo_data(user, (rests[0].get("organization_id") if rests else "demo-org-1")):
        return {"advice": _DEMO_ADVICE, "count": len(_DEMO_ADVICE), "demo": True}
    signals = await _gather_assistant_signals(user)
    advice = await assistant_ai.advise(signals)
    return {"advice": advice, "count": len(advice), "demo": False}
```

- [ ] **Step 2: Поднять бэк и проверить эндпоинт живьём**

Поднять `api.py` (см. `wxwx.md`) и:

```bash
curl -s "http://localhost:8000/api/assistant" | python3 -m json.tool | head -40
```

Expected: JSON с `advice` (демо-советы, если действуем как демо; реальные советы по филиалам клиента при DEV_TID). Ошибки Claude → в логе строка `[assistant] ... фоллбэк на правила`, но ответ 200 с советами из правил.

- [ ] **Step 3: Commit**

```bash
git add api.py
git commit -m "feat(assistant): эндпоинт /api/assistant (Claude + фоллбэк + демо)"
```

---

### Task 4: `web/src/lg/assistant.ts` — типы + действия

**Files:**
- Create: `web/src/lg/assistant.ts`
- Create: `web/src/lg/assistant.test.ts`

**Interfaces:**
- Produces: типы `AdviceAction`, `Advice`, `AssistantResp`; `runAction(a: AdviceAction): void` — исполняет действие (навигация через `lg:go`).

- [ ] **Step 1: Failing test**

```ts
// web/src/lg/assistant.test.ts
import { describe, it, expect, vi } from 'vitest'
import { runAction } from './assistant'

describe('runAction', () => {
  it('navigate диспатчит lg:go с нужной вкладкой', () => {
    const spy = vi.spyOn(window, 'dispatchEvent')
    runAction({ type: 'navigate', tab: 'fc' })
    const ev = spy.mock.calls.at(-1)![0] as CustomEvent
    expect(ev.type).toBe('lg:go')
    expect(ev.detail).toBe('fc')
    spy.mockRestore()
  })
})
```

- [ ] **Step 2: Run to verify fail**

Run: `cd web && npx vitest run src/lg/assistant.test.ts`
Expected: FAIL — не найден `./assistant`.

- [ ] **Step 3: Реализовать `assistant.ts`**

```ts
export type AdviceAction = { type: 'navigate' | 'showMetric'; tab: string; hint?: string | null }
export type Advice = {
  id: string; branch: string; severity: 'high' | 'med' | 'low'
  title: string; detail: string; money: number | null; action?: AdviceAction | null
}
export type AssistantResp = { advice: Advice[]; count: number; demo: boolean }

// белый список действий — исполняем только известные типы
export function runAction(a: AdviceAction): void {
  if (a.type === 'navigate' || a.type === 'showMetric') {
    window.dispatchEvent(new CustomEvent('lg:go', { detail: a.tab }))
    // showMetric: подсветка целевого показателя — Фаза 3 (пока просто навигация)
  }
}
```

- [ ] **Step 4: Run test → pass; commit**

Run: `cd web && npx vitest run src/lg/assistant.test.ts` → PASS.

```bash
git add web/src/lg/assistant.ts web/src/lg/assistant.test.ts
git commit -m "feat(assistant): типы советов + исполнение действий (навигация)"
```

---

### Task 5: Переписать `Agent.tsx` — проактивные советы вместо чата

**Files:**
- Rewrite: `web/src/lg/Agent.tsx`

**Interfaces:**
- Consumes: `useApi` (`web/src/lib/useApi.ts`), `Advice`/`AssistantResp`/`runAction` (Task 4). `useApi<AssistantResp>('assistant')` — путь без org-суффикса? Проверить: `apiGet` строит `/api/${path}/${org}`. Эндпоинт `/api/assistant` НЕ принимает org. → В `Agent.tsx` тянуть напрямую `fetch('/api/assistant')` (без useApi), т.к. ассистент кросс-филиальный.

- [ ] **Step 1: Реализовать новый `Agent.tsx`**

Убрать `reply`, `TIPS`, `CHIPS`, инпут. Тянуть советы напрямую; проактивно всплывать топ-1; тап по персонажу → панель со списком и кнопками-действиями.

```tsx
import { useEffect, useRef, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { runAction, type Advice, type AssistantResp } from './assistant'

/* Проактивный ИИ-ассистент «Директор»: сам анализирует все филиалы и выдаёт
   советы «проблема → деньги → что сделать» + действия. Не чат. */

const SEV_COLOR: Record<Advice['severity'], string> = {
  high: 'var(--red)', med: 'var(--amb)', low: 'var(--grn)',
}
const money = (n: number | null) =>
  n == null ? '' : n >= 1e6 ? `${(n / 1e6).toFixed(1).replace('.', ',')} млн ₸` : `${Math.round(n / 1000)} тыс ₸`

export default function Agent() {
  const [open, setOpen] = useState(false)
  const [advice, setAdvice] = useState<Advice[]>([])
  const [notif, setNotif] = useState<Advice | null>(null)

  useEffect(() => {
    let alive = true
    fetch('/api/assistant', { headers: { Accept: 'application/json' } })
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((d: AssistantResp) => { if (alive) setAdvice(d.advice || []) })
      .catch(() => {})
    return () => { alive = false }
  }, [])

  // проактивно всплываем топ-советом, когда панель закрыта
  useEffect(() => {
    if (open || advice.length === 0) { setNotif(null); return }
    const t = setTimeout(() => setNotif(advice[0]), 3500)
    return () => clearTimeout(t)
  }, [open, advice])

  const act = (a: Advice) => { if (a.action) runAction(a.action); setOpen(false) }

  return (
    <>
      {!open && (
        <button className="lg-agent-fab" onClick={() => setOpen(true)} aria-label="ИИ-ассистент">
          <img src="/agent2.png" alt="" />
          <span className="lg-agent-dot" />
        </button>
      )}

      <AnimatePresence>
        {notif && !open && (
          <motion.button className="lg-agent-toast" onClick={() => setOpen(true)}
            initial={{ opacity: 0, y: 10, scale: 0.96 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 10, scale: 0.96 }}>
            <img src="/agent2.png" alt="" />
            <span><b style={{ color: SEV_COLOR[notif.severity] }}>{notif.branch}</b> · {notif.title}
              {notif.money != null && <> · <span className="tnum">≈ {money(notif.money)}/мес</span></>}</span>
          </motion.button>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {open && (
          <motion.div className="lg-chat glass" initial={{ opacity: 0, y: 16, scale: 0.96 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 16, scale: 0.96 }} transition={{ type: 'spring', stiffness: 320, damping: 30 }}>
            <div className="lg-chat-head">
              <img src="/agent2.png" alt="" />
              <div>
                <div style={{ fontSize: 13.5, fontWeight: 700, color: 'var(--hi)' }}>ИИ-директор</div>
                <div style={{ fontSize: 11, color: 'var(--grn)' }}>● смотрит все филиалы</div>
              </div>
              <button onClick={() => setOpen(false)} className="lg-chat-x" aria-label="Закрыть">×</button>
            </div>
            <div className="lg-chat-body">
              {advice.length === 0 && <div style={{ padding: '14px 2px', fontSize: 13, color: 'var(--mute)' }}>Собираю сигналы по филиалам…</div>}
              {advice.map((a) => (
                <div key={a.id} style={{ padding: '12px 0', borderTop: '1px solid var(--hair-2)' }}>
                  <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
                    <span style={{ width: 7, height: 7, borderRadius: '50%', background: SEV_COLOR[a.severity], flex: 'none' }} />
                    <span style={{ fontSize: 13.5, fontWeight: 650, color: 'var(--hi)' }}>{a.branch} · {a.title}</span>
                    {a.money != null && <span className="tnum" style={{ marginLeft: 'auto', fontSize: 13, fontWeight: 700, color: SEV_COLOR[a.severity] }}>≈ {money(a.money)}</span>}
                  </div>
                  <p style={{ margin: '6px 0 0', fontSize: 12.5, lineHeight: 1.5, color: 'var(--lo)' }}>{a.detail}</p>
                  {a.action && (
                    <button onClick={() => act(a)} style={{ marginTop: 8, fontSize: 12, fontWeight: 600, color: 'var(--acc)', background: 'color-mix(in srgb,var(--acc) 12%,transparent)', border: '1px solid color-mix(in srgb,var(--acc) 26%,transparent)', borderRadius: 10, padding: '6px 11px', cursor: 'pointer' }}>Открыть →</button>
                  )}
                </div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  )
}
```

- [ ] **Step 2: Проверка типов**

Run: `cd web && npx tsc -b`
Expected: exit 0 (нет ошибок).

- [ ] **Step 3: Прогон в браузере (реальные данные)**

Поднять стек (api:8000 + insights:8010 + vite:5180, DEV_TID). Открыть :5180 → персонаж всплывает советом; тап → список по филиалам; «Открыть →» переключает вкладку. Проверить, что при отсутствии `ANTHROPIC_API_KEY` советы всё равно есть (правила).

- [ ] **Step 4: Commit**

```bash
git add web/src/lg/Agent.tsx
git commit -m "feat(assistant): Agent.tsx — проактивные советы вместо чата"
```

---

## Self-Review

**Spec coverage:** §3.1 мозг → Task 1 (advise) + Task 2 (сигналы) + Task 3 (эндпоинт). §3.2 действия navigate/showMetric → Task 4 (`runAction`) + Task 5 (кнопки). §3.3 фронт (проактив, без чата) → Task 5. §5 фоллбэк на правила → Task 1 (`rules_advice` + `advise` except). §5 нет данных → план → `rules_advice` ветки has_recipes/has_socials. §6 многофилиальность → Task 2 (`asyncio.gather` по филиалам, филиал в совете). §7 каденс/кэш → эндпоинт зовётся при монтировании `Agent.tsx`; серверный кэш ~15 мин — **вынести в Фазу 1.1 при необходимости** (сейчас каждый монтаж = 1 вызов; для дев-нагрузки приемлемо, отметить владельцу). §10 модель по claude-api → `MODEL="claude-opus-5"` (Global Constraints).

**Проверка перед стартом (исполнителю):** сверить фактические сигнатуры `dashboard`/`cancels`/`foodcost`/`branch_reviews` в `api.py` (Task 2 Step 1) — если арность/имена отличаются, привести вызовы; убедиться, что каталог `tests/` существует (иначе создать) и pytest доступен в `.venv`.

**Note:** `proposeShift` (поставить смену) и серверный кэш ассистента — Фаза 2 / 1.1, вне этого плана.
