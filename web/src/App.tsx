import { useState } from 'react'
import type { ReactNode } from 'react'
import type { Period } from './lib/api'
import Insights from './screens/Insights'
import Dashboard from './screens/Dashboard'
import Comparison from './screens/Comparison'
import Foodcost from './screens/Foodcost'
import Expenses from './screens/Expenses'
import Shifts from './screens/Shifts'
import Anomalies from './screens/Anomalies'
import Reviews from './screens/Reviews'

type Screen = {
  id: string
  label: string
  group: string
  render: (p: Period, nav: (id: string) => void) => ReactNode
  periodic: boolean
}

const SCREENS: Screen[] = [
  { id: 'ai',     label: 'Аналитика',  group: 'Сводка',    periodic: false, render: (_p, nav) => <Insights onOpen={nav} /> },
  { id: 'dash',   label: 'Главная',    group: 'Сводка',    periodic: true,  render: (p) => <Dashboard period={p} /> },
  { id: 'fc',     label: 'Фудкост',    group: 'Деньги',    periodic: true,  render: (p) => <Foodcost period={p} /> },
  { id: 'exp',    label: 'Расходы',    group: 'Деньги',    periodic: true,  render: (p) => <Expenses period={p} /> },
  { id: 'yoy',    label: 'Год к году', group: 'Деньги',    periodic: false, render: () => <Comparison /> },
  { id: 'shifts', label: 'Смены',      group: 'Операции',  periodic: true,  render: (p) => <Shifts period={p} /> },
  { id: 'anom',   label: 'Аномалии',   group: 'Операции',  periodic: true,  render: (p) => <Anomalies period={p} /> },
  { id: 'rev',    label: 'Соцсети',    group: 'Оценки',    periodic: false, render: () => <Reviews /> },
]

const GROUPS = ['Сводка', 'Деньги', 'Операции', 'Оценки']

const PERIODS: { id: Period; label: string }[] = [
  { id: 'today', label: 'Сегодня' },
  { id: 'yesterday', label: 'Вчера' },
  { id: 'week', label: 'Неделя' },
  { id: 'month', label: 'Месяц' },
]

export default function App() {
  const [active, setActive] = useState('ai')
  const [period, setPeriod] = useState<Period>('month')
  const screen = SCREENS.find((s) => s.id === active)!

  return (
    <div className="flex min-h-screen bg-paper">
      <aside className="sticky top-0 hidden h-screen w-56 shrink-0 flex-col border-r border-rule md:flex">
        <div className="border-b border-ink px-5 py-5">
          <div className="font-display text-[17px] leading-tight">iiko Финдиректор</div>
          <div className="mt-0.5 text-[11px] text-muted">Демо Ресторан · Алматы</div>
        </div>

        <nav className="flex-1 overflow-y-auto px-3 py-4">
          {GROUPS.map((g) => {
            const items = SCREENS.filter((s) => s.group === g)
            if (items.length === 0) return null
            return (
              <div key={g} className="mb-5">
                <div className="eyebrow px-2 pb-2">{g}</div>
                {items.map((s) => (
                  <button
                    key={s.id}
                    onClick={() => setActive(s.id)}
                    className={`block w-full cursor-pointer px-2 py-1.5 text-left text-[13px] transition-colors ${
                      s.id === active
                        ? 'border-l-2 border-neg font-semibold text-ink'
                        : 'border-l-2 border-transparent text-ink2 hover:text-ink'
                    }`}
                  >
                    {s.label}
                  </button>
                ))}
              </div>
            )
          })}
        </nav>

        <div className="border-t border-rule px-5 py-4 text-[11px] text-muted">
          данные примерные · демо-режим
        </div>
      </aside>

      <main className="min-w-0 flex-1">
        <header className="sticky top-0 z-10 flex flex-wrap items-baseline justify-between gap-3 border-b-2 border-ink bg-paper px-8 py-4">
          <h1 className="font-display text-[19px]">{screen.label}</h1>
          {screen.periodic && (
            <div className="flex items-center gap-4">
              {PERIODS.map((p) => (
                <button
                  key={p.id}
                  onClick={() => setPeriod(p.id)}
                  className={`eyebrow cursor-pointer pb-0.5 transition-colors ${
                    period === p.id
                      ? 'border-b-2 border-neg text-ink'
                      : 'border-b-2 border-transparent hover:text-ink'
                  }`}
                >
                  {p.label}
                </button>
              ))}
            </div>
          )}
        </header>

        <div className="mx-auto max-w-4xl px-8 pb-16">{screen.render(period, setActive)}</div>
      </main>
    </div>
  )
}
