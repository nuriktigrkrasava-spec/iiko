// Живой бэкенд: FastAPI api.py. Демо-организация "demo-org-1" всегда отдаёт
// демо-данные (см. _use_demo_data в api.py) — без Telegram-авторизации.
import { BAKED } from './bakedData'

export const ORG = 'demo-org-1'

export type Period = 'today' | 'yesterday' | 'week' | 'month'

// офлайн-сборка одним файлом: данные вшиты, сеть не нужна
const BAKED_MODE = import.meta.env.VITE_BAKED === '1'

export async function apiGet<T>(
  path: string,
  params: Record<string, string> = {},
): Promise<T> {
  const qs = new URLSearchParams(params).toString()
  const url = `/api/${path}/${ORG}${qs ? `?${qs}` : ''}`
  if (BAKED_MODE) {
    const hit = BAKED[url] ?? BAKED[`/api/${path}/${ORG}`]
    if (hit !== undefined) return Promise.resolve(hit as T)
    throw new Error(`${path}: нет вшитых данных`)
  }
  const res = await fetch(url, { headers: { Accept: 'application/json' } })
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`)
  return res.json() as Promise<T>
}
