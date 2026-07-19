import { useApi } from '../lib/useApi'
import { Card, Loading, ErrorBox, SectionTitle, Delta } from '../components/ui'
import { num } from '../lib/format'
import { Star } from 'lucide-react'

type Platform = { platform: string; label: string; rating: number; scale: number; reviews_count: number | null; delta: number | null }
type Review = { rating: number; text: string; date: string; author: string }
type Rev = { platforms: Platform[]; reviews: Review[] }

export default function Reviews() {
  const { data, error, loading } = useApi<Rev>('reviews')
  if (loading) return <Loading />
  if (error || !data) return <ErrorBox msg={error || 'нет данных'} />

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {data.platforms.map((p, i) => (
          <Card key={i} className="fade-in">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-muted">{p.label}</span>
              {p.delta != null && <Delta value={p.delta} />}
            </div>
            <div className="mt-2 flex items-baseline gap-2">
              <span className="num text-4xl font-semibold text-accent">{p.rating}</span>
              <span className="text-sm text-faint">/ {p.scale}</span>
            </div>
            {p.reviews_count != null && (
              <div className="mt-1 text-xs text-faint">{num(p.reviews_count)} отзывов</div>
            )}
          </Card>
        ))}
      </div>

      <Card>
        <SectionTitle hint="голос гостя">Последние отзывы</SectionTitle>
        <div className="space-y-3">
          {data.reviews.map((r, i) => (
            <div key={i} className="rounded-xl border border-border/60 bg-panel2/50 p-3">
              <div className="mb-1 flex items-center gap-2">
                <div className="flex">
                  {Array.from({ length: 5 }).map((_, s) => (
                    <Star key={s} size={13} className={s < r.rating ? 'fill-accent text-accent' : 'text-border'} />
                  ))}
                </div>
                <span className="text-xs text-faint">{r.date} · {r.author}</span>
              </div>
              <div className="text-sm text-ink">{r.text}</div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  )
}
