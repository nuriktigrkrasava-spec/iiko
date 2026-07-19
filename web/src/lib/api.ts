// Живой бэкенд: FastAPI api.py. Демо-организация "demo-org-1" всегда отдаёт
// демо-данные (см. _use_demo_data в api.py) — без Telegram-авторизации.
export const ORG = 'demo-org-1'

export type Period = 'today' | 'yesterday' | 'week' | 'month'

export async function apiGet<T>(
  path: string,
  params: Record<string, string> = {},
): Promise<T> {
  const qs = new URLSearchParams(params).toString()
  const url = `/api/${path}/${ORG}${qs ? `?${qs}` : ''}`
  const res = await fetch(url, { headers: { Accept: 'application/json' } })
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`)
  return res.json() as Promise<T>
}
