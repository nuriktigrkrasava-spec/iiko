import { fireEvent, render, screen, waitFor } from '@testing-library/react'
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
  kind: 'salmon', title: 'Разбор лосося', raw_label: 'Стейк в разбор',
  raw_short: 'стейк', teriyaki: true,
  kinds: [{ key: 'salmon', title: 'Разбор лосося', tab: 'Лосось' },
          { key: 'eel', title: 'Разбор угря', tab: 'Угорь' }],
}

/* Угорь разбирается так же, но без жарки, и цена обрезков у него ещё не
   константа учёта — её спрашивают полем. */
const EEL = {
  ...CTX,
  products: {
    raw: { id: '11', name: 'Угорь целый' },
    slice: { id: '13', name: 'П/Ф НАРЕЗКА УГОРЬ' },
    trim: { id: '12', name: 'П/Ф ОБРЕЗКИ УГОРЬ' },
    waste: { id: '16', name: 'Отход угря' },
  },
  price_per_kg: 14000, price_from: 'ЦЕХ · 2026-09-01', trim_price: 0,
  kind: 'eel', title: 'Разбор угря', raw_label: 'Угорь в разбор',
  raw_short: 'угорь', teriyaki: false,
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => ({
    ok: true,
    json: async () => (String(url).includes('/network') ? { branches: [] }
      : String(url).includes('/period') ? { acts: [], total: { acts: 0 } }
      : String(url).includes('/api/acts/eel/') ? EEL : CTX),
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

describe('терияки: ужарка вводится, а не додумывается', () => {
  it('два веса — что положили жарить и что сняли', async () => {
    render(<SalmonAct token="1.sig" />)
    await waitFor(() => expect(screen.getByText(/Стейк в разбор/)).toBeTruthy())
    expect(screen.getByText(/^В жарку/)).toBeTruthy()
    expect(screen.getByText(/^Терияки/)).toBeTruthy()
    expect(screen.getByText('обрезков на сковороду')).toBeTruthy()
    expect(screen.getByText('сколько сняли')).toBeTruthy()
  })
})

describe('переключение рыбы', () => {
  it('угорь спрашивает свой вход, цену обрезков и не знает жарки', async () => {
    render(<SalmonAct token="1.sig" />)
    await waitFor(() => expect(screen.getByText(/Стейк в разбор/)).toBeTruthy())

    fireEvent.click(screen.getByText('Угорь'))
    await waitFor(() => expect(screen.getByText(/Угорь в разбор/)).toBeTruthy())

    expect(screen.getByText('угорь − нарезка − обрезки')).toBeTruthy()
    expect(screen.queryByText(/^В жарку/)).toBeNull()
    expect(screen.queryByText(/^Терияки/)).toBeNull()
    // цена обрезков угря ещё не константа — без поля разбор не собрать
    expect(screen.getByPlaceholderText('почём считать')).toBeTruthy()
    // и запросы уходят на свой разбор, а не на лососёвый
    expect((fetch as unknown as { mock: { calls: [string][] } }).mock.calls
      .some(([u]) => String(u).includes('/api/acts/eel/'))).toBe(true)
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
