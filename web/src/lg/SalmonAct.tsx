import { useEffect, useState } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { Glass } from './ui'
import { tenge } from '../lib/format'
import { Button, Eyebrow, GLYPH, Segmented, Tile, field, kg, pc, photosOf, td, tdR, th, wasteTone } from './salmonKit'
import SalmonPeriod from './SalmonPeriod'
import SalmonNetwork from './SalmonNetwork'

/* «Акты и разборы» — рядом с горой, на тех же ссылках.

   Разбор один и тот же на две рыбы: лосось и угорь. Взвешивают то, что держат
   в руках: вход, нарезку и обрезки на выходе. Отход (кости и кожа) не
   взвешивают — он остаток веса, и его процент и есть оценка разбора.

   У лосося есть терияки. Это те же обрезки, снятые со сковороды, поэтому
   вводят ДВА веса: сколько обрезков положили жарить и сколько сняли. Разница —
   ужарка: вес ушёл, деньги остались, и килограмм терияки ровно на неё дороже
   килограмма обрезков. Рядом третье поле — ГРАММЫ соуса: соус приходит своей
   накладной, его цену мы берём из iiko, и он единственный в этом экране, кто
   деньги добавляет, а не переносит. Сумма акта от него не двигается.

   В iiko поштучно ничего не уходит: каждый разбор фиксируется у нас, а за
   период администратор заносит ОДИН сводный акт руками. Два документа на один
   и тот же вес задвоили бы списание.

   Цены — вход, соус, а у угря и обрезки — тянутся из накладных: вбитая с
   потолка цифра превращает себестоимость в фантазию. Поля рядом всё равно
   есть: бывает разовый закуп по другой цене, и заставлять человека верить
   истории накладных в таком случае неправильно. */

type Prod = { id: string; name: string; unit?: string } | null
type Ctx = {
  error?: string
  role?: 'owner' | 'manager'
  branch?: { organization_id: string; name: string }
  branches?: { organization_id: string; name: string }[]
  products?: { raw: Prod; trim: Prod; slice: Prod; waste: Prod; teriyaki?: Prod; sauce?: Prod }
  price_per_kg?: number
  price_from?: string
  trim_price?: number
  trim_from?: string
  trim_const?: boolean        // обрезки по константе учёта, а не из накладных
  sauce_price?: number
  sauce_from?: string
  kind?: string
  title?: string
  raw_label?: string
  raw_short?: string
  teriyaki?: boolean
  kinds?: { key: string; title: string; tab: string }[]
}
type Line = { weight: number; price_per_kg: number; sum: number; from_trim?: number; shrink?: number }
type Sauce = { grams: number; weight: number; price_per_kg: number; sum: number }
type Calc = {
  ok: boolean; error?: string
  raw?: Line; slice?: Line; trim?: Line; waste?: Line; teriyaki?: Line; sauce?: Sauce
  slice_pct?: number; trim_pct?: number; waste_pct?: number
  teriyaki_pct?: number; fry_pct?: number; teriyaki_yield_pct?: number
  sauce_g_per_kg?: number; check?: number
  saved?: boolean; id?: number
}

const KINDS = [{ k: 'salmon', t: 'Лосось' }, { k: 'eel', t: 'Угорь' }]
const num = (s: string) => Number(s.replace(',', '.')) || 0

export default function SalmonAct({ token }: { token: string }) {
  const [kind, setKind] = useState('salmon')
  const [ctx, setCtx] = useState<Ctx | null>(null)
  const [org, setOrg] = useState<string>('')
  const [raw, setRaw] = useState('')
  const [slice, setSlice] = useState('')
  const [trim, setTrim] = useState('')
  const [fry, setFry] = useState('')          // обрезков положили на сковороду
  const [ter, setTer] = useState('')          // терияки сняли со сковороды
  const [sauce, setSauce] = useState('')      // соуса налили, ГРАММЫ
  const [price, setPrice] = useState('')          // пусто = цена из накладных
  const [trimPrice, setTrimPrice] = useState('')  // пусто = константа или накладная
  const [saucePrice, setSaucePrice] = useState('')  // пусто = цена соуса из накладных
  const [calc, setCalc] = useState<Calc | null>(null)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState<Calc | null>(null)
  const [reload, setReload] = useState(0)         // счётчик: обновить свод и сеть
  const still = useReducedMotion()

  useEffect(() => {
    setCtx(null)
    fetch(`/api/acts/${kind}/${token}${org ? `?org=${org}` : ''}`)
      .then((r) => r.json())
      .then((d: Ctx) => { setCtx(d); if (!org && d.branch) setOrg(d.branch.organization_id) })
      .catch((e) => setCtx({ error: String(e.message || e) }))
  }, [token, org, kind])

  /** Рыбу сменили — веса чужие: у угря другой вход и другая цена обрезков. */
  function pickKind(k: string) {
    if (k === kind) return
    setKind(k)
    setRaw(''); setSlice(''); setTrim(''); setFry(''); setTer(''); setSauce('')
    setPrice(''); setTrimPrice(''); setSaucePrice(''); setCalc(null); setSaved(null)
  }

  // считаем на сервере: там же лежат тесты на эту арифметику
  useEffect(() => {
    const wr = num(raw)
    if (!wr) { setCalc(null); return }
    const t = setTimeout(() => {
      fetch(`/api/acts/${kind}/${token}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          org, weight_raw: wr, weight_slice: num(slice),
          weight_trim: num(trim),
          weight_fry: num(fry), weight_teriyaki: num(ter), weight_sauce: num(sauce),
          price_per_kg: price ? num(price) : null,
          trim_price: trimPrice ? num(trimPrice) : null,
          sauce_price: saucePrice ? num(saucePrice) : null,
        }),
      }).then((r) => r.json()).then(setCalc).catch(() => setCalc(null))
    }, 250)
    return () => clearTimeout(t)
  }, [raw, slice, trim, fry, ter, sauce, price, trimPrice, saucePrice, org, token, kind])

  async function save() {
    if (!calc?.ok) return
    setSaving(true)
    try {
      const r = await fetch(`/api/acts/${kind}/${token}/save`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          org,
          weight_raw: num(raw), weight_slice: num(slice), weight_trim: num(trim),
          weight_fry: num(fry), weight_teriyaki: num(ter), weight_sauce: num(sauce),
          price_per_kg: price ? num(price) : null,
          trim_price: trimPrice ? num(trimPrice) : null,
          sauce_price: saucePrice ? num(saucePrice) : null,
        }),
      })
      const d: Calc = await r.json()
      if (d.saved) {
        setSaved(d)
        setRaw(''); setSlice(''); setTrim(''); setFry(''); setTer(''); setSauce(''); setCalc(null)
        setReload((n) => n + 1)
        setTimeout(() => setSaved(null), 6000)
      } else {
        setCalc({ ...(calc as Calc), error: d.error || `HTTP ${r.status}`, ok: false })
      }
    } finally { setSaving(false) }
  }

  const kinds = (ctx?.kinds || []).map((k) => ({ k: k.key, t: k.tab }))
  const tabs = kinds.length ? kinds : KINDS
  const switcher = (
    <div style={{ marginTop: 12 }}>
      <Segmented id="acts-kind" value={kind} onChange={pickKind} options={tabs} />
    </div>
  )

  if (!ctx || ctx.error) return (
    <Glass span={12}>
      <Eyebrow t="Акты и разборы" />
      {switcher}
      <div style={{ padding: '12px 0 2px', fontSize: 13, color: ctx?.error ? 'var(--red)' : 'var(--mute)' }}>
        {ctx?.error || 'Гружу справочник…'}
      </div>
    </Glass>
  )

  const p = ctx.products || { raw: null, trim: null, slice: null, waste: null, teriyaki: null, sauce: null }
  const missing = !p.raw || !p.trim || !p.slice
  const w = calc?.ok ? calc : null
  const ph = photosOf(kind)
  const short = ctx.raw_short || 'стейк'
  const hasTer = ctx.teriyaki !== false
  // цену спрашиваем только там, где её не нашли: у угря обрезки без константы
  // учёта, а соус в филиал мог не приходить 60 дней
  const askTrimPrice = !ctx.trim_price
  const shownTrim = Number(trimPrice ? num(trimPrice) : ctx.trim_price || 0)
  const shownSauce = Number(saucePrice ? num(saucePrice) : ctx.sauce_price || 0)

  return (
    <>
      <Glass span={12}>
        <Eyebrow t={ctx.title || 'Разбор лосося'}
          hint={`вход ${p.raw?.name || '—'}${shownTrim ? ` · обрезки по ${tenge(shownTrim)}/кг` : ''}`} />
        {switcher}

        {missing && (
          <div style={{ marginTop: 10, fontSize: 12.5, color: 'var(--amb)' }}>
            В номенклатуре этого филиала нет одной из позиций разбора — акт не собрать.
          </div>
        )}

        {/* Вход и выходы. Отход не вводят: он остаток веса. */}
        <div style={{ marginTop: 14, display: 'grid', gap: 10, gridTemplateColumns: 'repeat(auto-fit,minmax(158px,1fr))' }}>
          <Tile photo={ph.raw} glyph={GLYPH.raw} label={ctx.raw_label || 'Стейк в разбор'} hint="вход"
            value={raw} onChange={setRaw} placeholder="10"
            foot={ctx.price_per_kg ? `${tenge(ctx.price_per_kg)}/кг` : 'цена не найдена'} />
          <Tile photo={ph.slice} glyph={GLYPH.slice} label="Нарезка" hint="выход" value={slice}
            onChange={setSlice} placeholder="8"
            foot={w ? `${pc(w.slice_pct)} · ${tenge(w.slice!.price_per_kg)}/кг` : undefined} />
          <Tile photo={ph.trim} glyph={GLYPH.trim} label="Обрезки"
            hint={shownTrim ? `по ${tenge(shownTrim)}` : 'цену ниже'}
            value={trim} onChange={setTrim} placeholder="2"
            foot={w ? `${pc(w.trim_pct)} веса${num(fry) ? ' · без жарки' : ''}` : undefined} />
          {hasTer && (
            /* Терияки — те же обрезки, обжаренные с соусом. Два веса, потому что
               между ними и живёт ужарка: положили 2 кг, сняли 1.4. Третье поле —
               соус: он не вес рыбы, а деньги со стороны, и меряется граммами. */
            <>
              <Tile photo={ph.trim} glyph={GLYPH.trim} label="В жарку" hint="из обрезков"
                value={fry} onChange={setFry} placeholder="0"
                foot={w && (w.fry_pct || 0) > 0 ? `${pc(w.fry_pct)} веса` : 'обрезков на сковороду'} />
              <Tile photo={ph.teriyaki} glyph={GLYPH.teriyaki} label="Терияки" hint="со сковороды"
                value={ter} onChange={setTer} placeholder="0"
                foot={w && w.teriyaki && w.teriyaki.weight > 0
                  ? `ужарка ${kg(w.teriyaki.shrink)} кг · ${tenge(w.teriyaki.price_per_kg)}/кг`
                  : 'сколько сняли'} />
              <Tile glyph={GLYPH.sauce} label="Соус терияки" unit="г"
                hint={shownSauce ? `по ${tenge(shownSauce)}/кг` : 'цену ниже'}
                value={sauce} onChange={setSauce} placeholder="0"
                foot={w && w.sauce && w.sauce.grams > 0
                  ? `${kg(w.sauce_g_per_kg)} г на кг · ${tenge(w.sauce.sum)}`
                  : 'сколько налили'} />
            </>
          )}
          <Tile photo={ph.waste} glyph={GLYPH.waste} label="Отход" hint="кости, кожа" readOnly
            value={w ? kg(w.waste!.weight) : ''}
            tone={w ? wasteTone(w.waste_pct || 0) : undefined}
            foot={w
              ? <b style={{ color: wasteTone(w.waste_pct || 0) }}>{pc(w.waste_pct)} отхода</b>
              : `${short} − нарезка − обрезки`} />
        </div>

        <div style={{ marginTop: 12, display: 'grid', gap: 10, gridTemplateColumns: 'repeat(auto-fit,minmax(190px,1fr))' }}>
          {ctx.role === 'owner' && (
            <label style={{ fontSize: 11.5, color: 'var(--mute)' }}>Филиал
              <select value={org} onChange={(e) => { setOrg(e.target.value); setCalc(null) }} style={{ ...field, marginTop: 5 }}>
                {(ctx.branches || []).map((b) => (
                  <option key={b.organization_id} value={b.organization_id}>{b.name}</option>
                ))}
              </select>
            </label>
          )}
          <label style={{ fontSize: 11.5, color: 'var(--mute)' }}>Цена входа, ₸/кг
            <input value={price} inputMode="decimal"
              placeholder={ctx.price_per_kg ? String(ctx.price_per_kg) : 'нет в накладных'}
              onChange={(e) => setPrice(e.target.value)} style={{ ...field, marginTop: 5 }} />
          </label>
          {askTrimPrice && (
            <label style={{ fontSize: 11.5, color: 'var(--mute)' }}>Обрезки, ₸/кг
              <input value={trimPrice} inputMode="decimal" placeholder="почём считать"
                onChange={(e) => setTrimPrice(e.target.value)} style={{ ...field, marginTop: 5 }} />
            </label>
          )}
          {hasTer && (
            <label style={{ fontSize: 11.5, color: 'var(--mute)' }}>Соус терияки, ₸/кг
              <input value={saucePrice} inputMode="decimal"
                placeholder={ctx.sauce_price ? String(ctx.sauce_price) : 'нет в накладных'}
                onChange={(e) => setSaucePrice(e.target.value)} style={{ ...field, marginTop: 5 }} />
            </label>
          )}
        </div>

        <div style={{ marginTop: 8, fontSize: 11.5, color: 'var(--mute)' }}>
          {ctx.price_per_kg
            ? <>Цена из накладных: <b style={{ color: 'var(--hi)' }}>{tenge(ctx.price_per_kg)}/кг</b>{ctx.price_from ? ` · ${ctx.price_from}` : ''}. Поле можно переписать.</>
            : <>В накладных этого филиала входа нет за 60 дней — впиши цену вручную.</>}
          {askTrimPrice && <> Обрезков этой рыбы в накладных за 60 дней нет, а константы учёта у неё ещё не назначили — цену вводят здесь.</>}
          {!askTrimPrice && !ctx.trim_const && ctx.trim_from
            && <> Обрезки — <b style={{ color: 'var(--hi)' }}>{tenge(ctx.trim_price || 0)}/кг</b> из накладных · {ctx.trim_from}.</>}
          {hasTer && (ctx.sauce_price
            ? <> Соус — <b style={{ color: 'var(--hi)' }}>{tenge(ctx.sauce_price)}/кг</b> из накладных{ctx.sauce_from ? ` · ${ctx.sauce_from}` : ''}; в акт он добавляет деньги со стороны и сумму разбора не двигает.</>
            : <> Соуса терияки в накладных за 60 дней нет — если его лили, впиши цену, иначе граммы не во что пересчитать.</>)}
        </div>

        {calc && !calc.ok && (
          <div style={{ marginTop: 12, fontSize: 13, color: 'var(--red)' }}>{calc.error}</div>
        )}

        {w && (
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
                  <td style={tdR}>{kg(w.raw!.weight)}</td>
                  <td style={tdR}>{tenge(w.raw!.price_per_kg)}</td>
                  <td style={tdR}>{tenge(w.raw!.sum)}</td>
                </tr>
                <tr>
                  <td style={{ ...td, color: 'var(--grn)', fontWeight: 650 }}>{p.slice?.name} <span style={{ color: 'var(--mute)', fontSize: 11, fontWeight: 400 }}>· остаток стоимости</span></td>
                  <td style={tdR}><b>{kg(w.slice!.weight)}</b></td>
                  <td style={tdR}><b>{tenge(w.slice!.price_per_kg)}</b></td>
                  <td style={tdR}><b>{tenge(w.slice!.sum)}</b></td>
                </tr>
                <tr>
                  <td style={td}>{p.trim?.name}</td>
                  <td style={tdR}>{kg(w.trim!.weight)}</td>
                  <td style={tdR}>{tenge(w.trim!.price_per_kg)}</td>
                  <td style={tdR}>{tenge(w.trim!.sum)}</td>
                </tr>
                {w.teriyaki && w.teriyaki.weight > 0 && (
                  <tr>
                    <td style={{ ...td, color: 'var(--amb)' }}>{p.teriyaki?.name || 'П/Ф Лосось терияки'}{' '}
                      <span style={{ color: 'var(--mute)', fontSize: 11 }}>
                        · из {kg(w.teriyaki.from_trim)} кг обрезков, ужарка {kg(w.teriyaki.shrink)}
                        {w.sauce && w.sauce.grams > 0 ? `, соуса ${kg(w.sauce.grams)} г` : ''}
                      </span>
                    </td>
                    <td style={tdR}>{kg(w.teriyaki.weight)}</td>
                    <td style={tdR}>{tenge(w.teriyaki.price_per_kg)}</td>
                    <td style={tdR}>{tenge(w.teriyaki.sum)}</td>
                  </tr>
                )}
                {w.sauce && w.sauce.grams > 0 && (
                  /* Соус отдельной строкой и с плюсом: в iiko он списывается
                     своим товаром, и в сходимость акта по рыбе не входит. */
                  <tr>
                    <td style={{ ...td, color: 'var(--mute)' }}>{p.sauce?.name || 'Соус терияки'}{' '}
                      <span style={{ fontSize: 11 }}>· со своего склада, сверх разбора</span>
                    </td>
                    <td style={tdR}>{kg(w.sauce.grams)} г</td>
                    <td style={tdR}>{tenge(w.sauce.price_per_kg)}</td>
                    <td style={tdR}>+{tenge(w.sauce.sum)}</td>
                  </tr>
                )}
                <tr>
                  <td style={{ ...td, color: 'var(--mute)' }}>{p.waste?.name || 'Отход'} <span style={{ fontSize: 11 }}>· по нулю</span></td>
                  <td style={tdR}>{kg(w.waste!.weight)}</td>
                  <td style={tdR}>0</td>
                  <td style={tdR}>0</td>
                </tr>
              </tbody>
            </table>

            <div style={{ marginTop: 10, display: 'flex', gap: 16, flexWrap: 'wrap', fontSize: 12.5, color: 'var(--mute)' }}>
              <span>Отход <b style={{ color: wasteTone(w.waste_pct || 0) }}>{pc(w.waste_pct)}</b></span>
              <span>В обрезки <b style={{ color: 'var(--hi)' }}>{pc(w.trim_pct)}</b></span>
              {(w.teriyaki_pct || 0) > 0 && (
                <span>
                  Выход жарки <b style={{ color: (w.teriyaki_yield_pct || 0) >= 70 ? 'var(--grn)' : 'var(--amb)' }}>
                    {pc(w.teriyaki_yield_pct)}
                  </b>
                </span>
              )}
              {(w.sauce_g_per_kg || 0) > 0 && (
                <span>Соуса <b style={{ color: 'var(--hi)' }}>{kg(w.sauce_g_per_kg)} г</b> на кг</span>
              )}
              <span>
                Сходимость{w.sauce && w.sauce.grams > 0 ? ' по рыбе' : ''}:&nbsp;
                <b style={{ color: Math.abs((w.check || 0) - w.raw!.sum) < 0.01 ? 'var(--grn)' : 'var(--red)' }}>
                  {tenge(w.check || 0)} из {tenge(w.raw!.sum)}
                </b>
              </span>
              <span style={{ marginLeft: 'auto' }}>
                себестоимость нарезки — <b style={{ color: 'var(--hi)' }}>{tenge(w.slice!.price_per_kg)}/кг</b>
              </span>
            </div>

            <div style={{ marginTop: 14, display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
              <Button onClick={save} disabled={saving || missing}>
                {saving ? 'Записываю…' : 'Зафиксировать разбор'}
              </Button>
              <span style={{ fontSize: 11.5, color: 'var(--mute)' }}>
                В iiko поштучно не уходит — за период администратор заносит один сводный акт.
              </span>
            </div>
          </>
        )}

        <AnimatePresence>
          {saved && (
            <motion.div
              initial={still ? { opacity: 0 } : { opacity: 0, y: 8, scale: .98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0 }}
              transition={{ type: 'spring', bounce: 0, duration: 0.35 }}
              style={{
                marginTop: 14, padding: '12px 14px', borderRadius: 14,
                border: '1px solid var(--hair)', background: 'var(--glass-2)',
              }}>
              <div style={{ fontSize: 13.5, fontWeight: 700, color: 'var(--grn)' }}>
                Разбор записан · нарезка {kg(saved.slice?.weight)} кг по {tenge(saved.slice?.price_per_kg || 0)}/кг
              </div>
              <div style={{ marginTop: 4, fontSize: 12.5, color: 'var(--mute)' }}>
                Он попал в свод за период — ниже. Ошиблись? Разбор можно удалить, пока свод не занесён в iiko.
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </Glass>

      <SalmonPeriod token={token} org={org} kind={kind} reload={reload} />
      <SalmonNetwork token={token} kind={kind} reload={reload} />
    </>
  )
}
