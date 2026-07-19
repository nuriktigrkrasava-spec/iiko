import { useApi } from '../lib/useApi'
import { Grade, Section, DataTable, Loading, ErrorBox, Empty } from '../components/ui'
import type { Column } from '../components/ui'
import { num } from '../lib/format'

type Platform = {
  platform: string; label: string; rating: number; scale: number
  reviews_count: number | null; delta: number | null
}
type Review = { rating: number; text: string; date: string; author: string }
type Rev = { platforms: Platform[]; reviews: Review[] }

/** Рейтинг площадки → 0–100. 2ГИС на шкале 5, Wolt на шкале 10 — приводим к общему. */
const norm = (p: Platform) => (p.rating / p.scale) * 100

/** Сводная оценка соцсетей: среднее по площадкам, взвешенное по числу отзывов. */
function socialScore(platforms: Platform[]): number | null {
  const scored = platforms.filter((p) => p.rating != null && p.scale)
  if (scored.length === 0) return null
  const wsum = scored.reduce((a, p) => a + (p.reviews_count || 1), 0)
  const acc = scored.reduce((a, p) => a + norm(p) * (p.reviews_count || 1), 0)
  return Math.round(acc / wsum)
}

const COLUMNS: Column[] = [
  { key: 'label', label: 'Площадка' },
  { key: 'rating', label: 'Рейтинг', numeric: true },
  { key: 'norm', label: 'Из 100', numeric: true },
  { key: 'count', label: 'Отзывов', numeric: true },
  { key: 'delta', label: 'Δ нед.', numeric: true },
]

export default function Reviews() {
  const { data, error, loading } = useApi<Rev>('reviews')
  if (loading) return <Loading />
  if (error || !data) return <ErrorBox msg={error || 'нет данных'} />

  const score = socialScore(data.platforms)
  const rows = data.platforms.map((p) => [
    p.label,
    `${p.rating} / ${p.scale}`,
    String(Math.round(norm(p))),
    p.reviews_count != null ? num(p.reviews_count) : '—',
    p.delta != null
      ? <span className={p.delta >= 0 ? 'text-pos' : 'text-neg'}>{p.delta >= 0 ? '+' : ''}{p.delta}</span>
      : '—',
  ])

  return (
    <div>
      {score != null && (
        <div className="border-b border-rule py-2">
          <Grade score={score} label="Оценка соцсетей" />
          <p className="max-w-lg px-5 pb-4 text-[13px] leading-relaxed text-ink2">
            Сводный балл голоса гостя по {data.platforms.length}{' '}
            {plural(data.platforms.length, 'площадке', 'площадкам', 'площадкам')} —
            2ГИС и Wolt, взвешенно по числу отзывов. Приведён к 100-балльной шкале, чтобы разные площадки сравнивались напрямую.
          </p>
        </div>
      )}

      <Section title="Из чего сложилась оценка" hint="рейтинги площадок и динамика за неделю">
        {data.platforms.length === 0 ? (
          <Empty msg="Площадки ещё не подключены" />
        ) : (
          <DataTable columns={COLUMNS} rows={rows} />
        )}
      </Section>

      <Section title="Голос гостя" hint="свежие отзывы — доказательства за оценкой">
        {data.reviews.length === 0 ? (
          <Empty msg="Отзывов пока нет" />
        ) : (
          <div>
            {data.reviews.map((r, i) => (
              <div key={i} className="border-b border-rule py-4 last:border-b-0">
                <div className="mb-1.5 flex items-center gap-2">
                  <span className="tnum text-[13px] font-semibold text-ink">{stars(r.rating)}</span>
                  <span className="text-[11px] text-muted">{r.date} · {r.author}</span>
                </div>
                <div className="text-[13px] leading-relaxed text-ink">{r.text}</div>
              </div>
            ))}
          </div>
        )}
      </Section>
    </div>
  )
}

/** ★★★★☆ по рейтингу 0–5. */
function stars(rating: number): string {
  const full = Math.round(rating)
  return '★'.repeat(full) + '☆'.repeat(Math.max(0, 5 - full))
}

function plural(n: number, one: string, few: string, many: string): string {
  const m10 = n % 10
  const m100 = n % 100
  if (m10 === 1 && m100 !== 11) return one
  if (m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20)) return few
  return many
}
