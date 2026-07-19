import { useApi } from '../lib/useApi'
import type { Period } from '../lib/api'
import { Card, Stat, Loading, ErrorBox, SectionTitle, Bar as MiniBar } from '../components/ui'
import { tenge, num } from '../lib/format'
import { XCircle, Banknote } from 'lucide-react'

type Cancels = { items: { name: string; amount: number }[]; total_amount: number; total_orders: number }
type Withdrawals = { withdrawals: { date: string; sum: number; comment: string }[]; total: number }

export default function Anomalies({ period }: { period: Period }) {
  const c = useApi<Cancels>('cancels', { period })
  const w = useApi<Withdrawals>('withdrawals', { period })
  if (c.loading || w.loading) return <Loading />
  if (c.error || !c.data) return <ErrorBox msg={c.error || 'нет данных'} />
  if (w.error || !w.data) return <ErrorBox msg={w.error || 'нет данных'} />

  const items = [...c.data.items].sort((a, b) => b.amount - a.amount)
  const maxItem = Math.max(...items.map((i) => i.amount), 1)

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Отмены/возвраты" value={tenge(c.data.total_amount)} delta={-100} invert />
        <Stat label="Кол-во отмен" value={num(c.data.total_orders)} />
        <Stat label="Изъятия наличных" value={tenge(w.data.total)} />
        <Stat label="Операций изъятия" value={String(w.data.withdrawals.length)} />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card>
          <SectionTitle hint="блюда с наибольшими списаниями"><span className="inline-flex items-center gap-2"><XCircle size={15} className="text-neg" /> Отмены и возвраты</span></SectionTitle>
          <div className="space-y-4">
            {items.map((it, i) => (
              <div key={i}>
                <div className="mb-1 flex items-baseline justify-between">
                  <span className="text-sm text-ink">{it.name}</span>
                  <span className="num text-sm text-neg">{tenge(it.amount)}</span>
                </div>
                <MiniBar value={it.amount} max={maxItem} tone="neg" />
              </div>
            ))}
          </div>
        </Card>

        <Card>
          <SectionTitle hint="выемки из кассы"><span className="inline-flex items-center gap-2"><Banknote size={15} className="text-accent" /> Изъятия наличных</span></SectionTitle>
          <div className="space-y-1">
            {w.data.withdrawals.map((it, i) => (
              <div key={i} className="flex items-center justify-between border-b border-border/50 py-2.5 last:border-0">
                <div>
                  <div className="text-sm text-ink">{it.comment}</div>
                  <div className="num text-xs text-faint">{it.date}</div>
                </div>
                <div className="num text-sm text-ink">{tenge(it.sum)}</div>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  )
}
