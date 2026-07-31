import { useState } from 'react'
import { motion } from 'framer-motion'
import { Glass } from './ui'

/* ─────────────────────────────────────────────────────────────
   Посадка зала — виджет для владельца «с телефона».
   План зала + занятость столов в реальном времени (демо-данные),
   как у SevenRooms/OpenTable. Оборачиваемость, лист ожидания.
   ───────────────────────────────────────────────────────────── */

type St = 'occ' | 'res' | 'free' | 'clean'
type Table = { id: string; x: number; y: number; seats: number; st: St; t?: string; who?: string }

/* координаты в % внутри плана (зал слева, терраса справа) */
const TABLES: Table[] = [
  { id: 'T1', x: 10, y: 16, seats: 2, st: 'occ', t: '1:05', who: 'Айгуль' },
  { id: 'T2', x: 28, y: 14, seats: 4, st: 'occ', t: '0:40', who: 'Данияр' },
  { id: 'T3', x: 46, y: 15, seats: 4, st: 'res', t: '19:30' },
  { id: 'T4', x: 10, y: 42, seats: 4, st: 'occ', t: '1:50', who: 'Сауле' },
  { id: 'T5', x: 28, y: 44, seats: 6, st: 'occ', t: '0:25', who: 'Айгуль' },
  { id: 'T6', x: 46, y: 43, seats: 2, st: 'free' },
  { id: 'T7', x: 10, y: 70, seats: 2, st: 'occ', t: '2:10', who: 'Ержан' },
  { id: 'T8', x: 28, y: 72, seats: 4, st: 'clean' },
  { id: 'T9', x: 46, y: 71, seats: 4, st: 'occ', t: '0:55', who: 'Данияр' },
  { id: 'V1', x: 72, y: 18, seats: 2, st: 'occ', t: '0:30', who: 'Сауле' },
  { id: 'V2', x: 88, y: 18, seats: 2, st: 'res', t: '20:00' },
  { id: 'V3', x: 72, y: 44, seats: 6, st: 'occ', t: '1:15', who: 'Айгуль' },
  { id: 'V4', x: 88, y: 46, seats: 4, st: 'occ', t: '0:20', who: 'Ержан' },
  { id: 'V5', x: 72, y: 72, seats: 4, st: 'free' },
  { id: 'V6', x: 88, y: 73, seats: 2, st: 'occ', t: '1:40', who: 'Сауле' },
  { id: 'V7', x: 80, y: 90, seats: 8, st: 'free' },
]

const COLOR: Record<St, string> = { occ: 'var(--acc)', res: 'var(--amb)', free: 'var(--grn)', clean: 'var(--mute)' }
const LABEL: Record<St, string> = { occ: 'Занят', res: 'Бронь', free: 'Свободен', clean: 'Убирают' }

function TableDot({ t, onHover }: { t: Table; onHover: (t: Table | null) => void }) {
  const c = COLOR[t.st]
  const size = t.seats <= 2 ? 34 : t.seats <= 4 ? 42 : 54
  const filled = t.st === 'occ'
  return (
    <motion.button
      onMouseEnter={() => onHover(t)} onMouseLeave={() => onHover(null)}
      whileHover={{ scale: 1.12 }} whileTap={{ scale: 0.95 }}
      aria-label={`Стол ${t.id}, ${LABEL[t.st]}, ${t.seats} мест`}
      style={{
        position: 'absolute', left: `${t.x}%`, top: `${t.y}%`, translate: '-50% -50%',
        width: size, height: size, borderRadius: t.seats <= 2 ? '50%' : 14, cursor: 'pointer',
        display: 'grid', placeItems: 'center', font: 'inherit', padding: 0,
        color: filled ? '#fff' : c,
        background: filled ? c : 'color-mix(in srgb, ' + c + ' 14%, transparent)',
        border: `1.5px solid ${filled ? 'transparent' : 'color-mix(in srgb,' + c + ' 55%,transparent)'}`,
        boxShadow: filled ? `0 6px 16px -6px ${c}` : 'none',
      }}>
      <span className="tnum" style={{ fontSize: 11, fontWeight: 700, lineHeight: 1 }}>{t.seats}</span>
      {t.st === 'occ' && t.t && <span className="tnum" style={{ fontSize: 8, opacity: 0.85 }}>{t.t}</span>}
    </motion.button>
  )
}

function ring(pct: number): string {
  const R = 46, C = 2 * Math.PI * R, off = C * (1 - pct / 100)
  return `<svg viewBox="0 0 120 120" style="width:104px;height:104px;display:block">
    <circle cx="60" cy="60" r="${R}" fill="none" stroke="var(--hair)" stroke-width="11"/>
    <circle cx="60" cy="60" r="${R}" fill="none" stroke="var(--acc)" stroke-width="11" stroke-linecap="round"
      stroke-dasharray="${C.toFixed(1)}" stroke-dashoffset="${off.toFixed(1)}" transform="rotate(-90 60 60)"/></svg>`
}

export default function Seating() {
  const [hover, setHover] = useState<Table | null>(null)
  const total = TABLES.length
  const occ = TABLES.filter((t) => t.st === 'occ').length
  const res = TABLES.filter((t) => t.st === 'res').length
  const free = TABLES.filter((t) => t.st === 'free').length
  const guests = TABLES.filter((t) => t.st === 'occ').reduce((s, t) => s + t.seats, 0)
  const pct = Math.round((occ / total) * 100)
  const kpi = [['Гостей сейчас', String(guests), 'в зале'], ['Средний оборот', '1 ч 18 м', 'на стол'], ['Лист ожидания', '2', 'группы'], ['Бронь на вечер', String(res), 'стола']]

  return (
    <>
      <Glass span={5} spot warp>
        <div style={{ display: 'flex', gap: 18, alignItems: 'center' }}>
          <div style={{ position: 'relative', flex: 'none', display: 'grid', placeItems: 'center' }}>
            <div dangerouslySetInnerHTML={{ __html: ring(pct) }} />
            <div style={{ position: 'absolute', textAlign: 'center' }}>
              <div className="tnum" style={{ fontSize: 28, fontWeight: 700, lineHeight: 1 }}>{pct}%</div>
              <div style={{ fontSize: 9.5, color: 'var(--mute)' }}>занято</div>
            </div>
          </div>
          <div>
            <div style={{ fontSize: 10, letterSpacing: '.12em', textTransform: 'uppercase', color: 'var(--mute)', fontWeight: 600 }}>Посадка зала</div>
            <div className="tnum" style={{ fontSize: 26, fontWeight: 700, letterSpacing: '-.02em', marginTop: 6 }}>{occ} / {total}</div>
            <div style={{ fontSize: 12.5, color: 'var(--lo)', marginTop: 4 }}>{free} свободно · {guests} гостей</div>
          </div>
        </div>
        <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', marginTop: 16, fontSize: 11.5, color: 'var(--lo)' }}>
          {(['occ', 'res', 'free', 'clean'] as St[]).map((s) => (
            <span key={s} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              <i style={{ width: 10, height: 10, borderRadius: '50%', background: COLOR[s] }} />{LABEL[s]}
            </span>
          ))}
        </div>
      </Glass>

      <Glass span={7}>
        <div className="eyebrow"><span>План зала</span><span className="hint">{hover ? `Стол ${hover.id} · ${LABEL[hover.st]}${hover.who ? ' · ' + hover.who : ''}${hover.t ? ' · ' + hover.t : ''}` : 'наведи на стол'}</span></div>
        <div style={{ position: 'relative', marginTop: 14, borderRadius: 18, minHeight: 300, aspectRatio: '16 / 10', overflow: 'hidden', background: 'var(--glass-2)', border: '1px solid var(--hair)' }}>
          {/* зонирование: зал / терраса */}
          <div style={{ position: 'absolute', inset: 0, left: '62%', background: 'color-mix(in srgb, var(--acc) 5%, transparent)', borderLeft: '1px dashed var(--hair)' }} />
          <div style={{ position: 'absolute', top: 8, left: 12, fontSize: 9.5, letterSpacing: '.1em', textTransform: 'uppercase', color: 'var(--mute)', fontWeight: 600 }}>Зал</div>
          <div style={{ position: 'absolute', top: 8, left: '64%', fontSize: 9.5, letterSpacing: '.1em', textTransform: 'uppercase', color: 'var(--mute)', fontWeight: 600 }}>Терраса</div>
          {TABLES.map((t) => <TableDot key={t.id} t={t} onHover={setHover} />)}
        </div>
      </Glass>

      {kpi.map((k, i) => (
        <Glass key={i} span={3} tap>
          <div style={{ fontSize: 10, letterSpacing: '.1em', textTransform: 'uppercase', color: 'var(--mute)', fontWeight: 600 }}>{k[0]}</div>
          <div className="tnum" style={{ fontSize: 26, fontWeight: 680, letterSpacing: '-.02em', marginTop: 7 }}>{k[1]}</div>
          <div style={{ fontSize: 11, color: 'var(--mute)', marginTop: 4 }}>{k[2]}</div>
        </Glass>
      ))}

      <Glass span={12}>
        <div className="eyebrow"><span>Занятые столы</span><span className="hint">официант · гости · время за столом</span></div>
        <table style={{ width: '100%', borderCollapse: 'collapse', marginTop: 10 }}>
          <thead><tr>
            {['Стол', 'Официант', 'Гостей', 'Время', 'Статус'].map((h, i) => (
              <th key={h} style={{ fontSize: 10, letterSpacing: '.1em', textTransform: 'uppercase', color: 'var(--mute)', fontWeight: 600, textAlign: i > 1 ? 'right' : 'left', padding: '0 0 10px', borderBottom: '1px solid var(--hair)' }}>{h}</th>
            ))}
          </tr></thead>
          <tbody>
            {TABLES.filter((t) => t.st === 'occ').sort((a, b) => (b.t || '').localeCompare(a.t || '')).map((t) => (
              <tr key={t.id}>
                <td style={{ padding: '11px 0', borderBottom: '1px solid var(--hair-2)', fontSize: 13, fontWeight: 600 }}>{t.id}<span style={{ color: 'var(--mute)', fontWeight: 400, marginLeft: 7 }}>{t.seats} мест</span></td>
                <td style={{ padding: '11px 0', borderBottom: '1px solid var(--hair-2)', fontSize: 13, color: 'var(--lo)' }}>{t.who}</td>
                <td className="tnum" style={{ padding: '11px 0', borderBottom: '1px solid var(--hair-2)', fontSize: 13, textAlign: 'right' }}>{t.seats}</td>
                <td className="tnum" style={{ padding: '11px 0', borderBottom: '1px solid var(--hair-2)', fontSize: 13, textAlign: 'right', color: (t.t && t.t > '2:00') ? 'var(--amb)' : 'var(--hi)' }}>{t.t}</td>
                <td style={{ padding: '11px 0', borderBottom: '1px solid var(--hair-2)', textAlign: 'right' }}>
                  <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--acc)', background: 'color-mix(in srgb,var(--acc) 14%,transparent)', padding: '3px 9px', borderRadius: 8 }}>Занят</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Glass>
    </>
  )
}
