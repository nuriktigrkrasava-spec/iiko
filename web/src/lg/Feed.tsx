import { useState } from 'react'
import './cases.css'
import { useCases } from '../cases/generate'
import CaseCard from './CaseCard'
import { buildingOf, BUILDING_LABEL } from '../cases/nodes'
import { kzt } from '../cases/money'
import type { Building } from '../cases/types'

type Filter = 'all' | Building

const MONTHS = ['январь', 'февраль', 'март', 'апрель', 'май', 'июнь', 'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь']

function periodLabel(cases: { period_from: string }[]): string {
  const from = cases[0]?.period_from
  if (!from) return ''
  const [y, m] = from.split('-').map(Number)
  return `${MONTHS[(m ?? 1) - 1]} ${y}`
}

export default function Feed() {
  const { cases, loading, error, total_kzt, open, reload } = useCases()
  const [filter, setFilter] = useState<Filter>('all')

  const live = cases.filter((c) => c.status !== 'rejected')
  const shown = live.filter((c) => filter === 'all' || buildingOf(c.node_id) === filter)
  const buildings = [...new Set(live.map((c) => buildingOf(c.node_id)))]
  const period = periodLabel(live)

  return (
    <div className="cs-feed" style={{ gridColumn: '1 / -1' }}>
      <div className="cs-sheet">
        <header className="cs-masthead">
          <div className="cs-mast-top">
            <span className="cs-mast-title">Акт сверки</span>
            {period && <span className="cs-mast-period">{period}</span>}
          </div>

          <div className="cs-mast-figure">
            <span className="cs-mast-label">на кону</span>
            <span className="cs-mast-sum">{kzt(total_kzt)}</span>
          </div>
          <div className="cs-mast-sub">
            {open} {plural(open, 'открытый кейс', 'открытых кейса', 'открытых кейсов')} · {filter === 'all' ? 'все филиалы' : BUILDING_LABEL[filter]}
          </div>

          {buildings.length > 1 && (
            <div className="cs-filters">
              <button className={`cs-chip ${filter === 'all' ? 'on' : ''}`} onClick={() => setFilter('all')}>Все</button>
              {buildings.map((b) => (
                <button key={b} className={`cs-chip ${filter === b ? 'on' : ''}`} onClick={() => setFilter(b)}>{BUILDING_LABEL[b]}</button>
              ))}
            </div>
          )}
        </header>

        <div className="cs-ledger">
          {loading && <div className="cs-state">Собираю очередь…</div>}
          {error && <div className="cs-state">Не удалось собрать очередь: {error}</div>}
          {!loading && !error && shown.length === 0 && (
            <div className="cs-state">Открытых кейсов нет — всё в норме.</div>
          )}
          {shown.map((c) => <CaseCard key={c.id} c={c} onChange={reload} />)}
        </div>

        {shown.length > 0 && (
          <footer className="cs-total">
            <span className="cs-total-label">Итог по листьям</span>
            <span className="cs-total-sum">{kzt(shown.reduce((s, c) => s + c.amount_kzt, 0))}</span>
          </footer>
        )}
      </div>
    </div>
  )
}

function plural(n: number, one: string, few: string, many: string): string {
  const m10 = n % 10, m100 = n % 100
  if (m10 === 1 && m100 !== 11) return one
  if (m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20)) return few
  return many
}
