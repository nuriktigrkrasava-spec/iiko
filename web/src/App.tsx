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
import {
  LayoutDashboard, TrendingUp, ChefHat, Wallet, Users, TriangleAlert, Star, Sparkles,
} from 'lucide-react'

type Screen = {
  id: string
  label: string
  icon: typeof LayoutDashboard
  render: (p: Period, nav: (id: string) => void) => ReactNode
  periodic: boolean
}

const SCREENS: Screen[] = [
  { id: 'ai', label: 'Аналитика', icon: Sparkles, periodic: false, render: (_p, nav) => <Insights onOpen={nav} /> },
  { id: 'dash', label: 'Главная', icon: LayoutDashboard, periodic: true, render: (p) => <Dashboard period={p} /> },
  { id: 'yoy', label: 'Год к году', icon: TrendingUp, periodic: false, render: () => <Comparison /> },
  { id: 'fc', label: 'Фудкост', icon: ChefHat, periodic: true, render: (p) => <Foodcost period={p} /> },
  { id: 'exp', label: 'Расходы', icon: Wallet, periodic: true, render: (p) => <Expenses period={p} /> },
  { id: 'shifts', label: 'Смены', icon: Users, periodic: true, render: (p) => <Shifts period={p} /> },
  { id: 'anom', label: 'Аномалии', icon: TriangleAlert, periodic: true, render: (p) => <Anomalies period={p} /> },
  { id: 'rev', label: 'Отзывы', icon: Star, periodic: false, render: () => <Reviews /> },
]

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
    <div className="flex min-h-screen">
      {/* Sidebar */}
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-border bg-panel/60 backdrop-blur-md md:flex">
        <div className="flex items-center gap-2.5 px-5 py-5">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary/15 text-primary2">
            <TrendingUp size={18} />
          </div>
          <div className="leading-tight">
            <div className="text-sm font-semibold text-ink">iiko Финдиректор</div>
            <div className="text-[11px] text-faint">аналитика ресторана</div>
          </div>
        </div>

        <nav className="mt-2 flex-1 space-y-0.5 px-3">
          {SCREENS.map((s) => {
            const Icon = s.icon
            const on = s.id === active
            return (
              <button
                key={s.id}
                onClick={() => setActive(s.id)}
                className={`flex w-full cursor-pointer items-center gap-3 rounded-xl px-3 py-2.5 text-sm transition-colors ${
                  on ? 'bg-primary/15 text-ink' : 'text-muted hover:bg-panel2 hover:text-ink'
                }`}
              >
                <Icon size={17} className={on ? 'text-primary2' : ''} />
                {s.label}
              </button>
            )
          })}
        </nav>

        <div className="border-t border-border px-5 py-4">
          <div className="flex items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-pos" />
            <span className="text-xs text-muted">Демо Ресторан</span>
          </div>
          <div className="mt-1 text-[11px] text-faint">данные примерные · демо-режим</div>
        </div>
      </aside>

      {/* Main */}
      <main className="min-w-0 flex-1">
        <header className="sticky top-0 z-10 flex flex-wrap items-center justify-between gap-3 border-b border-border bg-bg/80 px-6 py-4 backdrop-blur-md">
          <div>
            <h1 className="text-lg font-semibold text-ink">{screen.label}</h1>
            <div className="text-xs text-faint">Демо Ресторан · Алматы</div>
          </div>
          {screen.periodic && (
            <div className="flex items-center gap-1 rounded-xl border border-border bg-panel/70 p-1">
              {PERIODS.map((p) => (
                <button
                  key={p.id}
                  onClick={() => setPeriod(p.id)}
                  className={`cursor-pointer rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
                    period === p.id ? 'bg-primary text-white' : 'text-muted hover:text-ink'
                  }`}
                >
                  {p.label}
                </button>
              ))}
            </div>
          )}
        </header>

        <div className="mx-auto max-w-5xl px-6 py-6">
          {screen.render(period, setActive)}
        </div>
      </main>
    </div>
  )
}
