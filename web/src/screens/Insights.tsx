import { useApi } from '../lib/useApi'
import { Card, Loading, ErrorBox, SectionTitle } from '../components/ui'
import { tenge } from '../lib/format'
import { Sparkles, TrendingUp, AlertTriangle, CheckCircle2, ArrowRight } from 'lucide-react'

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

const dot = { green: 'bg-pos', yellow: 'bg-accent', red: 'bg-neg' } as const
const sevBorder = { high: 'border-neg/40', medium: 'border-accent/40', good: 'border-pos/40' }
const sevBadge = { high: 'bg-neg/15 text-neg', medium: 'bg-accent/15 text-accent', good: 'bg-pos/15 text-pos' }
const sevIcon = { high: AlertTriangle, medium: TrendingUp, good: CheckCircle2 }

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
    <div className="space-y-6">
      {/* Hero — разоблачение потерь */}
      <Card className="fade-in border-neg/30 bg-gradient-to-br from-neg/10 to-transparent">
        <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-muted">
          <Sparkles size={14} className="text-accent" /> ИИ-финдиректор {data.ai ? '· Claude' : ''}
        </div>
        <div className="num mt-3 text-4xl font-bold text-ink sm:text-5xl">
          ≈ {tenge(data.leakage_total)}<span className="text-lg font-medium text-muted"> / мес</span>
        </div>
        <div className="mt-1 text-sm text-neg">оценка потерь, которые можно вернуть</div>
        {data.headline && (
          <div className="mt-4 max-w-2xl border-l-2 border-accent pl-3 text-[15px] leading-relaxed text-ink">
            {data.headline}
          </div>
        )}
      </Card>

      {/* Светофор здоровья */}
      <div>
        <SectionTitle hint="открыл → понял, куда смотреть">Светофор здоровья</SectionTitle>
        <div className="flex flex-wrap gap-2">
          {data.health.map((h, i) => (
            <div key={i} className="flex items-center gap-2 rounded-xl border border-border bg-panel/70 px-3.5 py-2">
              <span className={`h-2.5 w-2.5 rounded-full ${dot[h.status]}`} />
              <span className="text-sm text-muted">{h.key}</span>
              <span className="num text-sm font-medium text-ink">{h.value}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Инсайты с деньгами */}
      <div>
        <SectionTitle hint="каждый привязан к деньгам">Что нашёл ИИ</SectionTitle>
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {data.insights.map((it, i) => {
            const Icon = sevIcon[it.severity] || TrendingUp
            const target = it.dimension ? DIM_SCREEN[it.dimension] : undefined
            const clickable = !!(target && onOpen)
            return (
              <Card
                key={i}
                onClick={clickable ? () => onOpen!(target!) : undefined}
                className={`fade-in ${sevBorder[it.severity] || ''} ${clickable ? 'cursor-pointer transition-colors hover:border-primary/50 hover:bg-panel2/60' : ''}`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <Icon size={15} className={it.severity === 'good' ? 'text-pos' : it.severity === 'high' ? 'text-neg' : 'text-accent'} />
                    {it.dimension && <span className="text-[11px] uppercase tracking-wider text-faint">{it.dimension}</span>}
                  </div>
                  {it.money && (
                    <span className={`num rounded-md px-2 py-0.5 text-xs font-semibold ${sevBadge[it.severity] || sevBadge.medium}`}>
                      {it.money}
                    </span>
                  )}
                </div>
                <div className="mt-2 text-[15px] font-semibold text-ink">{it.title}</div>
                <div className="mt-1 text-sm leading-relaxed text-muted">{it.detail}</div>
                {clickable && (
                  <div className="mt-3 flex items-center gap-1 text-xs font-medium text-primary2">
                    Открыть детали <ArrowRight size={12} />
                  </div>
                )}
              </Card>
            )
          })}
        </div>
      </div>

      {/* План роста */}
      {data.plan.length > 0 && (
        <Card>
          <SectionTitle hint="конкретные действия с эффектом">План роста</SectionTitle>
          <div className="space-y-3">
            {data.plan.map((p, i) => (
              <div key={i} className="flex items-start gap-3">
                <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary/15 text-xs font-semibold text-primary2">
                  {p.priority || i + 1}
                </div>
                <div className="flex-1">
                  <div className="text-sm text-ink">{p.action}</div>
                  <div className="mt-0.5 flex items-center gap-1.5 text-xs text-pos">
                    <ArrowRight size={12} /> {p.effect}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  )
}
