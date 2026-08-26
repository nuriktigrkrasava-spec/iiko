import { shiftMinutes, comparePlanFact } from './scheduleCalc'
import type { Shift, Fact } from './scheduleCalc'

describe('shiftMinutes', () => {
  it('считает длину дневной смены в минутах', () => {
    expect(shiftMinutes('10:00', '18:00')).toBe(480)
  })
  it('понимает ночную смену через полночь', () => {
    expect(shiftMinutes('22:00', '02:00')).toBe(240)
  })
})

const plan: Shift = { employeeId: 'e1', date: '2026-07-20', start: '10:00', end: '18:00' }

describe('comparePlanFact', () => {
  it('опоздание сверх допуска и переработка', () => {
    const fact: Fact = { employeeId: 'e1', date: '2026-07-20', start: '10:14', end: '18:20' }
    const r = comparePlanFact(plan, fact)
    expect(r.status).toBe('late')
    expect(r.lateMin).toBe(14)
    expect(r.overtimeMin).toBe(20)
  })
  it('приход в пределах допуска — вовремя', () => {
    const fact: Fact = { employeeId: 'e1', date: '2026-07-20', start: '10:03', end: '18:00' }
    const r = comparePlanFact(plan, fact)
    expect(r.status).toBe('ontime')
    expect(r.overtimeMin).toBe(0)
  })
  it('есть план, нет факта — прогул', () => {
    expect(comparePlanFact(plan, null).status).toBe('absent')
  })
  it('есть факт, нет плана — вне графика', () => {
    const fact: Fact = { employeeId: 'e1', date: '2026-07-20', start: '11:00', end: '15:00' }
    expect(comparePlanFact(null, fact).status).toBe('noplan')
  })
})
