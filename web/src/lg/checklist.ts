/* Общее для двух экранов чек-листа: управляющий СДАЁТ (ChecklistUpload),
   владелец СПРАШИВАЕТ (ChecklistBoard). Слоты, зоны и разбор описаны один раз —
   разъехавшиеся подписи зон уже стоили нам того, что сданный слот выглядел
   несданным. */

export const SLOTS = ['10:45', '15:00', '20:45', '23:45']
export const ZONES: [string, string][] = [['hall', 'Зал'], ['kitchen', 'Кухня'], ['wc', 'Санузел']]
// как зоны подписывает сервер (строчными) — нужно для старых ответов без zone_key
export const ZONE_LABEL: Record<string, string> = { hall: 'зал', kitchen: 'кухня', wc: 'санузел' }

export type Done = { branch: string; slot: string; zone: string; zone_key?: string; photos: number; at: string }
/* Замечание разбора приходит объектом {zone, what}. Раньше их склеивали как
   строки — на экран падало «[object Object]», то есть управляющий не узнавал
   ровно того, ради чего разбор и затевался. */
export type Issue = string | { zone?: string; what?: string }
export type Review = { slot: string; ok: boolean; issues: Issue[]; reason?: string; branch?: string }

export function issueText(i: Issue): string {
  if (typeof i === 'string') return i
  const zone = (i.zone || '').trim()
  const what = (i.what || '').trim()
  if (zone && what) return `${zone}: ${what}`
  return what || zone || 'замечание без описания'
}

/** Ближайший УЖЕ ПРОШЕДШИЙ слот — с него и начинают сдавать. */
export function nearestSlot(now = new Date()): string {
  const mins = now.getHours() * 60 + now.getMinutes()
  let best = 0
  SLOTS.forEach((s, i) => { if (slotMinutes(s) <= mins) best = i })
  return SLOTS[best]
}

export const slotMinutes = (s: string) => Number(s.slice(0, 2)) * 60 + Number(s.slice(3))

/** Прошёл ли слот: за будущие слоты спрашивать нечего, красным их красить нельзя. */
export const slotPassed = (slot: string, now = new Date()) =>
  slotMinutes(slot) <= now.getHours() * 60 + now.getMinutes()

/** Сдана ли зона в слоте. Сверяем по КЛЮЧУ («hall»), не по подписи: сервер
    пишет «зал», экран — «Зал», и сравнение подписей не сходилось на регистре. */
export const sentIn = (done: Done[], slot: string, key: string) =>
  done.find((d) => d.slot === slot
    && (d.zone_key || d.zone?.toLowerCase()) === (d.zone_key ? key : ZONE_LABEL[key]))
