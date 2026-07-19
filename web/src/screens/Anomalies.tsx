import { useApi } from '../lib/useApi'
import type { Period } from '../lib/api'
import {
  Hero, Metric, MetricRow, Section, DataTable, MiniBar, Loading, ErrorBox, Empty,
} from '../components/ui'
import type { Column } from '../components/ui'
import { tenge, num } from '../lib/format'

type Cancels = { items: { name: string; amount: number }[]; total_amount: number; total_orders: number }
type Withdrawals = { withdrawals: { date: string; sum: number; comment: string }[]; total: number }

const CANCEL_COLUMNS: Column[] = [
  { key: 'name', label: 'Блюдо' },
  { key: 'amount', label: 'Списано', numeric: true },
]
const WD_COLUMNS: Column[] = [
  { key: 'comment', label: 'Основание' },
  { key: 'date', label: 'Дата' },
  { key: 'sum', label: 'Сумма', numeric: true },
]

export default function Anomalies({ period }: { period: Period }) {
  const c = useApi<Cancels>('cancels', { period })
  const w = useApi<Withdrawals>('withdrawals', { period })
  if (c.loading || w.loading) return <Loading />
  if (c.error || !c.data) return <ErrorBox msg={c.error || 'нет данных'} />
  if (w.error || !w.data) return <ErrorBox msg={w.error || 'нет данных'} />

  const items = [...c.data.items].sort((a, b) => b.amount - a.amount)
  const maxItem = Math.max(...items.map((i) => i.amount), 1)

  const cancelRows = items.map((it) => [
    it.name,
    <div className="flex items-center justify-end gap-3">
      <div className="w-20"><MiniBar value={it.amount} max={maxItem} tone="neg" /></div>
      <span className="text-neg">{tenge(it.amount)}</span>
    </div>,
  ])

  const wdRows = w.data.withdrawals.map((it) => [
    it.comment,
    <span className="text-ink2">{it.date}</span>,
    tenge(it.sum),
  ])

  return (
    <div>
      <Hero
        label="Отмены, возвраты и изъятия"
        value={tenge(c.data.total_amount + w.data.total)}
        note={
          `Отмен и возвратов на ${tenge(c.data.total_amount)} (${num(c.data.total_orders)} заказов), ` +
          `изъятий наличных на ${tenge(w.data.total)}. Каждая строка — деньги, которые ушли мимо кассы.`
        }
      />

      <MetricRow>
        <Metric label="Отмены/возвраты" value={tenge(c.data.total_amount)} />
        <Metric label="Кол-во отмен" value={num(c.data.total_orders)} />
        <Metric label="Изъятия наличных" value={tenge(w.data.total)} />
        <Metric label="Операций изъятия" value={num(w.data.withdrawals.length)} />
      </MetricRow>

      <Section title="Отмены и возвраты" hint="блюда с наибольшими списаниями">
        {items.length === 0 ? (
          <Empty msg="Отмен за период нет" />
        ) : (
          <DataTable columns={CANCEL_COLUMNS} rows={cancelRows} />
        )}
      </Section>

      <Section title="Изъятия наличных" hint="выемки из кассы">
        {w.data.withdrawals.length === 0 ? (
          <Empty msg="Изъятий за период нет" />
        ) : (
          <DataTable columns={WD_COLUMNS} rows={wdRows} />
        )}
      </Section>
    </div>
  )
}
