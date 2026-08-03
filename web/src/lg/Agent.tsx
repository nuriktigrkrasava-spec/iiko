import { useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { runAction, type Advice, type AssistantResp } from './assistant'

/* Проактивный ИИ-ассистент «Директор»: сам анализирует все филиалы и выдаёт
   советы «проблема → деньги → что сделать» + действия. Не чат. */

const SEV_COLOR: Record<Advice['severity'], string> = {
  high: 'var(--red)', med: 'var(--amb)', low: 'var(--grn)',
}
const money = (n: number | null) =>
  n == null ? '' : n >= 1e6 ? `${(n / 1e6).toFixed(1).replace('.', ',')} млн ₸` : `${Math.round(n / 1000)} тыс ₸`

export default function Agent() {
  const [open, setOpen] = useState(false)
  const [advice, setAdvice] = useState<Advice[]>([])
  const [notif, setNotif] = useState<Advice | null>(null)

  useEffect(() => {
    let alive = true
    fetch('/api/assistant', { headers: { Accept: 'application/json' } })
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((d: AssistantResp) => { if (alive) setAdvice(d.advice || []) })
      .catch(() => {})
    return () => { alive = false }
  }, [])

  // проактивно всплываем топ-советом, когда панель закрыта
  useEffect(() => {
    if (open || advice.length === 0) { setNotif(null); return }
    const t = setTimeout(() => setNotif(advice[0]), 3500)
    return () => clearTimeout(t)
  }, [open, advice])

  const act = (a: Advice) => { if (a.action) runAction(a.action); setOpen(false) }

  return (
    <>
      {!open && (
        <button className="lg-agent-fab" onClick={() => setOpen(true)} aria-label="ИИ-ассистент">
          <img src="/agent2.png" alt="" />
          <span className="lg-agent-dot" />
        </button>
      )}

      <AnimatePresence>
        {notif && !open && (
          <motion.button className="lg-agent-toast" onClick={() => setOpen(true)}
            initial={{ opacity: 0, y: 10, scale: 0.96 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 10, scale: 0.96 }}>
            <img src="/agent2.png" alt="" />
            <span><b style={{ color: SEV_COLOR[notif.severity] }}>{notif.branch}</b> · {notif.title}
              {notif.money != null && <> · <span className="tnum">≈ {money(notif.money)}/мес</span></>}</span>
          </motion.button>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {open && (
          <motion.div className="lg-chat glass" initial={{ opacity: 0, y: 16, scale: 0.96 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 16, scale: 0.96 }} transition={{ type: 'spring', stiffness: 320, damping: 30 }}>
            <div className="lg-chat-head">
              <img src="/agent2.png" alt="" />
              <div>
                <div style={{ fontSize: 13.5, fontWeight: 700, color: 'var(--hi)' }}>ИИ-директор</div>
                <div style={{ fontSize: 11, color: 'var(--grn)' }}>● смотрит все филиалы</div>
              </div>
              <button onClick={() => setOpen(false)} className="lg-chat-x" aria-label="Закрыть">×</button>
            </div>
            <div className="lg-chat-body">
              {advice.length === 0 && <div style={{ padding: '14px 2px', fontSize: 13, color: 'var(--mute)' }}>Собираю сигналы по филиалам…</div>}
              {advice.map((a) => (
                <div key={a.id} style={{ padding: '12px 0', borderTop: '1px solid var(--hair-2)' }}>
                  <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
                    <span style={{ width: 7, height: 7, borderRadius: '50%', background: SEV_COLOR[a.severity], flex: 'none' }} />
                    <span style={{ fontSize: 13.5, fontWeight: 650, color: 'var(--hi)' }}>{a.branch} · {a.title}</span>
                    {a.money != null && <span className="tnum" style={{ marginLeft: 'auto', fontSize: 13, fontWeight: 700, color: SEV_COLOR[a.severity] }}>≈ {money(a.money)}</span>}
                  </div>
                  <p style={{ margin: '6px 0 0', fontSize: 12.5, lineHeight: 1.5, color: 'var(--lo)' }}>{a.detail}</p>
                  {a.action && (
                    <button onClick={() => act(a)} style={{ marginTop: 8, fontSize: 12, fontWeight: 600, color: 'var(--acc)', background: 'color-mix(in srgb,var(--acc) 12%,transparent)', border: '1px solid color-mix(in srgb,var(--acc) 26%,transparent)', borderRadius: 10, padding: '6px 11px', cursor: 'pointer' }}>Открыть →</button>
                  )}
                </div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  )
}
