/* Недели ISO для вкладки «План». Нумерация та же, что в таблице владельца
   («Неделя 35»), поэтому считаем по ISO, а не по семидневкам от 1-го числа.
   Вынесено из экрана: арифметика недель на границе года ошибается тихо. */

/** Дата → 'YYYY-Www'. Год берётся у четверга недели — так устроен ISO,
    иначе 31 декабря уезжало бы в первую неделю прошлого года. */
export function isoWeekOf(d: Date): string {
  const x = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()))
  x.setUTCDate(x.getUTCDate() + 4 - (x.getUTCDay() || 7))
  const y0 = new Date(Date.UTC(x.getUTCFullYear(), 0, 1))
  const n = Math.ceil(((x.getTime() - y0.getTime()) / 86400000 + 1) / 7)
  return `${x.getUTCFullYear()}-W${String(n).padStart(2, '0')}`
}

/** Понедельник недели 'YYYY-Www' (UTC-полночь). */
export function mondayOfWeek(week: string): Date {
  const [y, w] = week.split('-W').map(Number)
  const jan4 = new Date(Date.UTC(y, 0, 4))
  const mon = new Date(jan4)
  mon.setUTCDate(jan4.getUTCDate() - ((jan4.getUTCDay() || 7) - 1) + (w - 1) * 7)
  return mon
}

/** Соседняя неделя. Через понедельник, поэтому переход года считается сам. */
export function shiftWeek(week: string, delta: number): string {
  const mon = mondayOfWeek(week)
  mon.setUTCDate(mon.getUTCDate() + delta * 7)
  return isoWeekOf(new Date(mon.getUTCFullYear(), mon.getUTCMonth(), mon.getUTCDate()))
}
