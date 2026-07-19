import { useApi } from '../lib/useApi'
import {
  Hero, Metric, MetricRow, Section, DataTable, Loading, ErrorBox,
} from '../components/ui'
import type { Column } from '../components/ui'
import { CHART } from '../lib/chartTheme'
import { tenge, tengeShort, pct } from '../lib/format'
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid, Legend,
} from 'recharts'

type Week = { key: string; label: string; year: number; total_rev: number; total_orders: number }
type Cmp = {
  weeks: { current: Week[]; previous: Week[] }
  months?: { label: string; cur: number; prev: number }[]
  cur_year?: number; prev_year?: number
}

const COLUMNS: Column[] = [
  { key: 'week', label: 'Неделя' },
  { key: 'cur', label: 'Этот год', numeric: true },
  { key: 'prev', label: 'Год назад', numeric: true },
  { key: 'delta', label: 'Δ', numeric: true },
]

export default function Comparison() {
  const { data, error, loading } = useApi<Cmp>('comparison')
  if (loading) return <Loading />
  if (error || !data) return <ErrorBox msg={error || 'нет данных'} />

  const cur = data.weeks.current
  const prev = data.weeks.previous
  const curTotal = cur.reduce((a, w) => a + w.total_rev, 0)
  const prevTotal = prev.reduce((a, w) => a + w.total_rev, 0)
  const diff = curTotal - prevTotal
  const deltaPct = prevTotal ? (diff / prevTotal) * 100 : 0

  const chart = cur.map((w, i) => ({
    label: w.label,
    'В этом году': w.total_rev,
    'Год назад': prev[i]?.total_rev ?? 0,
  }))

  const rows = cur.map((w, i) => {
    const p = prev[i]?.total_rev ?? 0
    const d = p ? ((w.total_rev - p) / p) * 100 : 0
    return [
      w.label,
      tenge(w.total_rev),
      <span className="text-ink2">{tenge(p)}</span>,
      <span className={d >= 0 ? 'text-pos' : 'text-neg'}>{pct(d)}</span>,
    ]
  })

  return (
    <div>
      <Hero
        label="Разница год к году"
        value={tenge(diff)}
        delta={deltaPct}
        note={
          `Этот год${data.cur_year ? ` (${data.cur_year})` : ''} — ${tengeShort(curTotal)}, ` +
          `прошлый${data.prev_year ? ` (${data.prev_year})` : ''} — ${tengeShort(prevTotal)}. ` +
          `Сравниваются одни и те же недели.`
        }
      />

      <MetricRow>
        <Metric label={`Этот год${data.cur_year ? ` · ${data.cur_year}` : ''}`} value={tengeShort(curTotal)} />
        <Metric label={`Прошлый год${data.prev_year ? ` · ${data.prev_year}` : ''}`} value={tengeShort(prevTotal)} />
        <Metric label="Изменение г/г" value={pct(deltaPct)} delta={deltaPct} />
      </MetricRow>

      <Section title="Сравнение год к году" hint="выручка по неделям, текущий против прошлого">
        <div className="h-72">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chart} margin={{ top: 8, right: 4, left: 4, bottom: 0 }} barGap={2}>
              <CartesianGrid stroke={CHART.grid.stroke} vertical={false} />
              <XAxis dataKey="label" tick={CHART.axis} axisLine={false} tickLine={false} />
              <YAxis tick={CHART.axis} axisLine={false} tickLine={false}
                tickFormatter={(v) => `${Math.round(Number(v) / 1000000)}М`} width={36} />
              <Tooltip
                cursor={{ fill: CHART.paper2 }}
                contentStyle={CHART.tooltip}
                formatter={(value) => tenge(Number(value))}
              />
              <Legend wrapperStyle={{ fontSize: 11, fontFamily: '"Golos Text", sans-serif', color: CHART.muted }} />
              <Bar dataKey="Год назад" fill={CHART.muted} maxBarSize={24} />
              <Bar dataKey="В этом году" fill={CHART.ink} maxBarSize={24} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Section>

      <Section title="По неделям">
        <DataTable columns={COLUMNS} rows={rows} />
      </Section>
    </div>
  )
}
