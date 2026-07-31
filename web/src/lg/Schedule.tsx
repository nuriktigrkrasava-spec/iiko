import { useMemo, useState } from 'react'
import { Glass } from './ui'
import { useApi } from '../lib/useApi'
import { comparePlanFact } from './scheduleCalc'
import type { Fact, Shift } from './scheduleCalc'
import { setShift, removeShift, shiftFor } from './scheduleStore'

/* Расписание: план (расписание) — наш localStorage, факт (явки) — из iiko через
   /api/attendance. Экран составляет план с телефона и кладёт факт рядом. */

type Emp = { id: string; name: string }
type Row = { employee_id: string; name: string; date: string; start: string; end: string; hours: number }
type Att = { employees: Emp[]; rows: Row[] }

const DOW = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']

function iso(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
function mondayOf(d: Date) {
  const x = new Date(d); x.setDate(x.getDate() - ((x.getDay() + 6) % 7)); x.setHours(0, 0, 0, 0); return x
}
function addDays(d: Date, n: number) { const x = new Date(d); x.setDate(x.getDate() + n); return x }

const factToShift = (r: Row): Fact => ({ employeeId: r.employee_id, date: r.date, start: r.start, end: r.end })

function Note({ children }: { children: React.ReactNode }) {
  return <Glass span={12}><div style={{ padding: '10px 2px', fontSize: 13.5, color: 'var(--mute)' }}>{children}</div></Glass>
}

/* Плитка статуса «план vs факт» */
function Status({ plan, fact }: { plan: Shift | null; fact: Fact | null }) {
  const r = comparePlanFact(plan, fact)
  const map = {
    ontime: { t: 'Вовремя', c: 'var(--grn)' },
    late: { t: r.status === 'late' ? `Опоздание ${r.lateMin} мин` : '', c: 'var(--amb)' },
    absent: { t: 'Прогул', c: 'var(--red)' },
    noplan: { t: 'Вне графика', c: 'var(--mute)' },
  }[r.status]
  const over = (r.status === 'ontime' || r.status === 'late') && r.overtimeMin > 0
  return (
    <span style={{ display: 'inline-flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap' }}>
      <span style={{ fontSize: 12, fontWeight: 620, color: map.c }}>{map.t}</span>
      {over && <span style={{ fontSize: 11, color: 'var(--grn)' }}>+{r.overtimeMin} мин сверх</span>}
    </span>
  )
}

/* Инлайн-редактор смены в клетке недели */
function CellEditor({ init, onSave, onClear, onClose }: {
  init: Shift | null
  onSave: (start: string, end: string) => void
  onClear: () => void
  onClose: () => void
}) {
  const [start, setStart] = useState(init?.start ?? '10:00')
  const [end, setEnd] = useState(init?.end ?? '18:00')
  const inp: React.CSSProperties = {
    background: 'var(--glass-2)', border: '1px solid var(--hair)', borderRadius: 9,
    padding: '7px 9px', color: 'var(--hi)', fontSize: 13, fontVariantNumeric: 'tabular-nums',
  }
  const btn: React.CSSProperties = { border: '1px solid var(--hair)', borderRadius: 9, padding: '7px 12px', fontSize: 12.5, cursor: 'pointer', background: 'transparent', color: 'var(--lo)' }
  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginTop: 12, padding: 12, borderRadius: 13, border: '1px solid var(--hair)', background: 'var(--glass-2)' }}>
      <input type="time" value={start} onChange={(e) => setStart(e.target.value)} style={inp} aria-label="Начало" />
      <span style={{ color: 'var(--mute)' }}>–</span>
      <input type="time" value={end} onChange={(e) => setEnd(e.target.value)} style={inp} aria-label="Конец" />
      <button style={{ ...btn, borderColor: 'var(--grn)', color: 'var(--grn)' }} onClick={() => onSave(start, end)}>Сохранить</button>
      {init && <button style={btn} onClick={onClear}>Убрать</button>}
      <button style={{ ...btn, marginLeft: 'auto' }} onClick={onClose}>Отмена</button>
    </div>
  )
}

export default function Schedule() {
  const [weekStart, setWeekStart] = useState(() => mondayOf(new Date()))
  const [editing, setEditing] = useState<{ emp: string; date: string } | null>(null)
  const [, setVer] = useState(0)
  const bump = () => setVer((v) => v + 1)

  const days = useMemo(() => Array.from({ length: 7 }, (_, i) => addDays(weekStart, i)), [weekStart])
  const { data, error, loading } = useApi<Att>('attendance', { from: iso(days[0]), to: iso(days[6]) })

  const factMap = useMemo(() => {
    const m: Record<string, Row> = {}
    for (const r of data?.rows ?? []) m[`${r.employee_id}|${r.date}`] = r
    return m
  }, [data])

  if (loading) return <Note>Собираю явки…</Note>
  if (error || !data) return <Note>Не удалось загрузить явки: {error}</Note>

  const emps = data.employees
  const cell: React.CSSProperties = { padding: '9px 6px', textAlign: 'center', fontSize: 12, borderTop: '1px solid var(--hair-2)' }
  const label = (d: Date) => `${DOW[(d.getDay() + 6) % 7]} ${d.getDate()}`

  return (
    <>
      {/* ── Составить расписание ── */}
      <Glass span={12}>
        <div className="eyebrow" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span>Расписание · план</span>
          <span style={{ display: 'inline-flex', gap: 10, alignItems: 'center' }}>
            <button aria-label="Прошлая неделя" onClick={() => setWeekStart(addDays(weekStart, -7))} style={weekBtn}>‹</button>
            <span className="hint" style={{ minWidth: 96, textAlign: 'center' }}>{iso(days[0]).slice(5)} – {iso(days[6]).slice(5)}</span>
            <button aria-label="Следующая неделя" onClick={() => setWeekStart(addDays(weekStart, 7))} style={weekBtn}>›</button>
          </span>
        </div>

        <div style={{ overflowX: 'auto', marginTop: 12 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 560 }}>
            <thead>
              <tr>
                <th style={{ ...cell, borderTop: 'none', textAlign: 'left', color: 'var(--mute)' }}>Сотрудник</th>
                {days.map((d) => <th key={iso(d)} style={{ ...cell, borderTop: 'none', color: 'var(--mute)' }}>{label(d)}</th>)}
              </tr>
            </thead>
            <tbody>
              {emps.map((e) => (
                <tr key={e.id}>
                  <td style={{ ...cell, textAlign: 'left', fontWeight: 600, color: 'var(--hi)', whiteSpace: 'nowrap' }}>{e.name}</td>
                  {days.map((d) => {
                    const dISO = iso(d)
                    const s = shiftFor(e.id, dISO)
                    const on = editing?.emp === e.id && editing?.date === dISO
                    return (
                      <td key={dISO} style={cell}>
                        <button
                          onClick={() => setEditing(on ? null : { emp: e.id, date: dISO })}
                          style={{
                            width: '100%', cursor: 'pointer', borderRadius: 8, padding: '6px 4px',
                            fontSize: 11.5, fontVariantNumeric: 'tabular-nums',
                            border: `1px solid ${on ? 'var(--acc)' : s ? 'var(--hair)' : 'transparent'}`,
                            background: s ? 'var(--glass-2)' : 'transparent',
                            color: s ? 'var(--hi)' : 'var(--mute)',
                          }}
                        >
                          {s ? `${s.start}–${s.end}` : '+'}
                        </button>
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {editing && (
          <CellEditor
            init={shiftFor(editing.emp, editing.date)}
            onSave={(start, end) => { setShift({ employeeId: editing.emp, date: editing.date, start, end }); setEditing(null); bump() }}
            onClear={() => { removeShift(editing.emp, editing.date); setEditing(null); bump() }}
            onClose={() => setEditing(null)}
          />
        )}
        <div style={{ marginTop: 12, fontSize: 11.5, color: 'var(--amb)', display: 'inline-flex', alignItems: 'center', gap: 6 }}>
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--amb)', boxShadow: '0 0 6px var(--amb)' }} />
          план сохраняется на устройстве · факт — из явок iiko
        </div>
      </Glass>

      {/* ── План vs факт ── */}
      <Glass span={12}>
        <div className="eyebrow"><span>План vs факт · явки</span><span className="hint">{DOW[(days[0].getDay() + 6) % 7]}–{DOW[(days[6].getDay() + 6) % 7]}</span></div>
        <div style={{ overflowX: 'auto', marginTop: 10 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 520 }}>
            <thead>
              <tr>
                {['Сотрудник', 'День', 'План', 'Факт', 'Статус'].map((h, i) => (
                  <th key={h} style={{ fontSize: 10, letterSpacing: '.1em', textTransform: 'uppercase', color: 'var(--mute)', fontWeight: 600, textAlign: i > 1 ? 'left' : 'left', padding: '0 10px 10px 0', borderBottom: '1px solid var(--hair)' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {emps.flatMap((e) => days.map((d) => {
                const dISO = iso(d)
                const plan = shiftFor(e.id, dISO)
                const factRow = factMap[`${e.id}|${dISO}`]
                if (!plan && !factRow) return null
                const fact = factRow ? factToShift(factRow) : null
                return (
                  <tr key={`${e.id}|${dISO}`}>
                    <td style={rowTd}>{e.name}</td>
                    <td style={{ ...rowTd, color: 'var(--mute)' }}>{label(d)}</td>
                    <td style={{ ...rowTd, fontVariantNumeric: 'tabular-nums' }}>{plan ? `${plan.start}–${plan.end}` : '—'}</td>
                    <td style={{ ...rowTd, fontVariantNumeric: 'tabular-nums' }}>{fact ? `${fact.start}–${fact.end}` : '—'}</td>
                    <td style={rowTd}><Status plan={plan} fact={fact} /></td>
                  </tr>
                )
              }))}
            </tbody>
          </table>
        </div>
      </Glass>
    </>
  )
}

const weekBtn: React.CSSProperties = {
  width: 28, height: 28, borderRadius: 8, border: '1px solid var(--hair)', background: 'transparent',
  color: 'var(--lo)', cursor: 'pointer', fontSize: 16, lineHeight: 1,
}
const rowTd: React.CSSProperties = { padding: '11px 10px 11px 0', borderBottom: '1px solid var(--hair-2)', fontSize: 12.5, whiteSpace: 'nowrap' }
