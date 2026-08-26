import { useEffect, useState } from 'react'
import { Glass } from './ui'
import { SLOTS as DEFAULT_SLOTS, type Done, type Review, issueText, slotPassed } from './checklist'

/* Чек-листы филиалов глазами владельца: кто сдал, кто нет.

   Управляющий чек-лист СДАЁТ (ChecklistUpload), владелец его СПРАШИВАЕТ — это
   разные экраны, и второго на сайте не было вовсе: в «Горе» от всей сдачи
   оставался чип «чек-листы 3» внутри прогресса, по которому нельзя понять, кто
   именно не снял санузел в 20:45. Здесь — сетка филиалы × слоты за сегодня.

   Ходим в тот же /api/mountain/checklist/{token}: владельцу он и так отдаёт
   сдачи по всем его филиалам. */

const shortName = (name: string) => name.replace(/^Астана,?\s*(ул\.?)?\s*/i, '').trim() || name

export default function ChecklistBoard({ token, branches }: { token: string; branches: string[] }) {
  const [done, setDone] = useState<Done[]>([])
  const [reviews, setReviews] = useState<Review[]>([])
  const [slots, setSlots] = useState<string[]>(DEFAULT_SLOTS)
  const [zoneCount, setZoneCount] = useState(3)

  useEffect(() => {
    fetch(`/api/mountain/checklist/${token}`).then((r) => r.json())
      .then((d: { done?: Done[]; reviews?: Review[]; slots?: string[]; zones?: Record<string, string> }) => {
        setDone(d.done || [])
        setReviews(d.reviews || [])
        if (d.slots?.length) setSlots(d.slots)
        if (d.zones) setZoneCount(Object.keys(d.zones).length)
      }).catch(() => {})
  }, [token])

  const cell = (branch: string, slot: string) =>
    done.filter((d) => d.branch === branch && d.slot === slot)
  const problems = reviews.filter((r) => !r.ok && (r.issues || []).length)

  return (
    <Glass span={12}>
      <div className="eyebrow"><span>Чек-листы филиалов</span>
        <span className="hint">сегодня · зон в слоте {zoneCount}</span></div>

      <div style={{ marginTop: 12, overflowX: 'auto' }}>
        <table style={{ width: '100%', minWidth: 380, borderCollapse: 'collapse', fontSize: 12.5 }}>
          <thead><tr>
            <th style={{ textAlign: 'left', padding: '0 0 8px', fontSize: 10, letterSpacing: '.1em', textTransform: 'uppercase', color: 'var(--mute)', fontWeight: 600, borderBottom: '1px solid var(--hair)' }}>Филиал</th>
            {slots.map((s) => (
              <th key={s} className="tnum" style={{ textAlign: 'center', padding: '0 0 8px', fontSize: 10.5, color: 'var(--mute)', fontWeight: 600, borderBottom: '1px solid var(--hair)' }}>{s}</th>
            ))}
          </tr></thead>
          <tbody>
            {branches.map((b) => (
              <tr key={b}>
                <td style={{ padding: '9px 8px 9px 0', borderBottom: '1px solid var(--hair-2)', color: 'var(--hi)' }}>{shortName(b)}</td>
                {slots.map((s) => {
                  const got = cell(b, s)
                  const full = got.length >= zoneCount
                  // прошедший слот без сдачи — это и есть «не сдал», он красный;
                  // будущий просто ждёт своего часа
                  const late = !got.length && slotPassed(s)
                  const col = full ? 'var(--grn)' : got.length ? 'var(--amb)' : late ? 'var(--red)' : 'var(--mute)'
                  return (
                    <td key={s} className="tnum" title={got.map((g) => `${g.zone} · ${g.at}`).join('\n') || 'не сдано'}
                      style={{ padding: '9px 0', borderBottom: '1px solid var(--hair-2)', textAlign: 'center', color: col, fontWeight: got.length ? 700 : 500 }}>
                      {full ? '✓' : got.length ? `${got.length}/${zoneCount}` : late ? '—' : '·'}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Замечания разбора: ради них чек-лист и снимают — иначе это просто галочки */}
      {problems.length > 0 && (
        <div style={{ marginTop: 12, display: 'grid', gap: 6 }}>
          {problems.slice(0, 6).map((r, i) => (
            <div key={`${r.branch}${r.slot}${i}`} style={{ display: 'flex', gap: 10, alignItems: 'baseline', fontSize: 12.5 }}>
              <span className="tnum" style={{ color: 'var(--mute)', flex: 'none' }}>{r.slot}</span>
              <span style={{ color: 'var(--hi)', flex: 'none', fontWeight: 650 }}>{shortName(r.branch || '')}</span>
              <span style={{ color: 'var(--red)' }}>{(r.issues || []).map(issueText).join(' · ')}</span>
            </div>
          ))}
        </div>
      )}
    </Glass>
  )
}
