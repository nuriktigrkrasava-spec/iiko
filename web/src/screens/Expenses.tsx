import { useApi } from '../lib/useApi'
import type { Period } from '../lib/api'
import { Card, Stat, Loading, ErrorBox, SectionTitle, Bar as MiniBar } from '../components/ui'
import { tenge } from '../lib/format'

type Op = { name: string; cat: string; date: string; kassa: string; amount: number }
type Cat = { name: string; amount: number }
type Exp = { total: number; operations: Op[]; categories: Cat[] }

export default function Expenses({ period }: { period: Period }) {
  const { data, error, loading } = useApi<Exp>('expenses', { period })
  if (loading) return <Loading />
  if (error || !data) return <ErrorBox msg={error || 'нет данных'} />

  const cats = [...data.categories].sort((a, b) => b.amount - a.amount)
  const maxCat = Math.max(...cats.map((c) => c.amount), 1)

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-3">
        <Stat label="Всего расходов" value={tenge(data.total)} accent />
        <Stat label="Категорий" value={String(cats.length)} />
        <Stat label="Операций" value={String(data.operations.length)} />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card>
          <SectionTitle hint="доля в общих расходах">Категории</SectionTitle>
          <div className="space-y-4">
            {cats.map((c, i) => (
              <div key={i}>
                <div className="mb-1 flex items-baseline justify-between">
                  <span className="text-sm text-ink">{c.name}</span>
                  <span className="num text-sm text-muted">{tenge(c.amount)}</span>
                </div>
                <MiniBar value={c.amount} max={maxCat} tone={i === 0 ? 'accent' : 'primary'} />
              </div>
            ))}
          </div>
        </Card>

        <Card>
          <SectionTitle>Последние операции</SectionTitle>
          <div className="space-y-1">
            {data.operations.map((o, i) => (
              <div key={i} className="flex items-center justify-between border-b border-border/50 py-2 last:border-0">
                <div>
                  <div className="text-sm text-ink">{o.cat || o.name}</div>
                  <div className="text-xs text-faint">{o.date} · {o.kassa}</div>
                </div>
                <div className="num text-sm text-ink">{tenge(o.amount)}</div>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  )
}
