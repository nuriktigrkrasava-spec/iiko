import type { CaseStatus } from './types'

/* Статусы кейсов. В этом слое — localStorage (демо). В бэкенд-фазу переедет
   в Postgres `cases`, общий с Telegram. Интерфейс не меняется. */

const KEY = 'iiko.cases.status'

type Rec = { status: CaseStatus; reason?: string; assignee?: string }
type Store = Record<string, Rec>

function read(): Store {
  try {
    return JSON.parse(localStorage.getItem(KEY) || '{}') as Store
  } catch {
    return {}
  }
}
function write(s: Store) {
  try {
    localStorage.setItem(KEY, JSON.stringify(s))
  } catch { /* приватный режим — молча */ }
}

export function getStatus(id: string): CaseStatus {
  return read()[id]?.status ?? 'new'
}
export function getReason(id: string): string | undefined {
  return read()[id]?.reason
}
export function setStatus(id: string, status: CaseStatus) {
  const s = read()
  s[id] = { ...s[id], status }
  write(s)
}
export function reject(id: string, reason: string) {
  const s = read()
  s[id] = { status: 'rejected', reason }
  write(s)
}

/* Назначение: человек получает задачу лично (сообщение шлёт бот-слой).
   Кейс переходит в работу тем же статусом, что и «взять самому». */
export function assign(id: string, assignee: string) {
  const s = read()
  s[id] = { ...s[id], status: 'auditing', assignee }
  write(s)
}
export function getAssignee(id: string): string | undefined {
  return read()[id]?.assignee
}

/* Причины отказа — тренировочный сигнал: правило, отклонённое трижды по одной
   причине, понижается в приоритете (в бэкенд-фазе). */
export const REJECT_REASONS = [
  'Перерасход объясним',
  'Данные неверны',
  'Уже решаю',
  'Не моя зона',
  'Другое',
] as const
