import type { Shift } from './scheduleCalc'

/* План (расписание) в этом слое — localStorage (демо-мини-апп). В бэкенд-фазу
   переедет в таблицу schedule, общую с Telegram. Интерфейс не меняется —
   ровно как задумано в cases/store.ts. Одна плановая смена на (сотрудник, день). */

export type PlanShift = Shift

const KEY = 'iiko.schedule.v1'
const idOf = (employeeId: string, date: string) => `${employeeId}|${date}`

function read(): Record<string, PlanShift> {
  try {
    return JSON.parse(localStorage.getItem(KEY) || '{}') as Record<string, PlanShift>
  } catch {
    return {}
  }
}
function write(s: Record<string, PlanShift>) {
  try {
    localStorage.setItem(KEY, JSON.stringify(s))
  } catch { /* приватный режим — молча */ }
}

export function getPlan(): PlanShift[] {
  return Object.values(read())
}

export function shiftFor(employeeId: string, date: string): PlanShift | null {
  return read()[idOf(employeeId, date)] ?? null
}

export function setShift(s: PlanShift) {
  const all = read()
  all[idOf(s.employeeId, s.date)] = s
  write(all)
}

export function removeShift(employeeId: string, date: string) {
  const all = read()
  delete all[idOf(employeeId, date)]
  write(all)
}
