import { useApi } from '../lib/useApi'
import type { Period } from '../lib/api'
import { Hero, Metric, MetricRow, Section, Loading, ErrorBox } from '../components/ui'
import { CHART } from '../lib/chartTheme'
import { tenge, tengeShort, num } from '../lib/format'
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid, Cell,
} from 'recharts'

type Dash = {
  revenue_today: number; revenue_change: number
  avg_check: number; avg_check_change: number
  guests: number; guests_change: number
  open_orders: number; forecast: number
  chart_7days: { labels: string[]; data: number[] }
}

export default function Dashboard({ period }: { period: Period }) {
  const { data, error, loading } = useApi<Dash>('dashboard', { period })
  if (loading) return <Loading />
  if (error || !data) return <ErrorBox msg={error || 'нет данных'} />

  const chart = data.chart_7days.labels.map((l, i) => ({ day: l, rev: data.chart_7days.data[i] }))
  const maxRev = Math.max(...data.chart_7days.data)
  const avg7 = Math.round(
    data.chart_7days.data.reduce((a, b) => a + b, 0) / data.chart_7days.data.length,
  )

  return (
    <div>
      <Hero
        label="Выручка за период"
        value={tenge(data.revenue_today)}
        delta={data.revenue_change}
        note={`Средняя за 7 дней — ${tenge(avg7)}. Прогноз месяца — ${tengeShort(data.forecast)}.`}
      />

      <MetricRow>
        <Metric label="Средний чек" value={tenge(data.avg_check)} delta={data.avg_check_change} />
        <Metric label="Гостей" value={num(data.guests)} delta={data.guests_change} />
        <Metric label="Открытые заказы" value={num(data.open_orders)} />
        <Metric label="Прогноз месяца" value={tengeShort(data.forecast)} />
      </MetricRow>

      <Section title="Динамика за 7 дней" hint="выручка по кассовым сменам">
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chart} margin={{ top: 8, right: 4, left: 4, bottom: 0 }}>
              <CartesianGrid stroke={CHART.grid.stroke} vertical={false} />
              <XAxis dataKey="day" tick={CHART.axis} axisLine={false} tickLine={false} />
              <YAxis
                tick={CHART.axis} axisLine={{ stroke: CHART.rule }} tickLine={false}
                tickFormatter={(v) => `${Math.round(Number(v) / 1000)}k`} width={40}
              />
              <Tooltip
                cursor={{ fill: CHART.paper2 }}
                contentStyle={CHART.tooltip}
                formatter={(value) => [tenge(Number(value)), 'Выручка']}
              />
              <Bar dataKey="rev" maxBarSize={46}>
                {chart.map((c, i) => (
                  <Cell key={i} fill={c.rev === maxRev ? CHART.neg : CHART.ink} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Section>
    </div>
  )
}
