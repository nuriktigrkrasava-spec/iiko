import { useEffect, useState } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { Glass } from './ui'
import { tenge } from '../lib/format'
import { Button, Eyebrow, PHOTO, Tile, field, kg, pc, td, tdR, th, wasteTone } from './salmonKit'
import SalmonPeriod from './SalmonPeriod'
import SalmonNetwork from './SalmonNetwork'

/* «Акты и разборы» — рядом с горой, на тех же ссылках.

   Взвешивают то, что держат в руках: стейк на входе, нарезку и обрезки на
   выходе. Отход (кости и кожа) не взвешивают — он остаток веса, и его процент
   и есть оценка разбора.

   В iiko поштучно ничего не уходит: каждый разбор фиксируется у нас, а за
   период администратор заносит ОДИН сводный акт руками. Два документа на один
   и тот же вес задвоили бы списание.

   Цену входа можно переписать руками — бывает разовый закуп по другой цене, и
   заставлять человека верить истории накладных в таком случае неправильно. */

type Prod = { id: string; name: string; unit?: string } | null
type Ctx = {
  error?: string
  role?: 'owner' | 'manager'
  branch?: { organization_id: string; name: string }
  branches?: { organization_id: string; name: string }[]
  products?: { raw: Prod; trim: Prod; slice: Prod; waste: Prod }
  price_per_kg?: number
  price_from?: string
  trim_price?: number
}
type Line = { weight: number; price_per_kg: number; sum: number }
type Calc = {
  ok: boolean; error?: string
  raw?: Line; slice?: Line; trim?: Line; waste?: Line
  slice_pct?: number; trim_pct?: number; waste_pct?: number; check?: number
  saved?: boolean; id?: number
}

export default function SalmonAct({ token }: { token: string }) {
  const [ctx, setCtx] = useState<Ctx | null>(null)
  const [org, setOrg] = useState<string>('')
  const [raw, setRaw] = useState('')
  const [slice, setSlice] = useState('')
  const [trim, setTrim] = useState('')
  const [price, setPrice] = useState('')          // пусто = цена из накладных
  const [calc, setCalc] = useState<Calc | null>(null)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState<Calc | null>(null)
  const [reload, setReload] = useState(0)         // счётчик: обновить свод и сеть
  const still = useReducedMotion()

  useEffect(() => {
    fetch(`/api/acts/salmon/${token}${org ? `?org=${org}` : ''}`)
      .then((r) => r.json())
      .then((d: Ctx) => { setCtx(d); if (!org && d.branch) setOrg(d.branch.organization_id) })
      .catch((e) => setCtx({ error: String(e.message || e) }))
  }, [token, org])

  // считаем на сервере: там же лежат тесты на эту арифметику
  useEffect(() => {
    const wr = Number(raw.replace(',', '.')) || 0
    const ws = Number(slice.replace(',', '.')) || 0
    if (!wr) { setCalc(null); return }
    const t = setTimeout(() => {
      fetch(`/api/acts/salmon/${token}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          org, weight_raw: wr, weight_slice: ws,
          weight_trim: Number(trim.replace(',', '.')) || 0,
          price_per_kg: price ? Number(price.replace(',', '.')) : null,
        }),
      }).then((r) => r.json()).then(setCalc).catch(() => setCalc(null))
    }, 250)
    return () => clearTimeout(t)
  }, [raw, slice, trim, price, org, token])

  async function save() {
    if (!calc?.ok) return
    setSaving(true)
    try {
      const r = await fetch(`/api/acts/salmon/${token}/save`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          org,
          weight_raw: Number(raw.replace(',', '.')) || 0,
          weight_slice: Number(slice.replace(',', '.')) || 0,
          weight_trim: Number(trim.replace(',', '.')) || 0,
          price_per_kg: price ? Number(price.replace(',', '.')) : null,
        }),
      })
      const d: Calc = await r.json()
      if (d.saved) {
        setSaved(d)
        setRaw(''); setSlice(''); setTrim(''); setCalc(null)
        setReload((n) => n + 1)
        setTimeout(() => setSaved(null), 6000)
      } else {
        setCalc({ ...(calc as Calc), error: d.error || `HTTP ${r.status}`, ok: false })
      }
    } finally { setSaving(false) }
  }

  if (!ctx) return <Glass span={12}><div style={{ padding: 12, fontSize: 13, color: 'var(--mute)' }}>Гружу справочник…</div></Glass>
  if (ctx.error) return <Glass span={12}><div style={{ padding: 12, fontSize: 13, color: 'var(--red)' }}>{ctx.error}</div></Glass>

  const p = ctx.products || { raw: null, trim: null, slice: null, waste: null }
  const missing = !p.raw || !p.trim || !p.slice
  const w = calc?.ok ? calc : null

  return (
    <>
      <Glass span={12}>
        <Eyebrow t="Разбор лосося"
          hint={`вход ${p.raw?.name || '—'} · обрезки по ${tenge(ctx.trim_price || 8800)}/кг`} />

        {missing && (
          <div style={{ marginTop: 10, fontSize: 12.5, color: 'var(--amb)' }}>
            В номенклатуре этого филиала нет одной из позиций разбора — акт не собрать.
          </div>
        )}

        {/* Вход и три выхода. Отход не вводят: он остаток веса. */}
        <div style={{ marginTop: 14, display: 'grid', gap: 10, gridTemplateColumns: 'repeat(auto-fit,minmax(158px,1fr))' }}>
          <Tile photo={PHOTO.raw} label="Стейк в разбор" hint="вход" value={raw}
            onChange={setRaw} placeholder="10"
            foot={ctx.price_per_kg ? `${tenge(ctx.price_per_kg)}/кг` : 'цена не найдена'} />
          <Tile photo={PHOTO.slice} label="Нарезка" hint="выход" value={slice}
            onChange={setSlice} placeholder="8"
            foot={w ? `${pc(w.slice_pct)} · ${tenge(w.slice!.price_per_kg)}/кг` : undefined} />
          <Tile photo={PHOTO.trim} label="Обрезки" hint={`по ${tenge(ctx.trim_price || 8800)}`}
            value={trim} onChange={setTrim} placeholder="2"
            foot={w ? `${pc(w.trim_pct)} веса` : undefined} />
          <Tile photo={PHOTO.waste} label="Отход" hint="кости, кожа" readOnly
            value={w ? kg(w.waste!.weight) : ''}
            tone={w ? wasteTone(w.waste_pct || 0) : undefined}
            foot={w
              ? <b style={{ color: wasteTone(w.waste_pct || 0) }}>{pc(w.waste_pct)} отхода</b>
              : 'стейк − нарезка − обрезки'} />
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
                  <td style={{ ...td, color: 'var(--amb)' }}>{p.trim?.name} <span style={{ color: 'var(--mute)', fontSize: 11 }}>· константа</span></td>
                  <td style={tdR}>{kg(w.trim!.weight)}</td>
                  <td style={tdR}>{tenge(w.trim!.price_per_kg)}</td>
                  <td style={tdR}>{tenge(w.trim!.sum)}</td>
                </tr>
                <tr>
                  <td style={{ ...td, color: 'var(--mute)' }}>{p.waste?.name || 'Отход лосося'} <span style={{ fontSize: 11 }}>· по нулю</span></td>
                  <td style={tdR}>{kg(w.waste!.weight)}</td>
                  <td style={tdR}>0</td>
                  <td style={tdR}>0</td>
                </tr>
              </tbody>
            </table>

            <div style={{ marginTop: 10, display: 'flex', gap: 16, flexWrap: 'wrap', fontSize: 12.5, color: 'var(--mute)' }}>
              <span>Отход <b style={{ color: wasteTone(w.waste_pct || 0) }}>{pc(w.waste_pct)}</b></span>
              <span>В обрезки <b style={{ color: 'var(--hi)' }}>{pc(w.trim_pct)}</b></span>
              <span>
                Сходимость:&nbsp;
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

      <SalmonPeriod token={token} org={org} reload={reload} />
      <SalmonNetwork token={token} reload={reload} />
    </>
  )
}
