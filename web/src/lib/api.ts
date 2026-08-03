// Живой бэкенд: FastAPI api.py. Демо-организация "demo-org-1" всегда отдаёт
// демо-данные (см. _use_demo_data в api.py) — без Telegram-авторизации.
// Выбор филиала: ORG динамический (getOrg/setOrg), useApi перезапрашивает при смене.
import { BAKED } from './bakedData'

export type Period = 'today' | 'yesterday' | 'week' | 'month'
export type Branch = { organization_id: string; organization_name?: string; name?: string }

const BAKED_MODE = import.meta.env.VITE_BAKED === '1'
const DEMO_ORG = 'demo-org-1'

// ── текущий выбранный филиал (org) + подписка на смену ──
// В baked — сразу демо. В реальном режиме стартуем «не выбран» (''), чтобы НЕ мигать
// демо-данными: useApi ждёт, пока BranchSwitcher поставит первый реальный филиал.
let currentOrg = BAKED_MODE ? DEMO_ORG : ''
const listeners = new Set<() => void>()
export function getOrg() { return currentOrg }
export function setOrg(id: string) { if (id && id !== currentOrg) { currentOrg = id; listeners.forEach((l) => l()) } }
export function onOrgChange(fn: () => void) { listeners.add(fn); return () => { listeners.delete(fn) } }
export const ORG = DEMO_ORG // обратная совместимость

// ── глобальный период (тот же паттерн, что и org) ──
// периодичные экраны НЕ шлют period в useApi → берут отсюда и перезапрашивают при смене.
// экраны с фиксированным периодом (Home «сегодня») передают period явно и игнорируют это.
let currentPeriod: Period = 'month'
const periodListeners = new Set<() => void>()
export function getPeriod(): Period { return currentPeriod }
export function setPeriod(p: Period) { if (p && p !== currentPeriod) { currentPeriod = p; periodListeners.forEach((l) => l()) } }
export function onPeriodChange(fn: () => void) { periodListeners.add(fn); return () => { periodListeners.delete(fn) } }
// человекочитаемый ярлык текущего периода (для подписей/eyebrow)
const PERIOD_LABELS: Record<Period, string> = { today: 'сегодня', yesterday: 'вчера', week: 'за неделю', month: 'за месяц' }
export function periodLabel(): string { return PERIOD_LABELS[currentPeriod] }

// данные демо (офлайн-сборка или демо-организация), а не реальный iiko
export function isDemoData() { return BAKED_MODE || currentOrg === DEMO_ORG }

// в демо/baked — только один демо-ресторан (без выдуманных чужих филиалов).
// реальные филиалы появляются лишь после подключения своего аккаунта (/api/restaurants, изоляция по юзеру).
const DEMO_BRANCHES: Branch[] = [
  { organization_id: 'demo-org-1', organization_name: 'Демо-ресторан' },
]

export async function getBranches(): Promise<Branch[]> {
  if (BAKED_MODE) return DEMO_BRANCHES
  try {
    const res = await fetch('/api/restaurants', { headers: { Accept: 'application/json' } })
    if (!res.ok) throw new Error(String(res.status))
    const data = await res.json()
    return Array.isArray(data) && data.length ? data : DEMO_BRANCHES
  } catch { return DEMO_BRANCHES }
}

export async function apiGet<T>(path: string, params: Record<string, string> = {}): Promise<T> {
  const qs = new URLSearchParams(params).toString()
  const org = currentOrg
  const url = `/api/${path}/${org}${qs ? `?${qs}` : ''}`
  if (BAKED_MODE) {
    // в baked данные вшиты только под demo-org-1 — любой филиал показывает демо (для демонстрации выбора)
    const demoUrl = `/api/${path}/${DEMO_ORG}${qs ? `?${qs}` : ''}`
    const hit = BAKED[url] ?? BAKED[`/api/${path}/${org}`] ?? BAKED[demoUrl] ?? BAKED[`/api/${path}/${DEMO_ORG}`]
    if (hit !== undefined) return Promise.resolve(hit as T)
    throw new Error(`${path}: нет вшитых данных`)
  }
  const res = await fetch(url, { headers: { Accept: 'application/json' } })
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`)
  return res.json() as Promise<T>
}
