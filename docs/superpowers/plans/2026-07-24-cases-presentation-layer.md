# Слой подачи: продукт-очередь кейсов (Presentation Layer) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Заменить дашборд-из-графиков на очередь **кейсов** (одна проблема · одна сумма в ₸ · гипотеза · кнопки), собираемую детерминированными правилами из существующих `/api/*` эндпоинтов.

**Architecture:** Правила (чистые функции) считают кейсы client-side из текущих эндпоинтов; копия генерируется шаблонами (без LLM, без токенов); статус кейса хранится в localStorage (в бэкенд-фазу переедет в Postgres `cases`). Бэкенд-эндпоинты не трогаем. Лента — главный экран; старые 14 разделов становятся фильтрами/дриллдауном.

**Tech Stack:** React 19 + Vite + TypeScript, vitest (правила на TDD), существующий `useApi`/`apiGet`, дизайн-токены `lg.css`.

## Global Constraints (железные правила подачи — нарушение = переделка)

- Ни одного графика с осями/легендой. Исключение: спарклайн высотой в строку, встроенный в предложение.
- Процент без денег не показывается. «Фудкост 36%» запрещено; «Перерасход 340 000 ₸/мес» — правильно.
- Каждое число сопровождается интерпретацией в той же строке.
- Одна карточка = одна проблема (по узлу дерева, не «сводка по кухне»).
- У каждого кейса есть кнопка «Показать чеки» (прослеживаемость до первички).
- Копия: от лица продукта, активный залог, одно предложение.
- Никаких `!`, эмодзи, слов «внимание/важно/критично». Тревожность создаёт сумма в ₸.
- Порог: кейс дешевле **30 000 ₸/мес** не создаётся.
- Оценочное число помечается диапазоном и меткой «оценка», не одним цветом с фактом.
- Пол качества без объявления: мобильный, видимый focus, `prefers-reduced-motion`.
- Визуал: терминал / акт сверки — плотно, крупные числа моноширинным, узкая палитра, один акцент только на отклонения. Смелость — только на Острове (позже), всё вокруг тихое.

---

## File Structure

- `web/src/cases/nodes.ts` — справочник `GROWTH_NODES` (дерево зданий→узлов), хелперы `nodeOf`, `buildingOf`, `isLeaf`.
- `web/src/cases/types.ts` — типы `Case`, `GrowthNode`, `Building`, `CaseStatus`, `Confidence`.
- `web/src/cases/money.ts` — форматирование ₸ и диапазонов оценки (`kzt`, `kztRange`, `estimateTag`).
- `web/src/cases/rules.ts` — правила: чистые функции `(ctx) => Case[]`, порог 30 000 ₸.
- `web/src/cases/generate.ts` — грузит эндпоинты через `apiGet`, гоняет правила, дедуп по `node_id+branch_id+период`, сортировка по `amount_kzt` убыв.
- `web/src/cases/store.ts` — статусы в localStorage: `getStatus/setStatus/reject(reason)`.
- `web/src/cases/rules.test.ts` — vitest на правила (TDD).
- `web/src/lg/Feed.tsx` — Лента: шапка «N открытых · на кону X ₸» + фильтры (здание/филиал/статус) + поток `CaseCard`.
- `web/src/lg/CaseCard.tsx` — карточка кейса (бейдж здания+филиал, заголовок, сумма ₸ моно крупно, контекст+гипотеза, кнопки Взять/Показать чеки/Не согласен, диалог причины).
- `web/src/lg/cases.css` — терминальный визуал (моно-числа, узкая палитра, акцент отклонения).
- `web/src/lg/LiquidApp.tsx` (modify) — Лента = стартовый экран; док схлопывается до 4 иконок (Лента, Остров, Разговор, Ещё); старые разделы уходят в «Ещё»/фильтры.

---

## Task 1: Справочник узлов роста (growth_nodes)

**Files:**
- Create: `web/src/cases/types.ts`
- Create: `web/src/cases/nodes.ts`
- Test: `web/src/cases/nodes.test.ts`

**Interfaces:**
- Produces: `type Building = 'kitchen'|'storage'|'hall'|'cash'|'guests'|'street'`; `type GrowthNode = { node_id: string; parent_id: string|null; building: Building; is_leaf: boolean; label: string }`; `GROWTH_NODES: GrowthNode[]`; `nodeOf(id): GrowthNode|undefined`; `buildingOf(id): Building`; `leafIds(): string[]`.

- [ ] **Step 1: Write the failing test**

```ts
import { describe, it, expect } from 'vitest'
import { GROWTH_NODES, nodeOf, leafIds } from './nodes'

describe('growth nodes', () => {
  it('каждый лист имеет здание и не является родителем', () => {
    const ids = new Set(GROWTH_NODES.map(n => n.node_id))
    for (const n of GROWTH_NODES) {
      if (n.parent_id) expect(ids.has(n.parent_id)).toBe(true)
    }
    expect(nodeOf('foodcost.delta.portion')?.building).toBe('kitchen')
    expect(leafIds().length).toBeGreaterThan(6)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/cases/nodes.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Write `types.ts` and `nodes.ts`**

`types.ts` — the types listed under Interfaces plus:
```ts
export type CaseStatus = 'new'|'accepted'|'rejected'|'auditing'|'verifying'|'closed'
export type Confidence = 'high'|'medium'|'low'
export type Case = {
  id: string; node_id: string; branch_id: string | null
  title: string; body: string
  amount_kzt: number; estimated: boolean; amount_low?: number; amount_high?: number
  period_from: string; period_to: string
  confidence: Confidence; status: CaseStatus
  evidence: { kind: 'receipts'|'invoices'|'shifts'|'reviews'; label: string }[]
}
```
`nodes.ts` — a flat `GROWTH_NODES` covering the 6 buildings and the leaf nodes named in the spec's rules table (`foodcost.delta`, `foodcost.delta.portion`, `foodcost.delta.storage`, `cash.fraud.discount`, `cash.fraud.refund`, `cash.reconcile`, `revenue.menu.dogs`, `revenue.menu.puzzles`, `revenue.guests.return`, `street.reviews`) plus building roots. Implement `nodeOf`, `buildingOf`, `leafIds`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npx vitest run src/cases/nodes.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/cases/types.ts web/src/cases/nodes.ts web/src/cases/nodes.test.ts
git commit -m "feat(cases): growth-nodes справочник + типы кейсов"
```

---

## Task 2: Деньги и оценки (money.ts)

**Files:**
- Create: `web/src/cases/money.ts`
- Test: `web/src/cases/money.test.ts`

**Interfaces:**
- Produces: `kzt(n): string` («340 000 ₸»); `kztRange(low,high): string` («300–380 тыс ₸»); `MIN_CASE_KZT = 30000`.

- [ ] **Step 1: Write the failing test**

```ts
import { describe, it, expect } from 'vitest'
import { kzt, kztRange, MIN_CASE_KZT } from './money'
describe('money', () => {
  it('форматы', () => {
    expect(kzt(340000)).toBe('340 000 ₸')
    expect(kztRange(300000, 380000)).toMatch(/тыс ₸/)
    expect(MIN_CASE_KZT).toBe(30000)
  })
})
```

- [ ] **Step 2: Run — FAIL.** `cd web && npx vitest run src/cases/money.test.ts`
- [ ] **Step 3: Implement `money.ts`** (Intl.NumberFormat ru-RU; range compresses to «тыс/млн ₸»).
- [ ] **Step 4: Run — PASS.**
- [ ] **Step 5: Commit** `git commit -m "feat(cases): формат ₸ и диапазонов оценки"`

---

## Task 3: Правила генерации кейсов (rules.ts) — ядро слоя

**Files:**
- Create: `web/src/cases/rules.ts`
- Test: `web/src/cases/rules.test.ts`

**Interfaces:**
- Consumes: `Case`, `GROWTH_NODES`, `MIN_CASE_KZT` from Tasks 1–2.
- Produces: `type Ctx = { foodcost, writeoffs, cancels, sales, clients, retention, reviews, period: {from,to}, branch_id: string|null }`; `RULES: Array<(ctx: Ctx) => Case[]>`; `runRules(ctx): Case[]`.

Правила на старте (каждое — чистая функция, порог 30 000 ₸, копия по правилам подачи):
- `foodcostDelta` — узел `foodcost.delta`: перерасход = `fact_sum − norm_sum`; помечен `estimated:true` (категорийный уровень), диапазон ±15%.
- `writeoffCategory` — узел `foodcost.delta.storage`: по `writeoffs.categories[].alert`, деньги = `written` (факт), заголовок «по <категории> списали <₸> — <pct>% закупа».
- `discountFraud` — узел `cash.fraud.discount`: из `cancels`/`withdrawals` эвристика; деньги = сумма.
- `menuDogs` — узел `revenue.menu.dogs`: из `sales.top_dishes` ниже медианы по count и revenue; упущенная выгода оценкой.
- `menuPuzzles` — узел `revenue.menu.puzzles`: выше медианы по revenue, ниже по count.
- `guestReturn` — узел `revenue.guests.return`: из `clients.segments.repeat_pct`/`retention`; оценка недобора.
- `reviewUnanswered` — узел `street.reviews`: из `reviews.reviews` негатив (rating ниже порога) — деньги оценкой репутационного риска ИЛИ помечается `amount_kzt` минимальным с меткой оценки.

- [ ] **Step 1: Write the failing test** (пример на foodcostDelta + порог)

```ts
import { describe, it, expect } from 'vitest'
import { runRules, type Ctx } from './rules'

const base: Ctx = {
  foodcost: { norm_sum: 14272282, fact_sum: 17126739, fact_pct: 36, norm_pct: 30, categories: [], dishes: [] },
  writeoffs: { categories: [{ name: 'Мясо и птица', written: 85000, purchases: 450000, pct: 18.9, alert: true }] },
  cancels: { items: [], total_amount: 0, total_orders: 0 },
  sales: { top_dishes: [] }, clients: { segments: { repeat_pct: 20 } }, retention: { frequency: [] },
  reviews: { reviews: [] },
  period: { from: '2026-06-01', to: '2026-06-30' }, branch_id: null,
} as unknown as Ctx

describe('rules', () => {
  it('фудкост-дельта даёт кейс в ₸, помечен оценкой', () => {
    const c = runRules(base).find(x => x.node_id === 'foodcost.delta')!
    expect(c.amount_kzt).toBe(17126739 - 14272282)
    expect(c.estimated).toBe(true)
    expect(c.title).not.toMatch(/[36]%|!/) // без голого % и восклицаний
  })
  it('кейс дешевле 30 000 ₸ не создаётся', () => {
    const tiny = { ...base, foodcost: { ...base.foodcost, fact_sum: 14290000, norm_sum: 14272282 } }
    expect(runRules(tiny as Ctx).some(x => x.node_id === 'foodcost.delta')).toBe(false)
  })
})
```

- [ ] **Step 2: Run — FAIL.** `cd web && npx vitest run src/cases/rules.test.ts`
- [ ] **Step 3: Implement `rules.ts`** — each rule as pure function, templated one-sentence titles (active voice, ₸, no `%`-only, no `!`/emoji), `MIN_CASE_KZT` gate, `runRules` concatenates + filters.
- [ ] **Step 4: Run — PASS.**
- [ ] **Step 5: Commit** `git commit -m "feat(cases): правила генерации кейсов + порог 30k₸ (TDD)"`

---

## Task 4: Генератор + стор статусов (generate.ts, store.ts)

**Files:**
- Create: `web/src/cases/generate.ts`
- Create: `web/src/cases/store.ts`
- Test: `web/src/cases/generate.test.ts`

**Interfaces:**
- Consumes: `runRules`, `apiGet`, `Case`.
- Produces: `useCases(): { cases: Case[]; loading: boolean; error: string|null; total_kzt: number; open: number }` (хук: грузит эндпоинты, строит Ctx, `runRules`, дедуп по `node_id+branch_id`, сортировка по `amount_kzt` убыв, накладывает статусы из стора). `store`: `getStatus(id)`, `setStatus(id,status)`, `reject(id,reason)`.

- [ ] **Step 1: Write the failing test** — дедуп: два кейса одного `node_id` → один (обновляется). Мокать `apiGet`.
- [ ] **Step 2: Run — FAIL.**
- [ ] **Step 3: Implement** — `store.ts` (localStorage, ключ `iiko.cases.status`), `generate.ts` (`useCases` хук через `useApi`-стиль fetch; `total_kzt` = сумма только по листьям дерева среди открытых).
- [ ] **Step 4: Run — PASS.**
- [ ] **Step 5: Commit** `git commit -m "feat(cases): генератор кейсов + статусы в localStorage"`

---

## Task 5: Карточка кейса (CaseCard.tsx)

**Files:**
- Create: `web/src/lg/CaseCard.tsx`
- Create: `web/src/lg/cases.css`

**Interfaces:**
- Consumes: `Case`, `store`, `nodeOf/buildingOf`.
- Produces: `<CaseCard case={c} onChange={fn} />`.

Manual verification (UI): бейдж здание+филиал; заголовок одним предложением; сумма ₸ крупно моно (`--acc` только тут); 1–2 строки контекст+гипотеза; кнопки `Взять в работу` · `Показать чеки` · `Не согласен`. «Не согласен» открывает выбор причины из списка (перерасход объясним / данные неверны / уже решаю / не моя зона / другое) → `store.reject`. «Показать чеки» — раскрывает `evidence` списком (для этого слоя — метки первички; реальные ссылки в бэкенд-фазе). Терминальный визуал в `cases.css`. Оценочные суммы — с меткой «оценка» и диапазоном.

- [ ] **Step 1:** Реализовать `CaseCard.tsx` + `cases.css`.
- [ ] **Step 2:** Verify: `cd web && npx tsc --noEmit -p tsconfig.app.json` → 0 ошибок.
- [ ] **Step 3: Commit** `git commit -m "feat(cases): карточка кейса + терминальный визуал"`

---

## Task 6: Лента (Feed.tsx) + встраивание как главный экран

**Files:**
- Create: `web/src/lg/Feed.tsx`
- Modify: `web/src/lg/LiquidApp.tsx`

**Interfaces:**
- Consumes: `useCases`, `CaseCard`.
- Produces: `<Feed />` (default export).

Лента: шапка одной строкой «N открытых · на кону X ₸» (X — сумма по листьям); фильтры-чипы (здание · филиал · статус); вертикальный поток `CaseCard` по убыванию суммы; пустое состояние («Открытых кейсов нет — всё в норме», без восклицаний). LiquidApp: `Лента` = стартовый `active`; док схлопывается до 4 (Лента · Остров · Разговор · Ещё); «Ещё» открывает прежние 14 разделов как дриллдаун/доказательную базу (не удаляем).

- [ ] **Step 1:** Реализовать `Feed.tsx`; в `LiquidApp` добавить секцию `feed` первой, `active` по умолчанию `feed`, док — 4 иконки, остальные в подменю.
- [ ] **Step 2:** Verify: tsc 0 ошибок; `npm run dev` открывает Ленту первой.
- [ ] **Step 3: Commit** `git commit -m "feat(cases): Лента как главный экран, док в 4 иконки"`

---

## Task 7: Разговор (Ask.tsx) — минимально

**Files:**
- Create: `web/src/lg/Ask.tsx`
- Modify: `web/src/lg/LiquidApp.tsx` (секция `ask`)

Поле «спросить». Ответ — одно предложение из посчитанных сигналов (правила, не LLM) плюс при необходимости короткая таблица; никогда график. Для этого слоя — сопоставление вопроса с ближайшим кейсом/сигналом и шаблонный ответ. LLM-ответ — позже за флагом.

- [ ] **Step 1:** Реализовать `Ask.tsx` (детерминированный ответ по ключевым словам → кейс/сигнал).
- [ ] **Step 2:** Verify tsc 0 ошибок.
- [ ] **Step 3: Commit** `git commit -m "feat(cases): экран Разговор (детерминированные ответы)"`

---

## Вне этого плана (отдельные планы, нужна инфра/решения)

- **Зеркало iiko в Postgres + миграции `growth_nodes/cases/weighings/audits`** — нужен Postgres + креды синка iiko.
- **Настоящая дельта по ингредиентам** (теор. по техкартам vs факт по движению остатков) — нужна ингредиентная отдача; текущие эндпоинты дают уровень блюда/категории.
- **Остров на 6 зданий** (состояние без легенды, клик = фильтр Ленты, ленивый чанк, текстовый fallback) — рескоуп существующего 3D-острова.
- **Telegram-карточки с инлайн-кнопками** (общий статус с сайтом) + **голосовой недельный дайджест** — нужен бот-слой и общий стор статусов (Postgres).
- **Режим аудита + ручной ввод взвешиваний** — нужна таблица `weighings` (Postgres) и бот.
- **LLM-формулировки title/body** за флагом `INSIGHTS_AI` — включается, когда решишь тратить токены.

---

## Self-Review

- **Покрытие спеки (этот слой):** Лента ✓ (T6), карточка+кнопки ✓ (T5), правила+порог 30k ✓ (T3), деньги-первичка «показать чеки» ✓ (T5 evidence), «Не согласен»+причина ✓ (T5/T4 store), Разговор ✓ (T7), док в 4 иконки ✓ (T6), старые разделы как база ✓ (T6). Остров/Telegram/Аудит/зеркало/ингредиентная-дельта — вынесены в «Вне плана» с причиной (инфра).
- **Оценки vs факты:** правила помечают `estimated` + диапазон (T3), карточка рендерит метку (T5).
- **Железные правила** — в Global Constraints, тест T3 проверяет отсутствие голого `%` и `!` в заголовке.
