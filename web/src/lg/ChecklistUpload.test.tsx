import { render, screen } from '@testing-library/react'
import ChecklistUpload from './ChecklistUpload'
import { issueText, nearestSlot, sentIn, type Done } from './checklist'

/* Чек-лист глазами управляющего: что сдано и что с этим не так. */

const done: Done[] = [{
  branch: 'Астана, ул. Г.Алиева 10 (EXPO)', slot: '10:45',
  zone: 'зал', zone_key: 'hall', photos: 4, at: '10:47',
}]

function mock(body: Record<string, unknown>) {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(body),
    { status: 200, headers: { 'Content-Type': 'application/json' } })))
}

beforeEach(() => {
  // Время прибито: экран сам выбирает ближайший прошедший слот, и без этого
  // тест был бы зелёным или красным по часам запуска.
  vi.useFakeTimers({ shouldAdvanceTime: true })
  vi.setSystemTime(new Date(2026, 7, 26, 10, 50))
})
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })

describe('замечание разбора', () => {
  /* Модель отдаёт объекты {zone, what}. Их склеивали как строки — на экран
     падало «[object Object]», то есть ровно то, ради чего разбор и затевался,
     управляющий не узнавал. */
  it('объект превращается в читаемую строку, а не в [object Object]', () => {
    expect(issueText({ zone: 'санузел', what: 'нет мыла' })).toBe('санузел: нет мыла')
  })
  it('строку оставляет как есть — старый формат ответа', () => {
    expect(issueText('грязный пол')).toBe('грязный пол')
  })
  it('половинчатое замечание не теряется', () => {
    expect(issueText({ what: 'мусор у входа' })).toBe('мусор у входа')
  })
})

describe('сверка сдачи', () => {
  it('сходится по ключу зоны, хотя подписи в разном регистре', () => {
    expect(sentIn(done, '10:45', 'hall')?.at).toBe('10:47')
  })
  it('несданную зону не выдумывает', () => {
    expect(sentIn(done, '10:45', 'wc')).toBeUndefined()
  })
  it('ближайший слот — прошедший, а не будущий', () => {
    expect(nearestSlot(new Date(2026, 7, 26, 16, 10))).toBe('15:00')
  })
})

describe('экран сдачи', () => {
  it('показывает, какие зоны сданы: галочка на зоне и счётчик на слоте', async () => {
    mock({ done })
    render(<ChecklistUpload token="btok.sig" />)
    // на кнопке зоны — время сдачи, на кнопке слота — сколько зон из трёх
    expect(await screen.findByText('10:47')).toBeTruthy()
    expect(screen.getByText('1/3')).toBeTruthy()
    expect(screen.getAllByText('0/3')).toHaveLength(3)   // остальные три слота
  })

  it('показывает замечания разбора за сегодня', async () => {
    mock({ done, reviews: [{ slot: '10:45', ok: false, issues: [{ zone: 'санузел', what: 'нет мыла' }] }] })
    render(<ChecklistUpload token="btok.sig" />)
    await screen.findByText('Замечания за сегодня')
    expect(screen.getByText('санузел: нет мыла')).toBeTruthy()
  })

  it('чистый разбор в замечания не попадает', async () => {
    mock({ done, reviews: [{ slot: '10:45', ok: true, issues: [] }] })
    render(<ChecklistUpload token="btok.sig" />)
    await screen.findByText('Сдать чек-лист')
    expect(screen.queryByText('Замечания за сегодня')).toBeNull()
  })
})
