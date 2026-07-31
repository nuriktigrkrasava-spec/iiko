import type { Case } from '../cases/types'
import { buildingOf } from '../cases/nodes'

/* Экран зависит от того, кто вошёл. Это не формальность: запись о фроде,
   показанная тому, кого проверяют, ломает всю функцию. Права выдаёт владелец
   вручную (бэкенд-фаза); здесь — фильтр подачи, применяется до рендера. */

export type Role = 'owner' | 'manager' | 'chef' | 'waiter'

export function visibleCases(role: Role, cases: Case[], myBranch: string | null): Case[] {
  switch (role) {
    case 'owner':
      return cases
    case 'manager':
      // только свой филиал; подозрения на воровство своих сотрудников — никогда
      return cases.filter((c) =>
        c.branch_id === myBranch && !c.node_id.startsWith('cash.fraud'))
    case 'chef':
      // кухня и склад; сумм выручки не видит
      return cases.filter((c) =>
        ['kitchen', 'storage'].includes(buildingOf(c.node_id)) &&
        !c.node_id.startsWith('revenue') &&
        (c.branch_id === myBranch || c.branch_id === null))
    case 'waiter':
      // только свои столы; аналитики нет вообще
      return []
  }
}

export function roleFromUrl(): { role: Role; branch: string | null } {
  const p = new URLSearchParams(window.location.search)
  const r = p.get('role')
  const role: Role = r === 'manager' || r === 'chef' || r === 'waiter' ? r : 'owner'
  return { role, branch: p.get('branch') }
}
