import { useEffect, useState, type CSSProperties } from 'react'
import { Glass } from './ui'
import { useApi } from '../lib/useApi'
import { getOrg } from '../lib/api'

/* Вкладка «План»: руководитель ставит недельный план по КОЛИЧЕСТВУ заказов
   по 3 типам (Зал / Доставка / Агрегаторы), рядом — факт из /api/sales и прогресс.
   Ассистент «в процессе»: вписал план на неделю → предлагает поставить на весь
   месяц одним тапом. Хранение — в БД (план везде у владельца). */

type Grid = Record<string, Record<string, number>>
type Week = { widx: number; from: string; to: string }
type PlanData = { month: string; weeks: Week[]; types: string[]; plan: Grid; fact: Grid; demo: boolean }

const TYPES = ['hall', 'delivery', 'agg'] as const
const TYPE_LABEL: Record<string, string> = { hall: 'Зал + вынос', delivery: 'Доставка', agg: 'Агрегаторы' }
const MONTHS = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь']

const curYm = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}` }
const shiftYm = (ym: string, delta: number) => {
  let [y, m] = ym.split('-').map(Number); m += delta
  while (m < 1) { m += 12; y-- } while (m > 12) { m -= 12; y++ }
  return `${y}-${String(m).padStart(2, '0')}`
}
const ymLabel = (ym: string) => { const [y, m] = ym.split('-').map(Number); return `${MONTHS[m - 1]} ${y}` }
const dm = (iso: string) => iso.slice(8, 10) + '.' + iso.slice(5, 7)
const progColor = (p: number) => (p >= 100 ? 'var(--grn)' : p >= 70 ? 'var(--amb)' : 'var(--mute)')

export default function Plan() {
  const [ym, setYm] = useState(curYm())
  const { data, loading } = useApi<PlanData>('weekplan', { month: ym })
  const [plan, setPlan] = useState<Grid>({})
  const [prompt, setPrompt] = useState<{ type: string; val: number } | null>(null)

  // локальная редактируемая копия плана (мгновенный ввод); синхронизируем с сервером
  useEffect(() => { if (data) { setPlan(JSON.parse(JSON.stringify(data.plan))); setPrompt(null) } }, [data])

  if (loading || !data) return <Glass span={12}><div style={{ padding: '10px 2px', fontSize: 13.5, color: 'var(--mute)' }}>Загружаю план…</div></Glass>

  const weeks = data.weeks
  const fact = data.fact
  const gv = (g: Grid, w: number, t: string) => g[String(w)]?.[t] ?? 0

  const save = async (body: Record<string, unknown>) => {
    try {
      await fetch('/api/weekplan/' + getOrg(), {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ month: ym, ...body }),
      })
    } catch (e) { console.warn('plan save', e) }
  }

  const onCell = (widx: number, type: string, raw: string) => {
    const val = Math.max(0, Math.round(+raw || 0))
    setPlan((g) => ({ ...g, [widx]: { ...(g[String(widx)] || {}), [type]: val } }))
  }
  const commit = async (widx: number, type: string) => {
    const val = gv(plan, widx, type)
    if (gv(data.plan, widx, type) === val) return // не изменилось
    await save({ ch_type: type, planned: val, widx })
    const allEqual = weeks.filter((w) => w.widx !== widx).every((w) => gv(plan, w.widx, type) === val)
    if (!allEqual && val > 0) setPrompt({ type, val })
  }
  const applyAll = async () => {
    if (!prompt) return
    const { type, val } = prompt
    setPlan((g) => { const n = { ...g }; weeks.forEach((w) => { n[String(w.widx)] = { ...(n[String(w.widx)] || {}), [type]: val } }); return n })
    await save({ ch_type: type, planned: val, all_weeks: true })
    setPrompt(null)
  }

  const totals = TYPES.map((t) => {
    const p = weeks.reduce((s, w) => s + gv(plan, w.widx, t), 0)
    const f = weeks.reduce((s, w) => s + gv(fact, w.widx, t), 0)
    return { t, p, f, pct: p ? Math.round((f / p) * 100) : 0 }
  })

  return (
    <>
      <Glass span={12}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <div className="eyebrow"><span>План · количество заказов</span></div>
          <div className="lg-seg" style={{ marginLeft: 'auto' }}>
            <button className="lg-per" onClick={() => setYm((y) => shiftYm(y, -1))} aria-label="Пред. месяц"><span style={{ position: 'relative', zIndex: 1 }}>‹</span></button>
            <span style={{ padding: '0 12px', fontSize: 13, fontWeight: 650, color: 'var(--hi)' }}>{ymLabel(ym)}</span>
            <button className="lg-per" onClick={() => setYm((y) => shiftYm(y, 1))} aria-label="След. месяц"><span style={{ position: 'relative', zIndex: 1 }}>›</span></button>
          </div>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 12, marginTop: 14 }}>
          {totals.map((x) => (
            <div key={x.t} style={{ padding: 14, borderRadius: 14, background: 'var(--glass-2)', border: '1px solid var(--hair)' }}>
              <div style={{ fontSize: 12, color: 'var(--mute)' }}>{TYPE_LABEL[x.t]}</div>
              <div className="tnum" style={{ fontSize: 24, fontWeight: 680, marginTop: 6, color: 'var(--hi)' }}>{x.f} <span style={{ fontSize: 12, fontWeight: 500, color: 'var(--mute)' }}>факт за месяц</span></div>
              <div className="tnum" style={{ fontSize: 12, fontWeight: 600, color: progColor(x.pct), marginTop: 3 }}>{x.p ? `план ${x.p} · ${x.pct}%` : 'план не задан'}</div>
            </div>
          ))}
        </div>
        {data.demo && <div style={{ marginTop: 10, fontSize: 11.5, color: 'var(--amb)' }}>демо-данные</div>}
      </Glass>

      <Glass span={12}>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 520 }}>
            <thead><tr><th style={thL}>Неделя</th>{TYPES.map((t) => <th key={t} style={thC}>{TYPE_LABEL[t]}</th>)}</tr></thead>
            <tbody>
              {weeks.map((w) => (
                <tr key={w.widx}>
                  <td style={{ ...td, whiteSpace: 'nowrap' }}><b style={{ color: 'var(--hi)' }}>Неделя {w.widx}</b><div style={{ fontSize: 10.5, color: 'var(--mute)' }}>{dm(w.from)}–{dm(w.to)}</div></td>
                  {TYPES.map((t) => {
                    const pv = gv(plan, w.widx, t)
                    const fv = gv(fact, w.widx, t)
                    const pct = pv ? Math.round((fv / pv) * 100) : 0
                    return (
                      <td key={t} style={td}>
                        <div style={{ fontSize: 9, letterSpacing: '.08em', textTransform: 'uppercase', color: 'var(--mute)', textAlign: 'center', marginBottom: 3 }}>план</div>
                        <input type="number" min={0} value={pv || ''} placeholder="0"
                          onChange={(e) => onCell(w.widx, t, e.target.value)}
                          onBlur={() => commit(w.widx, t)}
                          onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
                          style={inp} />
                        <div className="tnum" style={{ fontSize: 12, marginTop: 5, textAlign: 'center', color: 'var(--lo)' }}>
                          факт: <b style={{ color: 'var(--hi)' }}>{fv}</b>{pv ? <span style={{ color: progColor(pct) }}> · {pct}%</span> : null}
                        </div>
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Glass>

      {prompt && (
        <div style={{ position: 'fixed', right: 20, bottom: 20, zIndex: 50, maxWidth: 340, display: 'flex', gap: 10, alignItems: 'flex-start', background: 'var(--card)', border: '1px solid var(--hair)', borderRadius: 16, padding: '12px 14px', boxShadow: '0 16px 40px -16px rgba(20,30,60,.4)' }}>
          <img src="/agent2.png" alt="" style={{ width: 34, height: 34, borderRadius: '50%', flex: 'none' }} />
          <div>
            <div style={{ fontSize: 12.5, color: 'var(--hi)', lineHeight: 1.45 }}>Поставить <b>{prompt.val}</b> на остальные недели месяца для «{TYPE_LABEL[prompt.type]}»?</div>
            <div style={{ display: 'flex', gap: 8, marginTop: 9 }}>
              <button onClick={applyAll} style={btnPri}>Да, на весь месяц</button>
              <button onClick={() => setPrompt(null)} style={btnSec}>Только эту</button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

const thL: CSSProperties = { fontSize: 10, letterSpacing: '.1em', textTransform: 'uppercase', color: 'var(--mute)', fontWeight: 600, textAlign: 'left', padding: '0 0 10px', borderBottom: '1px solid var(--hair)' }
const thC: CSSProperties = { ...thL, textAlign: 'center' }
const td: CSSProperties = { padding: '11px 8px', borderBottom: '1px solid var(--hair-2)', fontSize: 13, verticalAlign: 'top' }
const inp: CSSProperties = { width: '100%', maxWidth: 96, fontSize: 15, fontWeight: 650, textAlign: 'center', padding: '6px 8px', borderRadius: 10, border: '1px solid var(--hair)', background: 'var(--glass-2)', color: 'var(--hi)', fontVariantNumeric: 'tabular-nums' }
const btnPri: CSSProperties = { fontSize: 12, fontWeight: 650, color: 'var(--on-acc)', background: 'var(--acc)', border: 'none', borderRadius: 9, padding: '6px 11px', cursor: 'pointer' }
const btnSec: CSSProperties = { fontSize: 12, fontWeight: 600, color: 'var(--lo)', background: 'var(--glass-2)', border: '1px solid var(--hair)', borderRadius: 9, padding: '6px 11px', cursor: 'pointer' }
