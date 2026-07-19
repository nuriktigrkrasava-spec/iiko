import { useApi } from '../lib/useApi'
import { Hero, Section, Loading, ErrorBox, Empty } from '../components/ui'

type Insight = {
  title: string; detail: string; money?: string
  severity: 'high' | 'medium' | 'good'; dimension?: string
}
type PlanItem = { action: string; effect: string; priority: number }
type Health = { key: string; value: string; status: 'green' | 'yellow' | 'red' }
type Data = {
  leakage_total: number; health: Health[]; headline?: string
  insights: Insight[]; plan: PlanItem[]; ai: boolean
}

const STATUS_DOT = { green: 'bg-pos', yellow: 'bg-warn', red: 'bg-neg' } as const
const SEV_COLOR = { high: 'text-neg', medium: 'text-warn', good: 'text-pos' } as const

// инсайт по измерению → куда провалиться за деталями
const DIM_SCREEN: Record<string, string> = {
  'Фудкост': 'fc', 'Выручка': 'dash', 'Смены': 'shifts',
  'Отзывы': 'rev', 'Расходы': 'exp', 'Аномалии': 'anom',
}

export default function Insights({ onOpen }: { onOpen?: (id: string) => void }) {
  const { data, error, loading } = useApi<Data>('insights')
  if (loading) return <Loading label="ИИ анализирует ваши данные…" />
  if (error || !data) return <ErrorBox msg={error || 'нет данных'} />

  return (
    <div>
      <Hero
        label={`ИИ-финдиректор${data.ai ? ' · Claude' : ''} — потери, которые можно вернуть`}
        value={`≈ ${tengeMln(data.leakage_total)}`}
        note={data.headline}
      />

      <Section title="Светофор здоровья" hint="открыл → понял, куда смотреть">
        <div className="flex flex-wrap gap-x-8 gap-y-3">
          {data.health.map((h, i) => (
            <div key={i} className="flex items-center gap-2">
              <span className={`h-2 w-2 rounded-full ${STATUS_DOT[h.status]}`} />
              <span className="text-[13px] text-ink2">{h.key}</span>
              <span className="tnum text-[13px] font-semibold text-ink">{h.value}</span>
            </div>
          ))}
        </div>
      </Section>

      <Section title="Что нашёл ИИ" hint="каждый привязан к деньгам">
        {data.insights.length === 0 ? (
          <Empty msg="ИИ не нашёл значимых расхождений" />
        ) : (
          <div>
            {data.insights.map((it, i) => {
              const target = it.dimension ? DIM_SCREEN[it.dimension] : undefined
              const clickable = !!(target && onOpen)
              return (
                <div
                  key={i}
                  onClick={clickable ? () => onOpen!(target!) : undefined}
                  className={`border-b border-rule py-4 last:border-b-0 ${clickable ? 'cursor-pointer transition-colors hover:bg-paper2' : ''}`}
                >
                  <div className="flex items-baseline justify-between gap-4">
                    <h3 className="text-[14px] font-semibold text-ink">
                      {it.dimension && <span className="eyebrow mr-2">{it.dimension}</span>}
                      {it.title}
                    </h3>
                    {it.money && (
                      <span className={`tnum shrink-0 text-[13px] font-semibold ${SEV_COLOR[it.severity]}`}>
                        {it.money}
                      </span>
                    )}
                  </div>
                  <p className="mt-1.5 text-[12.5px] leading-relaxed text-ink2">{it.detail}</p>
                  {clickable && <div className="mt-2 text-[11px] font-semibold text-neg">Открыть детали →</div>}
                </div>
              )
            })}
          </div>
        )}
      </Section>

      {data.plan.length > 0 && (
        <Section title="План роста" hint="конкретные действия с эффектом">
          <ol>
            {data.plan.map((p, i) => (
              <li key={i} className="flex gap-4 border-b border-rule py-4 last:border-b-0">
                <span className="font-display text-[22px] leading-none text-muted">{p.priority || i + 1}</span>
                <div className="flex-1">
                  <div className="text-[13px] text-ink">{p.action}</div>
                  <div className="mt-1 text-[12px] font-semibold text-pos">→ {p.effect}</div>
                </div>
              </li>
            ))}
          </ol>
        </Section>
      )}
    </div>
  )
}

/** Крупная сумма героя — компактно до миллионов с полным знаком тенге. */
function tengeMln(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1).replace('.', ',')} млн ₸`
  return `${new Intl.NumberFormat('ru-RU').format(Math.round(n))} ₸`
}
