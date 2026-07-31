import { describe, it, expect } from 'vitest'
import { GROWTH_NODES, nodeOf, leafIds } from './nodes'

describe('growth nodes', () => {
  it('у каждого узла с родителем родитель существует', () => {
    const ids = new Set(GROWTH_NODES.map((n) => n.node_id))
    for (const n of GROWTH_NODES) {
      if (n.parent_id) expect(ids.has(n.parent_id)).toBe(true)
    }
  })

  it('лист порционной дельты живёт на кухне', () => {
    expect(nodeOf('foodcost.delta.portion')?.building).toBe('kitchen')
  })

  it('листьев больше шести', () => {
    expect(leafIds().length).toBeGreaterThan(6)
  })
})
