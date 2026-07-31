import { useMemo } from 'react'
import '../miniapp/app.css'
import { FeedScreen } from '../miniapp/App'
import Ask from '../miniapp/Ask'
import { useCases } from '../cases/generate'
import { visibleCases, roleFromUrl } from '../miniapp/roles'
import { goSection } from './CityScreen'

/* Ночные вкладки сайта: Лента и Разговор в той же теме, что Город и Отчёт.
   Одни компоненты с мини-аппом — одна тематика везде. */

const wrap: React.CSSProperties = {
  gridColumn: '1 / -1',
  borderRadius: 16,
  overflow: 'hidden',
  minHeight: 'min(78vh, 720px)',
}

export function NightFeed() {
  const { cases, loading, reload } = useCases()
  const { role, branch } = useMemo(roleFromUrl, [])
  const visible = useMemo(() => visibleCases(role, cases, branch), [role, cases, branch])
  return (
    <div className="night night-app" style={wrap}>
      <FeedScreen
        cases={visible} loading={loading} reload={reload}
        role={role} branch={branch}
        onAsk={() => goSection('ask')}
      />
    </div>
  )
}

export function NightAsk() {
  const { cases } = useCases()
  const { role, branch } = useMemo(roleFromUrl, [])
  const visible = useMemo(() => visibleCases(role, cases, branch), [role, cases, branch])
  return (
    <div className="night night-app" style={wrap}>
      <Ask cases={visible} />
    </div>
  )
}
