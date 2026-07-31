import { useEffect, useState } from 'react'
import type { ReactElement } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import './lg.css'
import { container } from './ui'
import { Icon } from './icons'
import { Dash, FC, Exp, YoY, Staff, Anom } from './screens'
import Analytics from './Analytics'
import Clients from './Clients'
import Reputation from './Reputation'
import Menu from './Menu'
import Supply from './Supply'
import Report from './Report'
import Seating from './Seating'
import Island from './Island'
import CityScreen from './CityScreen'
import Schedule from './Schedule'
import { NightFeed, NightAsk } from './NightSections'

type Sec = { id: string; group: string; label: string; icon: string; badge?: string; periodic: boolean; render: () => ReactElement }

const SECTIONS: Sec[] = [
  { id: 'feed', group: 'Очередь', label: 'Лента', icon: 'feed', periodic: false, render: NightFeed },
  { id: 'ask', group: 'Очередь', label: 'Разговор', icon: 'ask', periodic: false, render: NightAsk },
  { id: 'city', group: 'Витрина', label: 'Город', icon: 'island', periodic: false, render: CityScreen },
  { id: 'island', group: 'Витрина', label: 'Остров', icon: 'island', periodic: false, render: Island },
  { id: 'mocks', group: 'Витрина', label: 'Отчёт недели', icon: 'mocks', periodic: false, render: Report },
  { id: 'ai', group: 'Сводка', label: 'Аналитика', icon: 'ai', badge: 'var(--red)', periodic: false, render: Analytics },
  { id: 'dash', group: 'Сводка', label: 'Главная', icon: 'dash', periodic: true, render: Dash },
  { id: 'fc', group: 'Деньги', label: 'Фудкост', icon: 'fc', badge: 'var(--amb)', periodic: true, render: FC },
  { id: 'menu', group: 'Деньги', label: 'Меню · продажи', icon: 'menu', periodic: false, render: Menu },
  { id: 'exp', group: 'Деньги', label: 'Расходы', icon: 'exp', periodic: true, render: Exp },
  { id: 'supply', group: 'Деньги', label: 'Склад · заявки', icon: 'supply', badge: 'var(--red)', periodic: false, render: Supply },
  { id: 'yoy', group: 'Деньги', label: 'Год к году', icon: 'yoy', periodic: false, render: YoY },
  { id: 'seat', group: 'Операции', label: 'Посадка зала', icon: 'seat', badge: 'var(--grn)', periodic: false, render: Seating },
  { id: 'staff', group: 'Операции', label: 'Смены и персонал', icon: 'staff', periodic: true, render: Staff },
  { id: 'sched', group: 'Операции', label: 'Расписание', icon: 'sched', periodic: false, render: Schedule },
  { id: 'anom', group: 'Операции', label: 'Аномалии', icon: 'anom', badge: 'var(--amb)', periodic: true, render: Anom },
  { id: 'clients', group: 'Гости', label: 'Клиенты · RFM', icon: 'clients', badge: 'var(--grn)', periodic: false, render: Clients },
  { id: 'rep', group: 'Гости', label: 'Соцсети', icon: 'rep', periodic: false, render: Reputation },
]
const TABS = ['feed', 'city', 'ask', 'ai', 'dash']
const PRIMARY = ['feed', 'city', 'ask']
const PERIODS = [['today', 'Сегодня'], ['yesterday', 'Вчера'], ['week', 'Неделя'], ['month', 'Месяц']] as const

export default function LiquidApp() {
  const [active, setActive] = useState('feed')
  const [period, setPeriod] = useState('month')
  const [dark, setDark] = useState(true)
  const [more, setMore] = useState(false)

  // «Город» и другие экраны просят переключить вкладку событием
  useEffect(() => {
    const go = (e: Event) => setActive((e as CustomEvent<string>).detail)
    window.addEventListener('lg:go', go)
    return () => window.removeEventListener('lg:go', go)
  }, [])
  const sec = SECTIONS.find((s) => s.id === active)!
  const Body = sec.render
  const onFeed = active === 'feed'

  function toggleTheme() {
    const next = !dark
    setDark(next)
    document.documentElement.setAttribute('data-theme', next ? 'dark' : 'light')
  }

  const dockBtn = (s: Sec) => (
    <button key={s.id} onClick={() => setActive(s.id)} className={`lg-dock-btn ${active === s.id ? 'on' : ''}`} aria-label={s.label}>
      {active === s.id && <motion.span layoutId="dock" className="lg-dock-pill" transition={{ type: 'spring', stiffness: 340, damping: 30 }} />}
      <span style={{ position: 'relative', zIndex: 1, display: 'grid', placeItems: 'center' }}><Icon k={s.icon} size={19} /></span>
      {s.badge && <span className="lg-dock-badge" style={{ background: s.badge }} />}
      <span className="lg-dock-label">{s.label}</span>
    </button>
  )

  return (
    <div className={`lg-root ${onFeed ? 'on-feed' : ''}`} style={{ minHeight: '100vh' }}>
      <div className="lg-wallpaper" aria-hidden />
      <div className="lg-grain" aria-hidden />
      {onFeed && <div className="cs-desk" aria-hidden />}
      {/* SVG-фильтр преломления стекла (21st-техника) */}
      <svg style={{ position: 'absolute', width: 0, height: 0 }} aria-hidden>
        <filter id="lg-glass" x="-20%" y="-20%" width="140%" height="140%" colorInterpolationFilters="sRGB">
          <feTurbulence type="fractalNoise" baseFrequency="0.006 0.010" numOctaves="2" seed="12" result="n" />
          <feGaussianBlur in="n" stdDeviation="1" result="nb" />
          <feDisplacementMap in="SourceGraphic" in2="nb" scale="58" xChannelSelector="R" yChannelSelector="G" result="d" />
          <feGaussianBlur in="d" stdDeviation="7" />
        </filter>
      </svg>

      {/* Основная (на всю ширину — меню ушло в нижний док) */}
      <main style={{ minWidth: 0, display: 'flex', flexDirection: 'column' }}>
        {active !== 'mocks' && active !== 'island' && active !== 'feed' && active !== 'city' && active !== 'ask' && (
          <header className="lg-head">
            <div>
              <div style={{ fontSize: 9.5, letterSpacing: '.14em', textTransform: 'uppercase', color: 'var(--mute)', fontWeight: 600 }}>{sec.group}</div>
              <motion.h1 key={sec.id} className="display" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} style={{ margin: '2px 0 0', fontSize: 32, lineHeight: 1.04 }}>{sec.label}</motion.h1>
            </div>
            {sec.periodic && (
              <div className="lg-seg">
                {PERIODS.map((p) => (
                  <button key={p[0]} onClick={() => setPeriod(p[0])} className={`lg-per ${period === p[0] ? 'on' : ''}`}>
                    {period === p[0] && <motion.span layoutId="seg" className="lg-seg-pill" transition={{ type: 'spring', stiffness: 320, damping: 30 }} />}
                    <span style={{ position: 'relative', zIndex: 1 }}>{p[1]}</span>
                  </button>
                ))}
              </div>
            )}
          </header>
        )}

        <div style={{ padding: '24px 40px 130px', maxWidth: 1360, width: '100%', margin: '0 auto' }}>
          <AnimatePresence mode="wait">
            <motion.div key={active} variants={container} initial="hidden" animate="show" exit={{ opacity: 0, y: -8, transition: { duration: 0.18 } }}
              style={{ display: 'grid', gridTemplateColumns: 'repeat(12,1fr)', gap: 16, alignItems: 'stretch' }} className="lg-bento">
              <Body />
            </motion.div>
          </AnimatePresence>
        </div>
      </main>

      {/* Нижний плавающий стеклянный док (десктоп) — вся навигация */}
      <nav className="lg-dock glass warp" aria-label="Разделы">
        <span className="lg-dock-brand">iiko</span>
        <span className="lg-dock-sep" />
        {PRIMARY.map((id) => dockBtn(SECTIONS.find((s) => s.id === id)!))}
        <button className={`lg-dock-btn ${more ? 'on' : ''}`} onClick={() => setMore((v) => !v)} aria-label="Ещё разделы">
          <span style={{ position: 'relative', zIndex: 1, display: 'grid', placeItems: 'center' }}><Icon k="more" size={19} /></span>
          <span className="lg-dock-label">Ещё</span>
        </button>
        {more && (
          <>
            <span className="lg-dock-sep" />
            {SECTIONS.filter((s) => !PRIMARY.includes(s.id)).map(dockBtn)}
          </>
        )}
        <span className="lg-dock-sep" />
        <button onClick={toggleTheme} className="lg-dock-btn" aria-label="Сменить тему">
          <span style={{ position: 'relative', zIndex: 1, fontSize: 17 }}>{dark ? '◐' : '◑'}</span>
          <span className="lg-dock-label">{dark ? 'Ночь' : 'День'}</span>
        </button>
      </nav>

      {/* Таб-бар (телефон) */}
      <nav className="lg-tabbar glass">
        {TABS.map((id) => {
          const s = SECTIONS.find((x) => x.id === id)!
          return (
            <button key={id} onClick={() => setActive(id)} className={`lg-tab ${active === id ? 'on' : ''}`}>
              <Icon k={s.icon} /><span>{s.label}</span>
            </button>
          )
        })}
      </nav>
    </div>
  )
}
