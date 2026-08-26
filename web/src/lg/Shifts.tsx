import { useEffect, useState } from 'react'
import { useApi, useOrg } from '../lib/useApi'
import { Glass } from './ui'
import { tenge } from '../lib/format'
import StaffOnShift from './StaffOnShift'

/* Кассовые смены — то, по чему сверяются с кассой.

   Выручка смены = payOrders (наличные + карта + кредит), и именно она совпадает
   с тем, что видит ресторатор в iikoOffice. Поэтому здесь ничего не считаем
   заново: показываем ровно то, что отдал сервер.

   Три вещи, ради которых экран нужен: сколько сдала каждая касса, где
   расхождение по наличным (пересчёт кассира против системы) и какие смены
   висят непринятыми — по ним не закрыт учётный день. */

type Edit = { sum_was: number; sum_now: number; type?: string; time?: string; account_changed?: boolean }
type Shift = {
  number: number; cash_reg: number; cashier: string; open: string; close: string
  cash: number; card: number; credit: number; total: number
  pay_in: number; pay_out: number; cash_diff: number; counted?: number
  status: string; edits?: Edit[]
}
type DayT = { date: string; shifts: Shift[] }
type Pending = { count: number; items: { date: string; number: number; status: string; open_now?: boolean }[] }

const STATUS: Record<string, { label: string; color: string }> = {
  OPEN: { label: 'открыта', color: 'var(--amb)' },
  UNACCEPTED: { label: 'не принята', color: 'var(--red)' },
  ACCEPTED: { label: 'принята', color: 'var(--grn)' },
  CLOSED: { label: 'закрыта', color: 'var(--grn)' },
}

const th: React.CSSProperties = {
  fontSize: 10, letterSpacing: '.1em', textTransform: 'uppercase', color: 'var(--mute)',
  fontWeight: 600, textAlign: 'left', padding: '0 0 9px', borderBottom: '1px solid var(--hair)',
}
const td: React.CSSProperties = { padding: '11px 0', borderBottom: '1px solid var(--hair-2)', fontSize: 13 }
const tdR: React.CSSProperties = { ...td, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }

function Eyebrow({ t, hint }: { t: string; hint?: string }) {
  return <div className="eyebrow"><span>{t}</span>{hint && <span className="hint">{hint}</span>}</div>
}

const today = () => new Date().toISOString().slice(0, 10)
const shiftDay = (d: string, delta: number) => {
  const x = new Date(d + 'T12:00:00')
  x.setDate(x.getDate() + delta)
  return x.toISOString().slice(0, 10)
}

export default function Shifts() {
  const [date, setDate] = useState(today())
  const [day, setDay] = useState<DayT | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const pending = useApi<Pending>('cashshifts_pending', { days: '30' })
  const org = useOrg()

  useEffect(() => {
    if (!org) return
    setDay(null); setErr(null)
    fetch(`/api/cashshifts_day/${org}?date=${date}`, { headers: { Accept: 'application/json' } })
      .then((r) => (r.ok ? r.json() : r.json().then((d) => Promise.reject(new Error(d.detail || `HTTP ${r.status}`)))))
      .then(setDay)
      .catch((e) => setErr(String(e.message || e)))
  }, [org, date])

  const shifts = day?.shifts ?? []
  const sum = (k: keyof Shift) => shifts.reduce((a, s) => a + (Number(s[k]) || 0), 0)
  const diffTotal = shifts.reduce((a, s) => a + (Number(s.cash_diff) || 0), 0)

  return (
    <>
      <Glass span={12}>
        <Eyebrow t="Кассовые смены" hint="выручка смены = наличные + карта + кредит, как в кассе" />

        <div style={{ marginTop: 12, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <button onClick={() => setDate((d) => shiftDay(d, -1))}
            style={{ padding: '8px 13px', borderRadius: 11, border: '1px solid var(--hair)', background: 'transparent', color: 'var(--hi)', fontSize: 13, cursor: 'pointer', fontFamily: 'inherit' }}>←</button>
          <input type="date" value={date} max={today()} onChange={(e) => setDate(e.target.value || today())}
            style={{ padding: '8px 11px', borderRadius: 11, border: '1px solid var(--hair)', background: 'var(--glass-2)', color: 'var(--hi)', fontSize: 13, fontFamily: 'inherit' }} />
          <button onClick={() => setDate((d) => (d >= today() ? d : shiftDay(d, 1)))} disabled={date >= today()}
            style={{ padding: '8px 13px', borderRadius: 11, border: '1px solid var(--hair)', background: 'transparent', color: date >= today() ? 'var(--mute)' : 'var(--hi)', fontSize: 13, cursor: date >= today() ? 'default' : 'pointer', fontFamily: 'inherit' }}>→</button>
          {date !== today() && (
            <button onClick={() => setDate(today())}
              style={{ padding: '8px 13px', borderRadius: 11, border: '1px solid var(--hair)', background: 'transparent', color: 'var(--acc)', fontSize: 12.5, fontWeight: 650, cursor: 'pointer', fontFamily: 'inherit' }}>сегодня</button>
          )}
          {!!shifts.length && (
            <span className="tnum" style={{ marginLeft: 'auto', fontSize: 20, fontWeight: 760, letterSpacing: '-.02em', color: 'var(--hi)' }}>
              {tenge(sum('total'))}
              <span style={{ fontSize: 11.5, color: 'var(--mute)', fontWeight: 600 }}> за день</span>
            </span>
          )}
        </div>

        {err && <div style={{ marginTop: 12, fontSize: 13, color: 'var(--red)' }}>{err}</div>}
        {!err && !day && <div style={{ marginTop: 12, fontSize: 13, color: 'var(--mute)' }}>Считаю смены…</div>}
        {day && !shifts.length && <div style={{ marginTop: 12, fontSize: 13, color: 'var(--mute)' }}>За этот день смен нет.</div>}

        {/* Семь денежных колонок в 390 px не влезают ни при каком шрифте: таблица
            уезжает вбок внутри своего контейнера, а страница стоит на месте. */}
        {!!shifts.length && (
          <div style={{ overflowX: 'auto', minWidth: 0, marginTop: 16 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 620 }}>
            <thead><tr>
              <th style={th}>Смена</th>
              <th style={th}>Кассир</th>
              <th style={{ ...th, textAlign: 'right' }}>Наличные</th>
              <th style={{ ...th, textAlign: 'right' }}>Карта</th>
              <th style={{ ...th, textAlign: 'right' }}>Кредит</th>
              <th style={{ ...th, textAlign: 'right' }}>Итого</th>
              <th style={{ ...th, textAlign: 'right' }}>Расхождение</th>
            </tr></thead>
            <tbody>
              {shifts.map((s) => {
                const st = STATUS[s.status] || { label: s.status, color: 'var(--mute)' }
                return (
                  <tr key={`${s.number}-${s.cash_reg}`}>
                    <td style={td}>
                      <div style={{ fontWeight: 650, color: 'var(--hi)' }}>№{s.number} · касса {s.cash_reg}</div>
                      <div style={{ fontSize: 11, color: 'var(--mute)' }}>
                        {s.open || '—'}{s.close ? `–${s.close}` : ' · идёт'} ·
                        <span style={{ color: st.color, fontWeight: 650 }}> {st.label}</span>
                      </div>
                    </td>
                    <td style={td}>{s.cashier || '—'}</td>
                    <td style={tdR}>{tenge(s.cash)}</td>
                    <td style={tdR}>{tenge(s.card)}</td>
                    <td style={tdR}>{s.credit ? tenge(s.credit) : '—'}</td>
                    <td style={{ ...tdR, fontWeight: 700, color: 'var(--hi)' }}>{tenge(s.total)}</td>
                    <td style={{ ...tdR, color: s.cash_diff ? 'var(--red)' : 'var(--mute)' }}>
                      {s.cash_diff ? tenge(s.cash_diff) : '0'}
                    </td>
                  </tr>
                )
              })}
              <tr>
                <td style={{ ...td, fontWeight: 700, color: 'var(--hi)' }} colSpan={2}>Итого за день</td>
                <td style={{ ...tdR, fontWeight: 700 }}>{tenge(sum('cash'))}</td>
                <td style={{ ...tdR, fontWeight: 700 }}>{tenge(sum('card'))}</td>
                <td style={{ ...tdR, fontWeight: 700 }}>{sum('credit') ? tenge(sum('credit')) : '—'}</td>
                <td style={{ ...tdR, fontWeight: 800, color: 'var(--hi)' }}>{tenge(sum('total'))}</td>
                <td style={{ ...tdR, fontWeight: 700, color: diffTotal ? 'var(--red)' : 'var(--mute)' }}>
                  {diffTotal ? tenge(diffTotal) : '0'}
                </td>
              </tr>
            </tbody>
          </table>
          </div>
        )}

        {/* Правки платежей при приёмке: их видно только здесь, в выручке они уже учтены */}
        {shifts.some((s) => (s.edits || []).length) && (
          <div style={{ marginTop: 14 }}>
            <Eyebrow t="Правки платежей" hint="что изменили при приёмке смены" />
            <div style={{ marginTop: 8, display: 'grid', gap: 5 }}>
              {shifts.flatMap((s) => (s.edits || []).map((e, i) => (
                <div key={`${s.number}-${i}`} style={{ fontSize: 12.5, color: 'var(--mute)', display: 'flex', gap: 10 }}>
                  <span style={{ minWidth: 96 }}>№{s.number} · {e.time || ''}</span>
                  <span className="tnum" style={{ color: 'var(--hi)' }}>
                    {tenge(e.sum_was)} → {tenge(e.sum_now)}
                  </span>
                  <span>{e.type || ''}{e.account_changed ? ' · сменили счёт' : ''}</span>
                </div>
              )))}
            </div>
          </div>
        )}
      </Glass>

      {/* Кто пришёл на смену и кто опоздал — за тот же день, что выбран сверху */}
      <StaffOnShift date={date} />

      {/* Непринятые смены: по ним не закрыт учётный день */}
      <Glass span={12}>
        <Eyebrow t="Непринятые и открытые смены" hint="за 30 дней" />
        {pending.loading && <div style={{ marginTop: 10, fontSize: 13, color: 'var(--mute)' }}>Смотрю…</div>}
        {pending.data && !pending.data.count && (
          <div style={{ marginTop: 10, fontSize: 13, color: 'var(--grn)' }}>Все смены приняты.</div>
        )}
        {!!pending.data?.count && (
          <div style={{ marginTop: 10, display: 'grid', gap: 6 }}>
            {pending.data.items.map((it) => (
              <button key={`${it.date}-${it.number}`} onClick={() => setDate(it.date)}
                style={{ display: 'flex', gap: 12, alignItems: 'baseline', textAlign: 'left', padding: '8px 11px', borderRadius: 11, border: '1px solid var(--hair)', background: 'transparent', cursor: 'pointer', fontFamily: 'inherit' }}>
                <span className="tnum" style={{ fontSize: 12.5, color: 'var(--hi)' }}>{it.date}</span>
                <span style={{ fontSize: 12.5, color: 'var(--mute)' }}>смена №{it.number}</span>
                <span style={{ marginLeft: 'auto', fontSize: 12, fontWeight: 700, color: (STATUS[it.status] || {}).color || 'var(--mute)' }}>
                  {it.open_now ? 'идёт сейчас' : (STATUS[it.status] || { label: it.status }).label}
                </span>
              </button>
            ))}
          </div>
        )}
      </Glass>
    </>
  )
}
