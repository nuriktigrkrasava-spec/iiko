/* Деньги — единственный источник тревоги в продукте. Формат ₸ и диапазонов оценки. */

const NF = new Intl.NumberFormat('ru-RU')
// Intl разделяет разряды неразрывным пробелом — приводим к обычному
const fmt = (n: number) => NF.format(n).replace(/ /g, ' ')

export const MIN_CASE_KZT = 30_000

/** 340000 → "340 000 ₸" */
export function kzt(n: number): string {
  return `${fmt(Math.round(n))} ₸`
}

/** только число, без знака: 340000 → "340 000". Знак ₸ рендерится отдельной
    единицей (сторис: гигантское моно-число + ₸ в --ink-3 поменьше). */
export function kztNum(n: number): string {
  return fmt(Math.round(n))
}

/** компактная сумма для диапазона: 340000 → "340 тыс", 2854457 → "2,85 млн" */
function short(n: number): string {
  const a = Math.abs(n)
  if (a >= 1_000_000) return `${(n / 1_000_000).toFixed(2).replace('.', ',')} млн`
  if (a >= 1_000) return `${Math.round(n / 1_000)} тыс`
  return NF.format(Math.round(n))
}

/** диапазон оценки: (300000,380000) → "300–380 тыс ₸" */
export function kztRange(low: number, high: number): string {
  const aM = Math.abs(high) >= 1_000_000
  const lo = aM ? (low / 1_000_000).toFixed(2).replace('.', ',') : String(Math.round(low / 1_000))
  const hi = short(high)
  return `${lo}–${hi} ₸`
}
