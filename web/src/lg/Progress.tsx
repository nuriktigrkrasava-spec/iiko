import { useEffect, useMemo, useRef } from 'react'
import { motion } from 'framer-motion'

/* «Прогресс и динамика» — экран для собрания.

   Показывает то, что владелец называет вслух: сколько заказов и куда двинулось,
   сколько опоздало, сколько держат кухня и дорога, и кто наверху. Всё уже
   считается в /api/plan-week/{org}/metrics — здесь только подача.

   Подача по apple-design:
   • материал, а не плашка: слой с backdrop-filter, контент едет ПОД ним;
   • появление пружиной без отскока (damping 1.0): экран не жестовый, подпрыгивание
     было бы шумом. Уход тем же путём, каким пришёл — вниз, а не куда-то вбок;
   • типографика по размеру: у крупных чисел отрицательный трекинг и плотный
     интерлиньяж, у подписей — наоборот. Цифры табличные, иначе на собрании
     колонки «пляшут» при обновлении;
   • иерархия весом и размером, а не цветными плашками. Цвет несёт ровно один
     смысл — стало лучше или хуже;
   • prefers-reduced-motion уважаем: движение заменяем проявлением. */

export type Win = { key: string; label: string }
export type MetricDef = { key: string; label: string; unit: string; lower_better: boolean }
export type Row = {
  organization_id: string; name: string
  now: Record<string, number | null>; prev: Record<string, number | null>; wins: Win[]
}
export type MetricsData = { week: string; from: string; to: string; done_days?: number
                            metrics: MetricDef[]; branches: Row[] }
export type ScoreRow = { organization_id: string; name: string; score?: number | null; points?: number }

/* Показатели экрана — ровно те четыре, что просил владелец, в порядке разговора:
   сперва объём, потом качество доставки, потом где именно теряем минуты. */
const SHOW = ['orders', 'late_pct', 'kitchen', 'road'] as const

const shortName = (n: string) => n.replace(/^Астана,?\s*(ул\.?)?\s*/i, '').trim() || n
const fmt = (v: number | null | undefined, unit: string) =>
  v == null ? '—' : `${Math.round(v * 10) / 10}${unit ? ` ${unit}` : ''}`

/** Сумма по сети: заказы складываем, минуты и проценты усредняем — иначе
    «опозданий 340%» по девяти филиалам. */
export function networkValue(rows: Row[], key: string, side: 'now' | 'prev'): number | null {
  const vals = rows.map((r) => r[side]?.[key]).filter((v): v is number => typeof v === 'number')
  if (!vals.length) return null
  if (key === 'orders') return vals.reduce((a, b) => a + b, 0)
  return vals.reduce((a, b) => a + b, 0) / vals.length
}

/** Насколько стало лучше. Знак нормализуем: у «меньше — лучше» падение это плюс. */
export function delta(now: number | null, prev: number | null, lowerBetter: boolean) {
  if (now == null || prev == null || prev === 0) return null
  const diff = now - prev
  const pct = (diff / Math.abs(prev)) * 100
  return { diff, pct, better: lowerBetter ? diff < 0 : diff > 0 }
}

function Delta({ d, unit }: { d: ReturnType<typeof delta>; unit: string }) {
  if (!d || Math.abs(d.pct) < 0.5) {
    return <span style={{ fontSize: 12.5, color: 'var(--mute)', fontWeight: 600 }}>без изменений</span>
  }
  const col = d.better ? 'var(--grn)' : 'var(--red)'
  return (
    <span className="tnum" style={{ fontSize: 12.5, fontWeight: 700, color: col, letterSpacing: '.01em' }}>
      {d.diff > 0 ? '↑' : '↓'} {Math.abs(Math.round(d.diff * 10) / 10)}{unit ? ` ${unit}` : ''}
      <span style={{ color: 'var(--mute)', fontWeight: 600 }}> · {Math.abs(Math.round(d.pct))}%</span>
    </span>
  )
}

/* Карточка показателя. Иерархия: число крупное и плотное, подпись мелкая и
   разреженная — глаз ловит цифру первой, читает подпись второй. */
function Card({ def, rows, i, reduce }: { def: MetricDef; rows: Row[]; i: number; reduce: boolean }) {
  const now = networkValue(rows, def.key, 'now')
  const prev = networkValue(rows, def.key, 'prev')
  const d = delta(now, prev, def.lower_better)
  return (
    <motion.div
      initial={reduce ? { opacity: 0 } : { opacity: 0, y: 10 }}
      animate={reduce ? { opacity: 1 } : { opacity: 1, y: 0 }}
      transition={{ type: 'spring', bounce: 0, duration: 0.4, delay: i * 0.05 }}
      style={{
        padding: '16px 18px', borderRadius: 18, border: '1px solid var(--hair)',
        background: 'var(--card)', minWidth: 0,
      }}>
      <div style={{ fontSize: 10.5, letterSpacing: '.1em', textTransform: 'uppercase',
                    color: 'var(--mute)', fontWeight: 700 }}>{def.label}</div>
      <div className="tnum" style={{ marginTop: 8, fontSize: 34, fontWeight: 780,
                                     letterSpacing: '-.03em', lineHeight: 1, color: 'var(--hi)' }}>
        {fmt(now, def.unit)}
      </div>
      <div style={{ marginTop: 7 }}><Delta d={d} unit={def.unit} /></div>
      <div style={{ marginTop: 3, fontSize: 11, color: 'var(--mute)' }}>
        неделей раньше {fmt(prev, def.unit)}
      </div>
    </motion.div>
  )
}

/* Топ. Две колонки одного размера: слева движение за неделю, справа оценка.
   Разделять их на «главный» и «второстепенный» нельзя — на собрании называют оба. */
function Top({ title, hint, items, reduce }: {
  title: string; hint: string; reduce: boolean
  items: { id: string; name: string; value: string; tone?: string }[]
}) {
  return (
    <div style={{ padding: '16px 18px', borderRadius: 18, border: '1px solid var(--hair)', background: 'var(--card)' }}>
      <div style={{ fontSize: 10.5, letterSpacing: '.1em', textTransform: 'uppercase', color: 'var(--mute)', fontWeight: 700 }}>
        {title}
      </div>
      <div style={{ marginTop: 2, fontSize: 11.5, color: 'var(--mute)' }}>{hint}</div>
      <div style={{ marginTop: 12, display: 'grid', gap: 2 }}>
        {items.length === 0 && <div style={{ fontSize: 12.5, color: 'var(--mute)' }}>Пока нечего показать.</div>}
        {items.slice(0, 5).map((it, i) => (
          <motion.div key={it.id}
            initial={reduce ? { opacity: 0 } : { opacity: 0, x: -6 }}
            animate={reduce ? { opacity: 1 } : { opacity: 1, x: 0 }}
            transition={{ type: 'spring', bounce: 0, duration: 0.4, delay: 0.1 + i * 0.04 }}
            style={{ display: 'flex', alignItems: 'baseline', gap: 11, padding: '8px 0',
                     borderBottom: i < Math.min(items.length, 5) - 1 ? '1px solid var(--hair-2)' : 'none' }}>
            <span className="tnum" style={{ width: 20, textAlign: 'center', flex: 'none',
                                            fontSize: i === 0 ? 14 : 12, fontWeight: 800,
                                            color: i === 0 ? 'var(--amb)' : 'var(--mute)' }}>
              {i === 0 ? '★' : i + 1}
            </span>
            <span style={{ flex: 1, minWidth: 0, fontSize: 13.5, color: 'var(--hi)',
                           fontWeight: i === 0 ? 700 : 500, overflow: 'hidden',
                           textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {shortName(it.name)}
            </span>
            <span className="tnum" style={{ flex: 'none', fontSize: 13.5, fontWeight: 700,
                                            color: it.tone || 'var(--hi)' }}>{it.value}</span>
          </motion.div>
        ))}
      </div>
    </div>
  )
}

export default function Progress({ data, scores, onClose }: {
  data: MetricsData; scores: ScoreRow[]; onClose: () => void
}) {
  const reduce = typeof window !== 'undefined'
    && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  const closeRef = useRef<HTMLButtonElement>(null)

  // Выход всегда доступен: экран не должен запирать. Esc — и мы снаружи.
  useEffect(() => {
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', esc)
    closeRef.current?.focus()
    return () => window.removeEventListener('keydown', esc)
  }, [onClose])

  const defs = useMemo(
    () => SHOW.map((k) => data.metrics.find((m) => m.key === k)).filter((m): m is MetricDef => !!m),
    [data.metrics])
  const rows = data.branches

  const moved = useMemo(() => rows.filter((r) => r.wins.length)
    .sort((a, b) => b.wins.length - a.wins.length)
    .map((r) => ({ id: r.organization_id, name: r.name,
                   value: `+${r.wins.length}`, tone: 'var(--grn)' })), [rows])

  const byScore = useMemo(() => scores
    .filter((s) => typeof s.score === 'number')
    .sort((a, b) => (b.score || 0) - (a.score || 0))
    .map((s) => ({ id: s.organization_id, name: s.name, value: String(s.score),
                   tone: (s.score || 0) >= 70 ? 'var(--grn)' : (s.score || 0) >= 45 ? 'var(--amb)' : 'var(--red)' })),
    [scores])

  return (
    <motion.div
      /* Затемнение + материал: задача модальная, фон уводим назад. Появление и
         уход одним путём — снизу и вниз (см. пространственную симметрию). */
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
      transition={{ duration: 0.18 }}
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0, zIndex: 60, overflowY: 'auto',
        background: 'rgba(10,16,30,.44)', backdropFilter: 'blur(18px) saturate(140%)',
        WebkitBackdropFilter: 'blur(18px) saturate(140%)',
        padding: 'clamp(12px, 4vw, 40px)',
      }}>
      <motion.div
        onClick={(e) => e.stopPropagation()}
        initial={reduce ? { opacity: 0 } : { opacity: 0, y: 24, scale: .985 }}
        animate={reduce ? { opacity: 1 } : { opacity: 1, y: 0, scale: 1 }}
        exit={reduce ? { opacity: 0 } : { opacity: 0, y: 24, scale: .985 }}
        transition={{ type: 'spring', bounce: 0, duration: 0.4 }}
        style={{
          maxWidth: 980, margin: '0 auto', borderRadius: 26, padding: 'clamp(18px, 3vw, 30px)',
          background: 'var(--bg)', border: '1px solid var(--hair)',
          boxShadow: '0 40px 90px -30px rgba(10,20,50,.55)',
        }}>

        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 16, flexWrap: 'wrap' }}>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: 10.5, letterSpacing: '.14em', textTransform: 'uppercase',
                          color: 'var(--mute)', fontWeight: 700 }}>
              Неделя {data.week} · {data.from.slice(5)} — {data.to.slice(5)}
            </div>
            {/* Крупный заголовок: плотный интерлиньяж и отрицательный трекинг —
                на большом кегле буквы иначе расползаются. */}
            <h2 className="display" style={{ margin: '4px 0 0', fontSize: 'clamp(26px, 4vw, 38px)',
                                             lineHeight: 1.04, letterSpacing: '-.025em' }}>
              Прогресс и динамика
            </h2>
            <div style={{ marginTop: 6, fontSize: 12.5, color: 'var(--mute)' }}>
              {rows.length} филиалов · сравнение с прошлой неделей день в день
              {data.done_days ? ` (${data.done_days} дн.)` : ''}
            </div>
          </div>
          <button ref={closeRef} onClick={onClose} aria-label="Закрыть"
            style={{ marginLeft: 'auto', padding: '9px 16px', borderRadius: 12,
                     border: '1px solid var(--hair)', background: 'transparent',
                     color: 'var(--hi)', fontSize: 13, fontWeight: 650,
                     fontFamily: 'inherit', cursor: 'pointer' }}>
            Закрыть
          </button>
        </div>

        <div style={{ marginTop: 20, display: 'grid', gap: 12,
                      gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))' }}>
          {defs.map((m, i) => <Card key={m.key} def={m} rows={rows} i={i} reduce={reduce} />)}
        </div>

        <div style={{ marginTop: 14, display: 'grid', gap: 12,
                      gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))' }}>
          <Top title="Топ по движению" hint="сколько показателей улучшили за неделю"
               items={moved} reduce={reduce} />
          <Top title="Топ по оценке" hint="оценка филиала 0–100 с «Горы»"
               items={byScore} reduce={reduce} />
        </div>

        {/* Разбор по филиалам: то, к чему переходят после общих цифр */}
        <div style={{ marginTop: 14, borderRadius: 18, border: '1px solid var(--hair)',
                      background: 'var(--card)', padding: '16px 18px', overflowX: 'auto' }}>
          <div style={{ fontSize: 10.5, letterSpacing: '.1em', textTransform: 'uppercase',
                        color: 'var(--mute)', fontWeight: 700 }}>По филиалам</div>
          <table style={{ width: '100%', minWidth: 520, borderCollapse: 'collapse', marginTop: 12, fontSize: 12.5 }}>
            <thead><tr>
              <th style={{ textAlign: 'left', padding: '0 0 8px', color: 'var(--mute)', fontWeight: 600, borderBottom: '1px solid var(--hair)' }}>Филиал</th>
              {defs.map((m) => (
                <th key={m.key} style={{ textAlign: 'right', padding: '0 0 8px 12px', color: 'var(--mute)', fontWeight: 600, borderBottom: '1px solid var(--hair)' }}>
                  {m.label}
                </th>
              ))}
            </tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.organization_id}>
                  <td style={{ padding: '9px 0', borderBottom: '1px solid var(--hair-2)', color: 'var(--hi)' }}>
                    {shortName(r.name)}
                  </td>
                  {defs.map((m) => {
                    const d = delta(r.now?.[m.key] ?? null, r.prev?.[m.key] ?? null, m.lower_better)
                    return (
                      <td key={m.key} className="tnum" style={{ padding: '9px 0 9px 12px', textAlign: 'right', borderBottom: '1px solid var(--hair-2)' }}>
                        <span style={{ color: 'var(--hi)', fontWeight: 650 }}>{fmt(r.now?.[m.key] ?? null, '')}</span>
                        {d && Math.abs(d.pct) >= 0.5 && (
                          <span style={{ marginLeft: 6, fontSize: 11, fontWeight: 700,
                                         color: d.better ? 'var(--grn)' : 'var(--red)' }}>
                            {d.diff > 0 ? '↑' : '↓'}{Math.abs(Math.round(d.pct))}%
                          </span>
                        )}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </motion.div>
    </motion.div>
  )
}
