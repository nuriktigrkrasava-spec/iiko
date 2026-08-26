import { render, screen } from '@testing-library/react'
import Progress, { networkValue, delta, type MetricsData, type Row } from './Progress'

/* Экран собрания: цифры, которые владелец называет вслух. Ошибиться в них
   хуже, чем не показать вовсе. */

const metrics = [
  { key: 'orders', label: 'Заказов за неделю', unit: '', lower_better: false },
  { key: 'late_pct', label: 'Опоздавших заказов', unit: '%', lower_better: true },
  { key: 'kitchen', label: 'Время приготовления', unit: 'мин', lower_better: true },
  { key: 'road', label: 'Курьер в дороге', unit: 'мин', lower_better: true },
]
const row = (id: string, name: string, now: Record<string, number>, prev: Record<string, number>,
             wins: { key: string; label: string }[] = []): Row =>
  ({ organization_id: id, name, now, prev, wins })

const rows: Row[] = [
  row('a', 'Астана, ул. Г.Алиева 10', { orders: 100, late_pct: 10, kitchen: 20, road: 30 },
      { orders: 80, late_pct: 20, kitchen: 25, road: 30 }, [{ key: 'late_pct', label: 'опоздания' }]),
  row('b', 'Астана, ул. Бокейхана 25а', { orders: 50, late_pct: 20, kitchen: 30, road: 40 },
      { orders: 60, late_pct: 10, kitchen: 25, road: 40 }),
]
const data: MetricsData = { week: '2026-W35', from: '2026-08-24', to: '2026-08-30',
                            done_days: 3, metrics, branches: rows }

describe('арифметика сети', () => {
  /* Заказы складываются, а минуты и проценты усредняются. Сложить проценты по
     девяти филиалам — получить «опозданий 340%», то есть показать чепуху на
     собрании. */
  it('заказы по сети складывает', () => {
    expect(networkValue(rows, 'orders', 'now')).toBe(150)
  })
  it('проценты и минуты усредняет, а не суммирует', () => {
    expect(networkValue(rows, 'late_pct', 'now')).toBe(15)
    expect(networkValue(rows, 'kitchen', 'now')).toBe(25)
  })
  it('без данных не выдумывает ноль', () => {
    expect(networkValue([], 'orders', 'now')).toBeNull()
  })
})

describe('динамика', () => {
  /* Знак нормализуем по смыслу показателя: падение опозданий — это улучшение,
     падение заказов — ухудшение. Красить одинаково нельзя. */
  it('рост заказов — это лучше', () => {
    expect(delta(100, 80, false)?.better).toBe(true)
  })
  it('падение опозданий — тоже лучше', () => {
    expect(delta(10, 20, true)?.better).toBe(true)
  })
  it('рост времени приготовления — хуже', () => {
    expect(delta(30, 25, true)?.better).toBe(false)
  })
  it('считает процент от прошлой недели', () => {
    expect(Math.round(delta(100, 80, false)!.pct)).toBe(25)
  })
  it('без прошлой недели молчит, а не делит на ноль', () => {
    expect(delta(100, null, false)).toBeNull()
    expect(delta(100, 0, false)).toBeNull()
  })
})

describe('экран', () => {
  it('показывает четыре показателя и оба топа', async () => {
    render(<Progress data={data} scores={[
      { organization_id: 'a', name: 'Астана, ул. Г.Алиева 10', score: 72 },
      { organization_id: 'b', name: 'Астана, ул. Бокейхана 25а', score: 41 },
    ]} onClose={() => {}} />)

    expect(await screen.findByText('Прогресс и динамика')).toBeTruthy()
    for (const m of metrics) expect(screen.getAllByText(m.label).length).toBeGreaterThan(0)
    expect(screen.getByText('Топ по движению')).toBeTruthy()
    expect(screen.getByText('Топ по оценке')).toBeTruthy()
    expect(screen.getByText('150')).toBeTruthy()          // заказов по сети
  })

  it('без оценок не падает — топ по движению остаётся', async () => {
    render(<Progress data={data} scores={[]} onClose={() => {}} />)
    await screen.findByText('Топ по оценке')
    expect(screen.getByText('Пока нечего показать.')).toBeTruthy()
  })
})
