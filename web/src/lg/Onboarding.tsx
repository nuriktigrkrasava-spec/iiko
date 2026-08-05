import { useState } from 'react'
import { Glass } from './ui'
import { useInstagram } from '../lib/social'
import { Brand, BRAND_COLOR, brandKey } from './brands'
import { num } from '../lib/format'

/* Онбординг: подключить ресторан.
   1) Аналитика — iikoServer (адрес + логин + пароль) → проверка → выбор организации.
   2) Живой зал — iiko Cloud apiLogin (необязательно) для столов/стоп-листов/доставки.
   Валидация — POST /api/setup/validate, сохранение — POST /api/setup/save. */

type Org = { id: string; name: string }

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json() as Promise<T>
}

const inp: React.CSSProperties = {
  width: '100%', font: 'inherit', fontSize: 14, color: 'var(--hi)', background: 'var(--glass-2)',
  border: '1px solid var(--hair)', borderRadius: 12, padding: '11px 13px',
}
const lab: React.CSSProperties = { fontSize: 11.5, letterSpacing: '.04em', color: 'var(--mute)', fontWeight: 600, marginBottom: 6, display: 'block' }

function Field({ label, ...p }: { label: string } & React.InputHTMLAttributes<HTMLInputElement>) {
  return <div style={{ marginTop: 14 }}><label style={lab}>{label}</label><input style={inp} {...p} /></div>
}

/* Шаг 3 — соцсети (self-serve, для любого клиента): вход в Instagram через Meta
   OAuth + название бренда для автоподключения 2ГИС/Wolt. Привязка к текущему org. */
function SocialOnboard() {
  const { data: ig, msg, connect } = useInstagram()
  const [brand, setBrand] = useState('')
  const [saved, setSaved] = useState(false)
  const [busy, setBusy] = useState(false)
  const c = BRAND_COLOR[brandKey('instagram')]
  const on = !!ig?.connected

  async function saveBrand() {
    if (!brand.trim()) return
    setBusy(true); setSaved(false)
    try { await post('/api/reviews/brand', { brand: brand.trim() }); setSaved(true) }
    catch { /* тихо */ } finally { setBusy(false) }
  }

  return (
    <>
      <Glass span={7}>
        <div className="eyebrow"><span>3 · Соцсети · Instagram</span><span className="hint">подписчики и рост</span></div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 12 }}>
          <span style={{ width: 42, height: 42, borderRadius: '32%', flex: 'none', display: 'grid', placeItems: 'center', color: on ? c : 'var(--mute)', background: 'var(--glass-2)', border: '1px solid var(--hair)' }}>
            <Brand name="instagram" size={22} />
          </span>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: 14, fontWeight: 650, color: 'var(--hi)' }}>Instagram Business</div>
            <div style={{ fontSize: 12, color: 'var(--mute)' }}>{on ? (ig?.username ? '@' + ig.username : 'подключён') : 'подключается за один вход'}</div>
          </div>
          {!on && (
            <button onClick={connect} style={{ marginLeft: 'auto', font: 'inherit', fontSize: 13.5, fontWeight: 600, color: '#fff', border: 0, borderRadius: 12, padding: '11px 16px', cursor: 'pointer', background: c }}>
              Войти через Facebook
            </button>
          )}
        </div>
        {on && (
          <div className="tnum" style={{ fontSize: 30, fontWeight: 700, letterSpacing: '-.03em', marginTop: 14, color: c, display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
            {ig?.followers != null ? num(ig.followers) : '—'}
            <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--mute)' }}>подписчиков</span>
            {ig?.delta_30d != null && (
              <span style={{ fontSize: 13, fontWeight: 650, color: ig.delta_30d >= 0 ? 'var(--grn)' : 'var(--red)' }}>
                {ig.delta_30d >= 0 ? '▲' : '▼'} {num(Math.abs(ig.delta_30d))} / 30д
              </span>
            )}
          </div>
        )}
        <p style={{ fontSize: 12, color: 'var(--mute)', margin: '12px 0 0', lineHeight: 1.5 }}>
          Instagram должен быть Business/Creator и привязан к Facebook-странице. Токен хранится зашифрованно, только для чтения статистики.
        </p>
        {msg && <div style={{ marginTop: 10, fontSize: 12, color: 'var(--amb)', lineHeight: 1.45 }}>{msg}</div>}
      </Glass>

      <Glass span={5}>
        <div className="eyebrow"><span>Отзывы · 2ГИС и Wolt</span><span className="hint">автоподключение</span></div>
        <p style={{ fontSize: 12.5, color: 'var(--lo)', margin: '10px 0 4px', lineHeight: 1.5 }}>
          Укажи точное название бренда — найдём точки на 2ГИС и Wolt и подтянем рейтинг с отзывами автоматически.
        </p>
        <Field label="Название бренда" value={brand} onChange={(e) => setBrand(e.target.value)} placeholder="напр. Saya Sushi" autoComplete="off" />
        <button onClick={saveBrand} disabled={busy || !brand.trim()} style={{ width: '100%', marginTop: 14, font: 'inherit', fontSize: 14, fontWeight: 600, color: 'var(--hi)', background: 'var(--glass-2)', border: '1px solid var(--hair)', borderRadius: 12, padding: '11px 16px', cursor: 'pointer', opacity: busy || !brand.trim() ? 0.5 : 1 }}>
          {busy ? 'Сохраняю…' : 'Сохранить бренд'}
        </button>
        {saved && <div style={{ marginTop: 10, fontSize: 12, color: 'var(--grn)' }}>✓ Бренд сохранён — открой «Соцсети», рейтинг подтянется.</div>}
      </Glass>
    </>
  )
}

export default function Onboarding() {
  const [server, setServer] = useState('https://ваш-сервер.iiko.it:443/resto')
  const [login, setLogin] = useState('')
  const [pass, setPass] = useState('')
  const [cloud, setCloud] = useState('')
  const [orgs, setOrgs] = useState<Org[]>([])
  const [sel, setSel] = useState<string>('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [done, setDone] = useState(false)

  async function validate() {
    setErr(''); setBusy(true); setOrgs([])
    try {
      const r = await post<{ valid: boolean; organizations?: Org[]; error?: string }>('/api/setup/validate', { api_login: login, iiko_server: server, api_password: pass })
      if (!r.valid) { setErr(r.error || 'Не удалось подключиться'); return }
      setOrgs(r.organizations || [])
      if (r.organizations?.length) setSel(r.organizations[0].id)
    } catch (e) { setErr(String((e as Error).message)) } finally { setBusy(false) }
  }

  async function save() {
    const org = orgs.find((o) => o.id === sel); if (!org) return
    setErr(''); setBusy(true)
    try {
      await post('/api/setup/save', { api_login: login, organization_id: org.id, organization_name: org.name, iiko_server: server, api_password: pass, cloud_api_login: cloud || null })
      setDone(true)
    } catch (e) { setErr(String((e as Error).message)) } finally { setBusy(false) }
  }

  if (done) return (
    <>
      <Glass span={12}>
        <div style={{ textAlign: 'center', padding: '30px 10px' }}>
          <div style={{ fontSize: 40 }}>✓</div>
          <div className="display" style={{ fontSize: 24, marginTop: 8 }}>Ресторан подключён</div>
          <p style={{ color: 'var(--mute)', marginTop: 8 }}>Обнови страницу — филиал появится в переключателе вверху.</p>
          <button onClick={() => location.reload()} style={{ marginTop: 14, font: 'inherit', fontSize: 14, fontWeight: 600, color: '#fff', border: 0, borderRadius: 12, padding: '11px 20px', cursor: 'pointer', background: 'linear-gradient(135deg,var(--acc),var(--acc-2))' }}>Обновить</button>
        </div>
      </Glass>
      <SocialOnboard />
    </>
  )

  return (
    <>
      <Glass span={7}>
        <div className="eyebrow"><span>1 · Аналитика · iikoServer</span><span className="hint">выручка, фудкост, склад</span></div>
        <p style={{ fontSize: 12.5, color: 'var(--lo)', margin: '10px 0 4px', lineHeight: 1.5 }}>Самохостед iikoWeb / iikoServer (REST <code>/resto/api</code>). Адрес сервера, логин и пароль от API.</p>
        <Field label="Адрес iiko-сервера" value={server} onChange={(e) => setServer(e.target.value)} placeholder="https://ваш-сервер.iiko.it:443/resto" />
        <Field label="Логин API" value={login} onChange={(e) => setLogin(e.target.value)} placeholder="apiLogin" autoComplete="off" />
        <Field label="Пароль API" type="password" value={pass} onChange={(e) => setPass(e.target.value)} autoComplete="off" />
        <button onClick={validate} disabled={busy || !login} style={{ marginTop: 16, font: 'inherit', fontSize: 14, fontWeight: 600, color: 'var(--hi)', background: 'var(--glass-2)', border: '1px solid var(--hair)', borderRadius: 12, padding: '11px 18px', cursor: 'pointer', opacity: busy || !login ? 0.5 : 1 }}>
          {busy ? 'Проверяю…' : 'Проверить подключение'}
        </button>
        {err && <div style={{ marginTop: 12, fontSize: 12.5, color: 'var(--red)' }}>⚠ {err}</div>}

        {orgs.length > 0 && (
          <div style={{ marginTop: 18, paddingTop: 14, borderTop: '1px solid var(--hair)' }}>
            <label style={lab}>Организация (филиал)</label>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 4 }}>
              {orgs.map((o) => (
                <button key={o.id} onClick={() => setSel(o.id)} style={{ display: 'flex', alignItems: 'center', gap: 10, textAlign: 'left', font: 'inherit', fontSize: 13.5, color: 'var(--hi)', background: sel === o.id ? 'color-mix(in srgb,var(--acc) 12%,transparent)' : 'var(--glass-2)', border: `1px solid ${sel === o.id ? 'var(--acc)' : 'var(--hair)'}`, borderRadius: 11, padding: '11px 13px', cursor: 'pointer' }}>
                  <span style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--acc)', opacity: sel === o.id ? 1 : 0 }} />{o.name}
                </button>
              ))}
            </div>
          </div>
        )}
      </Glass>

      <Glass span={5}>
        <div className="eyebrow"><span>2 · Живой зал · iiko Cloud</span><span className="hint">необязательно</span></div>
        <p style={{ fontSize: 12.5, color: 'var(--lo)', margin: '10px 0 4px', lineHeight: 1.5 }}>Ключ <b>iiko Cloud apiLogin</b> из ЛК iiko.biz (Настройки → API). Даёт живой зал (столы, гости), стоп-листы и доставку/агрегаторы. Без него аналитика всё равно работает.</p>
        <Field label="iiko Cloud apiLogin" value={cloud} onChange={(e) => setCloud(e.target.value)} placeholder="ключ Cloud API" autoComplete="off" />
        <div style={{ marginTop: 16, fontSize: 11.5, color: 'var(--mute)', lineHeight: 1.5, padding: '12px', borderRadius: 12, background: 'var(--glass-2)', border: '1px solid var(--hair)' }}>
          Аналитика (шаг 1) — из iikoServer/OLAP. Живой зал (шаг 2) — из iiko Cloud. Это два разных ключа: сервер нужен всегда, Cloud — для реального времени.
        </div>

        <button onClick={save} disabled={busy || !sel} style={{ width: '100%', marginTop: 18, font: 'inherit', fontSize: 15, fontWeight: 650, color: '#fff', border: 0, borderRadius: 13, padding: '13px', cursor: 'pointer', background: 'linear-gradient(135deg,var(--acc),var(--acc-2))', boxShadow: '0 10px 24px -10px var(--acc-glow)', opacity: busy || !sel ? 0.5 : 1 }}>
          {busy ? 'Сохраняю…' : sel ? 'Подключить ресторан' : 'Сначала проверь подключение'}
        </button>
      </Glass>

      <SocialOnboard />
    </>
  )
}
