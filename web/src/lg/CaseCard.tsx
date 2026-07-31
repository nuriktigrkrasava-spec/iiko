import { useState } from 'react'
import type { Case } from '../cases/types'
import { buildingOf, BUILDING_LABEL } from '../cases/nodes'
import { kzt, kztRange } from '../cases/money'
import { setStatus, reject, REJECT_REASONS } from '../cases/store'

/* «Бумага»: цвет означает только деньги. Здание различается словом, не цветом. */

const EVI_LABEL: Record<Case['evidence'][number]['kind'], string> = {
  receipts: 'чеки', invoices: 'накладные', shifts: 'смены', reviews: 'отзывы',
}

export default function CaseCard({ c, onChange }: { c: Case; onChange: () => void }) {
  const [showEvi, setShowEvi] = useState(false)
  const [showReasons, setShowReasons] = useState(false)
  const b = buildingOf(c.node_id)

  const take = () => { setStatus(c.id, 'auditing'); onChange() }
  const doReject = (reason: string) => { reject(c.id, reason); setShowReasons(false); onChange() }

  return (
    <div className={`cs-card ${c.status === 'rejected' ? 'rejected' : ''}`}>
      <div className="cs-badge">
        {BUILDING_LABEL[b]}<span className="sep">·</span>{c.branch_id ?? 'все филиалы'}
      </div>

      <div className="cs-top">
        <div className="cs-title">{c.title}</div>
        <div className="cs-fig">
          <div className="cs-amount">{kzt(c.amount_kzt)}</div>
          {c.estimated
            ? <div className="cs-est"><span className="tag">оценка</span>{c.amount_low != null && c.amount_high != null ? kztRange(c.amount_low, c.amount_high) : 'приблизительно'} · за месяц</div>
            : <div className="cs-est">факт · за месяц</div>}
        </div>
      </div>

      <p className="cs-body">{c.body}</p>

      {c.status === 'auditing'
        ? <div className="cs-taken">Взято в работу</div>
        : c.status === 'rejected'
          ? <div className="cs-est" style={{ marginTop: 14 }}>Отклонено</div>
          : (
            <div className="cs-actions">
              <button className="cs-btn primary" onClick={take}>Взять в работу</button>
              <button className="cs-btn" onClick={() => setShowEvi((v) => !v)}>Показать чеки</button>
              <button className="cs-btn" onClick={() => setShowReasons((v) => !v)}>Не согласен</button>
            </div>
          )}

      {showReasons && c.status !== 'rejected' && (
        <div className="cs-reasons">
          {REJECT_REASONS.map((r) => (
            <button key={r} className="cs-chip" onClick={() => doReject(r)}>{r}</button>
          ))}
        </div>
      )}

      {showEvi && (
        <div className="cs-evi">
          {c.evidence.map((e, i) => (
            <div key={i} className="cs-evi-row">
              <span className="k">{EVI_LABEL[e.kind]}</span>
              <span>{e.label}</span>
              <span className="src">первичка в зеркале iiko</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
