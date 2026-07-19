import { useApi } from '../lib/useApi'
import type { Period } from '../lib/api'
import {
  Hero, Metric, MetricRow, Section, DataTable, MiniBar, Loading, ErrorBox, Empty,
} from '../components/ui'
import type { Column } from '../components/ui'
import { tenge, num } from '../lib/format'

type Staff = { name: string; since: string; revenue: number; orders: number }
type Shifts = { staff: Staff[] }

const COLUMNS: Column[] = [
  { key: 'name', label: 'Кассир' },
  { key: 'since', label: 'С' },
  { key: 'orders', label: 'Заказов', numeric: true },
  { key: 'revenue', label: 'Выручка', numeric: true },
]

export default function Shifts({ period }: { period: Period }) {
  const { data, error, loading } = useApi<Shifts>('shifts', { period })
  if (loading) return <Loading />
  if (error || !data) return <ErrorBox msg={error || 'нет данных'} />

  const staff = [...data.staff].sort((a, b) => b.revenue - a.revenue)
  const totalRev = staff.reduce((a, s) => a + s.revenue, 0)
  const totalOrders = staff.reduce((a, s) => a + s.orders, 0)
  const maxRev = Math.max(...staff.map((s) => s.revenue), 1)
  const avgCheck = totalOrders > 0 ? Math.round(totalRev / totalOrders) : 0

  const rows = staff.map((s) => [
    s.name,
    <span className="text-ink2">{s.since}</span>,
    num(s.orders),
    <div className="flex items-center justify-end gap-3">
      <div className="w-20"><MiniBar value={s.revenue} max={maxRev} tone="ink" /></div>
      <span>{tenge(s.revenue)}</span>
    </div>,
  ])

  return (
    <div>
      <Hero
        label="Выручка за смены"
        value={tenge(totalRev)}
        note={
          staff[0]
            ? `Лидер смены — ${staff[0].name}, ${tenge(staff[0].revenue)}. ` +
              `Всего ${staff.length} на смене, ${num(totalOrders)} заказов, средний чек ${tenge(avgCheck)}.`
            : undefined
        }
      />

      <MetricRow>
        <Metric label="Выручка за смены" value={tenge(totalRev)} />
        <Metric label="Заказов" value={num(totalOrders)} />
        <Metric label="Средний чек" value={tenge(avgCheck)} />
        <Metric label="На смене" value={num(staff.length)} />
      </MetricRow>

      <Section title="Кассиры и смены" hint="кто сколько принёс за смену">
        {staff.length === 0 ? (
          <Empty msg="Открытых смен нет" />
        ) : (
          <DataTable columns={COLUMNS} rows={rows} />
        )}
      </Section>
    </div>
  )
}
