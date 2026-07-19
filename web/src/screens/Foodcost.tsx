import { useApi } from '../lib/useApi'
import type { Period } from '../lib/api'
import { Card, Stat, Loading, ErrorBox, SectionTitle, Bar as MiniBar } from '../components/ui'
import { tenge, pct } from '../lib/format'
import { AlertTriangle } from 'lucide-react'
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

export default function Foodcost({ period }: { period: Period }) {
  const { data, error, loading } = useApi<FC>('foodcost', { period })
  if (loading) return <Loading />
  if (error || !data) return <ErrorBox msg={error || 'нет данных'} />

  const overspend = data.fact_sum - data.norm_sum
  const dishes = [...data.dishes].sort((a, b) => b.cost_pct - a.cost_pct)
  const maxCost = Math.max(...dishes.map((d) => d.cost_pct), data.norm_pct)

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Норма" value={pct(data.norm_pct, false)} />
        <Stat label="Факт" value={pct(data.fact_pct, false)} accent />
        <Stat label="Расхождение" value={pct(data.diff_pct, false)} delta={-data.diff_pct} invert />
        <Stat label="Переплата" value={tenge(overspend)} />
      </div>

      {data.warning && (
        <div className="flex items-center gap-2 rounded-xl border border-accent/40 bg-accent/10 p-3 text-sm text-accent">
          <AlertTriangle size={16} /> {data.warning}
        </div>
      )}

      <Card>
        <SectionTitle hint="факт vs норма по месяцам">Тренд фудкоста</SectionTitle>
        <div className="h-56">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data.trend} margin={{ top: 8, right: 8, left: 4, bottom: 0 }}>
              <CartesianGrid stroke="#232c40" vertical={false} />
              <XAxis dataKey="month" tick={{ fill: '#8891a6', fontSize: 12 }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fill: '#5b6478', fontSize: 11 }} axisLine={false} tickLine={false}
                tickFormatter={(v) => `${v}%`} width={36} domain={[0, 'dataMax + 4']} />
              <Tooltip
                contentStyle={{ background: '#111725', border: '1px solid #232c40', borderRadius: 12, color: '#e8ecf4' }}
                formatter={(v: number, n) => [`${v}%`, n === 'fact' ? 'Факт' : 'Норма']}
              />
              <Line type="monotone" dataKey="norm" stroke="#5b6478" strokeWidth={2} strokeDasharray="5 4" dot={false} />
              <Line type="monotone" dataKey="fact" stroke="#f5a524" strokeWidth={2.5} dot={{ r: 3, fill: '#f5a524' }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </Card>

      <Card>
        <SectionTitle hint="отсортировано по себестоимости">Блюда под контролем</SectionTitle>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wider text-muted">
                <th className="pb-2 font-medium">Блюдо</th>
                <th className="pb-2 font-medium">Категория</th>
                <th className="pb-2 text-right font-medium">Выручка</th>
                <th className="pb-2 pl-4 font-medium">Фудкост</th>
              </tr>
            </thead>
            <tbody>
              {dishes.map((d, i) => {
                const bad = d.cost_pct > data.norm_pct
                return (
                  <tr key={i} className="border-t border-border/60">
                    <td className="py-2.5 text-ink">{d.name}</td>
                    <td className="py-2.5 text-muted">{d.category}</td>
                    <td className="num py-2.5 text-right text-muted">{tenge(d.revenue)}</td>
                    <td className="py-2.5 pl-4">
                      <div className="flex items-center gap-3">
                        <div className="w-24"><MiniBar value={d.cost_pct} max={maxCost} tone={bad ? 'neg' : 'primary'} /></div>
                        <span className={`num w-12 text-right ${bad ? 'text-neg' : 'text-ink'}`}>{d.cost_pct}%</span>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  )
}
