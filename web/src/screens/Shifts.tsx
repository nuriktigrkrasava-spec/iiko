import { useApi } from '../lib/useApi'
import type { Period } from '../lib/api'
import { Card, Stat, Loading, ErrorBox, SectionTitle, Bar as MiniBar } from '../components/ui'
import { tenge, num } from '../lib/format'

type Staff = { name: string; since: string; revenue: number; orders: number }
type Shifts = { staff: Staff[] }

export default function Shifts({ period }: { period: Period }) {
  const { data, error, loading } = useApi<Shifts>('shifts', { period })
  if (loading) return <Loading />
  if (error || !data) return <ErrorBox msg={error || 'нет данных'} />

  const staff = [...data.staff].sort((a, b) => b.revenue - a.revenue)
  const totalRev = staff.reduce((a, s) => a + s.revenue, 0)
  const totalOrders = staff.reduce((a, s) => a + s.orders, 0)
  const maxRev = Math.max(...staff.map((s) => s.revenue), 1)

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-3">
        <Stat label="Выручка за смены" value={tenge(totalRev)} accent />
        <Stat label="Заказов" value={num(totalOrders)} />
        <Stat label="На смене" value={String(staff.length)} />
      </div>

      <Card>
        <SectionTitle hint="кто сколько принёс за смену">Кассиры и смены</SectionTitle>
        <div className="space-y-4">
          {staff.map((s, i) => (
            <div key={i} className="flex items-center gap-4">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-panel2 text-xs font-semibold text-primary2">
                {s.name.split(' ').map((p) => p[0]).slice(0, 2).join('')}
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline justify-between">
                  <span className="truncate text-sm text-ink">{s.name}</span>
                  <span className="num text-sm text-ink">{tenge(s.revenue)}</span>
                </div>
                <div className="mt-1.5 flex items-center gap-3">
                  <div className="flex-1"><MiniBar value={s.revenue} max={maxRev} tone={i === 0 ? 'accent' : 'primary'} /></div>
                  <span className="text-xs text-faint">с {s.since} · {s.orders} зак.</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  )
}
