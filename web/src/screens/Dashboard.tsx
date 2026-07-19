import { useApi } from '../lib/useApi'
import type { Period } from '../lib/api'
import { Card, Stat, Loading, ErrorBox, SectionTitle } from '../components/ui'
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

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Выручка" value={tenge(data.revenue_today)} delta={data.revenue_change} />
        <Stat label="Средний чек" value={tenge(data.avg_check)} delta={data.avg_check_change} />
        <Stat label="Гостей" value={num(data.guests)} delta={data.guests_change} />
        <Stat label="Прогноз месяца" value={tengeShort(data.forecast)} accent />
      </div>

      <Card>
        <SectionTitle hint="выручка по кассовым сменам">Динамика за 7 дней</SectionTitle>
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chart} margin={{ top: 8, right: 4, left: 4, bottom: 0 }}>
              <CartesianGrid stroke="#232c40" vertical={false} />
              <XAxis dataKey="day" tick={{ fill: '#8891a6', fontSize: 12 }} axisLine={false} tickLine={false} />
              <YAxis
                tick={{ fill: '#5b6478', fontSize: 11 }} axisLine={false} tickLine={false}
                tickFormatter={(v) => `${Math.round(v / 1000)}k`} width={40}
              />
              <Tooltip
                cursor={{ fill: '#ffffff08' }}
                contentStyle={{ background: '#111725', border: '1px solid #232c40', borderRadius: 12, color: '#e8ecf4' }}
                formatter={(v: number) => [tenge(v), 'Выручка']}
              />
              <Bar dataKey="rev" radius={[6, 6, 0, 0]} maxBarSize={54}>
                {chart.map((c, i) => (
                  <Cell key={i} fill={c.rev === maxRev ? '#f5a524' : '#3b82f6'} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Card>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Card className="flex items-center justify-between">
          <div>
            <div className="text-xs uppercase tracking-wider text-muted">Открытые заказы</div>
            <div className="num mt-1 text-2xl font-semibold">{data.open_orders}</div>
          </div>
          <div className="text-xs text-faint">сейчас в работе</div>
        </Card>
        <Card className="flex items-center justify-between">
          <div>
            <div className="text-xs uppercase tracking-wider text-muted">Средняя за 7 дней</div>
            <div className="num mt-1 text-2xl font-semibold">
              {tenge(Math.round(data.chart_7days.data.reduce((a, b) => a + b, 0) / data.chart_7days.data.length))}
            </div>
          </div>
          <div className="text-xs text-faint">выручка/день</div>
        </Card>
      </div>
    </div>
  )
}
