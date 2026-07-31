import { useMemo, useState } from 'react'
import '../miniapp/app.css'
import City from '../miniapp/City'
import { BuildingSheet, CaseSheet } from '../miniapp/App'
import { useCases } from '../cases/generate'
import { buildingOf } from '../cases/nodes'
import type { Building } from '../cases/types'

/* Вкладка «Город» на сайте: та же ночная сцена, что и в мини-аппе.
   Переключение на соседние вкладки — событием, которое слушает LiquidApp. */

export function goSection(id: string) {
  window.dispatchEvent(new CustomEvent('lg:go', { detail: id }))
}

export default function CityScreen() {
  const { cases, reload } = useCases()
  const [openBuilding, setOpenBuilding] = useState<{ key: Building; label: string } | null>(null)
  const [openId, setOpenId] = useState<string | null>(null)

  const fresh = useMemo(() => cases.filter((c) => c.status === 'new' || c.status === 'accepted'), [cases])
  const total = fresh.reduce((s, c) => s + c.amount_kzt, 0)
  const opened = openId ? cases.find((c) => c.id === openId) ?? null : null

  return (
    <div style={{ gridColumn: '1 / -1' }}>
      <City
        embedded
        cases={cases}
        total={total}
        onOpenBuilding={(key, label) => setOpenBuilding({ key, label })}
        onAsk={() => goSection('ask')}
        onReport={() => goSection('mocks')}
        onFeed={() => goSection('feed')}
      />
      {openBuilding && (
        <BuildingSheet
          label={openBuilding.label}
          cases={cases.filter((c) => buildingOf(c.node_id) === openBuilding.key && c.status !== 'rejected' && c.status !== 'closed')}
          onCase={(id) => { setOpenBuilding(null); setOpenId(id) }}
          onFeed={() => { setOpenBuilding(null); goSection('feed') }}
          onClose={() => setOpenBuilding(null)}
        />
      )}
      {opened && <CaseSheet c={opened} onClose={() => setOpenId(null)} onChange={reload} />}
    </div>
  )
}
