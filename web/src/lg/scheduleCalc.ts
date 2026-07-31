/* Логика расписания: план у нас, факт из явок iiko. Чистые функции — тестируются
   отдельно от UI. Время — строки 'HH:MM'; факт приходит уже свёрнутым по дню. */

export type Shift = { employeeId: string; date: string; start: string; end: string }
export type Fact = { employeeId: string; date: string; start: string; end: string }

export type CompareStatus = 'ontime' | 'late' | 'absent' | 'noplan'
export type Compare = { status: CompareStatus; lateMin: number; overtimeMin: number }

const toMin = (t: string): number => {
  const [h, m] = t.split(':').map(Number)
  return h * 60 + m
}

/** Длина смены в минутах; конец ≤ начала трактуется как переход через полночь. */
export function shiftMinutes(start: string, end: string): number {
  const s = toMin(start)
  let e = toMin(end)
  if (e <= s) e += 24 * 60
  return e - s
}

/** Сверяет плановую смену с фактической явкой. lateGraceMin — допуск на опоздание. */
export function comparePlanFact(
  plan: Shift | null,
  fact: Fact | null,
  lateGraceMin = 5,
): Compare {
  if (!plan && fact) return { status: 'noplan', lateMin: 0, overtimeMin: 0 }
  if (!plan || !fact) return { status: 'absent', lateMin: 0, overtimeMin: 0 }

  const lateMin = Math.max(0, toMin(fact.start) - toMin(plan.start))
  const overtimeMin = Math.max(0, toMin(fact.end) - toMin(plan.end))
  const status = lateMin > lateGraceMin ? 'late' : 'ontime'
  return { status, lateMin, overtimeMin }
}
