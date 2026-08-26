import { isoWeekOf, mondayOfWeek, shiftWeek } from './planWeek'

const iso = (d: Date) => d.toISOString().slice(0, 10)

describe('недели ISO во вкладке «План»', () => {
  it('номер недели совпадает с нумерацией в таблице владельца', () => {
    expect(isoWeekOf(new Date(2026, 7, 25))).toBe('2026-W35')
    expect(iso(mondayOfWeek('2026-W35'))).toBe('2026-08-24')
  })

  it('воскресенье остаётся в своей неделе, понедельник начинает следующую', () => {
    expect(isoWeekOf(new Date(2026, 7, 30))).toBe('2026-W35')
    expect(isoWeekOf(new Date(2026, 7, 31))).toBe('2026-W36')
  })

  it('переход через новый год не теряет неделю', () => {
    // 2026-W53 существует: 2026 год начинается с четверга
    expect(shiftWeek('2027-W01', -1)).toBe('2026-W53')
    expect(shiftWeek('2026-W53', 1)).toBe('2027-W01')
  })

  it('шаг вперёд и назад возвращает на место', () => {
    for (const w of ['2026-W01', '2026-W35', '2026-W52']) {
      expect(shiftWeek(shiftWeek(w, 1), -1)).toBe(w)
    }
  })

  it('понедельник недели — всегда понедельник', () => {
    for (const w of ['2026-W01', '2026-W09', '2026-W35', '2026-W53']) {
      expect(mondayOfWeek(w).getUTCDay()).toBe(1)
    }
  })
})
