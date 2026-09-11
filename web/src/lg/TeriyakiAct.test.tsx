import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import TeriyakiAct from './TeriyakiAct'
import SalmonAct from './SalmonAct'

/* Терияки — передел, а не разбор. Требование со скрина: жарки в разборе быть не
   должно, у неё своя вкладка, свои два веса и граммы соуса. */

const CTX = {
  role: 'manager',
  branch: { organization_id: 'org-1', name: 'Астана, Бейбітшілік' },
  branches: [{ organization_id: 'org-1', name: 'Астана, Бейбітшілік' }],
  products: {
    trim: { id: '2', name: 'П/Ф ОБРЕЗКИ ЛОСОСЬ' },
    teriyaki: { id: '4', name: 'П/Ф ЛОСОСЬ ТЕРИЯКИ' },
    sauce: { id: '7', name: 'Соус терияки' },
  },
  trim_price: 8800,
  sauce_price: 4200,
  sauce_from: 'Азия Фуд · 2026-09-02',
  kind: 'teriyaki',
  title: 'Терияки из обрезков',
  kinds: [{ key: 'salmon', title: 'Разбор лосося', tab: 'Лосось' },
          { key: 'eel', title: 'Разбор угря', tab: 'Угорь' },
          { key: 'teriyaki', title: 'Терияки из обрезков', tab: 'Терияки' }],
}

const SALMON = {
  ...CTX,
  products: {
    raw: { id: '1', name: 'П/Ф ЛОСОСЬ СТЕЙК' },
    slice: { id: '3', name: 'П/Ф НАРЕЗКА ЛОСОСЬ' },
    trim: { id: '2', name: 'П/Ф ОБРЕЗКИ ЛОСОСЬ' },
    waste: { id: '6', name: 'Отход лосося' },
  },
  price_per_kg: 9300, price_from: 'ЦЕХ · 2026-08-30', trim_const: true,
  kind: 'salmon', title: 'Разбор лосося', raw_label: 'Стейк в разбор', raw_short: 'стейк',
}

/* 2 кг обрезков → 1.4 кг терияки, 200 г соуса: ужарка 0.6, выход 70 %. */
const CALC = {
  ok: true,
  trim: { weight: 2, price_per_kg: 8800, sum: 17600 },
  sauce: { grams: 200, price_per_kg: 4200, sum: 840 },
  teriyaki: { weight: 1.4, price_per_kg: 13171.43, sum: 18440, from_trim: 2, shrink: 0.6 },
  yield_pct: 70, shrink_pct: 30, sauce_g_per_kg: 142.9, check: 18440,
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(async (url: string, opts?: RequestInit) => ({
    ok: true,
    json: async () => (String(url).includes('/period') ? { acts: [], total: { acts: 0 } }
      : String(url).includes('/network') ? { branches: [] }
      : opts?.method === 'POST' ? CALC
      : String(url).includes('/api/teriyaki/') ? CTX : SALMON),
  })) as unknown as typeof fetch)
})

describe('вкладка терияки', () => {
  it('спрашивает два веса и граммы соуса, ужарку считает сама', async () => {
    render(<TeriyakiAct token="1.sig" switcher={null} />)
    await waitFor(() => expect(screen.getByText(/Обрезки в жарку/)).toBeTruthy())
    // плитки узнаём по подписи под полем — она у каждой своя
    expect(screen.getByText('сколько сняли')).toBeTruthy()
    expect(screen.getByText('сколько налили')).toBeTruthy()
    // ужарка не вводится — она разница двух весов
    expect(screen.getByText('обрезки − терияки')).toBeTruthy()
    expect(screen.getByText('г')).toBeTruthy()            // соус в граммах
  })

  it('цена обрезков — константа учёта, цена соуса — из накладных', async () => {
    render(<TeriyakiAct token="1.sig" switcher={null} />)
    await waitFor(() => expect(screen.getByText(/Обрезки в жарку/)).toBeTruthy())
    expect(screen.getByPlaceholderText('8800')).toBeTruthy()
    expect(screen.getByPlaceholderText('4200')).toBeTruthy()
    expect(screen.getByText(/Азия Фуд/)).toBeTruthy()
  })

  it('показывает выход жарки и соус на килограмм', async () => {
    render(<TeriyakiAct token="1.sig" switcher={null} />)
    await waitFor(() => expect(screen.getByText(/Обрезки в жарку/)).toBeTruthy())
    fireEvent.change(screen.getByPlaceholderText('2'), { target: { value: '2' } })
    fireEvent.change(screen.getByPlaceholderText('1,4'), { target: { value: '1.4' } })
    fireEvent.change(screen.getByPlaceholderText('200'), { target: { value: '200' } })
    await waitFor(() => expect(screen.getByText(/Выход жарки/)).toBeTruthy(), { timeout: 2000 })
    expect(screen.getAllByText('70%').length).toBeGreaterThan(0)
    expect(screen.getByText('142,9 г')).toBeTruthy()
  })

  it('в запрос уезжают обрезки, терияки и граммы соуса', async () => {
    render(<TeriyakiAct token="1.sig" switcher={null} />)
    await waitFor(() => expect(screen.getByText(/Обрезки в жарку/)).toBeTruthy())
    fireEvent.change(screen.getByPlaceholderText('2'), { target: { value: '2' } })
    fireEvent.change(screen.getByPlaceholderText('1,4'), { target: { value: '1.4' } })
    fireEvent.change(screen.getByPlaceholderText('200'), { target: { value: '200' } })
    await waitFor(() => {
      const calls = (fetch as unknown as { mock: { calls: [string, RequestInit?][] } }).mock.calls
      const post = calls.find(([u, o]) => o?.method === 'POST' && String(u).includes('/api/teriyaki/'))
      expect(post).toBeTruthy()
      const body = JSON.parse(String(post![1]!.body))
      expect(body).toMatchObject({ weight_fry: 2, weight_teriyaki: 1.4, weight_sauce: 200 })
    }, { timeout: 2000 })
  })

  it('таблица говорит, что списать и что оприходовать', async () => {
    render(<TeriyakiAct token="1.sig" switcher={null} />)
    await waitFor(() => expect(screen.getByText(/Обрезки в жарку/)).toBeTruthy())
    fireEvent.change(screen.getByPlaceholderText('2'), { target: { value: '2' } })
    await waitFor(() => expect(screen.getByText(/П\/Ф ОБРЕЗКИ ЛОСОСЬ/)).toBeTruthy(), { timeout: 2000 })
    expect(screen.getAllByText(/списать/).length).toBe(2)      // обрезки и соус
    expect(screen.getByText(/оприходовать/)).toBeTruthy()      // П/Ф терияки
  })
})

describe('переключатель', () => {
  it('терияки открывается третьей вкладкой, а не плитками в разборе', async () => {
    render(<SalmonAct token="1.sig" />)
    await waitFor(() => expect(screen.getByText(/Стейк в разбор/)).toBeTruthy())
    expect(screen.queryByText(/^В жарку/)).toBeNull()

    fireEvent.click(screen.getByText('Терияки'))
    await waitFor(() => expect(screen.getByText(/Обрезки в жарку/)).toBeTruthy())
    // разбора на этом экране больше нет
    expect(screen.queryByText(/Стейк в разбор/)).toBeNull()
    expect((fetch as unknown as { mock: { calls: [string][] } }).mock.calls
      .some(([u]) => String(u).startsWith('/api/teriyaki/'))).toBe(true)
  })
})
