import { useApi } from '../lib/useApi'
import type { Period } from '../lib/api'
import {
  Hero, Metric, MetricRow, Section, DataTable, MiniBar, Loading, ErrorBox, Empty,
} from '../components/ui'
import type { Column } from '../components/ui'
import { tenge, num } from '../lib/format'

type Op = { name: string; cat: string; date: string; kassa: string; amount: number }
type Cat = { name: string; amount: number }
type Exp = { total: number; operations: Op[]; categories: Cat[] }

const OP_COLUMNS: Column[] = [
  { key: 'cat', label: 'Статья' },
  { key: 'where', label: 'Дата · касса' },
  { key: 'amount', label: 'Сумма', numeric: true },
]

export default function Expenses({ period }: { period: Period }) {
  const { data, error, loading } = useApi<Exp>('expenses', { period })
  if (loading) return <Loading />
  if (error || !data) return <ErrorBox msg={error || 'нет данных'} />

  const cats = [...data.categories].sort((a, b) => b.amount - a.amount)
  const maxCat = Math.max(...cats.map((c) => c.amount), 1)
  const topShare = data.total > 0 && cats[0] ? (cats[0].amount / data.total) * 100 : 0

  const opRows = data.operations.map((o) => [
    o.cat || o.name,
    <span className="text-ink2">{o.date} · {o.kassa}</span>,
    tenge(o.amount),
  ])

  return (
    <div>
      <Hero
        label="Расходы за период"
        value={tenge(data.total)}
        note={
          cats[0]
            ? `Крупнейшая статья — «${cats[0].name}», ${tenge(cats[0].amount)} (${topShare.toFixed(0)}% всех расходов). ` +
              `Всего ${cats.length} статей, ${data.operations.length} операций.`
            : undefined
        }
      />

      <MetricRow>
        <Metric label="Всего расходов" value={tenge(data.total)} />
        <Metric label="Статей" value={num(cats.length)} />
        <Metric label="Операций" value={num(data.operations.length)} />
      </MetricRow>

      <Section title="Категории" hint="доля в общих расходах">
        {cats.length === 0 ? (
          <Empty msg="Расходов за период нет" />
        ) : (
          <div className="space-y-4">
            {cats.map((c, i) => (
              <div key={i}>
                <div className="mb-1.5 flex items-baseline justify-between">
                  <span className="text-[13px] text-ink">{c.name}</span>
                  <span className="tnum text-[13px] text-ink2">{tenge(c.amount)}</span>
                </div>
                <MiniBar value={c.amount} max={maxCat} tone={i === 0 ? 'neg' : 'ink'} />
              </div>
            ))}
          </div>
        )}
      </Section>

      <Section title="Последние операции">
        {data.operations.length === 0 ? (
          <Empty msg="Операций нет" />
        ) : (
          <DataTable columns={OP_COLUMNS} rows={opRows} />
        )}
      </Section>
    </div>
  )
}
