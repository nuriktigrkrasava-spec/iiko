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
    teriyaki: { id: '4', name: 'П/Ф ЛОСОСЬ ТЕРИЯКИ' },
    sauce: { id: '7', name: 'Соус Терияки' },
  },
  price_per_kg: 9300, price_from: 'ЦЕХ · 2026-08-30', trim_price: 8800,
  trim_const: true,
  sauce_price: 4200, sauce_from: 'Азия Фуд · 2026-09-02',
  kind: 'salmon', title: 'Разбор лосося', raw_label: 'Стейк в разбор',
  raw_short: 'стейк', teriyaki: true,
  kinds: [{ key: 'salmon', title: 'Разбор лосося', tab: 'Лосось' },
          { key: 'eel', title: 'Разбор угря', tab: 'Угорь' }],
}

/* Угорь разбирается иначе: один выход и отход. В номенклатуре сети по нему
   ровно две строки — «угорь» и «П/Ф угорь», обрезков нет ни на одном филиале. */
const EEL = {
  ...CTX,
  products: {
    raw: { id: '11', name: 'угорь' },
    slice: { id: '13', name: 'П/Ф угорь' },
    waste: { id: '16', name: 'Отход угря' },
  },
  roles: ['raw', 'slice', 'waste'],
  price_per_kg: 14000, price_from: 'себестоимость iiko', trim_price: 0,
  trim_const: false, sauce_price: 0, sauce_from: '',
  kind: 'eel', title: 'Разбор угря', raw_label: 'Угорь в разбор',
  slice_label: 'П/Ф угорь', raw_short: 'угорь', teriyaki: false,
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => ({
    ok: true,
    json: async () => (String(url).includes('/network') ? { branches: [] }
      : String(url).includes('/period') ? { acts: [], total: { acts: 0 } }
      : String(url).includes('/api/acts/eel/') ? EEL : CTX),
  })) as unknown as typeof fetch)
})

/* Требование со скрина: «отход не считается совсем». Когда цены обрезков нет
   ни в себестоимости, ни константой, расчёт падал в ошибку целиком — вместе с
   отходом, который от цены не зависит вовсе. */
const NO_TRIM_PRICE = {
  ok: true, money: false, need: 'trim_price',
  need_text: 'Цена обрезков не задана — впиши, почём их считать.',
  kind: 'salmon',
  raw: { weight: 10, price_per_kg: 14000, sum: 140000 },
  slice: { weight: 7, price_per_kg: null, sum: null },
  trim: { weight: 2, price_per_kg: null, sum: null },
  waste: { weight: 1, price_per_kg: 0, sum: 0 },
  slice_pct: 70, trim_pct: 20, waste_pct: 10, check: null,
}

describe('отход без цены', () => {
  it('без цены обрезков считаются вес отхода и его процент', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string, opts?: RequestInit) => ({
      ok: true,
      json: async () => (String(url).includes('/network') ? { branches: [] }
        : String(url).includes('/period') ? { acts: [], total: { acts: 0 } }
        : opts?.method === 'POST' ? NO_TRIM_PRICE : { ...CTX, trim_price: 0, trim_const: false }),
    })) as unknown as typeof fetch)
    const { container } = render(<SalmonAct token="1.sig" />)
    await waitFor(() => expect(screen.getByText(/Разбор лосося/)).toBeTruthy())
    fireEvent.change(screen.getByPlaceholderText('10'), { target: { value: '10' } })
    fireEvent.change(screen.getByPlaceholderText('8'), { target: { value: '7' } })
    fireEvent.change(screen.getByPlaceholderText('2'), { target: { value: '2' } })
    await waitFor(() => expect(screen.getByText(/уже посчитаны/)).toBeTruthy(), { timeout: 2000 })
    const waste = Array.from(container.querySelectorAll('.sal-tile'))
      .map((el) => el.textContent || '').find((t) => t.includes('Отход')) || ''
    expect(waste).toMatch(/10%/)          // процент отхода
    expect(waste).toMatch(/10 − 7 − 2/)   // вычитание, из которого он получился
    expect(screen.queryByText(/остаток стоимости/)).toBeNull()   // денег ещё нет
  })
})

/* На живой сети у угря в номенклатуре есть только «угорь» и «П/Ф угорь»:
   ни нарезки, ни обрезков, ни отхода. Пустая ячейка вместо имени превращала
   строку таблицы в «· остаток стоимости» без хозяина. */
describe('позиции, которых нет в номенклатуре', () => {
  const HALF = {
    ...CTX,
    products: { raw: { id: '1', name: 'П/Ф ЛОСОСЬ СТЕЙК' }, slice: null, trim: null, waste: null },
  }
  const CALC = {
    ok: true, money: true, need: '', kind: 'salmon',
    raw: { weight: 12, price_per_kg: 9300, sum: 111600 },
    slice: { weight: 10, price_per_kg: 11157.6, sum: 111576 },
    trim: { weight: 2, price_per_kg: 12, sum: 24 },
    waste: { weight: 0, price_per_kg: 0, sum: 0 },
    slice_pct: 83.3, trim_pct: 16.7, waste_pct: 0, check: 111600,
  }

  it('строка без позиции подписана ролью и помечена, а не пуста', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string, opts?: RequestInit) => ({
      ok: true,
      json: async () => (String(url).includes('/network') ? { branches: [] }
        : String(url).includes('/period') ? { acts: [], total: { acts: 0 } }
        : opts?.method === 'POST' ? CALC : HALF),
    })) as unknown as typeof fetch)
    render(<SalmonAct token="1.sig" />)
    await waitFor(() => expect(screen.getByText(/Разбор лосося/)).toBeTruthy())
    fireEvent.change(screen.getByPlaceholderText('10'), { target: { value: '12' } })
    await waitFor(() => expect(screen.getAllByText(/нет в номенклатуре/).length).toBeGreaterThan(1),
      { timeout: 2000 })
    expect(screen.getAllByText(/Нарезка/).length).toBeGreaterThan(0)
    // и сверху сказано, каких именно позиций не хватает
    expect(screen.getByText(/нарезка, обрезки/)).toBeTruthy()
  })
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

describe('в разборе жарки нет', () => {
  /* Терияки — передел обрезков на сковороде, а не разбор рыбы. Пока они жили в
     одном экране, «насколько аккуратно разделали» путалось со «сколько дала
     сковорода». Тест сторожит, чтобы жарка сюда не вернулась. */
  it('ни жарки, ни терияки, ни соуса — только рыба', async () => {
    render(<SalmonAct token="1.sig" />)
    await waitFor(() => expect(screen.getByText(/Стейк в разбор/)).toBeTruthy())
    expect(screen.queryByText(/^В жарку/)).toBeNull()
    expect(screen.queryByText(/^Терияки/)).toBeNull()
    expect(screen.queryByText('сколько налили')).toBeNull()
    expect(screen.queryByText(/Соус терияки, ₸\/кг/)).toBeNull()
  })

  it('взвешивают три вещи: вход, нарезку и обрезки', async () => {
    render(<SalmonAct token="1.sig" />)
    await waitFor(() => expect(screen.getByText(/Стейк в разбор/)).toBeTruthy())
    // плитки с вводом — ровно три, отход считается сам
    expect(screen.getAllByPlaceholderText(/^(10|8|2)$/)).toHaveLength(3)
    expect(screen.queryAllByPlaceholderText('0')).toHaveLength(0)
  })

  it('в запрос уезжают только веса разбора', async () => {
    render(<SalmonAct token="1.sig" />)
    await waitFor(() => expect(screen.getByText(/Стейк в разбор/)).toBeTruthy())
    fireEvent.change(screen.getByPlaceholderText('10'), { target: { value: '10' } })
    await waitFor(() => {
      const calls = (fetch as unknown as { mock: { calls: [string, RequestInit?][] } }).mock.calls
      const post = calls.find(([, o]) => o?.method === 'POST')
      expect(post).toBeTruthy()
      const body = JSON.parse(String(post![1]!.body))
      expect(body.weight_raw).toBe(10)
      expect(body.weight_sauce).toBeUndefined()
      expect(body.weight_fry).toBeUndefined()
      expect(body.weight_teriyaki).toBeUndefined()
    }, { timeout: 2000 })
  })
})

describe('переключение рыбы', () => {
  it('у угря два веса и никаких обрезков', async () => {
    render(<SalmonAct token="1.sig" />)
    await waitFor(() => expect(screen.getByText(/Стейк в разбор/)).toBeTruthy())

    fireEvent.click(screen.getByText('Угорь'))
    // формула отхода у угря короче: вычитается только выход
    await waitFor(() => expect(screen.getByText('угорь − п/ф угорь')).toBeTruthy())
    expect(screen.getAllByText(/Угорь в разбор/).length).toBeGreaterThan(0)
    // обрезков у угря нет: ни плитки веса, ни поля цены
    expect(screen.queryByText(/Обрезки/)).toBeNull()
    expect(screen.queryByPlaceholderText('почём считать')).toBeNull()
    // и запросы уходят на свой разбор, а не на лососёвый
    expect((fetch as unknown as { mock: { calls: [string][] } }).mock.calls
      .some(([u]) => String(u).includes('/api/acts/eel/'))).toBe(true)
  })

  it('вес обрезков не уезжает на сервер там, где обрезков нет', async () => {
    render(<SalmonAct token="1.sig" />)
    await waitFor(() => expect(screen.getByText(/Стейк в разбор/)).toBeTruthy())
    fireEvent.click(screen.getByText('Угорь'))
    await waitFor(() => expect(screen.getByText('угорь − п/ф угорь')).toBeTruthy())
    fireEvent.change(screen.getByPlaceholderText('10'), { target: { value: '12' } })
    await waitFor(() => {
      const calls = (fetch as unknown as { mock: { calls: [string, RequestInit?][] } }).mock.calls
      const post = calls.find(([u, o]) => o?.method === 'POST' && String(u).includes('/api/acts/eel/'))
      expect(post).toBeTruthy()
      expect(JSON.parse(String(post![1]!.body)).weight_trim).toBe(0)
    }, { timeout: 2000 })
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
