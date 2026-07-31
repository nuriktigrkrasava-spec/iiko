import { useEffect, useState, useCallback } from 'react'
import { apiGet } from '../lib/api'
import { runRules, type Ctx } from './rules'
import { getStatus } from './store'
import { nodeOf } from './nodes'
import type { Case, CaseStatus } from './types'

/* Грузит существующие эндпоинты → строит Ctx → правила → дедуп по узлу →
   накладывает статусы → сортирует по ₸. Рантайм НЕ трогает бэкенд-запись. */

const P = { period: 'month' } as const
async function grab<T>(path: string, fallback: T): Promise<T> {
  try { return await apiGet<T>(path, P) } catch { return fallback }
}

const OPEN: CaseStatus[] = ['new', 'accepted', 'auditing', 'verifying']

export type FeedData = {
  cases: Case[]
  loading: boolean
  error: string | null
  total_kzt: number   // сумма только по открытым листьям
  open: number
  reload: () => void
}

export function useCases(): FeedData {
  const [cases, setCases] = useState<Case[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [tick, setTick] = useState(0)
  const reload = useCallback(() => setTick((t) => t + 1), [])

  useEffect(() => {
    let alive = true
    setLoading(true)
    setError(null)
    Promise.all([
      grab('foodcost', { norm_sum: 0, fact_sum: 0, fact_pct: 0, norm_pct: 0, dishes: [] }),
      grab('writeoffs', { categories: [] }),
      grab('cancels', { items: [], total_amount: 0, total_orders: 0 }),
      grab('sales', { top_dishes: [] }),
      grab('clients', { segments: { repeat_pct: 0 } }),
      grab('retention', { frequency: [] }),
      grab('reviews', { reviews: [] }),
    ]).then(([foodcost, writeoffs, cancels, sales, clients, retention, reviews]) => {
      if (!alive) return
      const ctx = {
        foodcost, writeoffs, cancels, sales, clients, retention, reviews,
        period: { from: '', to: '' }, branch_id: null,
      } as unknown as Ctx

      // дедуп по node_id — оставляем самый дорогой кейс на узел (одна карточка = одна проблема)
      const byNode = new Map<string, Case>()
      for (const c of runRules(ctx)) {
        const prev = byNode.get(c.node_id)
        if (!prev || c.amount_kzt > prev.amount_kzt) byNode.set(c.node_id, c)
      }
      const list = [...byNode.values()]
        .map((c) => ({ ...c, status: getStatus(c.id) }))
        .sort((a, b) => b.amount_kzt - a.amount_kzt)
      setCases(list)
    }).catch((e) => alive && setError(String(e?.message || e)))
      .finally(() => alive && setLoading(false))
    return () => { alive = false }
  }, [tick])

  const openCases = cases.filter((c) => OPEN.includes(c.status) && (nodeOf(c.node_id)?.is_leaf ?? true))
  const total_kzt = openCases.reduce((s, c) => s + c.amount_kzt, 0)

  return { cases, loading, error, total_kzt, open: openCases.length, reload }
}
