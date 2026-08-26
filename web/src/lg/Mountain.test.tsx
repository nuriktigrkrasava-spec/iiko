import { render, screen, waitFor } from '@testing-library/react'
import Mountain from './Mountain'

/* Регрессия по ролям на «Горе».

   Сайт управляющего однажды показал доску ВЛАДЕЛЬЦА: форму постановки задач,
   рассылку «отправить всем» и прогресс всех девяти филиалов — а сдача чек-листа
   при этом пропала, потому что она рисуется только не-владельцу. Причина одна:
   доска приехала с role="owner". Здесь фиксируем обе стороны — что управляющий
   видит своё, и что протухшая ссылка филиала НЕ открывает кабинет владельца. */

const level = { step: 0, steps: 40, height_pct: 0, to_next: 25, summit: 1000 }
const row = (id: string, name: string) => ({
  organization_id: id, name, tasks_open: [], tasks_done: 0, task_points: 0,
  checklist: { done: 0, missed: 0, points: 0 }, points: 0, level, score: null,
})
const board = (role: string, names: [string, string][]) => ({
  role, month: '2026-08',
  scale: { tasks: {}, step_points: 25, steps: 40 },
  ranking: names.map(([id, n]) => ({ organization_id: id, name: n, points: 0, level, place: 1, tasks_done: 0 })),
  branches: names.map(([id, n]) => row(id, n)),
})

const OWNER_BRANCHES: [string, string][] = [
  ['a', 'Астана, ул. Бейбітшілік 71'], ['b', 'Астана, ул. Бокейхана 25а'],
  ['c', 'Астана, ул. Г.Алиева 10 (EXPO)'],
]

function mockFetch(routes: Record<string, () => Response | Promise<Response>>) {
  const json = (d: unknown, status = 200) =>
    new Response(JSON.stringify(d), { status, headers: { 'Content-Type': 'application/json' } })
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    for (const [frag, make] of Object.entries(routes)) if (url.includes(frag)) return make()
    return json({})
  }))
  return json
}

afterEach(() => { vi.unstubAllGlobals(); history.replaceState({}, '', '/') })

describe('«Гора» глазами управляющего', () => {
  it('не даёт ставить задачи, рассылать всем и не показывает чужой прогресс', async () => {
    history.replaceState({}, '', '/?m=900010.sig')
    const json = mockFetch({
      '/api/mountain/data/': () => new Response(
        JSON.stringify(board('manager', [['c', 'Астана, ул. Г.Алиева 10 (EXPO)']])),
        { status: 200, headers: { 'Content-Type': 'application/json' } }),
    })
    void json
    render(<Mountain />)

    await screen.findByText('Мои задачи')
    expect(screen.queryByText('Поставить задачу')).toBeNull()
    expect(screen.queryByText('Отправить всем')).toBeNull()
    // прогресс — только по своему филиалу
    expect(screen.getAllByText(/Ступень/)).toHaveLength(1)
  })

  it('показывает сдачу чек-листа — ради неё управляющий и заходит', async () => {
    history.replaceState({}, '', '/?m=900010.sig')
    mockFetch({
      '/api/mountain/data/': () => new Response(
        JSON.stringify(board('manager', [['c', 'Астана, ул. Г.Алиева 10 (EXPO)']])),
        { status: 200, headers: { 'Content-Type': 'application/json' } }),
    })
    render(<Mountain />)
    await screen.findByText('Сдать чек-лист')
  })

  it('протухшая ссылка филиала не открывает кабинет владельца', async () => {
    history.replaceState({}, '', '/?m=900010.stale')
    mockFetch({
      '/api/mountain/data/': () => new Response('{"error":"bad token"}', { status: 404 }),
      // сервер в dev-режиме отдаёт ссылку владельца любому, кто спросил без токена
      '/api/mountain/links': () => new Response(
        JSON.stringify({ owner: { tid: 1, link: '/m/8727082281.own' } }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }),
    })
    render(<Mountain />)

    await waitFor(() => expect(screen.getByText(/Ссылка/)).toBeTruthy())
    expect(screen.queryByText('Поставить задачу')).toBeNull()
    expect(screen.queryByText('Отправить всем')).toBeNull()
  })
})

describe('«Гора» глазами владельца', () => {
  it('видит все филиалы и картину по чек-листам, а не только свою сдачу', async () => {
    mockFetch({
      '/api/mountain/data/': () => new Response(
        JSON.stringify(board('owner', OWNER_BRANCHES)),
        { status: 200, headers: { 'Content-Type': 'application/json' } }),
      '/api/mountain/links': () => new Response(
        JSON.stringify({ owner: { tid: 1, link: '/m/8727082281.own' } }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }),
    })
    render(<Mountain />)

    await screen.findByText('Задачи филиалам')
    expect(screen.getAllByText(/Ступень/)).toHaveLength(3)
    // сдавать чек-листы владельцу нечего — но видеть, кто сдал, он обязан
    expect(screen.queryByText('Сдать чек-лист')).toBeNull()
    await screen.findByText('Чек-листы филиалов')
  })
})
