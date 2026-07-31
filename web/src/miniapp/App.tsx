import { useEffect, useMemo, useState } from 'react'
import './app.css'
import { useCases } from '../cases/generate'
import { kzt, kztRange } from '../cases/money'
import { buildingOf, BUILDING_LABEL } from '../cases/nodes'
import { setStatus, reject, assign, getAssignee, REJECT_REASONS } from '../cases/store'
import type { Case, Building } from '../cases/types'
import { haptic, backButton, mainButton, hasMainButton, inTelegram } from '../stories/tg'
import { visibleCases, roleFromUrl, type Role } from './roles'
import { TEAM } from './team'
import Ask from './Ask'
import City from './City'
import Stories from '../stories/Stories'

/* Оболочка мини-аппа: Город — главный экран, из него Дела, Спросить, Отчёт.
   Возврат — родная стрелка телеграма, основное действие — родная кнопка. */

const EVI_LABEL: Record<Case['evidence'][number]['kind'], string> = {
  receipts: 'чеки', invoices: 'накладные', shifts: 'смены', reviews: 'отзывы',
}

type View = 'city' | 'feed' | 'ask' | 'report'

export default function App() {
  const { cases, loading, reload } = useCases()
  const [view, setView] = useState<View>('city')
  const [openId, setOpenId] = useState<string | null>(null)
  const [openBuilding, setOpenBuilding] = useState<{ key: Building; label: string } | null>(null)
  const { role, branch } = useMemo(roleFromUrl, [])

  const visible = useMemo(() => visibleCases(role, cases, branch), [role, cases, branch])
  const fresh = visible.filter((c) => c.status === 'new' || c.status === 'accepted')
  const total = fresh.reduce((s, c) => s + c.amount_kzt, 0)
  const opened = openId ? visible.find((c) => c.id === openId) ?? null : null

  // родная стрелка: с любого вью и из шторок — назад к городу
  useEffect(() => {
    if (opened) return backButton(() => setOpenId(null))
    if (openBuilding) return backButton(() => setOpenBuilding(null))
    if (view !== 'city') return backButton(() => setView('city'))
  }, [view, opened, openBuilding])

  if (view === 'report') return <Stories onExit={() => setView('feed')} />

  if (view === 'ask') {
    return (
      <div className="night night-app" style={{ minHeight: '100%' }}>
        <Ask cases={visible} onBack={() => setView('city')} />
      </div>
    )
  }

  if (view === 'city') {
    return (
      <>
        <City
          cases={visible}
          total={total}
          onOpenBuilding={(key, label) => setOpenBuilding({ key, label })}
          onAsk={() => setView('ask')}
          onReport={() => setView('report')}
          onFeed={() => setView('feed')}
        />
        {openBuilding && (
          <BuildingSheet
            label={openBuilding.label}
            cases={visible.filter((c) => buildingOf(c.node_id) === openBuilding.key && c.status !== 'rejected' && c.status !== 'closed')}
            onCase={(id) => { setOpenBuilding(null); setOpenId(id) }}
            onFeed={() => { setOpenBuilding(null); setView('feed') }}
            onClose={() => setOpenBuilding(null)}
          />
        )}
        {opened && (
          <CaseSheet c={opened} onClose={() => setOpenId(null)} onChange={() => { reload() }} />
        )}
      </>
    )
  }

  return (
    <div className="night night-app" style={{ minHeight: '100%' }}>
      <FeedScreen
        cases={visible} loading={loading} reload={reload}
        role={role} branch={branch}
        onAsk={() => setView('ask')}
        onBack={() => setView('city')}
      />
    </div>
  )
}

/* ── ДЕЛА: все проблемы и задачи, отсортированы по деньгам ─────────────── */

export function FeedScreen({ cases, loading, reload, role, branch, onAsk, onBack }: {
  cases: Case[]; loading: boolean; reload: () => void
  role: Role; branch: string | null
  onAsk: () => void; onBack?: () => void
}) {
  const [openId, setOpenId] = useState<string | null>(null)
  const fresh = cases.filter((c) => c.status === 'new' || c.status === 'accepted')
  const inWork = cases.filter((c) => c.status === 'auditing' || c.status === 'verifying')
  const closed = cases.filter((c) => c.status === 'closed')
  const rejected = cases.filter((c) => c.status === 'rejected')
  const total = fresh.reduce((s, c) => s + c.amount_kzt, 0)
  const opened = openId ? cases.find((c) => c.id === openId) ?? null : null

  return (
    <div className="ma-root">
      <header className="ma-head">
        <div className="ma-overline">
          {onBack && !inTelegram() && (
            <button className="ma-back inline" onClick={onBack} aria-label="К городу">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m15 18-6-6 6-6" /></svg>
            </button>
          )}
          {role === 'owner' ? 'Все филиалы' : branch ?? 'Филиал'} · демо-данные
        </div>
        <div className="ma-stake">
          {loading && cases.length === 0
            ? <span className="ma-sk ma-sk-stake" />
            : <>
                <span className="ma-stake-num">{kzt(total)}</span>
                <span className="ma-stake-sub">на кону по {fresh.length} открытым</span>
              </>}
        </div>
        <button className="ma-ask" onClick={() => { haptic('light'); onAsk() }}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="8" /><path d="m21 21-4.3-4.3" /></svg>
          <span>Спросить о деньгах</span>
        </button>
      </header>

      {role === 'waiter' && (
        <p className="ma-empty">Здесь появятся твои задачи по столам. Аналитика доступна владельцу.</p>
      )}

      {role !== 'waiter' && fresh.length === 0 && !loading && (
        <p className="ma-empty">Открытых проблем нет. Всё, что нашли, уже в работе.</p>
      )}

      {fresh.length > 0 && (
        <section className="ma-sec">
          <h2 className="ma-sec-title">Проблемы</h2>
          {fresh.map((c) => <CaseRow key={c.id} c={c} onOpen={() => { haptic('light'); setOpenId(c.id) }} />)}
        </section>
      )}

      {inWork.length > 0 && (
        <section className="ma-sec">
          <h2 className="ma-sec-title">В работе</h2>
          {inWork.map((c) => <WorkRow key={c.id} c={c} onOpen={() => setOpenId(c.id)} />)}
        </section>
      )}

      {closed.length > 0 && (
        <section className="ma-sec">
          <h2 className="ma-sec-title">Вернули</h2>
          {closed.map((c) => (
            <article key={c.id} className="ma-row">
              <div className="ma-row-over">{place(c)}</div>
              <div className="ma-row-title">{c.title}</div>
              <div className="ma-row-money gain">{kzt(c.amount_kzt)}</div>
            </article>
          ))}
        </section>
      )}

      {rejected.length > 0 && (
        <section className="ma-sec">
          <h2 className="ma-sec-title">Отклонено</h2>
          {rejected.map((c) => (
            <article key={c.id} className="ma-row muted">
              <div className="ma-row-over">{place(c)}</div>
              <div className="ma-row-title">{c.title}</div>
            </article>
          ))}
        </section>
      )}

      {opened && <CaseSheet c={opened} onClose={() => setOpenId(null)} onChange={reload} />}
    </div>
  )
}

function place(c: Case): string {
  return `${BUILDING_LABEL[buildingOf(c.node_id)]} · ${c.branch_id ?? 'все филиалы'}`
}

function CaseRow({ c, onOpen }: { c: Case; onOpen: () => void }) {
  return (
    <article className="ma-row tappable" onClick={onOpen} role="button" tabIndex={0}
      onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), onOpen())}>
      <div className="ma-row-over">{place(c)}</div>
      <div className="ma-row-title">{c.title}</div>
      <div className="ma-row-money loss">
        {kzt(c.amount_kzt)}
        <span className="ma-row-per"> в месяц</span>
      </div>
      <div className="ma-row-sub">
        {c.estimated
          ? `оценка · ${c.amount_low != null && c.amount_high != null ? kztRange(c.amount_low, c.amount_high) : 'приблизительно'}`
          : 'факт по первичке'}
        {' · '}{c.body}
      </div>
    </article>
  )
}

function WorkRow({ c, onOpen }: { c: Case; onOpen: () => void }) {
  const who = getAssignee(c.id)
  return (
    <article className="ma-row tappable" onClick={onOpen} role="button" tabIndex={0}
      onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), onOpen())}>
      <div className="ma-row-over">{place(c)}</div>
      <div className="ma-row-title">{c.title}</div>
      <div className="ma-row-sub">
        {who ? `Назначено: ${who}` : 'Взято в работу'} · проверяем, итог в отчёте недели
      </div>
    </article>
  )
}

/* Шторка здания: список проблем именно этого отдела, по убыванию денег */
export function BuildingSheet({ label, cases, onCase, onFeed, onClose }: {
  label: string; cases: Case[]
  onCase: (id: string) => void; onFeed: () => void; onClose: () => void
}) {
  return (
    <div className="ma-scrim night" onClick={onClose}>
      <div className="ma-sheet dark" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-label={label}>
        <div className="ma-sheet-grip" aria-hidden="true" />
        <div className="ma-row-over">{label}</div>
        {cases.length === 0 && <p className="ma-empty">Здесь сейчас чисто. Деньги не теряются.</p>}
        {cases.map((c) => (
          <article key={c.id} className="ma-row tappable" onClick={() => onCase(c.id)} role="button" tabIndex={0}
            onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), onCase(c.id))}>
            <div className="ma-row-title">{c.title}</div>
            <div className="ma-row-money loss">{kzt(c.amount_kzt)}<span className="ma-row-per"> в месяц</span></div>
          </article>
        ))}
        {cases.length > 0 && (
          <div className="ma-actions">
            <button className="ma-btn" onClick={onFeed}>Все дела</button>
          </div>
        )}
      </div>
    </div>
  )
}

export function CaseSheet({ c, onClose, onChange }: { c: Case; onClose: () => void; onChange: () => void }) {
  const [panel, setPanel] = useState<'none' | 'evidence' | 'assign' | 'reasons'>('none')
  const isOpen = c.status === 'new' || c.status === 'accepted'

  const take = () => { haptic('success'); setStatus(c.id, 'auditing'); onChange(); onClose() }
  const doAssign = (name: string) => { haptic('success'); assign(c.id, name); onChange(); onClose() }
  const doReject = (reason: string) => { haptic('medium'); reject(c.id, reason); onChange(); onClose() }

  // основное действие — родная кнопка телеграма
  useEffect(() => {
    if (!isOpen) return
    return mainButton('Взять в работу', take)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [c.id, isOpen])

  return (
    <div className="ma-scrim night" onClick={onClose}>
      <div className="ma-sheet dark" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-label={c.title}>
        <div className="ma-sheet-grip" aria-hidden="true" />
        <div className="ma-row-over">{place(c)}</div>
        <h3 className="ma-sheet-title">{c.title}</h3>
        <div className="ma-sheet-money loss">
          {kzt(c.amount_kzt)}<span className="ma-row-per"> в месяц</span>
        </div>
        <div className="ma-sheet-est">
          {c.estimated
            ? `Оценка: ${c.amount_low != null && c.amount_high != null ? kztRange(c.amount_low, c.amount_high) : 'приблизительно'}`
            : 'Факт, собран из первички'}
        </div>
        <p className="ma-sheet-body">{c.body}</p>

        {panel === 'evidence' && (
          <div className="ma-evi">
            {c.evidence.map((e, i) => (
              <div key={i} className="ma-evi-row">
                <span className="k">{EVI_LABEL[e.kind]}</span>
                <span>{e.label}</span>
              </div>
            ))}
            <div className="ma-evi-note">Первичка открывается из зеркала iiko построчно</div>
          </div>
        )}

        {panel === 'assign' && (
          <div className="ma-panel">
            {TEAM.map((m) => (
              <button key={m.id} className="ma-chip" onClick={() => doAssign(m.name)}>
                {m.name} · {m.role}
              </button>
            ))}
            <div className="ma-evi-note">Сообщение уйдёт назначенному лично, не в общий чат</div>
          </div>
        )}

        {panel === 'reasons' && (
          <div className="ma-panel">
            {REJECT_REASONS.map((r) => (
              <button key={r} className="ma-chip" onClick={() => doReject(r)}>{r}</button>
            ))}
          </div>
        )}

        {isOpen && (
          <div className="ma-actions">
            {!hasMainButton() && <button className="ma-btn primary" onClick={take}>Взять в работу</button>}
            <button className="ma-btn" onClick={() => setPanel(panel === 'assign' ? 'none' : 'assign')}>Назначить</button>
            <button className="ma-btn" onClick={() => setPanel(panel === 'evidence' ? 'none' : 'evidence')}>Показать чеки</button>
            <button className="ma-btn" onClick={() => setPanel(panel === 'reasons' ? 'none' : 'reasons')}>Не согласен</button>
          </div>
        )}
        {!isOpen && (
          <div className="ma-actions">
            <button className="ma-btn" onClick={() => setPanel(panel === 'evidence' ? 'none' : 'evidence')}>Показать чеки</button>
          </div>
        )}
      </div>
    </div>
  )
}
