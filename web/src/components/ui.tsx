import type { ReactNode } from 'react'
import { pct } from '../lib/format'

export function Card({ children, className = '', onClick }: { children: ReactNode; className?: string; onClick?: () => void }) {
  return (
    <div onClick={onClick} className={`rounded-2xl border border-border bg-panel/80 backdrop-blur-sm p-5 ${className}`}>
      {children}
    </div>
  )
}

export function SectionTitle({ children, hint }: { children: ReactNode; hint?: string }) {
  return (
    <div className="mb-3 flex items-baseline justify-between gap-3">
      <h2 className="text-[15px] font-semibold tracking-wide text-ink">{children}</h2>
      {hint && <span className="text-xs text-faint">{hint}</span>}
    </div>
  )
}

/** Дельта в цвете: рост зелёный, падение красное */
export function Delta({ value, invert = false }: { value: number | null | undefined; invert?: boolean }) {
  if (value == null) return null
  const good = invert ? value < 0 : value > 0
  const color = value === 0 ? 'text-muted' : good ? 'text-pos' : 'text-neg'
  const arrow = value === 0 ? '' : value > 0 ? '▲' : '▼'
  return (
    <span className={`num text-xs font-medium ${color}`}>
      {arrow} {pct(Math.abs(value), false)}
    </span>
  )
}

export function Stat({
  label, value, delta, invert, accent,
}: {
  label: string; value: ReactNode; delta?: number | null; invert?: boolean; accent?: boolean
}) {
  return (
    <Card className="fade-in">
      <div className="text-xs uppercase tracking-wider text-muted">{label}</div>
      <div className={`num mt-2 text-[26px] leading-none font-semibold ${accent ? 'text-accent' : 'text-ink'}`}>
        {value}
      </div>
      {delta != null && <div className="mt-2"><Delta value={delta} invert={invert} /></div>}
    </Card>
  )
}

export function Loading({ label = 'Загрузка данных…' }: { label?: string }) {
  return (
    <div className="flex h-64 flex-col items-center justify-center gap-3 text-muted">
      <div className="h-6 w-6 animate-spin rounded-full border-2 border-border border-t-primary" />
      <span className="text-sm">{label}</span>
    </div>
  )
}

export function ErrorBox({ msg }: { msg: string }) {
  return (
    <div className="rounded-xl border border-neg/40 bg-neg/10 p-4 text-sm text-neg">
      Не удалось загрузить: {msg}
    </div>
  )
}

/** горизонтальный бар для долей внутри таблиц */
export function Bar({ value, max, tone = 'primary' }: { value: number; max: number; tone?: 'primary' | 'accent' | 'neg' }) {
  const w = max > 0 ? Math.max(2, Math.round((value / max) * 100)) : 0
  const color = tone === 'accent' ? 'bg-accent' : tone === 'neg' ? 'bg-neg' : 'bg-primary'
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-panel2">
      <div className={`h-full rounded-full ${color}`} style={{ width: `${w}%` }} />
    </div>
  )
}
