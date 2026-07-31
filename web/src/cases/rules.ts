import type { Case, Confidence } from './types'
import { MIN_CASE_KZT } from './money'

/* Правила считают, LLM формулирует — здесь только детерминированная часть.
   Каждое правило — чистая функция (ctx) => Case[]. Порог 30 000 ₸.
   Копия: одно предложение, активный залог, ₸, без голого %, без ! и эмодзи. */

export type Ctx = {
  foodcost: { norm_sum: number; fact_sum: number; fact_pct: number; norm_pct: number; dishes: { name: string; category: string; revenue: number; count: number; cost_pct: number }[] }
  writeoffs: { categories: { name: string; written: number; purchases: number; pct: number; alert: boolean }[] }
  cancels: { items: { name: string; amount: number }[]; total_amount: number; total_orders: number }
  sales: { top_dishes: { name: string; revenue: number; count: number }[] }
  clients: { segments: { repeat_pct: number } }
  retention: { frequency: number[] }
  reviews: { reviews: { rating: number; text: string; date: string; author: string }[] }
  period: { from: string; to: string }
  branch_id: string | null
}

const median = (xs: number[]): number => {
  if (!xs.length) return 0
  const s = [...xs].sort((a, b) => a - b)
  const m = Math.floor(s.length / 2)
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2
}

function mk(ctx: Ctx, node_id: string, suffix: string, fields: {
  title: string; body: string; amount_kzt: number
  estimated?: boolean; amount_low?: number; amount_high?: number
  confidence?: Confidence; evidence: Case['evidence']
}): Case {
  return {
    id: `${node_id}:${ctx.branch_id ?? 'all'}:${suffix}`,
    node_id, branch_id: ctx.branch_id,
    title: fields.title, body: fields.body,
    amount_kzt: Math.round(fields.amount_kzt),
    estimated: fields.estimated ?? false,
    amount_low: fields.amount_low, amount_high: fields.amount_high,
    period_from: ctx.period.from, period_to: ctx.period.to,
    confidence: fields.confidence ?? 'medium', status: 'new',
    evidence: fields.evidence,
  }
}

/* Дельта списаний (уровень кухни/категорий) — оценка, ядро упирается в ингредиентную отдачу */
function foodcostDelta(ctx: Ctx): Case[] {
  const over = ctx.foodcost.fact_sum - ctx.foodcost.norm_sum
  if (over < MIN_CASE_KZT) return []
  return [mk(ctx, 'foodcost.delta', 'month', {
    title: 'Кухня тратит продукты сверх нормы техкарт',
    body: 'Фактический расход за период выше нормы по техкартам. Точная причина видна в разрезе смен и складского движения.',
    amount_kzt: over, estimated: true, amount_low: over * 0.85, amount_high: over * 1.15,
    confidence: 'medium', evidence: [{ kind: 'invoices', label: 'накладные и списания' }],
  })]
}

/* Дельта по складу — берём худшую категорию со списаниями выше обычного (факт) */
function writeoffStorage(ctx: Ctx): Case[] {
  const worst = [...ctx.writeoffs.categories].filter((c) => c.alert && c.written >= MIN_CASE_KZT).sort((a, b) => b.written - a.written)[0]
  if (!worst) return []
  return [mk(ctx, 'foodcost.delta.storage', worst.name, {
    title: `Списания «${worst.name}» дошли до ${worst.pct}% закупа`,
    body: `Списания по категории «${worst.name}» выше обычного. Сверьте инвентаризацию и приёмку.`,
    amount_kzt: worst.written, confidence: 'high',
    evidence: [{ kind: 'invoices', label: 'акты списания' }],
  })]
}

/* Возвраты/отмены после закрытия — фрод-паттерн (факт) */
function refundFraud(ctx: Ctx): Case[] {
  if (ctx.cancels.total_amount < MIN_CASE_KZT) return []
  return [mk(ctx, 'cash.fraud.refund', 'month', {
    title: `После закрытия чеков прошло ${ctx.cancels.total_orders} отмен`,
    body: 'В норме отмен после оплаты почти не бывает. Поднимите смены и записи по этим чекам.',
    amount_kzt: ctx.cancels.total_amount, confidence: 'high',
    evidence: [{ kind: 'receipts', label: 'чеки отмен' }, { kind: 'shifts', label: 'смены' }],
  })]
}

/* Собаки в меню — ниже медианы по продажам и выручке; упущенная выгода (оценка) */
function menuDogs(ctx: Ctx): Case[] {
  const d = ctx.sales.top_dishes
  if (d.length < 4) return []
  const medRev = median(d.map((x) => x.revenue))
  const medCnt = median(d.map((x) => x.count))
  const dogs = d.filter((x) => x.revenue < medRev && x.count < medCnt)
  const worst = dogs.sort((a, b) => a.revenue - b.revenue)[0]
  if (!worst) return []
  const gap = medRev - worst.revenue
  if (gap < MIN_CASE_KZT) return []
  return [mk(ctx, 'revenue.menu.dogs', worst.name, {
    title: `Блюдо «${worst.name}» продаётся редко и приносит мало`,
    body: 'По продажам и марже ниже медианы меню. Замена или переоформление освободит слот под более доходное блюдо.',
    amount_kzt: gap, estimated: true, amount_low: gap * 0.7, amount_high: gap * 1.3,
    confidence: 'low', evidence: [{ kind: 'receipts', label: 'продажи блюда' }],
  })]
}

export const RULES: Array<(ctx: Ctx) => Case[]> = [foodcostDelta, writeoffStorage, refundFraud, menuDogs]

export function runRules(ctx: Ctx): Case[] {
  return RULES.flatMap((r) => r(ctx)).filter((c) => c.amount_kzt >= MIN_CASE_KZT)
}
