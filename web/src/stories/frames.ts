import type { Case } from '../cases/types'
import { buildingOf, nodeOf, BUILDING_LABEL } from '../cases/nodes'

/* Кадры недельного отчёта. Правила уже посчитали кейсы — здесь только раскладка
   в арку: период → 2–3 утечки → СРАБОТАЛО → итог → 3 задачи. Ни одна цифра
   тут не выдумывается: всё берётся из кейсов генератора. */

export type Tone = 'loss' | 'gain' | 'neutral'

export type Frame =
  | { kind: 'period'; overline: string; amount: number; tone: Tone; sentence: string; sub: string }
  | { kind: 'leak'; overline: string; amount: number; tone: Tone; sentence: string; sub: string }
  | { kind: 'worked'; overline: string; amount: number | null; count?: number; tone: Tone; sentence: string; sub: string }
  | { kind: 'total'; overline: string; amount: number; tone: Tone; sentence: string; sub: string }
  | { kind: 'tasks'; overline: string; sentence: string; items: { title: string; amount: number }[] }

const MONTHS = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря']

function periodLabel(from?: string): { title: string; range: string } {
  if (!from) return { title: 'Отчёт недели', range: '' }
  const [y, m] = from.split('-').map(Number)
  return { title: `${MONTHS[(m ?? 1) - 1]} ${y}`, range: 'за месяц' }
}

function overlineOf(c: Case): string {
  return `${BUILDING_LABEL[buildingOf(c.node_id)]} · ${c.branch_id ?? 'все филиалы'}`
}

function plural(n: number, one: string, few: string, many: string): string {
  const m10 = n % 10, m100 = n % 100
  if (m10 === 1 && m100 !== 11) return one
  if (m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20)) return few
  return many
}

const OPEN = new Set(['new', 'accepted', 'auditing', 'verifying'])

export function buildFrames(cases: Case[]): Frame[] {
  const open = cases.filter((c) => OPEN.has(c.status)).sort((a, b) => b.amount_kzt - a.amount_kzt)
  const closed = cases.filter((c) => c.status === 'closed')
  const inWork = cases.filter((c) => c.status === 'auditing')
  const total = open.reduce((s, c) => s + c.amount_kzt, 0)
  const { title: period, range } = periodLabel(open[0]?.period_from)
  const frames: Frame[] = []

  // 1 — период: общая картина, не обвинение — тон нейтральный, свет тёплый
  frames.push({
    kind: 'period',
    overline: 'Отчёт недели',
    amount: total,
    tone: 'neutral',
    sentence: `Столько утекает ${range || 'за месяц'}, если не закрыть очередь`,
    sub: `${period} · ${open.length} ${plural(open.length, 'открытый кейс', 'открытых кейса', 'открытых кейсов')}`,
  })

  // 2–4 — до трёх крупнейших утечек
  for (const c of open.slice(0, 3)) {
    frames.push({
      kind: 'leak',
      overline: overlineOf(c),
      amount: c.amount_kzt,
      tone: 'loss',
      sentence: c.title,
      sub: c.body,
    })
  }

  // 5 — СРАБОТАЛО (обязателен: если закрытых нет — прогресс по открытым)
  const gain = closed.reduce((s, c) => s + c.amount_kzt, 0)
  if (gain > 0) {
    frames.push({
      kind: 'worked',
      overline: 'Сработало',
      amount: gain,
      tone: 'gain',
      sentence: `Вернули за счёт ${closed.length} ${plural(closed.length, 'закрытого кейса', 'закрытых кейсов', 'закрытых кейсов')}`,
      sub: 'Проверено первичкой и весами',
    })
  } else {
    frames.push({
      kind: 'worked',
      overline: 'Сработало',
      amount: null,
      count: inWork.length,
      tone: 'neutral',
      sentence: inWork.length > 0
        ? 'Команда уже разбирает, итог будет на следующей неделе'
        : 'Пока ничего не закрыто. Возьми первый кейс в работу',
      sub: `${inWork.length} ${plural(inWork.length, 'кейс в аудите', 'кейса в аудите', 'кейсов в аудите')}`,
    })
  }

  // 6 — итог
  frames.push({
    kind: 'total',
    overline: 'Итог месяца',
    amount: total,
    tone: 'loss',
    sentence: 'Столько на кону по всем открытым кейсам',
    sub: 'Сумма только по листьям, без двойного счёта',
  })

  // 7 — три задачи на неделю. Название короткое (узел · филиал),
  // сумма один раз в колонке — без дубля внутри предложения
  frames.push({
    kind: 'tasks',
    overline: 'Три задачи на неделю',
    sentence: 'Закрой их, и половина утечки уйдёт',
    items: open.slice(0, 3).map((c) => ({
      title: `${nodeOf(c.node_id)?.label ?? BUILDING_LABEL[buildingOf(c.node_id)]} · ${c.branch_id ?? 'все филиалы'}`,
      amount: c.amount_kzt,
    })),
  })

  return frames
}
