import { render, screen, waitFor } from '@testing-library/react'
import { periodBounds, wasteTone } from './salmonKit'
import SalmonAct from './SalmonAct'

/* Требование со скрина: взвешивают стейк, НАРЕЗКУ и обрезки, а отход считает
   программа. Тест сторожит именно это — раньше вторым полем шли обрезки, и
   оператор вводил вес не в ту графу. */

const CTX = {
  role: 'manager',
  branch: { organization_id: 'org-1', name: 'Астана, Бейбітшілік' },
  branches: [{ organization_id: 'org-1', name: 'Астана, Бейбітшілік' }],
  products: {
    raw: { id: '1', name: 'П/Ф ЛОСОСЬ СТЕЙК (ЦЕХ)' },
    slice: { id: '3', name: 'П/Ф НАРЕЗКА ЛОСОСЬ' },
    trim: { id: '2', name: 'П/Ф ОБРЕЗКИ ЛОСОСЬ' },
    waste: { id: '6', name: 'Отход лосося' },
  },
  price_per_kg: 9300, price_from: 'ЦЕХ · 2026-08-30', trim_price: 8800,
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => ({
    ok: true,
    json: async () => (String(url).includes('/network') ? { branches: [] }
      : String(url).includes('/period') ? { acts: [], total: { acts: 0 } } : CTX),
  })) as unknown as typeof fetch)
})

describe('экран разбора', () => {
  it('поля идут стейк → нарезка → обрезки, отход не вводится', async () => {
    render(<SalmonAct token="1.sig" />)
    await waitFor(() => expect(screen.getByText(/Стейк в разбор/)).toBeTruthy())
    expect(screen.getByText(/^Нарезка/)).toBeTruthy()
    expect(screen.getByText(/^Обрезки/)).toBeTruthy()
    // отход подписан формулой, а не полем ввода
    expect(screen.getByText('стейк − нарезка − обрезки')).toBeTruthy()
    expect(screen.getAllByPlaceholderText(/^(10|8|2)$/)).toHaveLength(3)
  })

  it('не обещает отправку в iiko: свод заносит администратор', async () => {
    render(<SalmonAct token="1.sig" />)
    await waitFor(() => expect(screen.getByText(/Стейк в разбор/)).toBeTruthy())
    expect(screen.queryByText(/Провести акт в iiko/)).toBeNull()
  })
})

describe('период и цвет отхода', () => {
  it('«к занесению» не режется календарём — границу ставит проводка', () => {
    const b = periodBounds('open', '', '')
    expect(b.from).toBe('2020-01-01')
  })

  it('прошлый месяц заканчивается последним его днём', () => {
    vi.setSystemTime(new Date('2026-03-17T12:00:00'))
    expect(periodBounds('prev', '', '')).toEqual({ from: '2026-02-01', to: '2026-02-28' })
    vi.useRealTimers()
  })

  it('свои даты передаются как есть', () => {
    expect(periodBounds('dates', '2026-01-05', '2026-01-09'))
      .toEqual({ from: '2026-01-05', to: '2026-01-09' })
  })

  it('отход красится по порогам 5 и 10 процентов', () => {
    expect(wasteTone(4.9)).toBe('var(--grn)')
    expect(wasteTone(9.9)).toBe('var(--amb)')
    expect(wasteTone(10.1)).toBe('var(--red)')
  })
})
