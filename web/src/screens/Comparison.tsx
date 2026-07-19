import { useApi } from '../lib/useApi'
import { Card, Stat, Loading, ErrorBox, SectionTitle } from '../components/ui'
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

export default function Comparison() {
  const { data, error, loading } = useApi<Cmp>('comparison')
  if (loading) return <Loading />
  if (error || !data) return <ErrorBox msg={error || 'нет данных'} />

  const cur = data.weeks.current
  const prev = data.weeks.previous
  const curTotal = cur.reduce((a, w) => a + w.total_rev, 0)
  const prevTotal = prev.reduce((a, w) => a + w.total_rev, 0)
  const deltaPct = prevTotal ? ((curTotal - prevTotal) / prevTotal) * 100 : 0

  const chart = cur.map((w, i) => ({
    label: w.label,
    'В этом году': w.total_rev,
    'Год назад': prev[i]?.total_rev ?? 0,
  }))

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-3">
        <Stat label={`Этот год${data.cur_year ? ` · ${data.cur_year}` : ''}`} value={tengeShort(curTotal)} />
        <Stat label={`Прошлый год${data.prev_year ? ` · ${data.prev_year}` : ''}`} value={tengeShort(prevTotal)} />
        <Stat label="Изменение г/г" value={pct(deltaPct)} delta={deltaPct} accent />
      </div>

      <Card>
        <SectionTitle hint="выручка по неделям, текущий vs прошлый год">Сравнение год к году</SectionTitle>
        <div className="h-72">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chart} margin={{ top: 8, right: 4, left: 4, bottom: 0 }} barGap={2}>
              <CartesianGrid stroke="#232c40" vertical={false} />
              <XAxis dataKey="label" tick={{ fill: '#8891a6', fontSize: 12 }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fill: '#5b6478', fontSize: 11 }} axisLine={false} tickLine={false}
                tickFormatter={(v) => `${Math.round(v / 1000000)}М`} width={36} />
              <Tooltip
                cursor={{ fill: '#ffffff08' }}
                contentStyle={{ background: '#111725', border: '1px solid #232c40', borderRadius: 12, color: '#e8ecf4' }}
                formatter={(v: number) => tenge(v)}
              />
              <Legend wrapperStyle={{ fontSize: 12, color: '#8891a6' }} />
              <Bar dataKey="Год назад" fill="#37415a" radius={[4, 4, 0, 0]} maxBarSize={26} />
              <Bar dataKey="В этом году" fill="#3b82f6" radius={[4, 4, 0, 0]} maxBarSize={26} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Card>

      <Card>
        <SectionTitle>По неделям</SectionTitle>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wider text-muted">
                <th className="pb-2 font-medium">Неделя</th>
                <th className="pb-2 text-right font-medium">Этот год</th>
                <th className="pb-2 text-right font-medium">Год назад</th>
                <th className="pb-2 text-right font-medium">Δ</th>
              </tr>
            </thead>
            <tbody className="num">
              {cur.map((w, i) => {
                const p = prev[i]?.total_rev ?? 0
                const d = p ? ((w.total_rev - p) / p) * 100 : 0
                return (
                  <tr key={w.key} className="border-t border-border/60">
                    <td className="py-2.5 font-sans text-ink">{w.label}</td>
                    <td className="py-2.5 text-right text-ink">{tenge(w.total_rev)}</td>
                    <td className="py-2.5 text-right text-muted">{tenge(p)}</td>
                    <td className={`py-2.5 text-right ${d >= 0 ? 'text-pos' : 'text-neg'}`}>{pct(d)}</td>
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
