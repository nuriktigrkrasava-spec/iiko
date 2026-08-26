import { useEffect, useRef, useState } from 'react'
import { Glass } from './ui'

/* Сдача чек-листа прямо с сайта: слот → зона → кадры.

   Экономия заложена в загрузку, а не в разбор: кадры сжимаются В БРАУЗЕРЕ до
   1024 px и JPEG 0.7 ещё до отправки. Это режет и трафик управляющего, и —
   когда включим разбор фото — стоимость vision, которая считается по площади
   картинки. Восемь кадров на зону хватает, больше — только вес. */

const SLOTS = ['10:45', '15:00', '20:45', '23:45']
const ZONES: [string, string][] = [['hall', 'Зал'], ['kitchen', 'Кухня'], ['wc', 'Санузел']]
const MAX_PHOTOS = 8
const MAX_SIDE = 1024
// подписи зон строчными — как их отдаёт сервер в старых ответах, без zone_key
const ZONE_LABEL: Record<string, string> = { hall: 'зал', kitchen: 'кухня', wc: 'санузел' }

type Done = { branch: string; slot: string; zone: string; zone_key?: string; photos: number; at: string }
type Criteria = Record<string, { label: string; items: string[] }>

function compress(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    const url = URL.createObjectURL(file)
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('не картинка')) }
    img.onload = () => {
      URL.revokeObjectURL(url)
      const k = Math.min(1, MAX_SIDE / Math.max(img.width, img.height))
      const c = document.createElement('canvas')
      c.width = Math.round(img.width * k)
      c.height = Math.round(img.height * k)
      const ctx = c.getContext('2d')
      if (!ctx) { reject(new Error('canvas недоступен')); return }
      ctx.drawImage(img, 0, 0, c.width, c.height)
      resolve(c.toDataURL('image/jpeg', 0.7).split(',', 2)[1] || '')
    }
    img.src = url
  })
}

const nearestSlot = () => {
  const now = new Date().getHours() * 60 + new Date().getMinutes()
  const mins = SLOTS.map((s) => Number(s.slice(0, 2)) * 60 + Number(s.slice(3)))
  let best = 0
  mins.forEach((m, i) => { if (m <= now) best = i })
  return SLOTS[best]
}

export default function ChecklistUpload({ token }: { token: string }) {
  const input = useRef<HTMLInputElement>(null)
  const [slot, setSlot] = useState(nearestSlot())
  const [zone, setZone] = useState('hall')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [done, setDone] = useState<Done[]>([])
  const [criteria, setCriteria] = useState<Criteria>({})

  const load = () => {
    fetch(`/api/mountain/checklist/${token}`).then((r) => r.json())
      .then((d: { done?: Done[]; criteria?: Criteria }) => {
        setDone(d.done || []); setCriteria(d.criteria || {})
      }).catch(() => {})
  }
  useEffect(load, [token])

  async function upload(list: FileList | null) {
    if (!list?.length) return
    const files = Array.from(list).slice(0, MAX_PHOTOS)
    setErr(null); setBusy(true)
    try {
      const photos = await Promise.all(files.map(compress))
      const r = await fetch(`/api/mountain/checklist/${token}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ slot, zone, photos }),
      })
      const d = await r.json()
      if (!r.ok || d.error) setErr(d.error || `HTTP ${r.status}`)
      else load()
    } catch (e) {
      setErr(String((e as Error).message || e))
    } finally {
      setBusy(false)
      if (input.current) input.current.value = ''
    }
  }

  /* Сверяем по КЛЮЧУ зоны («hall»), а не по подписи: сервер подписывает зоны
     строчными («зал»), здесь они с заглавной («Зал») — сравнение подписей не
     сходилось на регистре, и сданный слот навсегда оставался пустым: ни
     галочки в таблице, ни строки «уже сдано в 10:47». zone_key появился не
     сразу, поэтому старый ответ дочитываем подписью. */
  const sent = (s: string, key: string) => done.find((d) => d.slot === s
    && (d.zone_key || d.zone?.toLowerCase()) === (d.zone_key ? key : ZONE_LABEL[key]))

  return (
    <Glass span={12}>
      <div className="eyebrow"><span>Сдать чек-лист</span>
        <span className="hint">кадры сжимаются в браузере · до {MAX_PHOTOS} на зону</span></div>

      <div style={{ marginTop: 12, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {SLOTS.map((s) => (
          <button key={s} onClick={() => setSlot(s)}
            style={{
              padding: '7px 13px', borderRadius: 11, fontSize: 12.5, fontWeight: 650, cursor: 'pointer',
              border: '1px solid var(--hair)', fontFamily: 'inherit',
              background: slot === s ? 'var(--glass-2)' : 'transparent',
              color: slot === s ? 'var(--hi)' : 'var(--mute)',
            }}>{s}</button>
        ))}
        <span style={{ width: 1, background: 'var(--hair)', margin: '0 4px' }} />
        {ZONES.map(([k, label]) => (
          <button key={k} onClick={() => setZone(k)}
            style={{
              padding: '7px 13px', borderRadius: 11, fontSize: 12.5, fontWeight: 650, cursor: 'pointer',
              border: '1px solid var(--hair)', fontFamily: 'inherit',
              background: zone === k ? 'var(--glass-2)' : 'transparent',
              color: zone === k ? 'var(--hi)' : 'var(--mute)',
            }}>{label}</button>
        ))}
      </div>

      {/* Что именно снимать: без этого «сдал чистоту» превращается в пять кадров потолка */}
      {criteria[zone] && (
        <div style={{ marginTop: 12, padding: '11px 13px', borderRadius: 12, border: '1px solid var(--hair)', background: 'var(--glass-2)' }}>
          <div style={{ fontSize: 11, letterSpacing: '.08em', textTransform: 'uppercase', color: 'var(--mute)', fontWeight: 700 }}>
            {criteria[zone].label} · что снять
          </div>
          <div style={{ marginTop: 7, display: 'grid', gap: 4 }}>
            {criteria[zone].items.map((it) => (
              <div key={it} style={{ fontSize: 12.5, color: 'var(--hi)', display: 'flex', gap: 8 }}>
                <span style={{ color: 'var(--mute)' }}>•</span>{it}
              </div>
            ))}
          </div>
        </div>
      )}

      <div style={{ marginTop: 12, display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
        <button onClick={() => input.current?.click()} disabled={busy}
          style={{ padding: '11px 18px', borderRadius: 14, border: 'none', background: 'linear-gradient(135deg,var(--acc),var(--acc-2))', color: 'var(--on-acc)', fontSize: 13.5, fontWeight: 700, cursor: busy ? 'default' : 'pointer', opacity: busy ? .6 : 1 }}>
          {busy ? 'Загружаю…' : `Сдать ${slot} · ${ZONES.find(([k]) => k === zone)?.[1]}`}
        </button>
        <input ref={input} type="file" accept="image/*" multiple capture="environment" hidden
          onChange={(e) => upload(e.target.files)} />
        {sent(slot, zone) && (
          <span style={{ fontSize: 12.5, color: 'var(--grn)', fontWeight: 650 }}>
            уже сдано в {sent(slot, zone)?.at}
          </span>
        )}
      </div>

      {err && <div style={{ marginTop: 10, fontSize: 12.5, color: 'var(--red)' }}>{err}</div>}

      {/* что сдано сегодня: слоты × зоны */}
      <table style={{ width: '100%', borderCollapse: 'collapse', marginTop: 16, fontSize: 12.5 }}>
        <thead><tr>
          <th style={{ textAlign: 'left', padding: '0 0 8px', fontSize: 10, letterSpacing: '.1em', textTransform: 'uppercase', color: 'var(--mute)', fontWeight: 600, borderBottom: '1px solid var(--hair)' }}>Слот</th>
          {ZONES.map(([, label]) => (
            <th key={label} style={{ textAlign: 'center', padding: '0 0 8px', fontSize: 10, letterSpacing: '.1em', textTransform: 'uppercase', color: 'var(--mute)', fontWeight: 600, borderBottom: '1px solid var(--hair)' }}>{label}</th>
          ))}
        </tr></thead>
        <tbody>
          {SLOTS.map((s) => (
            <tr key={s}>
              <td className="tnum" style={{ padding: '9px 0', borderBottom: '1px solid var(--hair-2)', color: 'var(--hi)' }}>{s}</td>
              {ZONES.map(([k]) => {
                const d = sent(s, k)
                return (
                  <td key={k} style={{ padding: '9px 0', borderBottom: '1px solid var(--hair-2)', textAlign: 'center', color: d ? 'var(--grn)' : 'var(--mute)' }}>
                    {d ? `✓ ${d.photos} · ${d.at}` : '—'}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </Glass>
  )
}
