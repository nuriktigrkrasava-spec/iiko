import { useState } from 'react'
import { kzt } from '../cases/money'
import { buildingOf, BUILDING_LABEL } from '../cases/nodes'
import type { Case } from '../cases/types'
import { haptic, inTelegram } from '../stories/tg'

/* «Спросить» — вопрос своими словами, ответ предложением с суммой в тенге.
   Никогда график, никогда выгрузка. Ответ детерминированный: сопоставление
   с ближайшим кейсом. LLM подключается позже за флагом. */

const HINTS = [
  'Сколько сейчас на кону',
  'Что происходит на кухне',
  'Что по складу',
  'Какое блюдо теряет деньги',
]

type Answer = { text: string; amount: number | null; rows: Case[] }

function answer(q: string, cases: Case[]): Answer {
  const open = cases.filter((c) => c.status !== 'rejected' && c.status !== 'closed')
  if (!open.length) return { text: 'Открытых проблем нет, очередь пуста.', amount: null, rows: [] }
  const t = q.toLowerCase()
  const hit = open.find((c) =>
    c.title.toLowerCase().split(' ').some((w) => w.length > 3 && t.includes(w.slice(0, 5))) ||
    BUILDING_LABEL[buildingOf(c.node_id)].toLowerCase().split(' ').some((w) => t.includes(w.slice(0, 4))) ||
    c.node_id.split('.').some((w) => t.includes(w)))
  if (hit) return { text: hit.title, amount: hit.amount_kzt, rows: [hit] }
  const total = open.reduce((s, c) => s + c.amount_kzt, 0)
  return {
    text: `На кону по ${open.length} открытым проблемам. Самая дорогая сверху.`,
    amount: total,
    rows: open.slice(0, 3),
  }
}

export default function Ask({ cases, onBack }: { cases: Case[]; onBack?: () => void }) {
  const [q, setQ] = useState('')
  const [res, setRes] = useState<Answer | null>(null)

  const ask = (text: string) => {
    if (!text.trim()) return
    haptic('light')
    setRes(answer(text.trim(), cases))
  }

  return (
    <div className="ma-root ask">
      <header className="ma-head">
        <div className="ma-overline">
          {onBack && !inTelegram() && (
            <button className="ma-back inline" onClick={onBack} aria-label="Назад">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m15 18-6-6 6-6" /></svg>
            </button>
          )}
          Разговор
        </div>
        <h1 className="ask-title">Спросите о деньгах своими словами</h1>
        <div className="ma-ask-field">
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && ask(q)}
            placeholder="Почему в среду было пусто…"
            aria-label="Вопрос"
          />
          <button className="ma-btn primary" onClick={() => ask(q)} aria-label="Спросить">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m5 12 14 0" /><path d="m13 6 6 6-6 6" /></svg>
          </button>
        </div>
      </header>

      {!res && (
        <section className="ma-sec">
          <h2 className="ma-sec-title">Например</h2>
          {HINTS.map((h) => (
            <button key={h} className="ask-hint" onClick={() => { setQ(h); ask(h) }}>
              <span>{h}</span>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m9 18 6-6-6-6" /></svg>
            </button>
          ))}
          <p className="ma-evi-note">Ответ приходит предложением с суммой. Никогда графиком.</p>
        </section>
      )}

      {res && (
        <section className="ma-sec" aria-live="polite">
          <h2 className="ma-sec-title">Ответ</h2>
          {res.amount != null && (
            <div className="ask-amount loss">{kzt(res.amount)}<span className="ma-row-per"> в месяц</span></div>
          )}
          <p className="ma-answer">{res.text}</p>
          {res.rows.length > 1 && (
            <div className="ma-evi">
              {res.rows.map((c) => (
                <div key={c.id} className="ma-evi-row">
                  <span>{c.title}</span>
                  <span className="ma-evi-money loss">{kzt(c.amount_kzt)}</span>
                </div>
              ))}
            </div>
          )}
          <div className="ma-actions">
            <button className="ma-btn" onClick={() => { setRes(null); setQ('') }}>Спросить ещё</button>
          </div>
          <p className="ma-evi-note">Всё это уже лежит в делах, отсортировано по сумме</p>
        </section>
      )}
    </div>
  )
}
