import type { ReactNode } from 'react'
import { useApi } from '../lib/useApi'
import { Glass, Chart, Delta } from './ui'
import { barChart } from './charts'
import { tengeShort } from '../lib/format'

/* ─────────────────────────────────────────────────────────────
   Отчёт недели — БРИФИНГ, читается сверху вниз (как «Аналитика»).
   Три полноширинных стеклянных блока: итог недели · приоритеты
   по важности · план на неделю. Живые данные: dashboard ·
   comparison · foodcost · sales · reviews · insights.
   ───────────────────────────────────────────────────────────── */

type Dash = {
  chart_7days: { labels: string[]; data: number[] }
  avg_check: number; avg_check_change: number
  guests: number; guests_change: number
  revenue_change: number
}
type CmpRow = { label: string; total_rev: number; total_orders: number }
type Cmp = { weeks: { current: CmpRow[]; previous: CmpRow[] } }
type FC = { fact_pct: number | null; norm_pct: number; diff_pct: number | null; fact_sum: number | null }
type Channel = { name: string; revenue: number }
type Dish = { name: string; revenue: number; count: number }
type Sales = { channels: Channel[]; top_dishes: Dish[] }
type Plat = { platform: string; label: string; rating: number; scale: number; delta: number | null }
type Rev = { platforms: Plat[] }
type Ins = {
  leakage_total: number
  headline: string
  insights: { title: string; detail: string; money: string; severity: string; dimension: string }[]
  plan: { action: string; effect: string; priority: number }[]
}

const GRAD = 'linear-gradient(90deg,#4f6ef7 0%,#7b5cff 42%,#ff9d4d 78%,#ffd24d 100%)'
const ru1 = (n: number) => `${n >= 0 ? '+' : ''}${n.toFixed(1).replace('.', ',')}%`

/* строка приоритета — ранг, заголовок, тег, деньги справа, деталь */
type Prio = { rank: number; c: string; tag: string; grew: boolean; title: string; money: string; detail: string }

/* Заглушка состояния — единый вид на всю сетку */
function Note({ children }: { children: ReactNode }) {
  return <Glass span={12}><div style={{ padding: '10px 2px', fontSize: 13.5, color: 'var(--mute)' }}>{children}</div></Glass>
}

/* последние две недели с ненулевой выручкой */
function lastTwo(weeks: CmpRow[]): [CmpRow | undefined, CmpRow | undefined] {
  const live = weeks.filter((w) => w.total_rev > 0)
  return [live[live.length - 1], live[live.length - 2]]
}

export default function Report() {
  const dash = useApi<Dash>('dashboard', { period: 'month' })
  const cmp = useApi<Cmp>('comparison', { period: 'month' })
  const fc = useApi<FC>('foodcost', { period: 'month' })
  const sales = useApi<Sales>('sales', { period: 'month' })
  const rev = useApi<Rev>('reviews', { period: 'month' })
  const ins = useApi<Ins>('insights')

  const loading = dash.loading || cmp.loading || fc.loading || sales.loading || rev.loading || ins.loading
  if (loading) return <Note>Собираю отчёт недели…</Note>
  if (dash.error || !dash.data) return <Note>Не удалось собрать отчёт: {dash.error}</Note>

  const d = dash.data
  const c = d.chart_7days
  const weekRev = c.data.reduce((a, b) => a + b, 0)
  const peakIdx = c.data.indexOf(Math.max(...c.data))
  const bars = c.labels.map((l, i) => ({ l, v: +(c.data[i] / 1_000_000).toFixed(2) }))

  // WoW из comparison (последние две живые недели)
  const [wLast, wPrev] = lastTwo(cmp.data?.weeks.current ?? [])
  const wow = wLast && wPrev && wPrev.total_rev ? ((wLast.total_rev - wPrev.total_rev) / wPrev.total_rev) * 100 : 0
  const up = wow >= 0
  const lightC = up ? 'var(--grn)' : 'var(--red)'

  // утечка за неделю (месячная / 4.3)
  const leakWeek = ins.data ? ins.data.leakage_total / 4.3 : 0
  const insList = ins.data?.insights ?? []
  const plan = ins.data?.plan ?? []
  const topLeak = insList[0]?.title ?? 'скрытые потери'

  // что выиграло: топ-канал + топ-блюдо
  const channels = sales.data?.channels ?? []
  const chTotal = channels.reduce((a, x) => a + x.revenue, 0) || 1
  const topCh = channels.reduce<Channel | null>((a, x) => (!a || x.revenue > a.revenue ? x : a), null)
  const topShare = topCh ? (topCh.revenue / chTotal) * 100 : 0
  const topDish = sales.data?.top_dishes?.[0]

  // фудкост
  const f = fc.data
  const fcOk = f && f.fact_pct != null && f.diff_pct != null
  const fcGap = fcOk ? (f!.diff_pct! * weekRev) / 100 : 0

  // средний чек vs трафик — что тянет рост
  const drive = Math.abs(d.avg_check_change) >= Math.abs(d.guests_change)
    ? 'тянет средний чек, не трафик'
    : 'тянет поток гостей, не чек'
  const chkUp = d.avg_check_change >= 0

  // репутация: платформа со свежим сигналом (ненулевая дельта) или самая слабая
  const plats = rev.data?.platforms ?? []
  const signal = plats.find((p) => p.delta != null && p.delta !== 0)
    ?? [...plats].sort((a, b) => a.rating / a.scale - b.rating / b.scale)[0]
  const weakSignal = signal && (signal.rating / signal.scale < 0.8 || (signal.delta != null && signal.delta !== 0))

  /* ── Приоритеты — собираем из реальных сигналов, ранжируем по важности ── */
  const prios: Prio[] = []

  // Утечка недели — всегда риск
  prios.push({
    rank: 0, c: 'var(--red)', tag: 'риск', grew: false,
    title: 'Утечка недели',
    money: `~${tengeShort(leakWeek)}`,
    detail: `Основной источник — ${topLeak.toLowerCase()}. Оценка потерь по чекам за 7 дней.`,
  })

  // Фудкост — риск/внимание при перерасходе, иначе в норме
  if (fcOk) {
    const over = f!.diff_pct! > 0
    const big = f!.diff_pct! >= 3
    prios.push({
      rank: over ? (big ? 0 : 1) : 2,
      c: over ? (big ? 'var(--red)' : 'var(--amb)') : 'var(--grn)',
      tag: over ? (big ? 'риск' : 'внимание') : 'растёт', grew: !over,
      title: 'Фудкост',
      money: over ? `~${tengeShort(fcGap)}/нед` : 'в норме',
      detail: `Факт ${ru1(f!.fact_pct!).replace('+', '')} при норме ${f!.norm_pct}%. ${over ? `Переплата съедает маржу — ${ru1(f!.diff_pct!)} к обороту.` : 'Себестоимость держится в пределах нормы.'}`,
    })
  }

  // Что выиграло — рост
  if (topCh) {
    prios.push({
      rank: 2, c: 'var(--grn)', tag: 'растёт', grew: true,
      title: `Что выиграло — ${topCh.name}`,
      money: tengeShort(topCh.revenue),
      detail: `Лучший канал недели · ${topShare.toFixed(0)}% выручки.${topDish ? ` Топ-блюдо — ${topDish.name} (${topDish.count} шт).` : ''}`,
    })
  }

  // Средний чек / гости — рост или внимание
  prios.push({
    rank: chkUp ? 2 : 1, c: chkUp ? 'var(--grn)' : 'var(--red)',
    tag: chkUp ? 'растёт' : 'внимание', grew: chkUp,
    title: 'Средний чек и гости',
    money: tengeShort(d.avg_check),
    detail: `Чек ${ru1(d.avg_check_change)}, гостей ${d.guests} (${ru1(d.guests_change)}) — ${drive}.`,
  })

  // Репутация — только при свежем сигнале / низком рейтинге
  if (signal && weakSignal) {
    const rUp = signal.delta != null && signal.delta > 0
    prios.push({
      rank: rUp ? 2 : 1, c: rUp ? 'var(--grn)' : 'var(--amb)',
      tag: rUp ? 'растёт' : 'внимание', grew: rUp,
      title: `Репутация — ${signal.label}`,
      money: `${signal.rating.toFixed(1).replace('.', ',')} из ${signal.scale}`,
      detail: signal.delta != null && signal.delta !== 0
        ? `Рейтинг ${ru1(signal.delta)} за период — держите планку в отзывах.`
        : 'Рейтинг ниже целевого — стоит поработать с отзывами.',
    })
  }

  const ranked = [...prios].sort((a, b) => a.rank - b.rank)

  return (
    <>
      {/* ── 1 · Итог недели — вердикт + выручка + график (одна поверхность) ── */}
      <Glass span={12} spot warp>
        <div className="eyebrow">
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7 }}>
            <span style={{ width: 7, height: 7, borderRadius: '50%', background: lightC, boxShadow: `0 0 8px ${lightC}` }} />
            Отчёт недели · последние 7 дней
          </span>
          <span className="hint">iiko · сверено по чекам</span>
        </div>
        <p className="display tnum" style={{ margin: '16px 0 0', fontSize: 24, lineHeight: 1.45, letterSpacing: '-.014em', color: 'var(--hi)', maxWidth: '60ch' }}>
          Неделя <b style={{ color: lightC }}>{up ? '🟢' : '🔴'} {ru1(wow)}</b> к прошлой (<b style={{ color: 'var(--hi)' }}>{tengeShort(weekRev)}</b>).{' '}
          Утекло <b style={{ color: '#ff8f6b' }}>~{tengeShort(leakWeek)}</b>.{' '}
          {topCh && <>Тянет <b style={{ color: 'var(--grn)' }}>{topCh.name}</b>.</>}
        </p>
        <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', gap: 32, marginTop: 26, flexWrap: 'wrap' }}>
          <div style={{ minWidth: 200 }}>
            <div style={{ fontSize: 11, letterSpacing: '.09em', textTransform: 'uppercase', color: 'var(--mute)', fontWeight: 650 }}>Выручка недели</div>
            <div className="tnum" style={{ fontSize: 48, fontWeight: 720, letterSpacing: '-.035em', lineHeight: 1, marginTop: 8, color: 'var(--hi)' }}>{tengeShort(weekRev)}</div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 16, marginTop: 12 }}>
              <span style={{ display: 'inline-flex', alignItems: 'baseline', gap: 6 }}>
                <Delta v={wow} /><span style={{ fontSize: 11.5, color: 'var(--mute)' }}>к прошлой</span>
              </span>
              <span style={{ display: 'inline-flex', alignItems: 'baseline', gap: 6 }}>
                <Delta v={d.revenue_change} /><span style={{ fontSize: 11.5, color: 'var(--mute)' }}>г/г</span>
              </span>
            </div>
          </div>
          <div style={{ flex: 1, minWidth: 280 }}>
            <div style={{ fontSize: 11, letterSpacing: '.09em', textTransform: 'uppercase', color: 'var(--mute)', fontWeight: 650, textAlign: 'right' }}>млн ₸ · пик выделен</div>
            <Chart html={barChart(bars, peakIdx, up ? 'var(--grn)' : 'var(--red)', ' млн')} style={{ marginTop: 6 }} />
          </div>
        </div>
        <div style={{ height: 8, borderRadius: 6, marginTop: 22, background: GRAD, opacity: 0.92 }} />
      </Glass>

      {/* ── 2 · Что важнее — приоритеты (ранжированный список, не карточки) ── */}
      <Glass span={12}>
        <div className="eyebrow"><span>Что важнее · приоритеты недели</span><span className="hint">{ranked.length} сигналов · по важности</span></div>
        <div style={{ marginTop: 8 }}>
          {ranked.map((x, i) => (
            <div key={i} style={{ display: 'flex', gap: 16, padding: '16px 0', borderTop: i ? '1px solid var(--hair-2)' : 'none' }}>
              <span style={{ flex: 'none', width: 28, height: 28, borderRadius: 9, display: 'grid', placeItems: 'center', fontSize: 13, fontWeight: 700, color: x.c, background: `color-mix(in srgb, ${x.c} 15%, transparent)` }}>{i + 1}</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
                  <span style={{ fontSize: 15, fontWeight: 650, color: 'var(--hi)', letterSpacing: '-.01em' }}>{x.title}</span>
                  <span style={{ fontSize: 10.5, letterSpacing: '.06em', textTransform: 'uppercase', fontWeight: 700, color: x.c, background: `color-mix(in srgb, ${x.c} 14%, transparent)`, padding: '2px 8px', borderRadius: 6 }}>{x.tag}</span>
                  <span className="tnum" style={{ marginLeft: 'auto', fontSize: 15, fontWeight: 700, color: x.c, whiteSpace: 'nowrap' }}>{x.grew ? '▲ ' : ''}{x.money}</span>
                </div>
                <p style={{ margin: '7px 0 0', fontSize: 13.5, lineHeight: 1.55, color: 'var(--lo)', maxWidth: '82ch' }}>{x.detail}</p>
              </div>
            </div>
          ))}
        </div>
      </Glass>

      {/* ── 3 · План на неделю ── */}
      <Glass span={12}>
        <div className="eyebrow"><span>План на неделю</span><span className="hint">по приоритету · с эффектом в ₸</span></div>
        {plan.length ? (
          <div style={{ marginTop: 14, display: 'flex', flexDirection: 'column', gap: 4 }}>
            {plan.map((p, i) => (
              <div key={i} style={{ display: 'flex', gap: 14, alignItems: 'center', padding: '14px 0', borderTop: i ? '1px solid var(--hair-2)' : 'none' }}>
                <span style={{ flex: 'none', width: 28, height: 28, borderRadius: '50%', display: 'grid', placeItems: 'center', fontSize: 13, fontWeight: 700, background: 'color-mix(in srgb,var(--acc) 20%,transparent)', color: 'var(--acc)' }}>{p.priority}</span>
                <div style={{ flex: 1, minWidth: 0, fontSize: 14.5, lineHeight: 1.5, color: 'var(--hi)' }}>{p.action}</div>
                <span style={{ flex: 'none', fontSize: 12.5, fontWeight: 700, color: 'var(--grn)', background: 'color-mix(in srgb,var(--grn) 14%,transparent)', padding: '6px 12px', borderRadius: 9, whiteSpace: 'nowrap' }}>{p.effect}</span>
              </div>
            ))}
          </div>
        ) : (
          <p style={{ margin: '14px 0 0', fontSize: 13.5, color: 'var(--mute)' }}>план формируется…</p>
        )}
      </Glass>
    </>
  )
}
