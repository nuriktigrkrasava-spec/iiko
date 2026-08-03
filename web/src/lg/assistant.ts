export type AdviceAction = { type: 'navigate' | 'showMetric'; tab: string; hint?: string | null }
export type Advice = {
  id: string; branch: string; severity: 'high' | 'med' | 'low'
  title: string; detail: string; money: number | null; action?: AdviceAction | null
}
export type AssistantResp = { advice: Advice[]; count: number; demo: boolean }

// белый список действий — исполняем только известные типы
export function runAction(a: AdviceAction): void {
  if (a.type === 'navigate' || a.type === 'showMetric') {
    window.dispatchEvent(new CustomEvent('lg:go', { detail: a.tab }))
    // showMetric: подсветка целевого показателя — Фаза 3 (пока просто навигация)
  }
}
