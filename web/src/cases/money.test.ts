import { describe, it, expect } from 'vitest'
import { kzt, kztRange, MIN_CASE_KZT } from './money'

describe('money', () => {
  it('формат ₸', () => {
    expect(kzt(340000)).toBe('340 000 ₸')
  })
  it('диапазон оценки в тыс', () => {
    expect(kztRange(300000, 380000)).toMatch(/тыс ₸/)
  })
  it('порог кейса', () => {
    expect(MIN_CASE_KZT).toBe(30000)
  })
})
