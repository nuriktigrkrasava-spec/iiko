import { useCallback, useEffect, useMemo, useState } from 'react'
import { Glass } from './ui'
import { useOrg } from '../lib/useApi'

/* Панель управляющего под расписанием: доступы сотрудников, точка филиала и
   сообщения смене. Живёт рядом с сеткой намеренно — ссылку выдают, глядя на
   того же человека, которому только что поставили смену. */

type Emp = { id: string; name: string }
type Access = { employee_id: string; name: string; bound: boolean; bound_at: string | null; url: string }
type Geo = { lat: number; lon: number; radius: number } | null
type Sent = { id: number; text: string; created_at: string; to_employee_id: string | null; read_by: number }

const btn: React.CSSProperties = {
  border: '1px solid var(--hair)', borderRadius: 9, padding: '7px 12px',
  fontSize: 12.5, cursor: 'pointer', background: 'transparent', color: 'var(--lo)',
}
const inp: React.CSSProperties = {
  background: 'var(--glass-2)', border: '1px solid var(--hair)', borderRadius: 10,
  padding: '9px 11px', color: 'var(--hi)', fontSize: 13, width: '100%',
}

async function post<T>(url: string, body: unknown): Promise<T> {
  const r = await fetch(url, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `HTTP ${r.status}`)
  return r.json() as Promise<T>
}

/* ── Точка филиала: сверять гео не с чем, пока её не задали ── */
function BranchPoint({ org }: { org: string }) {
  const [geo, setGeo] = useState<Geo>(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')

  useEffect(() => {
    if (!org) return
    fetch(`/api/branch-geo/${org}`, { headers: { Accept: 'application/json' } })
      .then((r) => (r.ok ? r.json() : { geo: null }))
      .then((d) => setGeo(d.geo))
      .catch(() => { /* не критично: просто предложим задать */ })
  }, [org])

  const here = () => {
    setBusy(true); setMsg('')
    navigator.geolocation?.getCurrentPosition(
      async (p) => {
        try {
          const d = await post<{ geo: Geo }>(`/api/branch-geo/${org}`, {
            lat: p.coords.latitude, lon: p.coords.longitude, radius: geo?.radius ?? 250,
          })
          setGeo(d.geo); setMsg('Точка сохранена')
        } catch (e) { setMsg(String((e as Error).message)) } finally { setBusy(false) }
      },
      () => { setBusy(false); setMsg('Телефон не дал геопозицию') },
      { enableHighAccuracy: true, timeout: 10000 },
    )
  }

  return (
    <Glass span={6}>
      <div className="eyebrow"><span>Точка филиала</span></div>
      <div style={{ marginTop: 10, fontSize: 13, color: geo ? 'var(--hi)' : 'var(--mute)' }}>
        {geo
          ? `Задана · радиус ${geo.radius} м`
          : 'Не задана — гео у сотрудников не проверяется, смены открываются без отметки о месте.'}
      </div>
      <button onClick={here} disabled={busy} style={{ ...btn, marginTop: 12, borderColor: 'var(--acc)', color: 'var(--acc)' }}>
        {busy ? 'Определяю…' : geo ? 'Переставить сюда' : 'Филиал здесь'}
      </button>
      <div style={{ marginTop: 8, fontSize: 11.5, color: 'var(--mute)' }}>
        Нажимайте, стоя в заведении. {msg}
      </div>
    </Glass>
  )
}

/* ── Личные ссылки сотрудников ── */
function StaffLinks({ org, employees, onWrite }: { org: string; employees: Emp[]; onWrite: (e: Emp) => void }) {
  const [access, setAccess] = useState<Access[]>([])
  const [copied, setCopied] = useState('')

  const load = useCallback(() => {
    if (!org) return
    fetch(`/api/staff-access/${org}`, { headers: { Accept: 'application/json' } })
      .then((r) => (r.ok ? r.json() : { access: [] }))
      .then((d) => setAccess(d.access || []))
      .catch(() => { /* покажем пустым */ })
  }, [org])
  useEffect(load, [load])

  const byId = useMemo(() => new Map(access.map((a) => [a.employee_id, a])), [access])

  const issue = async (e: Emp) => {
    const d = await post<{ url: string }>(`/api/staff-access/${org}`, { employee_id: e.id, name: e.name })
    load()
    copy(d.url, e.id)
  }
  const copy = (url: string, id: string) => {
    navigator.clipboard?.writeText(url).then(() => { setCopied(id); setTimeout(() => setCopied(''), 2000) })
      .catch(() => { /* буфер недоступен — ссылка видна в поле ниже */ })
  }

  if (!employees.length) return null
  return (
    <Glass span={6}>
      <div className="eyebrow"><span>Доступ в мини-апп</span><span className="hint">личная ссылка</span></div>
      <div style={{ marginTop: 8, maxHeight: 260, overflowY: 'auto' }}>
        {employees.map((e) => {
          const a = byId.get(e.id)
          return (
            <div key={e.id} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '9px 0', borderTop: '1px solid var(--hair-2)' }}>
              <span style={{ flex: 1, fontSize: 13, color: 'var(--hi)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {e.name}
                {a && <span style={{ marginLeft: 8, fontSize: 11, color: a.bound ? 'var(--grn)' : 'var(--mute)' }}>
                  {a.bound ? 'привязан' : 'ссылка выдана'}
                </span>}
              </span>
              <button onClick={() => onWrite(e)} style={{ ...btn, padding: '5px 9px' }}>Написать</button>
              {a
                ? <button onClick={() => copy(a.url, e.id)} style={{ ...btn, padding: '5px 9px' }}>
                    {copied === e.id ? 'Скопировано' : 'Ссылка'}
                  </button>
                : <button onClick={() => issue(e)} style={{ ...btn, padding: '5px 9px', borderColor: 'var(--acc)', color: 'var(--acc)' }}>Выдать</button>}
            </div>
          )
        })}
      </div>
      <div style={{ marginTop: 10, fontSize: 11.5, color: 'var(--mute)' }}>
        Ссылка привязывается к первому, кто откроет её в Telegram. Утекла — выдайте заново, прежняя перестанет работать.
      </div>
    </Glass>
  )
}

/* ── Сообщения смене ── */
function ShiftMessage({ org, to, onDone }: { org: string; to: Emp | null; onDone: () => void }) {
  const [text, setText] = useState('')
  const [sent, setSent] = useState<Sent[]>([])
  const [msg, setMsg] = useState('')

  const load = useCallback(() => {
    if (!org) return
    fetch(`/api/staff-notice/${org}`, { headers: { Accept: 'application/json' } })
      .then((r) => (r.ok ? r.json() : { sent: [] }))
      .then((d) => setSent(d.sent || []))
      .catch(() => { /* пусто */ })
  }, [org])
  useEffect(load, [load])

  const send = async () => {
    const t = text.trim()
    if (!t) return
    try {
      await post(`/api/staff-notice/${org}`, { text: t, employee_id: to?.id ?? null })
      setText(''); setMsg(to ? `Отправлено: ${to.name}` : 'Отправлено всей смене'); onDone(); load()
    } catch (e) { setMsg(String((e as Error).message)) }
  }

  return (
    <Glass span={12}>
      <div className="eyebrow">
        <span>Сообщение смене</span>
        <span className="hint">{to ? `лично · ${to.name}` : 'всем сотрудникам филиала'}</span>
      </div>
      <textarea
        value={text} onChange={(e) => setText(e.target.value)} rows={3}
        placeholder={to ? `Что передать: ${to.name}` : 'Что передать всей смене'}
        style={{ ...inp, marginTop: 10, resize: 'vertical', fontFamily: 'inherit' }}
      />
      <div style={{ marginTop: 10, display: 'flex', gap: 8, alignItems: 'center' }}>
        <button onClick={send} style={{ ...btn, borderColor: 'var(--grn)', color: 'var(--grn)' }}>Отправить</button>
        {to && <button onClick={onDone} style={btn}>Всей смене</button>}
        <span style={{ fontSize: 12, color: 'var(--mute)' }}>{msg}</span>
      </div>
      {sent.length > 0 && (
        <div style={{ marginTop: 14 }}>
          {sent.slice(0, 5).map((s) => (
            <div key={s.id} style={{ padding: '9px 0', borderTop: '1px solid var(--hair-2)', display: 'flex', gap: 10, alignItems: 'baseline' }}>
              <span style={{ flex: 1, fontSize: 12.5, color: 'var(--lo)' }}>{s.text}</span>
              <span style={{ fontSize: 11, color: 'var(--mute)', whiteSpace: 'nowrap' }}>
                {s.to_employee_id ? 'лично' : 'всем'} · прочитали {s.read_by}
              </span>
            </div>
          ))}
        </div>
      )}
    </Glass>
  )
}

export default function ShiftAdmin({ employees }: { employees: Emp[] }) {
  const org = useOrg()
  const [to, setTo] = useState<Emp | null>(null)
  if (!org) return null
  return (
    <>
      <BranchPoint org={org} />
      <StaffLinks org={org} employees={employees} onWrite={setTo} />
      <ShiftMessage org={org} to={to} onDone={() => setTo(null)} />
    </>
  )
}
