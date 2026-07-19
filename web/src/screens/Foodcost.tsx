import { useApi } from '../lib/useApi'
import type { Period } from '../lib/api'
import {
  Hero, Metric, MetricRow, Section, DataTable, MiniBar, Loading, ErrorBox,
} from '../components/ui'
import type { Column } from '../components/ui'
import { CHART } from '../lib/chartTheme'
import { tenge, pct } from '../lib/format'
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid,
} from 'recharts'

type Dish = { name: string; category: string; revenue: number; count: number; cost_pct: number }
type FC = {
  norm_pct: number; fact_pct: number; diff_pct: number
  norm_sum: number; fact_sum: number; warning?: string
  trend: { month: string; fact: number; norm: number }[]
  dishes: Dish[]
}

const COLUMNS: Column[] = [
  { key: 'name', label: 'Блюдо' },
  { key: 'category', label: 'Категория' },
  { key: 'revenue', label: 'Выручка', numeric: true },
  { key: 'cost', label: 'Фудкост', numeric: true },
]

export default function Foodcost({ period }: { period: Period }) {
  const { data, error, loading } = useApi<FC>('foodcost', { period })
  if (loading) return <Loading />
  if (error || !data) return <ErrorBox msg={error || 'нет данных'} />

  const overspend = data.fact_sum - data.norm_sum
  const dishes = [...data.dishes].sort((a, b) => b.cost_pct - a.cost_pct)
  const maxCost = Math.max(...dishes.map((d) => d.cost_pct), data.norm_pct)

  const rows = dishes.map((d) => {
    const bad = d.cost_pct > data.norm_pct
    return [
      d.name,
      <span className="text-ink2">{d.category}</span>,
      tenge(d.revenue),
      <div className="flex items-center justify-end gap-3">
        <div className="w-20"><MiniBar value={d.cost_pct} max={maxCost} tone={bad ? 'neg' : 'ink'} /></div>
        <span className={bad ? 'text-neg' : 'text-ink'}>{d.cost_pct}%</span>
      </div>,
    ]
  })

  return (
    <div>
      <Hero
        label="Переплата по себестоимости"
        value={tenge(overspend)}
        delta={data.diff_pct}
        note={
          `Фактический фудкост ${pct(data.fact_pct, false)} против нормы ${pct(data.norm_pct, false)}. ` +
          `Расхождение ${pct(data.diff_pct, false)}.` + (data.warning ? ` ${data.warning}` : '')
        }
      />

      <MetricRow>
        <Metric label="Норма" value={pct(data.norm_pct, false)} />
        <Metric label="Факт" value={pct(data.fact_pct, false)} />
        <Metric label="Норма, сумма" value={tenge(data.norm_sum)} />
        <Metric label="Факт, сумма" value={tenge(data.fact_sum)} />
      </MetricRow>

      <Section title="Тренд фудкоста" hint="факт против нормы по месяцам">
        <div className="h-56">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data.trend} margin={{ top: 8, right: 8, left: 4, bottom: 0 }}>
              <CartesianGrid stroke={CHART.grid.stroke} vertical={false} />
              <XAxis dataKey="month" tick={CHART.axis} axisLine={false} tickLine={false} />
              <YAxis tick={CHART.axis} axisLine={false} tickLine={false}
                tickFormatter={(v) => `${v}%`} width={36} domain={[0, 'dataMax + 4']} />
              <Tooltip
                contentStyle={CHART.tooltip}
                formatter={(value, name) => [`${value}%`, name === 'fact' ? 'Факт' : 'Норма']}
              />
              <Line type="monotone" dataKey="norm" stroke={CHART.muted} strokeWidth={1.5} strokeDasharray="4 4" dot={false} />
              <Line type="monotone" dataKey="fact" stroke={CHART.neg} strokeWidth={2} dot={{ r: 2.5, fill: CHART.neg }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </Section>

      <Section title="Блюда под контролем" hint="отсортировано по себестоимости">
        <DataTable columns={COLUMNS} rows={rows} />
      </Section>
    </div>
  )
}
