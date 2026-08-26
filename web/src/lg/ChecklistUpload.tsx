import { useEffect, useRef, useState } from 'react'
import { Glass } from './ui'
import { SLOTS, ZONES, type Done, type Issue, type Review,
         issueText, nearestSlot, sentIn } from './checklist'

/* Сдача чек-листа прямо с сайта: слот → зона → кадры → РАЗБОР.

   Экономия заложена в загрузку, а не в разбор: кадры сжимаются В БРАУЗЕРЕ до
   1024 px и JPEG 0.7 ещё до отправки. Это режет и трафик управляющего, и
   стоимость vision, которая считается по площади картинки.

   Разбор модели раньше приходил в ответе и молча выбрасывался: управляющий
   отправлял восемь кадров и не узнавал, что не так с санузлом. Теперь вердикт
   виден сразу после отправки, а замечания за день — списком ниже. */

const MAX_PHOTOS = 8
const MAX_SIDE = 1024

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

export default function ChecklistUpload({ token }: { token: string }) {
  const input = useRef<HTMLInputElement>(null)
  const [slot, setSlot] = useState(() => nearestSlot())
  const [zone, setZone] = useState('hall')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [done, setDone] = useState<Done[]>([])
  const [reviews, setReviews] = useState<Review[]>([])
  const [criteria, setCriteria] = useState<Criteria>({})
  const [verdict, setVerdict] = useState<{ ok?: boolean; checked?: boolean; issues?: Issue[]; reason?: string } | null>(null)

  const load = () => {
    fetch(`/api/mountain/checklist/${token}`).then((r) => r.json())
      .then((d: { done?: Done[]; criteria?: Criteria; reviews?: Review[] }) => {
        setDone(d.done || []); setCriteria(d.criteria || {}); setReviews(d.reviews || [])
      }).catch(() => {})
  }
  useEffect(load, [token])

  async function upload(list: FileList | null) {
    if (!list?.length) return
    const files = Array.from(list).slice(0, MAX_PHOTOS)
    setErr(null); setBusy(true); setVerdict(null)
    try {
      const photos = await Promise.all(files.map(compress))
      const r = await fetch(`/api/mountain/checklist/${token}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ slot, zone, photos }),
      })
      const d = await r.json()
      if (!r.ok || d.error) setErr(d.error || `HTTP ${r.status}`)
      else { setVerdict(d.review || { checked: false }); load() }
    } catch (e) {
      setErr(String((e as Error).message || e))
    } finally {
      setBusy(false)
      if (input.current) input.current.value = ''
    }
  }

  const sent = (s: string, key: string) => sentIn(done, s, key)
  const slotCount = (s: string) => ZONES.filter(([k]) => sent(s, k)).length
  // Замечания за сегодня по всем слотам — в одном месте, свежие сверху
  const problems = reviews.filter((r) => !r.ok && (r.issues || []).length)

  const chip = (on: boolean, extra?: React.CSSProperties): React.CSSProperties => ({
    padding: '7px 13px', borderRadius: 11, fontSize: 12.5, fontWeight: 650, cursor: 'pointer',
    border: '1px solid var(--hair)', fontFamily: 'inherit',
    background: on ? 'var(--glass-2)' : 'transparent',
    color: on ? 'var(--hi)' : 'var(--mute)', ...extra,
  })

  return (
    <Glass span={12}>
      <div className="eyebrow"><span>Сдать чек-лист</span>
        <span className="hint">кадры сжимаются в браузере · до {MAX_PHOTOS} на зону</span></div>

      {/* Слоты: рядом с временем — сколько зон из трёх уже сдано. Без счётчика
          приходилось открывать каждый слот, чтобы понять, где дыра. */}
      <div style={{ marginTop: 12, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {SLOTS.map((s) => {
          const n = slotCount(s)
          return (
            <button key={s} onClick={() => setSlot(s)} style={chip(slot === s)}>
              {s}
              <span style={{ marginLeft: 6, fontSize: 11, fontWeight: 700,
                             color: n === ZONES.length ? 'var(--grn)' : n ? 'var(--amb)' : 'var(--mute)' }}>
                {n}/{ZONES.length}
              </span>
            </button>
          )
        })}
      </div>

      {/* Зоны выбранного слота: галочка прямо на кнопке — видно, что уже сдано,
          не заглядывая в таблицу ниже. */}
      <div style={{ marginTop: 8, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {ZONES.map(([k, label]) => {
          const d = sent(slot, k)
          return (
            <button key={k} onClick={() => setZone(k)}
              style={chip(zone === k, d ? { borderColor: 'var(--grn)' } : undefined)}>
              {d && <span style={{ color: 'var(--grn)', marginRight: 5, fontWeight: 800 }}>✓</span>}
              {label}
              {d && <span style={{ marginLeft: 5, fontSize: 11, color: 'var(--mute)' }}>{d.at}</span>}
            </button>
          )
        })}
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

      {/* Кнопку не должно вести: подпись меняет длину на каждый тап по зоне и
          ещё раз на «Загружаю…». Постоянная ширина + состояние своей строкой. */}
      <div style={{ marginTop: 12 }}>
        <button onClick={() => input.current?.click()} disabled={busy}
          style={{ minWidth: 208, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', padding: '11px 18px', borderRadius: 14, border: 'none', background: 'linear-gradient(135deg,var(--acc),var(--acc-2))', color: 'var(--on-acc)', fontSize: 13.5, fontWeight: 700, fontFamily: 'inherit', cursor: busy ? 'default' : 'pointer', opacity: busy ? .6 : 1 }}>
          {busy ? 'Загружаю…' : `Сдать ${slot} · ${ZONES.find(([k]) => k === zone)?.[1]}`}
        </button>
        <input ref={input} type="file" accept="image/*" multiple capture="environment" hidden
          onChange={(e) => upload(e.target.files)} />
        <div style={{ minHeight: 18, marginTop: 7, fontSize: 12.5, fontWeight: 650, color: 'var(--grn)' }}>
          {sent(slot, zone) ? `уже сдано в ${sent(slot, zone)?.at}` : ''}
        </div>
      </div>

      {err && <div style={{ marginTop: 10, fontSize: 12.5, color: 'var(--red)' }}>{err}</div>}

      {/* Вердикт разбора сразу после отправки — ради него всё и снимают */}
      {verdict && (
        <div style={{ marginTop: 12, padding: '11px 13px', borderRadius: 12,
                      border: `1px solid ${verdict.checked ? (verdict.ok ? 'var(--grn)' : 'var(--red)') : 'var(--hair)'}`,
                      background: 'var(--glass-2)' }}>
          {verdict.checked ? (
            verdict.ok ? (
              <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--grn)' }}>Разбор: замечаний нет</div>
            ) : (
              <>
                <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--red)' }}>Разбор нашёл, что поправить</div>
                <div style={{ marginTop: 6, display: 'grid', gap: 4 }}>
                  {(verdict.issues || []).map((it, i) => (
                    <div key={i} style={{ fontSize: 12.5, color: 'var(--hi)', display: 'flex', gap: 8 }}>
                      <span style={{ color: 'var(--red)' }}>•</span>{issueText(it)}
                    </div>
                  ))}
                </div>
              </>
            )
          ) : (
            /* Разбор не гоняли — так и говорим. Молчание читалось как «всё хорошо». */
            <div style={{ fontSize: 12.5, color: 'var(--mute)' }}>
              Кадры приняты. Разбор не запускался{verdict.reason ? `: ${verdict.reason}` : ''}
            </div>
          )}
        </div>
      )}

      {/* Замечания за сегодня — что плохо по всем слотам, а не только по последнему */}
      {problems.length > 0 && (
        <div style={{ marginTop: 14 }}>
          <div style={{ fontSize: 11, letterSpacing: '.08em', textTransform: 'uppercase', color: 'var(--mute)', fontWeight: 700 }}>
            Замечания за сегодня
          </div>
          <div style={{ marginTop: 7, display: 'grid', gap: 5 }}>
            {problems.map((r, i) => (
              <div key={`${r.slot}${i}`} style={{ display: 'flex', gap: 9, alignItems: 'baseline', fontSize: 12.5 }}>
                <span className="tnum" style={{ color: 'var(--mute)', flex: 'none' }}>{r.slot}</span>
                <span style={{ color: 'var(--red)' }}>{(r.issues || []).map(issueText).join(' · ')}</span>
              </div>
            ))}
          </div>
        </div>
      )}

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
