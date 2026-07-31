import { describe, it, expect } from 'vitest'
import { runRules, type Ctx } from './rules'

const base: Ctx = {
  foodcost: { norm_sum: 14272282, fact_sum: 17126739, fact_pct: 36, norm_pct: 30, dishes: [] },
  writeoffs: { categories: [{ name: 'Мясо и птица', written: 85000, purchases: 450000, pct: 18.9, alert: true }] },
  cancels: { items: [], total_amount: 52330, total_orders: 19 },
  sales: { top_dishes: [] },
  clients: { segments: { repeat_pct: 20 } },
  retention: { frequency: [] },
  reviews: { reviews: [] },
  period: { from: '2026-06-01', to: '2026-06-30' },
  branch_id: null,
}

describe('rules', () => {
  it('фудкост-дельта даёт кейс в ₸, помечен оценкой, без голого % и восклицаний', () => {
    const c = runRules(base).find((x) => x.node_id === 'foodcost.delta')!
    expect(c.amount_kzt).toBe(17126739 - 14272282)
    expect(c.estimated).toBe(true)
    expect(c.title).not.toMatch(/!/)
    expect(/\d%/.test(c.title)).toBe(false) // нет голого процента в заголовке дельты
  })

  it('кейс дешевле 30 000 ₸ не создаётся', () => {
    const tiny: Ctx = { ...base, foodcost: { ...base.foodcost, fact_sum: 14290000, norm_sum: 14272282 } }
    expect(runRules(tiny).some((x) => x.node_id === 'foodcost.delta')).toBe(false)
  })

  it('склад и отмены дают кейсы в ₸', () => {
    const nodes = runRules(base).map((c) => c.node_id)
    expect(nodes).toContain('foodcost.delta.storage')
    expect(nodes).toContain('cash.fraud.refund')
  })
})
