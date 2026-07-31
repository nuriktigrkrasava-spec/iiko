import { useApi } from '../lib/useApi'
import { Glass, Chart, Delta, Orb, Insight } from './ui'
import { hbar, color } from './charts'
import { tenge, tengeShort, num } from '../lib/format'

/* ── Формы данных (подтверждены curl) ── */
type StockItem = { name: string; sku: string; balance: number; category: string; status: string }
type Stoplist = { items: StockItem[]; total: number; updated_at: string }
type WoCat = { name: string; written: number; purchases: number; pct: number; alert: boolean }
type Writeoffs = { total_written: number; purchases: number; loss_pct: number; categories: WoCat[] }
type Cancels = { items: { name: string; amount: number }[]; total_amount: number; total_orders: number }
type Withdrawals = { withdrawals: { date: string; sum: number; comment: string }[]; total: number }
type Invoices = { invoices: { id: string; status: string; supplier: string; date: string; items: number; amount: number }[] }

/* ── табличные стили (как в screens.tsx) ── */
const th: React.CSSProperties = { fontSize: 10, letterSpacing: '.1em', textTransform: 'uppercase', color: 'var(--mute)', fontWeight: 600, textAlign: 'left', padding: '0 0 10px', borderBottom: '1px solid var(--hair)' }
const td: React.CSSProperties = { padding: '11px 0', borderBottom: '1px solid var(--hair-2)', fontSize: 13 }
const tdR: React.CSSProperties = { ...td, textAlign: 'right', fontVariantNumeric: 'tabular-nums', letterSpacing: '-.01em' }
function Sub({ children }: { children: React.ReactNode }) { return <div style={{ fontSize: 10, color: 'var(--mute)', marginTop: 2 }}>{children}</div> }
function Eyebrow({ t, hint }: { t: string; hint?: string }) { return <div className="eyebrow"><span>{t}</span>{hint && <span className="hint">{hint}</span>}</div> }
function Note({ children }: { children: React.ReactNode }) { return <Glass span={12}><div style={{ padding: '10px 2px', fontSize: 13.5, color: 'var(--mute)' }}>{children}</div></Glass> }

/* мелкая иконка-искра для флагманского блока */
const Spark = () => <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2l2.9 6.3 6.9.7-5.1 4.7 1.4 6.8L12 17.8 5.9 20.5l1.4-6.8L2.2 9l6.9-.7z" /></svg>
const Arrow = () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12h13M12 6l6 6-6 6" /></svg>

const stTone = (s: string): 'green' | 'amber' | 'red' => (s === 'stop' ? 'red' : s === 'low' ? 'amber' : 'green')
const stLabel = (s: string) => (s === 'stop' ? 'стоп' : s === 'low' ? 'мало' : 'ок')

export default function Supply() {
  const stock = useApi<Stoplist>('stoplist', { period: 'month' })
  const wo = useApi<Writeoffs>('writeoffs', { period: 'month' })
  const cn = useApi<Cancels>('cancels', { period: 'month' })
  const wd = useApi<Withdrawals>('withdrawals', { period: 'month' })
  const inv = useApi<Invoices>('invoices', { period: 'month' })

  if (stock.loading || wo.loading || cn.loading || wd.loading || inv.loading) return <Note>Сводим склад и закупки…</Note>
  if (!stock.data || !wo.data || !cn.data || !wd.data) return <Note>Не удалось собрать данные склада: {stock.error || wo.error || cn.error || wd.error}</Note>

  const items = stock.data.items
  const outN = items.filter((i) => i.status === 'stop').length
  const lowN = items.filter((i) => i.status === 'low').length

  /* ⭐ авто-заявка: строки на дозаказ из позиций low/stop.
     Нет данных о расходе/сроке поставки → правило «довести до пар-уровня». */
  const need = items.filter((i) => i.status === 'stop' || i.status === 'low')
  const reorder = need.map((i) => {
    const par = i.status === 'stop' ? 12 : 8 // целевой остаток (пар-уровень), эвристика
    return { ...i, par, qty: Math.max(1, par - i.balance) }
  })
  /* стоп-позиции повторяются в отменах → упущенная выручка из-за стоп-листа */
  const stopNames = new Set(need.map((n) => n.name))
  const lost = cn.data.items.filter((c) => stopNames.has(c.name)).reduce((s, c) => s + c.amount, 0)

  /* списания по категориям → % от закупа, alert красным, худшая по сумме */
  const cats = [...wo.data.categories].sort((a, b) => b.pct - a.pct)
  const woBars = cats.map((c) => ({ l: c.name, v: c.pct, c: c.alert ? 'var(--red)' : color(0), sub: tengeShort(c.written) }))
  const worst = [...wo.data.categories].sort((a, b) => b.written - a.written)[0]

  /* отмены */
  const cnBars = cn.data.items.map((c, i) => ({ l: c.name, v: c.amount, c: color(i) }))

  /* закуп по поставщикам (из накладных) — реальная агрегация вместо price-drift */
  const invs = inv.data?.invoices ?? []
  const bySup: Record<string, number> = {}
  invs.forEach((v) => { bySup[v.supplier] = (bySup[v.supplier] || 0) + v.amount })
  const supRows = Object.entries(bySup).map(([l, v], i) => ({ l, v, c: color(i) })).sort((a, b) => b.v - a.v)
  const supTotal = supRows.reduce((s, r) => s + r.v, 0)

  return (
    <>
      {/* 1 · Герой — списания + доля + остатки */}
      <Glass span={5} spot>
        <Eyebrow t="Склад · закупки" hint={`обновлено ${stock.data.updated_at}`} />
        <div className="tnum" style={{ fontSize: 44, fontWeight: 680, letterSpacing: '-.035em', lineHeight: 1, marginTop: 16, display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
          {tengeShort(wo.data.total_written)} <Delta v={wo.data.loss_pct} invert />
        </div>
        <div style={{ marginTop: 9, fontSize: 12.5, color: 'var(--mute)' }}>списано за месяц · {wo.data.loss_pct.toFixed(1).replace('.', ',')}% от закупа {tengeShort(wo.data.purchases)}</div>
        <p style={{ marginTop: 14, fontSize: 13, lineHeight: 1.5, color: 'var(--lo)', maxWidth: '46ch' }}>
          Каждый шестой тенге закупа уходит в списание. {outN} позиции в стоп-листе — упущенная выручка.
        </p>
        <div style={{ display: 'flex', gap: 22, marginTop: 18, flexWrap: 'wrap' }}>
          <div><div className="tnum" style={{ fontSize: 22, fontWeight: 680 }}>{stock.data.total}</div><Sub>позиций на контроле</Sub></div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}><Orb tone="red" /><div><div className="tnum" style={{ fontSize: 22, fontWeight: 680, color: 'var(--red)' }}>{outN}</div><Sub>стоп (0 в остатке)</Sub></div></div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}><Orb tone="amber" /><div><div className="tnum" style={{ fontSize: 22, fontWeight: 680, color: 'var(--amb)' }}>{lowN}</div><Sub>заканчивается</Sub></div></div>
        </div>
      </Glass>

      {/* 2 · ⭐ ФЛАГМАН — авто-заявка на поставку */}
      <Glass span={7} spot warp>
        <div className="eyebrow">
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7 }}><span style={{ color: 'var(--acc)', display: 'inline-flex' }}><Spark /></span>Авто-заявка на поставку</span>
          <span className="hint">{reorder.length} позиций · до пар-уровня</span>
        </div>
        <p style={{ margin: '12px 0 0', fontSize: 12.5, lineHeight: 1.5, color: 'var(--lo)', maxWidth: '46ch' }}>
          Данных о расходе пока нет — дозаказ по правилу <span style={{ color: 'var(--hi)' }}>«довести до пар-уровня»</span> (целевого остатка).
        </p>
        <div style={{ marginTop: 14, border: '1px solid var(--hair)', borderRadius: 16, overflow: 'hidden', background: 'var(--glass-2)' }}>
          {reorder.map((r, i) => (
            <div key={r.sku} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '13px 15px', borderTop: i ? '1px solid var(--hair-2)' : 'none' }}>
              <Orb tone={stTone(r.status)} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13.5, fontWeight: 600, color: 'var(--hi)' }}>{r.name}</div>
                <Sub>{r.category} · остаток {num(r.balance)} → цель {r.par}</Sub>
              </div>
              <div style={{ fontSize: 10, letterSpacing: '.06em', textTransform: 'uppercase', fontWeight: 700, color: stTone(r.status) === 'red' ? 'var(--red)' : 'var(--amb)' }}>{stLabel(r.status)}</div>
              <div style={{ textAlign: 'right', minWidth: 78 }}>
                <div className="tnum" style={{ fontSize: 20, fontWeight: 700, letterSpacing: '-.02em', color: 'var(--acc)' }}>+{num(r.qty)}</div>
                <Sub>к заказу, ед.</Sub>
              </div>
            </div>
          ))}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 14, marginTop: 16, flexWrap: 'wrap' }}>
          <div style={{ fontSize: 12, color: 'var(--lo)' }}>
            Упущено на отменах стоп-блюд: <span className="tnum" style={{ color: '#ff8f6b', fontWeight: 700 }}>{tenge(lost)}</span>
          </div>
          <button
            onClick={(e) => e.preventDefault()}
            style={{ display: 'inline-flex', alignItems: 'center', gap: 8, fontSize: 13, fontWeight: 650, color: 'var(--on-acc,#fff)', border: 'none', borderRadius: 12, padding: '11px 18px', cursor: 'pointer', background: 'linear-gradient(135deg,var(--acc),var(--acc-2,#7b5cff))', boxShadow: '0 8px 22px -8px var(--acc-glow,rgba(79,110,247,.6))' }}>
            Сформировать заявку <Arrow />
          </button>
        </div>
      </Glass>

      {/* 3 · Стоп-лист / остатки */}
      <Glass span={7}>
        <Eyebrow t="Стоп-лист · остатки" hint="красный = 0 в остатке = упущенная выручка" />
        <table style={{ width: '100%', borderCollapse: 'collapse', marginTop: 10 }}>
          <thead><tr><th style={th}>Позиция</th><th style={th}>Категория</th><th style={{ ...th, textAlign: 'right' }}>Остаток</th><th style={{ ...th, textAlign: 'right' }}>Статус</th></tr></thead>
          <tbody>{items.map((it) => (
            <tr key={it.sku}>
              <td style={td}>{it.name}<Sub>{it.sku}</Sub></td>
              <td style={{ ...td, color: 'var(--lo)' }}>{it.category}</td>
              <td style={{ ...tdR, color: it.status === 'stop' ? 'var(--red)' : it.status === 'low' ? 'var(--amb)' : 'var(--hi)' }}>{num(it.balance)}</td>
              <td style={td}><div style={{ display: 'flex', alignItems: 'center', gap: 8, justifyContent: 'flex-end' }}><span style={{ fontSize: 12, color: 'var(--lo)' }}>{stLabel(it.status)}</span><Orb tone={stTone(it.status)} /></div></td>
            </tr>
          ))}</tbody>
        </table>
      </Glass>

      {/* 4 · Списания по категориям */}
      <Glass span={5}>
        <Eyebrow t="Списания по категориям" hint="% от закупа · красный — сигнал" />
        <Chart html={hbar(woBars, '%')} />
        {worst && <div style={{ marginTop: 8 }}>
          <Insight tag="списания" title={`${worst.name} — крупнейшая утечка`} money={tenge(worst.written)} tone="neg"
            detail={`${worst.pct.toFixed(1).replace('.', ',')}% от закупа (${tengeShort(worst.purchases)}). Проверить сроки, порции, заготовку — цель ниже 10%.`} />
        </div>}
      </Glass>

      {/* 5 · Отмены */}
      <Glass span={6}>
        <Eyebrow t="Отмены заказов" hint={`${cn.data.total_orders} отмен · ${tenge(cn.data.total_amount)}`} />
        <Chart html={hbar(cnBars, ' ₸')} />
      </Glass>

      {/* 6 · Изъятия из кассы */}
      <Glass span={6}>
        <Eyebrow t="Изъятия из кассы" hint={`итого ${tenge(wd.data.total)}`} />
        <div style={{ marginTop: 8 }}>
          {wd.data.withdrawals.map((w, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '13px 0', borderTop: i ? '1px solid var(--hair-2)' : 'none' }}>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 13.5, color: 'var(--hi)' }}>{w.comment}</div>
                <Sub>{w.date}</Sub>
              </div>
              <span className="tnum" style={{ fontSize: 15, fontWeight: 650 }}>{tenge(w.sum)}</span>
            </div>
          ))}
        </div>
      </Glass>

      {/* 7 · Закуп по поставщикам (из накладных) */}
      {supRows.length > 0 && (
        <Glass span={12}>
          <Eyebrow t="Закуп по поставщикам" hint={`${invs.length} накладных · ${tenge(supTotal)}`} />
          <Chart html={hbar(supRows, ' ₸')} />
        </Glass>
      )}
    </>
  )
}
