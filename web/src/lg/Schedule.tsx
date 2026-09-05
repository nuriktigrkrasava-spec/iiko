import { useEffect, useMemo, useState } from 'react'
import { Glass, tg, fmt } from './ui'
import { useApi, useOrg } from '../lib/useApi'
import { setShift, removeShift, shiftFor, syncPlan } from './scheduleStore'
import ShiftAdmin from './ShiftAdmin'

/* Расписание: целиком наше. Из iiko приходят ТОЛЬКО имена (/api/employees) —
   план живёт в нашей БД, факт смены ставится отметкой в приложении, и по ней
   же считаются опоздания. Раньше сетка строилась по явкам терминала: в ней
   были видны лишь те, кто пробил чек, а весь зал — нет.

   Имена приезжают на весь сервер одной пачкой, поэтому в сетке — бригада
   филиала (кого уже ставили в график, чаще ставили — выше), а остальные
   добираются поиском.

   Оплата пишется прямо на смене: ставок у нас нет намеренно — за выход платят
   по-разному (полсмены, подмена, премия), и одна цифра на сотрудника это
   враньё. Пустое поле значит «не проставили», ноль — «этот выход бесплатный»,
   поэтому недельный итог считает только проставленные смены. */

type Emp = { id: string; name: string; shifts: number }
type Dir = { employees: Emp[] }
type Mark = { employee_id: string; date: string; start: string; geo_ok: number | null }
type Att = { rows: Mark[] }

const DOW = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']

function iso(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
function mondayOf(d: Date) {
  const x = new Date(d); x.setDate(x.getDate() - ((x.getDay() + 6) % 7)); x.setHours(0, 0, 0, 0); return x
}
function addDays(d: Date, n: number) { const x = new Date(d); x.setDate(x.getDate() + n); return x }

function Note({ children }: { children: React.ReactNode }) {
  return <Glass span={12}><div style={{ padding: '10px 2px', fontSize: 13.5, color: 'var(--mute)' }}>{children}</div></Glass>
}

/* Инлайн-редактор смены в клетке недели */
function CellEditor({ init, onSave, onClear, onClose }: {
  init: { start: string; end: string; pay?: number | null } | null
  onSave: (start: string, end: string, pay: number | null) => void
  onClear: () => void
  onClose: () => void
}) {
  const [start, setStart] = useState(init?.start ?? '10:00')
  const [end, setEnd] = useState(init?.end ?? '18:00')
  // Строка, а не число: пустое поле должно оставаться пустым («не проставили»),
  // а не превращаться в 0 при первом же нажатии Backspace.
  const [pay, setPay] = useState(init?.pay == null ? '' : String(init.pay))
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
      <input
        type="number" inputMode="numeric" min={0} step={500} placeholder="оплата, ₸"
        value={pay} onChange={(e) => setPay(e.target.value)} aria-label="Оплата за смену"
        style={{ ...inp, width: 116 }}
      />
      <button style={{ ...btn, borderColor: 'var(--grn)', color: 'var(--grn)' }}
              onClick={() => onSave(start, end, pay.trim() === '' ? null : Number(pay))}>Сохранить</button>
      {init && <button style={btn} onClick={onClear}>Убрать</button>}
      <button style={{ ...btn, marginLeft: 'auto' }} onClick={onClose}>Отмена</button>
    </div>
  )
}

/* Поиск по всему справочнику — добрать в сетку того, кого ещё не ставили */
function AddEmployee({ pool, onPick }: { pool: Emp[]; onPick: (id: string) => void }) {
  const [q, setQ] = useState('')
  const hits = useMemo(() => {
    const s = q.trim().toLowerCase()
    if (!s) return []
    return pool.filter((e) => e.name.toLowerCase().includes(s)).slice(0, 8)
  }, [q, pool])
  return (
    <div style={{ marginTop: 12, position: 'relative', maxWidth: 320 }}>
      <input
        value={q} onChange={(e) => setQ(e.target.value)} placeholder="Добавить сотрудника в график"
        aria-label="Поиск сотрудника"
        style={{
          width: '100%', background: 'var(--glass-2)', border: '1px solid var(--hair)',
          borderRadius: 9, padding: '8px 10px', color: 'var(--hi)', fontSize: 13,
        }}
      />
      {hits.length > 0 && (
        // Фон обязан быть НЕПРОЗРАЧНЫМ: список висит поверх таблицы, и сквозь
        // него просвечивали смены — казалось, что блоки наехали друг на друга.
        <div style={{ position: 'absolute', zIndex: 20, left: 0, right: 0, marginTop: 4, borderRadius: 11, border: '1px solid var(--hair)', background: 'var(--card)', boxShadow: 'var(--shadow)', maxHeight: 260, overflowY: 'auto' }}>
          {hits.map((e) => (
            <button key={e.id} onClick={() => { onPick(e.id); setQ('') }}
              style={{ display: 'block', width: '100%', textAlign: 'left', padding: '9px 11px', fontSize: 13, background: 'transparent', border: 'none', borderBottom: '1px solid var(--hair-2)', color: 'var(--hi)', cursor: 'pointer' }}>
              {e.name}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

export default function Schedule() {
  const [weekStart, setWeekStart] = useState(() => mondayOf(new Date()))
  const [editing, setEditing] = useState<{ emp: string; date: string } | null>(null)
  const [extra, setExtra] = useState<string[]>([])   // добраны поиском в этой сессии
  const [, setVer] = useState(0)
  const bump = () => setVer((v) => v + 1)

  const days = useMemo(() => Array.from({ length: 7 }, (_, i) => addDays(weekStart, i)), [weekStart])
  // period фиксирован: справочник имён от периода не зависит, а без него useApi
  // перезапрашивал бы iiko на каждое переключение «Неделя/Месяц» в шапке.
  const { data, error, loading } = useApi<Dir>('employees', { period: 'week' })
  // Факт: во сколько человек открыл смену в мини-аппе и был ли он на месте.
  // Без этого пометка «отмечено вне заведения» никому бы не показалась.
  const att = useApi<Att>('attendance', { from: iso(days[0]), to: iso(days[6]), period: 'week' })
  const marks = useMemo(() => {
    const m: Record<string, Mark> = {}
    for (const r of att.data?.rows ?? []) m[`${r.employee_id}|${r.date}`] = r
    return m
  }, [att.data])

  // График общий (лежит на сервере): подтягиваем неделю при её смене и при
  // смене филиала. Без org в зависимостях переключение филиала оставляло бы в
  // сетке чужой график, и первая правка ушла бы на сервер не в тот филиал.
  const org = useOrg()
  useEffect(() => {
    if (!org) return
    syncPlan(iso(days[0]), iso(days[6])).then(bump)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [org, weekStart])

  // Филиал сменили — добранные вручную люди относились к прошлому.
  useEffect(() => { setExtra([]); setEditing(null) }, [org])

  const all = useMemo(() => data?.employees ?? [], [data])
  // Бригада филиала: кого уже ставили в график. Сервер вернул их первыми.
  const rows = useMemo(() => {
    const byId = new Map(all.map((e) => [e.id, e]))
    const roster = all.filter((e) => e.shifts > 0)
    const added = extra.map((id) => byId.get(id)).filter((e): e is Emp => !!e && e.shifts === 0)
    return [...roster, ...added]
  }, [all, extra])
  const pool = useMemo(() => {
    const shown = new Set(rows.map((e) => e.id))
    return all.filter((e) => !shown.has(e.id))
  }, [all, rows])

  if (loading) return <Note>Загружаю сотрудников…</Note>
  if (error || !data) return <Note>Не удалось загрузить сотрудников: {error}</Note>

  const cell: React.CSSProperties = { padding: '9px 6px', textAlign: 'center', fontSize: 12, borderTop: '1px solid var(--hair-2)' }
  const label = (d: Date) => `${DOW[(d.getDay() + 6) % 7]} ${d.getDate()}`
  // Смены без проставленной оплаты в итог не идут: иначе недельный фонд выглядел
  // бы посчитанным, хотя половину сумм ещё не вписали.
  const weekPay = (empId: string) => days.reduce(
    (sum, d) => sum + (shiftFor(empId, iso(d))?.pay ?? 0), 0)
  const total = rows.reduce((sum, e) => sum + weekPay(e.id), 0)

  return (
    <>
    <Glass span={12}>
      <div className="eyebrow" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span>Расписание · план</span>
        <span style={{ display: 'inline-flex', gap: 10, alignItems: 'center' }}>
          <button aria-label="Прошлая неделя" onClick={() => setWeekStart(addDays(weekStart, -7))} style={weekBtn}>‹</button>
          <span className="hint" style={{ minWidth: 96, textAlign: 'center' }}>{iso(days[0]).slice(5)} – {iso(days[6]).slice(5)}</span>
          <button aria-label="Следующая неделя" onClick={() => setWeekStart(addDays(weekStart, 7))} style={weekBtn}>›</button>
        </span>
      </div>

      {rows.length === 0 ? (
        <div style={{ marginTop: 12, fontSize: 13.5, color: 'var(--mute)' }}>
          В этом филиале ещё никого не ставили в график. Найдите сотрудника поиском ниже — дальше он будет здесь сам.
        </div>
      ) : (
        <div style={{ overflowX: 'auto', marginTop: 12 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 560 }}>
            <thead>
              <tr>
                <th style={{ ...cell, borderTop: 'none', textAlign: 'left', color: 'var(--mute)' }}>Сотрудник</th>
                {days.map((d) => <th key={iso(d)} style={{ ...cell, borderTop: 'none', color: 'var(--mute)' }}>{label(d)}</th>)}
                <th style={{ ...cell, borderTop: 'none', color: 'var(--mute)', textAlign: 'right', whiteSpace: 'nowrap' }}>За неделю</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((e) => (
                <tr key={e.id}>
                  <td style={{ ...cell, textAlign: 'left', fontWeight: 600, color: 'var(--hi)', whiteSpace: 'nowrap' }}>{e.name}</td>
                  {days.map((d) => {
                    const dISO = iso(d)
                    const s = shiftFor(e.id, dISO)
                    const mark = marks[`${e.id}|${dISO}`]
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
                          {s || mark ? (
                            <>
                              <span style={{ display: 'block' }}>{s ? `${s.start}–${s.end}` : '—'}</span>
                              {s?.pay != null && (
                                <span style={{ display: 'block', fontSize: 10.5, color: 'var(--grn)', marginTop: 2 }}>
                                  {fmt(s.pay)}
                                </span>
                              )}
                              {mark && (
                                <span style={{ display: 'block', fontSize: 10, marginTop: 2,
                                               color: mark.geo_ok === 0 ? 'var(--amb)' : 'var(--grn)' }}>
                                  {mark.geo_ok === 0 ? `⚑ ${mark.start}` : `✓ ${mark.start}`}
                                </span>
                              )}
                            </>
                          ) : '+'}
                        </button>
                      </td>
                    )
                  })}
                  <td style={{ ...cell, textAlign: 'right', fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap',
                               color: weekPay(e.id) ? 'var(--hi)' : 'var(--mute)', fontWeight: 600 }}>
                    {weekPay(e.id) ? tg(weekPay(e.id)) : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <td colSpan={8} style={{ ...cell, textAlign: 'right', color: 'var(--mute)' }}>Фонд оплаты за неделю</td>
                <td style={{ ...cell, textAlign: 'right', fontVariantNumeric: 'tabular-nums',
                             fontWeight: 700, color: 'var(--hi)', whiteSpace: 'nowrap' }}>
                  {total ? tg(total) : '—'}
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
      )}

      {editing && (
        <CellEditor
          init={shiftFor(editing.emp, editing.date)}
          onSave={(start, end, pay) => { setShift({ employeeId: editing.emp, date: editing.date, start, end, pay }); setEditing(null); bump() }}
          onClear={() => { removeShift(editing.emp, editing.date); setEditing(null); bump() }}
          onClose={() => setEditing(null)}
        />
      )}

      <AddEmployee pool={pool} onPick={(id) => setExtra((x) => (x.includes(id) ? x : [...x, id]))} />

      <div style={{ marginTop: 12, fontSize: 11.5, color: 'var(--mute)' }}>
        график общий для филиала · из iiko берутся только имена · оплата пишется на смене
        <br />✓ — сотрудник открыл смену на месте · ⚑ — открыл вне заведения
      </div>
    </Glass>

    {/* Доступы, точка филиала и сообщения — рядом с сеткой: ссылку выдают,
        глядя на того же человека, которому только что поставили смену. */}
    <ShiftAdmin employees={rows.map((e) => ({ id: e.id, name: e.name }))} />
    </>
  )
}

const weekBtn: React.CSSProperties = {
  width: 28, height: 28, borderRadius: 8, border: '1px solid var(--hair)', background: 'transparent',
  color: 'var(--lo)', cursor: 'pointer', fontSize: 16, lineHeight: 1,
}
