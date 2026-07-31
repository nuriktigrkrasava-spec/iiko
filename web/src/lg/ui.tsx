import type { ReactNode } from 'react'
import { motion } from 'framer-motion'

/* ── Формат (₸, проценты, дельты) ── */
export const fmt = (n: number) => new Intl.NumberFormat('ru-RU').format(Math.round(n))
export const tg = (n: number) => fmt(n) + ' ₸'

export function Delta({ v, invert = false, size = 13 }: { v?: number | null; invert?: boolean; size?: number }) {
  if (v == null) return null
  const good = invert ? v < 0 : v > 0
  const color = v === 0 ? 'var(--mute)' : good ? 'var(--grn)' : 'var(--red)'
  const a = v === 0 ? '' : v > 0 ? '▲' : '▼'
  return (
    <span className="tnum" style={{ color, fontSize: size, fontWeight: 600 }}>
      {a} {Math.abs(v).toFixed(1).replace('.', ',')}%
    </span>
  )
}

/* ── Пружины iOS ── */
export const spring = { type: 'spring', stiffness: 260, damping: 26 } as const
export const container = { hidden: {}, show: { transition: { staggerChildren: 0.06, delayChildren: 0.04 } } }
export const item = {
  hidden: { opacity: 0, y: 16, scale: 0.98 },
  show: { opacity: 1, y: 0, scale: 1, transition: spring },
}

/* ── Стеклянная карточка ── */
export function Glass({
  children, span = 4, tap = false, warp = false, className = '', style,
}: { children: ReactNode; span?: number; spot?: boolean; tap?: boolean; warp?: boolean; className?: string; style?: React.CSSProperties }) {
  return (
    <motion.div
      variants={item}
      whileHover={tap ? { y: -3, transition: spring } : undefined}
      whileTap={tap ? { scale: 0.985 } : undefined}
      className={`glass ${warp ? 'warp' : ''} ${className}`}
      style={{
        gridColumn: `span ${span}`, cursor: tap ? 'pointer' : undefined,
        ...style,
      }}
    >
      {children}
    </motion.div>
  )
}

/* ── SVG-график из строки ── */
export function Chart({ html, style }: { html: string; style?: React.CSSProperties }) {
  return <div style={{ marginTop: 14, ...style }} dangerouslySetInnerHTML={{ __html: html }} />
}

/* ── Орб светофора ── */
export function Orb({ tone }: { tone: 'green' | 'amber' | 'red' }) {
  const c = tone === 'green' ? 'var(--grn)' : tone === 'amber' ? 'var(--amb)' : 'var(--red)'
  return (
    <span style={{ position: 'relative', flex: 'none' }}>
      <span style={{ display: 'block', width: 13, height: 13, borderRadius: '50%', background: c }} />
      <motion.span
        aria-hidden
        style={{ position: 'absolute', inset: -5, borderRadius: '50%', background: c, filter: 'blur(6px)', opacity: 0.55 }}
        animate={tone === 'red' ? { opacity: [0.35, 0.7, 0.35] } : {}}
        transition={tone === 'red' ? { duration: 2.2, repeat: Infinity } : {}}
      />
    </span>
  )
}

export function Light({ tone, k, v }: { tone: 'green' | 'amber' | 'red'; k: string; v: string }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 11, padding: '12px 13px', borderRadius: 15,
      border: '1px solid var(--hair)', background: 'var(--glass-2)',
    }}>
      <Orb tone={tone} />
      <span style={{ fontSize: 12.5, color: 'var(--lo)' }}>{k}</span>
      <span className="tnum" style={{ fontSize: 13.5, fontWeight: 650, marginLeft: 'auto' }}>{v}</span>
    </div>
  )
}

/* ── Буллет «факт vs цель» ── */
export function Bullet({ value, target, max, tone = 'acc' }: { value: number; target?: number; max: number; tone?: 'acc' | 'warn' | 'bad' }) {
  const pct = Math.min(100, (value / max) * 100)
  const bg = tone === 'bad' ? 'linear-gradient(90deg,var(--red),#ff8a7d)'
    : tone === 'warn' ? 'linear-gradient(90deg,var(--amb),#ffbf5a)'
    : 'linear-gradient(90deg,var(--acc),var(--acc-2))'
  return (
    <div style={{ position: 'relative', height: 9, borderRadius: 6, background: 'var(--glass-2)', border: '1px solid var(--hair)', overflow: 'visible' }}>
      <motion.div initial={{ width: 0 }} animate={{ width: `${pct}%` }} transition={{ ...spring, delay: 0.15 }}
        style={{ height: '100%', borderRadius: 6, background: bg }} />
      {target != null && (
        <div style={{ position: 'absolute', top: -3, bottom: -3, left: `${(target / max) * 100}%`, width: 2, background: 'var(--hi)', borderRadius: 2 }} />
      )}
    </div>
  )
}

/* ── Раскрывающийся инсайт ── */
export function Insight({ tag, title, money, tone, detail }: { tag: string; title: string; money: string; tone: 'neg' | 'warn' | 'pos'; detail: string }) {
  const c = tone === 'pos' ? 'var(--grn)' : tone === 'warn' ? 'var(--amb)' : 'var(--red)'
  return (
    <motion.details style={{ borderTop: '1px solid var(--hair-2)', padding: '14px 0' }}>
      <summary style={{ listStyle: 'none', cursor: 'pointer', display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 16 }}>
        <span style={{ fontSize: 14, fontWeight: 620, letterSpacing: '-.01em', display: 'flex', gap: 9, alignItems: 'baseline' }}>
          <span style={{ fontSize: 9, letterSpacing: '.09em', textTransform: 'uppercase', color: 'var(--acc)', fontWeight: 700, background: 'color-mix(in srgb,var(--acc) 13%,transparent)', padding: '3px 7px', borderRadius: 7 }}>{tag}</span>
          {title}
        </span>
        <span className="tnum" style={{ color: c, fontWeight: 650, fontSize: 13, whiteSpace: 'nowrap' }}>{money}</span>
      </summary>
      <p style={{ margin: '10px 0 0', fontSize: 12.5, lineHeight: 1.55, color: 'var(--lo)' }}>{detail}</p>
    </motion.details>
  )
}

/* ── Табличные строки ── */
export function Row({ children }: { children: ReactNode }) {
  return <tr style={{ borderBottom: '1px solid var(--hair-2)' }}>{children}</tr>
}
