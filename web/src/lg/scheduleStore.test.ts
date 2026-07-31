import { getPlan, setShift, removeShift, shiftFor } from './scheduleStore'

beforeEach(() => localStorage.clear())

describe('scheduleStore', () => {
  it('пустой план в начале', () => {
    expect(getPlan()).toEqual([])
  })
  it('ставит смену и находит её по сотруднику и дню', () => {
    setShift({ employeeId: 'e1', date: '2026-07-20', start: '10:00', end: '18:00' })
    expect(shiftFor('e1', '2026-07-20')).toEqual({
      employeeId: 'e1', date: '2026-07-20', start: '10:00', end: '18:00',
    })
  })
  it('повтор для того же дня перезаписывает, а не дублирует', () => {
    setShift({ employeeId: 'e1', date: '2026-07-20', start: '10:00', end: '18:00' })
    setShift({ employeeId: 'e1', date: '2026-07-20', start: '11:00', end: '19:00' })
    expect(getPlan()).toHaveLength(1)
    expect(shiftFor('e1', '2026-07-20')?.start).toBe('11:00')
  })
  it('удаляет смену', () => {
    setShift({ employeeId: 'e1', date: '2026-07-20', start: '10:00', end: '18:00' })
    removeShift('e1', '2026-07-20')
    expect(shiftFor('e1', '2026-07-20')).toBeNull()
  })
})
