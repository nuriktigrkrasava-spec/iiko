import { useApi } from '../lib/useApi'
import { useInstagram } from '../lib/social'
import { Glass, Chart, Delta, Orb, Insight, GBar, PlanFallback } from './ui'
import { donut, hbar, legend } from './charts'
import { num } from '../lib/format'
import { Brand, BrandChip, BRAND_COLOR, brandKey } from './brands'

/* ── Формы данных (живой /api/reviews) ── */
type Platform = {
  platform: string
  label: string
  rating: number
  scale: number
  reviews_count: number | null
  delta: number | null
  title?: string
}
type Review = { rating: number; text: string; date: string; author: string }
type Reviews = { platforms: Platform[]; reviews: Review[] }

/* Заглушка состояния — единый вид на всю сетку */
function Note({ children }: { children: React.ReactNode }) {
  return <Glass span={12}><div style={{ padding: '10px 2px', fontSize: 13.5, color: 'var(--mute)' }}>{children}</div></Glass>
}

/* ── Тональность ── */
type Tone = 'pos' | 'neu' | 'neg'
/* Отзыв не несёт площадку → выводим шкалу из значения (rating > 5 ⇒ 10-балльная) */
const revScale = (rating: number) => (rating > 5 ? 10 : 5)
const toneOf = (rating: number): Tone => {
  const f = rating / revScale(rating)
  return f >= 0.8 ? 'pos' : f >= 0.55 ? 'neu' : 'neg'
}
const orbTone = (t: Tone) => (t === 'pos' ? 'green' : t === 'neu' ? 'amber' : 'red')
const toneColor = (t: Tone) => (t === 'pos' ? 'var(--grn)' : t === 'neu' ? 'var(--amb)' : 'var(--red)')
const cut = (s: string, n = 140) => (s.length > n ? s.slice(0, n - 1).trimEnd() + '…' : s)
const ru1 = (n: number) => n.toFixed(1).replace('.', ',')

/* ── Темы: наивный тезаурус по тексту отзыва ── */
const THEMES: { l: string; keys: string[] }[] = [
  { l: 'Вкус / еда', keys: ['вкус', 'еда', 'блюд', 'порци', 'свеж', 'ролл', 'горяч', 'вкусно', 'невкус'] },
  { l: 'Скорость / ожидание', keys: ['быстр', 'долго', 'ждал', 'ожидан', 'медлен', 'опозда', 'вовремя', 'час'] },
  { l: 'Чистота', keys: ['чист', 'гряз', 'убор', 'пыл', 'туалет', 'липк'] },
  { l: 'Персонал / сервис', keys: ['официант', 'персонал', 'сервис', 'обслуж', 'хам', 'вежлив', 'приветлив', 'менеджер', 'груб'] },
  { l: 'Цена', keys: ['цена', 'дорог', 'дёшев', 'дешев', 'стоимост', 'ценник', 'переплат'] },
]

/* ── Соцсети: переход в «Подключить» + карточки платформ ── */
const goConnect = () => window.dispatchEvent(new CustomEvent('lg:go', { detail: 'connect' }))
const iconBox: React.CSSProperties = { width: 38, height: 38, borderRadius: '32%', flex: 'none', display: 'grid', placeItems: 'center', color: 'var(--mute)', background: 'var(--glass-2)', border: '1px solid var(--hair)' }
const btnStyle: React.CSSProperties = { marginLeft: 'auto', fontSize: 12, fontWeight: 600, color: 'var(--acc)', background: 'color-mix(in srgb,var(--acc) 12%,transparent)', border: '1px solid color-mix(in srgb,var(--acc) 26%,transparent)', borderRadius: 10, padding: '7px 12px', cursor: 'pointer' }

/* Threads/TikTok пока не подключаются кодом — статичная карточка с переходом */
function SocialStatic({ k, l }: { k: string; l: string }) {
  return (
    <Glass span={4}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 11 }}>
        <span style={iconBox}><Brand name={k} size={20} /></span>
        <div>
          <div style={{ fontSize: 13.5, fontWeight: 650, color: 'var(--lo)' }}>{l}</div>
          <div style={{ fontSize: 11, color: 'var(--mute)' }}>не подключён</div>
        </div>
        <button onClick={goConnect} style={btnStyle}>Подключить</button>
      </div>
    </Glass>
  )
}

/* Живой Instagram: OAuth через Meta. Показывает подписчиков и рост, когда подключён. */
function InstagramCard() {
  const { data: d, msg, connect } = useInstagram()
  const c = BRAND_COLOR[brandKey('instagram')]
  const on = !!d?.connected
  return (
    <Glass span={4}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 11 }}>
        <span style={{ ...iconBox, color: on ? c : 'var(--mute)' }}><Brand name="instagram" size={20} /></span>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 13.5, fontWeight: 650, color: 'var(--lo)' }}>Instagram</div>
          <div style={{ fontSize: 11, color: 'var(--mute)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {on ? (d?.username ? '@' + d.username : 'подключён') : 'не подключён'}
          </div>
        </div>
        {!on && <button onClick={connect} style={btnStyle}>Подключить</button>}
      </div>
      {on && (
        <>
          <div className="tnum" style={{ fontSize: 34, fontWeight: 700, letterSpacing: '-.03em', lineHeight: 1, marginTop: 14, color: c, display: 'flex', alignItems: 'baseline', gap: 8 }}>
            {d?.followers != null ? num(d.followers) : '—'}
            <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--mute)' }}>подписчиков</span>
          </div>
          <div style={{ marginTop: 8, display: 'flex', gap: 16, fontSize: 12, color: 'var(--mute)' }}>
            {d?.delta_30d != null && (
              <span style={{ color: d.delta_30d > 0 ? 'var(--grn)' : d.delta_30d < 0 ? 'var(--red)' : 'var(--mute)', fontWeight: 650 }}>
                {d.delta_30d > 0 ? '▲' : d.delta_30d < 0 ? '▼' : '•'} {num(Math.abs(d.delta_30d))} / 30 дней
              </span>
            )}
            {d?.media_count != null && <span>{num(d.media_count)} постов</span>}
          </div>
          {d?.stale && <div style={{ marginTop: 8, fontSize: 11, color: 'var(--amb)' }}>Данные не обновились — проверь доступ.</div>}
        </>
      )}
      {msg && <div style={{ marginTop: 10, fontSize: 11.5, lineHeight: 1.45, color: 'var(--amb)' }}>{msg}</div>}
    </Glass>
  )
}

export default function Reputation() {
  const { data, error, loading } = useApi<Reviews>('reviews', { period: 'month' })
  if (loading) return <Note>Собираем отзывы со всех площадок…</Note>
  if (error || !data) return <Note>Не удалось загрузить отзывы: {error}</Note>

  const platforms = data.platforms ?? []
  const reviews = data.reviews ?? []

  // Площадок нет → рейтинг/отзывы взять неоткуда: ставим планом, а не 0.0/5 и пустую ленту.
  if (platforms.length === 0) return (
    <>
      <Glass span={12} spot>
        <PlanFallback
          title="Оценка соцсетей появится после подключения площадок"
          reason="Мы не нашли точки бренда на площадках отзывов (2ГИС, Wolt) — рейтинг и отзывы брать неоткуда."
          action="Укажи точное название бренда в разделе «Подключить» — найдём точки на 2ГИС и Wolt автоматически." />
      </Glass>
      <InstagramCard />
      <SocialStatic k="threads" l="Threads" />
      <SocialStatic k="tiktok" l="TikTok" />
    </>
  )

  /* Средний рейтинг: взвешен по числу отзывов, нормирован к 5 */
  let wSum = 0, rSum = 0, normSum = 0
  platforms.forEach((p) => {
    const norm = (p.rating / p.scale) * 5
    normSum += norm
    const w = p.reviews_count ?? 0
    wSum += w
    rSum += norm * w
  })
  const avg5 = wSum > 0 ? rSum / wSum : platforms.length ? normSum / platforms.length : 0
  const totalReviews = platforms.reduce((s, p) => s + (p.reviews_count ?? 0), 0)
  const deltas = platforms.map((p) => p.delta).filter((d): d is number => d != null)
  const netTrend = deltas.length ? deltas.reduce((s, d) => s + d, 0) / deltas.length : 0
  const trendC = netTrend > 0 ? 'var(--grn)' : netTrend < 0 ? 'var(--red)' : 'var(--mute)'

  /* Тональность отзывов */
  const rated = reviews.map((r) => ({ ...r, t: toneOf(r.rating), f: r.rating / revScale(r.rating) }))
  const pos = rated.filter((r) => r.t === 'pos').length
  const neu = rated.filter((r) => r.t === 'neu').length
  const neg = rated.filter((r) => r.t === 'neg').length
  const tot = rated.length || 1
  const dpct = (n: number) => Math.round((n / tot) * 100)
  const sentiment = [
    { l: 'Позитив', v: pos, c: 'var(--grn)' },
    { l: 'Нейтрал', v: neu, c: 'var(--amb)' },
    { l: 'Негатив', v: neg, c: 'var(--red)' },
  ]

  /* Лента: худшее — вперёд */
  const feed = [...rated].sort((a, b) => a.f - b.f)

  /* Темы: позитив/негатив упоминаний */
  const themes = THEMES.map((th) => {
    let p = 0, n = 0, all = 0
    rated.forEach((r) => {
      const txt = r.text.toLowerCase()
      if (th.keys.some((k) => txt.includes(k))) {
        all++
        if (r.t === 'pos') p++
        else if (r.t === 'neg') n++
      }
    })
    return { l: th.l, pos: p, neg: n, all }
  }).filter((t) => t.all > 0)

  const worst = [...themes].sort((a, b) => (b.neg - a.neg) || (b.all - a.all))[0]
  const themeBars = themes.map((t) => ({ l: t.l, v: t.all, c: t.neg > t.pos ? 'var(--red)' : t.pos > t.neg ? 'var(--grn)' : 'var(--amb)', sub: `+${t.pos} / −${t.neg}` }))

  return (
    <>
      {/* Row 1 · Герой (6) + две реальные площадки (3+3) = 12 */}
      <Glass span={6} spot>
        <div className="eyebrow"><span>Соцсети · репутация</span><span className="hint">{platforms.length} площадок · за месяц</span></div>
        <div className="tnum" style={{ fontSize: 60, fontWeight: 720, letterSpacing: '-.04em', lineHeight: 1, marginTop: 16, display: 'flex', alignItems: 'baseline', gap: 10 }}>
          {ru1(avg5)}
          <span style={{ fontSize: 22, fontWeight: 600, color: 'var(--mute)' }}>/ 5</span>
        </div>
        <div style={{ marginTop: 12, display: 'flex', gap: 22, flexWrap: 'wrap', alignItems: 'baseline' }}>
          <div>
            <span className="tnum" style={{ fontSize: 20, fontWeight: 660 }}>{num(totalReviews)}</span>
            <span style={{ fontSize: 12, color: 'var(--mute)', marginLeft: 6 }}>отзывов</span>
          </div>
          <div>
            <span className="tnum" style={{ fontSize: 20, fontWeight: 660, color: trendC }}>
              {netTrend > 0 ? '▲' : netTrend < 0 ? '▼' : '•'} {ru1(Math.abs(netTrend))}
            </span>
            <span style={{ fontSize: 12, color: 'var(--mute)', marginLeft: 6 }}>тренд</span>
          </div>
        </div>
        <p style={{ marginTop: 16, fontSize: 13, lineHeight: 1.5, color: 'var(--lo)', maxWidth: '46ch' }}>
          Средний балл, взвешенный по числу отзывов, — по шкале 5.
        </p>
      </Glass>

      {/* Реальные площадки — бренд-иконка + фирменный акцент */}
      {platforms.map((p) => {
        const c = BRAND_COLOR[brandKey(p.platform)]
        const frac = Math.max(0, Math.min(1, p.rating / p.scale))
        return (
          <Glass key={p.platform} span={3} tap>
            <div style={{ display: 'flex', alignItems: 'center', gap: 11 }}>
              <BrandChip name={p.platform} />
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 13.5, fontWeight: 650, color: 'var(--hi)' }}>{p.label}</div>
                <div style={{ fontSize: 11, color: 'var(--mute)' }}>{p.reviews_count != null ? `${num(p.reviews_count)} отзывов` : 'без счётчика'}</div>
              </div>
              <span style={{ marginLeft: 'auto' }}><Delta v={p.delta} size={12} /></span>
            </div>
            <div className="tnum" style={{ fontSize: 34, fontWeight: 700, letterSpacing: '-.03em', lineHeight: 1, marginTop: 14, color: c, display: 'flex', alignItems: 'baseline', gap: 4 }}>
              {ru1(p.rating)}<span style={{ fontSize: 15, fontWeight: 600, color: 'var(--mute)' }}>/{p.scale}</span>
            </div>
            <div style={{ marginTop: 12 }}>
              <GBar pct={frac * 100} color={c} h={7} />
            </div>
          </Glass>
        )
      })}

      {/* Row 2 · Лента (7) + тональность (5) = 12 */}
      <Glass span={7}>
        <div className="eyebrow"><span>Лента отзывов</span><span className="hint">худшее — вперёд</span></div>
        <div style={{ marginTop: 6 }}>
          {feed.length === 0 && <div style={{ padding: '14px 0', fontSize: 13, color: 'var(--mute)' }}>Отзывов за период нет.</div>}
          {feed.map((r, i) => (
            <div key={i} style={{ display: 'flex', gap: 12, padding: '13px 0', borderTop: i ? '1px solid var(--hair-2)' : 'none' }}>
              <div style={{ paddingTop: 3 }}><Orb tone={orbTone(r.t)} /></div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
                  <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--hi)' }}>{r.author || 'Гость'}</span>
                  <span className="tnum" style={{ fontSize: 12, fontWeight: 650, color: toneColor(r.t) }}>{ru1(r.rating)}/{revScale(r.rating)}</span>
                  <span className="tnum" style={{ fontSize: 11.5, color: 'var(--mute)', marginLeft: 'auto' }}>{r.date}</span>
                </div>
                <p style={{ margin: '5px 0 0', fontSize: 12.5, lineHeight: 1.5, color: 'var(--lo)', maxWidth: '62ch' }}>{cut(r.text, 120)}</p>
              </div>
            </div>
          ))}
        </div>
      </Glass>

      {/* Тональность — донат */}
      <Glass span={5}>
        <div className="eyebrow"><span>Тональность</span><span className="hint">{num(rated.length)} за период</span></div>
        <Chart html={donut(sentiment, { label: String(rated.length), sub: 'отзывов' })} />
        <div dangerouslySetInnerHTML={{
          __html: legend([
            { l: 'Позитив', v: `${pos} · ${dpct(pos)}%`, c: 'var(--grn)' },
            { l: 'Нейтрал', v: `${neu} · ${dpct(neu)}%`, c: 'var(--amb)' },
            { l: 'Негатив', v: `${neg} · ${dpct(neg)}%`, c: 'var(--red)' },
          ]),
        }} />
        <div style={{ marginTop: 12, fontSize: 12, color: 'var(--mute)' }}>
          Позитив ≥ 80% · нейтрал 55–80% · негатив &lt; 55%.
        </div>
      </Glass>

      {/* Row 3 · Темы отзывов + действие (12) */}
      <Glass span={12}>
        <div className="eyebrow"><span>Темы отзывов</span><span className="hint">упоминаний · плюс против минуса</span></div>
        {themes.length === 0
          ? <div style={{ padding: '14px 0', fontSize: 13, color: 'var(--mute)' }}>Темы пока не распознаны.</div>
          : <Chart html={hbar(themeBars)} />}
        {worst && worst.neg > 0 && (
          <div style={{ marginTop: 14 }}>
            <Insight
              tag="Действие"
              title={`«${worst.l}» — главный источник негатива`}
              money={`${worst.neg} жалоб`}
              tone="neg"
              detail={`${worst.neg} из ${worst.all} упоминаний темы «${worst.l}» — негативные. Разберите свежие жалобы из ленты и закройте общий сбой.`}
            />
          </div>
        )}
      </Glass>

      {/* Row 4 · Соцсети: Instagram (живой OAuth) + Threads/TikTok (4+4+4 = 12) */}
      <InstagramCard />
      <SocialStatic k="threads" l="Threads" />
      <SocialStatic k="tiktok" l="TikTok" />
    </>
  )
}
