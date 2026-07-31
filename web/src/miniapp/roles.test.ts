import { describe, it, expect } from 'vitest'
import { visibleCases, type Role } from './roles'
import type { Case } from '../cases/types'

const mk = (node_id: string, branch_id: string | null): Case => ({
  id: `${node_id}:${branch_id ?? 'all'}`, node_id, branch_id,
  title: 't', body: 'b', amount_kzt: 100000, estimated: false,
  period_from: '', period_to: '', confidence: 'high', status: 'new', evidence: [],
})

const cases: Case[] = [
  mk('foodcost.delta', 'abaya'),
  mk('foodcost.delta.storage', 'abaya'),
  mk('cash.fraud.refund', 'abaya'),
  mk('revenue.menu.dogs', 'dostyk'),
  mk('street.reviews', null),
]

describe('роли видят только своё', () => {
  it('владелец видит всё', () => {
    expect(visibleCases('owner', cases, null)).toHaveLength(5)
  })
  it('управляющий: только свой филиал и без фрода своих сотрудников', () => {
    const v = visibleCases('manager', cases, 'abaya')
    expect(v.map((c) => c.node_id)).toEqual(['foodcost.delta', 'foodcost.delta.storage'])
  })
  it('шеф: кухня и склад, без выручки и без кассы', () => {
    const v = visibleCases('chef', cases, 'abaya')
    expect(v.every((c) => ['kitchen', 'storage'].includes(nodeBuilding(c)))).toBe(true)
    expect(v.some((c) => c.node_id.startsWith('revenue'))).toBe(false)
  })
  it('официант аналитики не видит', () => {
    expect(visibleCases('waiter', cases, 'abaya')).toHaveLength(0)
  })
})

import { buildingOf } from '../cases/nodes'
function nodeBuilding(c: Case) { return buildingOf(c.node_id) }

export type { Role }
