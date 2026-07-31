import { useState } from 'react'
import './cases.css'
import { useCases } from '../cases/generate'
import { buildingOf, BUILDING_LABEL } from '../cases/nodes'
import { kzt } from '../cases/money'
import type { Case } from '../cases/types'

/* Ответ — предложение (и при необходимости короткая таблица), никогда график.
   В этом слое — детерминированное сопоставление вопроса с ближайшим кейсом.
   LLM-ответ подключается позже за флагом. */

function answer(q: string, cases: Case[]): { text: string; rows: Case[] } {
  const open = cases.filter((c) => c.status !== 'rejected')
  if (!open.length) return { text: 'Открытых проблем нет — очередь пуста.', rows: [] }
  const t = q.toLowerCase()
  const hit = open.find((c) =>
    c.title.toLowerCase().includes(t) ||
    BUILDING_LABEL[buildingOf(c.node_id)].toLowerCase().includes(t) ||
    c.node_id.includes(t))
  if (hit) return { text: `${hit.title}. Оценка — ${kzt(hit.amount_kzt)}.`, rows: [hit] }
  const top = open[0]
  return {
    text: `Сейчас на кону ${kzt(open.reduce((s, c) => s + c.amount_kzt, 0))} по ${open.length} кейсам. Главный — ${top.title.toLowerCase()}.`,
    rows: open.slice(0, 3),
  }
}

export default function Ask() {
  const { cases, loading } = useCases()
  const [q, setQ] = useState('')
  const [res, setRes] = useState<{ text: string; rows: Case[] } | null>(null)

  const ask = () => { if (q.trim()) setRes(answer(q.trim(), cases)) }

  return (
    <div className="cs-feed" style={{ gridColumn: '1 / -1' }}>
      <div style={{ display: 'flex', gap: 10, padding: '4px 2px 18px' }}>
        <input
          value={q} onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && ask()}
          placeholder="Спросить: где течёт, что по кухне, сколько на кону…"
          style={{ flex: 1, font: 'inherit', fontSize: 14, color: 'var(--hi)', background: 'var(--glass-2)', border: '1px solid var(--hair)', borderRadius: 11, padding: '11px 14px' }}
        />
        <button className="cs-btn primary" onClick={ask} disabled={loading}>Спросить</button>
      </div>

      {res && (
        <div className="cs-card">
          <p className="cs-title" style={{ fontWeight: 550 }}>{res.text}</p>
          {res.rows.length > 1 && (
            <div className="cs-evi" style={{ marginTop: 12 }}>
              {res.rows.map((c) => (
                <div key={c.id} className="cs-evi-row">
                  <span>{c.title}</span>
                  <span className="tnum" style={{ marginLeft: 'auto', fontFamily: 'var(--mono)', color: '#ff8f6b', fontWeight: 700 }}>{kzt(c.amount_kzt)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
      {!res && <div style={{ padding: '20px 2px', color: 'var(--mute)', fontSize: 14 }}>Ответ — предложением, не графиком.</div>}
    </div>
  )
}
