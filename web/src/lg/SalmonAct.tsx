import { useEffect, useState } from 'react'
import { Glass } from './ui'
import { tenge } from '../lib/format'

/* «Акты и разборы» — рядом с горой, на тех же ссылках.

   Три позиции, больше ничего: П/Ф стейк (вход, цена из накладных), П/Ф обрезки
   (константа) и П/Ф нарезка (остаток веса и остаток денег). Оператор вводит
   два веса — сколько стейка разобрал и сколько вышло обрезков.

   Цену можно переписать руками — бывает разовый закуп по другой цене, и
   заставлять человека верить истории накладных в таком случае неправильно. */

type Prod = { id: string; name: string; unit?: string } | null
type Ctx = {
  error?: string
  role?: 'owner' | 'manager'
  branch?: { organization_id: string; name: string }
  branches?: { organization_id: string; name: string }[]
  products?: { raw: Prod; trim: Prod; slice: Prod }
  price_per_kg?: number
  price_from?: string
  trim_price?: number
}
type Line = { weight: number; price_per_kg: number; sum: number }
type Calc = {
  ok: boolean; error?: string
  raw?: Line; trim?: Line; slice?: Line; waste?: Line
  trim_pct?: number; check?: number
  sent?: boolean; number?: string; send_error?: string
}
type Store = { id: string; name: string }

const field: React.CSSProperties = {
  width: '100%', boxSizing: 'border-box', padding: '9px 11px', fontSize: 13.5,
  fontFamily: 'inherit', fontVariantNumeric: 'tabular-nums',
  background: 'var(--glass-2)', color: 'var(--hi)',
  border: '1px solid var(--hair)', borderRadius: 11,
}
const td: React.CSSProperties = { padding: '9px 0', borderBottom: '1px solid var(--hair-2)', fontSize: 13 }
const tdR: React.CSSProperties = { ...td, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }
const th: React.CSSProperties = {
  fontSize: 10, letterSpacing: '.1em', textTransform: 'uppercase', color: 'var(--mute)',
  fontWeight: 600, textAlign: 'left', padding: '0 0 9px', borderBottom: '1px solid var(--hair)',
}

function Eyebrow({ t, hint }: { t: string; hint?: string }) {
  return <div className="eyebrow"><span>{t}</span>{hint && <span className="hint">{hint}</span>}</div>
}

export default function SalmonAct({ token }: { token: string }) {
  const [ctx, setCtx] = useState<Ctx | null>(null)
  const [org, setOrg] = useState<string>('')
  const [raw, setRaw] = useState('')
  const [trim, setTrim] = useState('')
  const [waste, setWaste] = useState('')   // отход: кости и кожа, 0 ₸
  const [price, setPrice] = useState('')          // пусто = цена из накладных
  const [calc, setCalc] = useState<Calc | null>(null)
  const [stores, setStores] = useState<Store[]>([])
  const [store, setStore] = useState('')
  const [sending, setSending] = useState(false)
  const [sent, setSent] = useState<{ number?: string } | null>(null)

  useEffect(() => {
    fetch(`/api/acts/salmon/${token}${org ? `?org=${org}` : ''}`)
      .then((r) => r.json())
      .then((d: Ctx) => { setCtx(d); if (!org && d.branch) setOrg(d.branch.organization_id) })
      .catch((e) => setCtx({ error: String(e.message || e) }))
  }, [token, org])

  useEffect(() => {
    if (!org) return
    fetch(`/api/acts/salmon/${token}/stores?org=${org}`).then((r) => r.json())
      .then((d: { stores?: Store[]; suggest?: string }) => {
        setStores(d.stores || [])
        if (d.suggest) setStore(d.suggest)      // склад, где реально лежит вход
      }).catch(() => {})
  }, [token, org])

  // считаем на сервере: там же лежат тесты на эту арифметику
  useEffect(() => {
    const wr = Number(raw.replace(',', '.')) || 0
    const wt = Number(trim.replace(',', '.')) || 0
    if (!wr) { setCalc(null); return }
    const t = setTimeout(() => {
      fetch(`/api/acts/salmon/${token}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          org, weight_raw: wr, weight_trim: wt,
          weight_waste: Number(waste.replace(',', '.')) || 0,
          price_per_kg: price ? Number(price.replace(',', '.')) : null,
        }),
      }).then((r) => r.json()).then(setCalc).catch(() => setCalc(null))
    }, 250)
    return () => clearTimeout(t)
  }, [raw, trim, waste, price, org, token])

  async function send() {
    if (!calc?.ok) return
    // Запись в учёт — спрашиваем прямо, потом уже не отменить через API.
    const q = `Провести акт: ${calc.raw?.weight} кг → обрезки ${calc.trim?.weight}`
      + (calc.waste?.weight ? ` + отход ${calc.waste.weight}` : '')
      + ` + нарезка ${calc.slice?.weight}?`
    if (!window.confirm(q)) return
    setSending(true)
    try {
      const r = await fetch(`/api/acts/salmon/${token}/send`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          org, store_id: store || null,
          weight_raw: Number(raw.replace(',', '.')) || 0,
          weight_trim: Number(trim.replace(',', '.')) || 0,
          weight_waste: Number(waste.replace(',', '.')) || 0,
          price_per_kg: price ? Number(price.replace(',', '.')) : null,
        }),
      })
      const d: Calc = await r.json()
      if (d.sent) setSent({ number: d.number })
      else setCalc({ ...(calc as Calc), send_error: d.send_error || d.error || `HTTP ${r.status}` })
    } finally { setSending(false) }
  }

  if (!ctx) return <Glass span={12}><div style={{ padding: 12, fontSize: 13, color: 'var(--mute)' }}>Гружу справочник…</div></Glass>
  if (ctx.error) return <Glass span={12}><div style={{ padding: 12, fontSize: 13, color: 'var(--red)' }}>{ctx.error}</div></Glass>

  const p = ctx.products || { raw: null, trim: null, slice: null }
  const missing = !p.raw || !p.trim || !p.slice

  return (
    <Glass span={12}>
      <Eyebrow t="Акты и разборы · лосось"
        hint={`вход ${p.raw?.name || '—'} · обрезки по ${tenge(ctx.trim_price || 8800)}/кг`} />

      {missing && (
        <div style={{ marginTop: 10, fontSize: 12.5, color: 'var(--amb)' }}>
          В номенклатуре этого филиала нет одной из позиций разбора — акт не собрать.
        </div>
      )}

      <div style={{ marginTop: 12, display: 'grid', gap: 10, gridTemplateColumns: 'repeat(auto-fit,minmax(170px,1fr))' }}>
        {ctx.role === 'owner' && (
          <label style={{ fontSize: 11.5, color: 'var(--mute)' }}>Филиал
            <select value={org} onChange={(e) => { setOrg(e.target.value); setCalc(null) }} style={{ ...field, marginTop: 5 }}>
              {(ctx.branches || []).map((b) => (
                <option key={b.organization_id} value={b.organization_id}>{b.name}</option>
              ))}
            </select>
          </label>
        )}
        <label style={{ fontSize: 11.5, color: 'var(--mute)' }}>П/Ф стейк в разбор, кг
          <input value={raw} inputMode="decimal" placeholder="10"
            onChange={(e) => setRaw(e.target.value)} style={{ ...field, marginTop: 5 }} />
        </label>
        <label style={{ fontSize: 11.5, color: 'var(--mute)' }}>Обрезки, кг
          <input value={trim} inputMode="decimal" placeholder="2"
            onChange={(e) => setTrim(e.target.value)} style={{ ...field, marginTop: 5 }} />
        </label>
        <label style={{ fontSize: 11.5, color: 'var(--mute)' }}>Отход (кости, кожа), кг
          <input value={waste} inputMode="decimal" placeholder="0"
            onChange={(e) => setWaste(e.target.value)} style={{ ...field, marginTop: 5 }} />
        </label>
        <label style={{ fontSize: 11.5, color: 'var(--mute)' }}>Склад
          <select value={store} onChange={(e) => setStore(e.target.value)} style={{ ...field, marginTop: 5 }}>
            <option value="">по умолчанию</option>
            {stores.map((st) => <option key={st.id} value={st.id}>{st.name}</option>)}
          </select>
        </label>
        <label style={{ fontSize: 11.5, color: 'var(--mute)' }}>Цена стейка, ₸/кг
          <input value={price} inputMode="decimal"
            placeholder={ctx.price_per_kg ? String(ctx.price_per_kg) : 'нет в накладных'}
            onChange={(e) => setPrice(e.target.value)} style={{ ...field, marginTop: 5 }} />
        </label>
      </div>

      <div style={{ marginTop: 8, fontSize: 11.5, color: 'var(--mute)' }}>
        {ctx.price_per_kg
          ? <>Цена из накладных: <b style={{ color: 'var(--hi)' }}>{tenge(ctx.price_per_kg)}/кг</b>{ctx.price_from ? ` · ${ctx.price_from}` : ''}. Поле можно переписать.</>
          : <>В накладных этого филиала П/Ф стейка нет за 60 дней — впиши цену вручную.</>}
      </div>

      {calc && !calc.ok && (
        <div style={{ marginTop: 12, fontSize: 13, color: 'var(--red)' }}>{calc.error}</div>
      )}

      {calc?.ok && calc.raw && calc.trim && calc.slice && (
        <>
          <table style={{ width: '100%', borderCollapse: 'collapse', marginTop: 16 }}>
            <thead><tr>
              <th style={th}>Позиция</th>
              <th style={{ ...th, textAlign: 'right' }}>Вес, кг</th>
              <th style={{ ...th, textAlign: 'right' }}>₸ / кг</th>
              <th style={{ ...th, textAlign: 'right' }}>Сумма</th>
            </tr></thead>
            <tbody>
              <tr>
                <td style={td}>{p.raw?.name} <span style={{ color: 'var(--mute)', fontSize: 11 }}>· вход</span></td>
                <td style={tdR}>{calc.raw.weight}</td>
                <td style={tdR}>{tenge(calc.raw.price_per_kg)}</td>
                <td style={tdR}>{tenge(calc.raw.sum)}</td>
              </tr>
              <tr>
                <td style={{ ...td, color: 'var(--amb)' }}>{p.trim?.name} <span style={{ color: 'var(--mute)', fontSize: 11 }}>· константа</span></td>
                <td style={tdR}>{calc.trim.weight}</td>
                <td style={tdR}>{tenge(calc.trim.price_per_kg)}</td>
                <td style={tdR}>{tenge(calc.trim.sum)}</td>
              </tr>
              {!!calc.waste?.weight && (
                <tr>
                  <td style={{ ...td, color: 'var(--mute)' }}>Отход лосося <span style={{ fontSize: 11 }}>· по нулю</span></td>
                  <td style={tdR}>{calc.waste.weight}</td>
                  <td style={tdR}>0</td>
                  <td style={tdR}>0</td>
                </tr>
              )}
              <tr>
                <td style={{ ...td, color: 'var(--grn)', fontWeight: 650 }}>{p.slice?.name} <span style={{ color: 'var(--mute)', fontSize: 11, fontWeight: 400 }}>· остаток</span></td>
                <td style={tdR}><b>{calc.slice.weight}</b></td>
                <td style={tdR}><b>{tenge(calc.slice.price_per_kg)}</b></td>
                <td style={tdR}><b>{tenge(calc.slice.sum)}</b></td>
              </tr>
            </tbody>
          </table>

          <div style={{ marginTop: 10, display: 'flex', gap: 16, flexWrap: 'wrap', fontSize: 12.5, color: 'var(--mute)' }}>
            <span>В обрезки ушло <b style={{ color: 'var(--hi)' }}>{calc.trim_pct}%</b></span>
            <span>
              Сходимость:&nbsp;
              <b style={{ color: Math.abs((calc.check || 0) - calc.raw.sum) < 0.01 ? 'var(--grn)' : 'var(--red)' }}>
                {tenge(calc.check || 0)} из {tenge(calc.raw.sum)}
              </b>
            </span>
            <span style={{ marginLeft: 'auto' }}>
              себестоимость нарезки — <b style={{ color: 'var(--hi)' }}>{tenge(calc.slice.price_per_kg)}/кг</b>
            </span>
          </div>

          {calc.send_error && (
            <div style={{ marginTop: 12, fontSize: 12.5, color: 'var(--red)' }}>iiko не принял: {calc.send_error}</div>
          )}
          {sent ? (
            <div style={{ marginTop: 14, padding: '12px 14px', borderRadius: 13, border: '1px solid var(--hair)', background: 'var(--glass-2)' }}>
              <div style={{ fontSize: 13.5, fontWeight: 700, color: 'var(--grn)' }}>
                Акт создан в iiko{sent.number ? ` · №${sent.number}` : ''}
              </div>
              <div style={{ marginTop: 5, fontSize: 12.5, color: 'var(--mute)' }}>
                Это <b style={{ color: 'var(--hi)' }}>черновик</b>: остатки сдвинутся после проводки.
                Проведи в iikoOffice — «Склад → Акты приготовления». API этой версии
                iiko документ проводить не умеет: эндпоинта смены статуса нет, а
                прочитать акт обратно (чтобы переимпортировать проведённым) нельзя —
                экспорт по этому типу документа сервер не отдаёт.
              </div>
            </div>
          ) : (
            <button onClick={send} disabled={sending || missing}
              style={{ marginTop: 14, padding: '12px 20px', borderRadius: 14, border: 'none', background: 'linear-gradient(135deg,var(--acc),var(--acc-2))', color: 'var(--on-acc)', fontSize: 13.5, fontWeight: 700, cursor: sending ? 'default' : 'pointer', opacity: sending ? .6 : 1 }}>
              {sending ? 'Отправляю…' : 'Провести акт в iiko'}
            </button>
          )}
        </>
      )}
    </Glass>
  )
}
