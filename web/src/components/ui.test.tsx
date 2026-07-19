import { render, screen } from '@testing-library/react'
import { Delta, Metric, DataTable, Grade, FindingRow, Empty } from './ui'

describe('Delta', () => {
  it('красит рост зелёным и рисует стрелку вверх', () => {
    const { container } = render(<Delta value={21.4} />)
    expect(container.textContent).toContain('▲')
    expect(container.querySelector('.text-pos')).not.toBeNull()
  })
  it('красит падение красным', () => {
    const { container } = render(<Delta value={-34.3} />)
    expect(container.textContent).toContain('▼')
    expect(container.querySelector('.text-neg')).not.toBeNull()
  })
  it('при invert рост считается плохим', () => {
    const { container } = render(<Delta value={6} invert />)
    expect(container.querySelector('.text-neg')).not.toBeNull()
  })
  it('ничего не рисует на пустом значении', () => {
    const { container } = render(<Delta value={null} />)
    expect(container.firstChild).toBeNull()
  })
})

describe('Metric', () => {
  it('показывает подпись и значение', () => {
    render(<Metric label="Средний чек" value="14 759 ₸" />)
    expect(screen.getByText('Средний чек')).toBeTruthy()
    expect(screen.getByText('14 759 ₸')).toBeTruthy()
  })
})

describe('DataTable', () => {
  it('числовым колонкам ставит моноширинный класс и правое выравнивание', () => {
    const { container } = render(
      <DataTable
        columns={[
          { key: 'name', label: 'Блюдо' },
          { key: 'rev', label: 'Выручка', numeric: true },
        ]}
        rows={[['Рибай', '4 200 000 ₸']]}
      />,
    )
    const cells = container.querySelectorAll('tbody td')
    expect(cells[0].className).not.toContain('tnum')
    expect(cells[1].className).toContain('tnum')
    expect(cells[1].className).toContain('text-right')
  })
})

describe('Grade', () => {
  it('переводит балл в букву', () => {
    render(<Grade score={72} label="Оценка ресторана" />)
    expect(screen.getByText('C+')).toBeTruthy()
  })
})

describe('FindingRow', () => {
  it('показывает сумму потерь рядом с заголовком', () => {
    render(<FindingRow finding={{ title: 'Допники в убыток', detail: 'cost 72%', money: 205000 }} />)
    expect(screen.getByText('Допники в убыток')).toBeTruthy()
    expect(screen.getByText('205 000 ₸')).toBeTruthy()
  })
})

describe('Empty', () => {
  it('показывает сообщение', () => {
    render(<Empty msg="Нет данных за период" />)
    expect(screen.getByText('Нет данных за период')).toBeTruthy()
  })
})
