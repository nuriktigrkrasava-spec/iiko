import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '../index.css'
import LiquidApp from '../lg/LiquidApp'
import { tgInit, colorScheme, onThemeChange } from '../stories/tg'

/* Мини-апп рендерит тот же продукт, что и сайт: одни вкладки, одни экраны.
   TG-инициализация и синхронизация темы поверх. */
function syncTheme() {
  document.documentElement.dataset.appTheme = colorScheme()
}

tgInit()
syncTheme()
onThemeChange(syncTheme)

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <LiquidApp />
  </StrictMode>,
)
