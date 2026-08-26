import { render, screen } from '@testing-library/react'
import ChecklistUpload from './ChecklistUpload'

/* Регрессия: сданный чек-лист выглядел несданным.

   Сервер отдаёт подпись зоны строчными («зал»), а на сайте зоны подписаны с
   заглавной («Зал») — сверка шла по подписи и не сходилась на регистре. Ни
   галочки в таблице, ни строки «уже сдано в 10:47» управляющий не видел
   никогда, и чек-лист выглядел потерянным. Сверяем по КЛЮЧУ зоны. */

// Время прибито: экран сам выбирает ближайший прошедший слот, и «уже сдано»
// показывается только для выбранного — иначе тест зелёный или красный по часам.
beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  vi.setSystemTime(new Date(2026, 7, 26, 10, 50))
})
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })

it('отмечает сданный слот галочкой, хотя подписи зон в разном регистре', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({
    day: '2026-08-26', slots: ['10:45', '15:00', '20:45', '23:45'],
    done: [{ branch: 'Астана, ул. Г.Алиева 10 (EXPO)', slot: '10:45',
             zone: 'зал', zone_key: 'hall', photos: 4, at: '10:47' }],
  }), { status: 200, headers: { 'Content-Type': 'application/json' } })))

  render(<ChecklistUpload token="900010.sig" />)

  expect(await screen.findByText(/✓ 4 · 10:47/)).toBeTruthy()
  expect(screen.getByText(/уже сдано в 10:47/)).toBeTruthy()
})
