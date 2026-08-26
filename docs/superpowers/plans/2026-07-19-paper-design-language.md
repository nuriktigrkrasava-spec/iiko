# Дизайн-язык «Бумага» — план реализации (фаза 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Перевести `web/` с тёмного шаблонного дашборда на светлый дизайн-язык «Бумага» — токены, три гарнитуры, отказ от карточек, перекрашенные графики, восемь экранов на четырёх шаблонах.

**Architecture:** Токены объявляются один раз в `index.css` через Tailwind v4 `@theme` и раздаются как utility-классы. Цвета графиков вынесены в `lib/chartTheme.ts`, чтобы recharts не хардкодил их по экранам. `components/ui.tsx` теряет `Card` и получает набор примитивов «Бумаги». Экраны не рисуют собственную вёрстку — они собираются из примитивов.

**Tech Stack:** React 19, TypeScript, Vite 8, Tailwind CSS v4, recharts 3, lucide-react. Тесты — Vitest + @testing-library/react (добавляются в Task 1).

## Global Constraints

- Тема только светлая. Тёмной темы в этой фазе нет.
- Гарнитуры и их роли жёсткие:
  - **Playfair Display** (`font-display`) — цифры и метрики только от 22px (герои, крупные метрики, оценка). Короткие витринные надписи, которые читают один раз (название продукта, заголовок экрана), допустимы от 17px. **Никогда в `DataTable`** — он не моноширинный, колонки цифр разъезжаются — и никогда для подписей, лейблов и текста абзацами.
  - **Golos Text** (`font-sans`) — весь интерфейс: подписи, заголовки, текст.
  - **JetBrains Mono** + `tabular-nums` (класс `.tnum`) — числовые значения, которым нужна ровная ширина цифр: все колонки цифр в таблицах, а также отдельно стоящие денежные суммы и баллы. `.tnum` привязан к смыслу «это число», а не к тому, находится ли оно внутри `<table>`.
- Карточек нет. Структуру держат линейки (`border-rule`) и сетка. Скругления: `0` на структуре, `4px` на кнопках и полях ввода.
- Правило из `01 — Концепция`: **нет числа в тенге — инсайт не показываем.** У типа `Finding` поле `money` обязательное, не опциональное.
- Точные значения токенов:
  `--paper #faf7f2` · `--paper-2 #f2ede4` · `--ink #17171a` · `--ink-2 #57544c` · `--muted #8b8574` · `--rule #ded8cc` · `--neg #c8562f` · `--pos #2f7a52` · `--warn #b8860b`
- `--pos` / `--warn` / `--neg` — это же светофор 🟢🟡🔴. Отдельных цветов для светофора не заводить.
- Все существующие вызовы API и типы данных экранов остаются без изменений. Эта фаза не трогает бэкенд и не трогает `lib/api.ts`.
- Коммит после каждой задачи.

## Структура файлов

| Файл | Ответственность | Действие |
|---|---|---|
| `web/vite.config.ts` | сборка + конфиг Vitest | изменить |
| `web/src/lib/format.ts` | форматирование чисел | без изменений, покрыть тестами |
| `web/src/lib/chartTheme.ts` | цвета и стили recharts | создать |
| `web/src/lib/grade.ts` | балл → буква оценки | создать |
| `web/src/index.css` | токены, шрифты, базовые стили | переписать |
| `web/index.html` | title страницы | изменить |
| `web/src/components/ui.tsx` | примитивы «Бумаги» | переписать |
| `web/src/App.tsx` | оболочка, сгруппированная навигация | переписать |
| `web/src/screens/*.tsx` | 8 экранов | перевести на примитивы |

---

### Task 1: Тестовый каркас

Тестов в `web/` нет. Без них весь план держится на «посмотрел глазами». Начинаем с харнесса и покрываем им `format.ts`, который уже используется всеми экранами и ни разу не проверен.

**Files:**
- Modify: `web/package.json`
- Modify: `web/vite.config.ts`
- Test: `web/src/lib/format.test.ts` (создать)

**Interfaces:**
- Consumes: ничего
- Produces: команда `npm test` в `web/`; окружение `jsdom`; глобальные `describe`/`it`/`expect` без импорта

- [ ] **Step 1: Поставить зависимости**

```bash
cd web && npm i -D vitest@^3 @testing-library/react@^16 jsdom@^25
```

- [ ] **Step 2: Прописать Vitest в конфиг Vite**

Открыть `web/vite.config.ts` и добавить секцию `test` в объект, передаваемый в `defineConfig`. Первой строкой файла добавить директиву типов:

```ts
/// <reference types="vitest" />
```

Внутри `defineConfig({ ... })` добавить:

```ts
  test: {
    environment: 'jsdom',
    globals: true,
    css: false,
  },
```

- [ ] **Step 3: Добавить скрипт**

В `web/package.json` в секцию `scripts` добавить:

```json
    "test": "vitest run",
```

- [ ] **Step 4: Написать падающий тест**

Создать `web/src/lib/format.test.ts`:

```ts
import { tenge, tengeShort, num, pct } from './format'

describe('tenge', () => {
  it('форматирует с неразрывными разрядами и знаком тенге', () => {
    expect(tenge(944617)).toBe('944 617 ₸')
  })
  it('отдаёт прочерк на пустом значении', () => {
    expect(tenge(null)).toBe('—')
    expect(tenge(undefined)).toBe('—')
    expect(tenge(NaN)).toBe('—')
  })
  it('округляет до целых тенге', () => {
    expect(tenge(1234.6)).toBe('1 235 ₸')
  })
})

describe('tengeShort', () => {
  it('сокращает миллионы с запятой как разделителем', () => {
    expect(tengeShort(2906787)).toBe('2,9 млн ₸')
  })
  it('сокращает тысячи', () => {
    expect(tengeShort(52330)).toBe('52 тыс ₸')
  })
  it('не сокращает мелкие суммы', () => {
    expect(tengeShort(940)).toBe('940 ₸')
  })
  it('работает на отрицательных', () => {
    expect(tengeShort(-2906787)).toBe('-2,9 млн ₸')
  })
})

describe('pct', () => {
  it('ставит плюс на росте', () => {
    expect(pct(21.4)).toBe('+21,4%')
  })
  it('не ставит плюс когда попросили без знака', () => {
    expect(pct(21.4, false)).toBe('21,4%')
  })
  it('минус остаётся всегда', () => {
    expect(pct(-34.3)).toBe('-34,3%')
  })
})

describe('num', () => {
  it('разделяет разряды', () => {
    expect(num(14759)).toBe('14 759')
  })
})
```

- [ ] **Step 5: Запустить и убедиться, что тесты идут**

Run: `cd web && npm test`
Expected: тесты выполняются. Если какой-то падает — это настоящий баг в `format.ts`, зафиксируй его в выводе и почини `format.ts`, а не тест. Ожидаемое место расхождения — `Intl.NumberFormat('ru-RU')` использует узкий неразрывный пробел `U+202F`, а не обычный. Если тесты падают именно из-за этого, замени в тестах пробелы на те, что реально отдаёт `Intl`, взяв их из вывода теста.

- [ ] **Step 6: Коммит**

```bash
cd /Users/kiluazoldik/Desktop/Work/iiiko
git add web/package.json web/package-lock.json web/vite.config.ts web/src/lib/format.test.ts
git commit -m "test(web): каркас Vitest + покрытие format.ts"
```

---

### Task 2: Токены и шрифты

**Files:**
- Modify: `web/src/index.css` (переписать целиком)
- Modify: `web/index.html`

**Interfaces:**
- Consumes: ничего
- Produces: utility-классы `bg-paper` `bg-paper2` `text-ink` `text-ink2` `text-muted` `border-rule` `text-neg` `text-pos` `text-warn`; семейства `font-display` `font-sans` `font-mono`; класс `.tnum` для табличных цифр

- [ ] **Step 1: Переписать `web/src/index.css`**

```css
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;500;600&family=Golos+Text:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
@import "tailwindcss";

/* Дизайн-язык «Бумага»: светлый финансовый отчёт.
   pos/warn/neg — это же светофор 🟢🟡🔴 из «01 — Концепция». */
@theme {
  --color-paper:  #faf7f2;
  --color-paper2: #f2ede4;
  --color-ink:    #17171a;
  --color-ink2:   #57544c;
  --color-muted:  #8b8574;
  --color-rule:   #ded8cc;
  --color-neg:    #c8562f;
  --color-pos:    #2f7a52;
  --color-warn:   #b8860b;

  --font-display: "Playfair Display", Georgia, serif;
  --font-sans:    "Golos Text", ui-sans-serif, system-ui, sans-serif;
  --font-mono:    "JetBrains Mono", ui-monospace, monospace;
}

* { box-sizing: border-box; }

html, body, #root { height: 100%; margin: 0; }

body {
  background: var(--color-paper);
  color: var(--color-ink);
  font-family: var(--font-sans);
  -webkit-font-smoothing: antialiased;
}

/* Цифры в таблицах: моноширинные, колонки выстраиваются столбиком */
.tnum {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.02em;
}

/* Подпись капсом — повторяется на каждом экране */
.eyebrow {
  font-size: 9px;
  letter-spacing: 0.11em;
  text-transform: uppercase;
  color: var(--color-muted);
  font-weight: 600;
}

::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-thumb { background: #d6cec0; border-radius: 8px; }
::-webkit-scrollbar-thumb:hover { background: #c4bbaa; }

@media (prefers-reduced-motion: no-preference) {
  .fade-in { animation: fade 0.3s ease both; }
  @keyframes fade { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }
}
```

- [ ] **Step 2: Поправить title страницы**

В `web/index.html` заменить `<title>web</title>` на:

```html
    <title>iiko Финдиректор</title>
```

- [ ] **Step 3: Проверить, что сборка проходит**

Run: `cd web && npm run build`
Expected: сборка падает с ошибками TypeScript в экранах — они всё ещё ссылаются на классы старых токенов (`bg-panel`, `text-faint`, `border-border`). Это ожидаемо: Tailwind не типизирует классы, поэтому падений TS быть не должно, а вот классы вроде `bg-panel` просто перестанут существовать и элементы станут прозрачными. Сборка должна **пройти успешно**, а сайт временно выглядеть сломанным. Если `npm run build` завершился с ошибкой — читай ошибку, она не про токены.

- [ ] **Step 4: Коммит**

```bash
git add web/src/index.css web/index.html
git commit -m "feat(web): токены и гарнитуры «Бумаги»"
```

---

### Task 3: Тема графиков и функция оценки

Два маленьких модуля с чистой логикой, оба нужны компонентам из Task 4.

**Files:**
- Create: `web/src/lib/chartTheme.ts`
- Create: `web/src/lib/grade.ts`
- Test: `web/src/lib/grade.test.ts`

**Interfaces:**
- Consumes: ничего
- Produces: `CHART` (объект с полями `ink`, `neg`, `pos`, `warn`, `muted`, `rule`, `paper`, `axis`, `tooltip`, `grid`); `gradeOf(score: number): string`

- [ ] **Step 1: Написать падающий тест оценки**

Создать `web/src/lib/grade.test.ts`:

```ts
import { gradeOf } from './grade'

describe('gradeOf', () => {
  it('отдаёт A на девяноста и выше', () => {
    expect(gradeOf(90)).toBe('A')
    expect(gradeOf(100)).toBe('A')
  })
  it('различает B+ и B', () => {
    expect(gradeOf(86)).toBe('B+')
    expect(gradeOf(75)).toBe('B')
  })
  it('различает C+ и C', () => {
    expect(gradeOf(72)).toBe('C+')
    expect(gradeOf(61)).toBe('C')
  })
  it('отдаёт D и E внизу шкалы', () => {
    expect(gradeOf(55)).toBe('D')
    expect(gradeOf(10)).toBe('E')
  })
  it('зажимает выход за границы шкалы', () => {
    expect(gradeOf(140)).toBe('A')
    expect(gradeOf(-20)).toBe('E')
  })
})
```

- [ ] **Step 2: Запустить, убедиться что падает**

Run: `cd web && npm test`
Expected: FAIL — `Failed to resolve import "./grade"`

- [ ] **Step 3: Написать `web/src/lib/grade.ts`**

```ts
/** Балл 0–100 → буквенная оценка. Используется на экранах «Оценка». */
export function gradeOf(score: number): string {
  const s = Math.max(0, Math.min(100, score))
  if (s >= 90) return 'A'
  if (s >= 85) return 'B+'
  if (s >= 75) return 'B'
  if (s >= 70) return 'C+'
  if (s >= 60) return 'C'
  if (s >= 50) return 'D'
  return 'E'
}
```

- [ ] **Step 4: Запустить, убедиться что проходит**

Run: `cd web && npm test`
Expected: PASS, все тесты `gradeOf` зелёные

- [ ] **Step 5: Написать `web/src/lib/chartTheme.ts`**

Сейчас эти цвета захардкожены прямо в JSX трёх экранов. Выносим один раз, чтобы перекраска не расползлась.

```ts
/** Единственный источник цветов для recharts. В JSX экранов цвета не хардкодить. */
export const CHART = {
  ink: '#17171a',
  neg: '#c8562f',
  pos: '#2f7a52',
  warn: '#b8860b',
  muted: '#8b8574',
  rule: '#ded8cc',
  paper: '#faf7f2',
  paper2: '#f2ede4',

  /** подписи осей */
  axis: {
    fill: '#8b8574',
    fontSize: 10,
    fontFamily: '"Golos Text", sans-serif',
  },

  /** горизонтальная сетка — волосяная, вертикальной нет */
  grid: {
    stroke: '#ded8cc',
    strokeWidth: 1,
  },

  /** всплывающая подсказка: бумага с чернильной рамкой, без скруглений и теней */
  tooltip: {
    background: '#faf7f2',
    border: '1px solid #17171a',
    borderRadius: 0,
    color: '#17171a',
    fontFamily: '"Golos Text", sans-serif',
    fontSize: 12,
    boxShadow: 'none',
  },
} as const
```

- [ ] **Step 6: Проверить типы**

Run: `cd web && npx tsc -b`
Expected: без ошибок

- [ ] **Step 7: Коммит**

```bash
git add web/src/lib/chartTheme.ts web/src/lib/grade.ts web/src/lib/grade.test.ts
git commit -m "feat(web): тема графиков и шкала оценки"
```

---

### Task 4: Примитивы «Бумаги»

`Card` уходит целиком. Экраны собираются из этих примитивов и своей вёрстки почти не имеют.

**Files:**
- Modify: `web/src/components/ui.tsx` (переписать целиком)
- Test: `web/src/components/ui.test.tsx` (создать)

**Interfaces:**
- Consumes: `pct` из `lib/format`, `gradeOf` из `lib/grade`
- Produces:
  - `Section({ title, hint?, children })`
  - `Hero({ label, value, delta?, note? })`
  - `Metric({ label, value, delta?, invert? })`
  - `Delta({ value, invert? })`
  - `DataTable({ columns, rows })` где `columns: Column[]`, `rows: ReactNode[][]`
  - `type Column = { key: string; label: string; align?: 'left' | 'right'; numeric?: boolean }`
  - `type Finding = { title: string; detail: string; money: number; tone?: 'neg' | 'warn' | 'pos' }`
  - `FindingRow({ finding })`
  - `Grade({ score, label })`
  - `MiniBar({ value, max, tone? })`
  - `Loading({ label? })`
  - `ErrorBox({ msg })`
  - `Empty({ msg })`

- [ ] **Step 1: Написать падающие тесты**

Создать `web/src/components/ui.test.tsx`:

```tsx
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
```

- [ ] **Step 2: Запустить, убедиться что падает**

Run: `cd web && npm test`
Expected: FAIL — `Delta`, `Metric`, `DataTable`, `Grade`, `FindingRow`, `Empty` не экспортируются

- [ ] **Step 3: Переписать `web/src/components/ui.tsx`**

```tsx
import type { ReactNode } from 'react'
import { pct, tenge } from '../lib/format'
import { gradeOf } from '../lib/grade'

/* ── Структура ───────────────────────────────────────────── */

/** Секция вместо карточки: заголовок капсом + линейка снизу. */
export function Section({ title, hint, children }: {
  title: string; hint?: string; children: ReactNode
}) {
  return (
    <section className="border-b border-rule py-6 last:border-b-0">
      <div className="mb-4 flex items-baseline justify-between gap-3">
        <h2 className="eyebrow">{title}</h2>
        {hint && <span className="text-[11px] text-muted">{hint}</span>}
      </div>
      {children}
    </section>
  )
}

/* ── Числа ───────────────────────────────────────────────── */

/** Рост зелёный, падение красное. invert — когда рост это плохо (фудкост). */
export function Delta({ value, invert = false }: {
  value: number | null | undefined; invert?: boolean
}) {
  if (value == null || Number.isNaN(value)) return null
  const good = invert ? value < 0 : value > 0
  const tone = value === 0 ? 'text-muted' : good ? 'text-pos' : 'text-neg'
  const arrow = value === 0 ? '' : value > 0 ? '▲' : '▼'
  return (
    <span className={`text-xs font-semibold ${tone}`}>
      {arrow} {pct(Math.abs(value), false)}
    </span>
  )
}

/** Герой экрана. Playfair — единственное место, где он крупный. */
export function Hero({ label, value, delta, note }: {
  label: string; value: string; delta?: number | null; note?: string
}) {
  return (
    <div className="border-b border-rule py-7 fade-in">
      <div className="eyebrow mb-3">{label}</div>
      <div className="flex items-baseline gap-4">
        <span className="font-display text-[46px] leading-none tracking-tight">{value}</span>
        <Delta value={delta} />
      </div>
      {note && <p className="mt-3 max-w-lg text-[13px] leading-relaxed text-ink2">{note}</p>}
    </div>
  )
}

/** Метрика в ряду. Playfair на 22px — нижняя граница его допустимого кегля. */
export function Metric({ label, value, delta, invert }: {
  label: string; value: ReactNode; delta?: number | null; invert?: boolean
}) {
  return (
    <div className="border-r border-rule px-5 py-4 last:border-r-0">
      <div className="eyebrow mb-2">{label}</div>
      <div className="flex items-baseline gap-2">
        <span className="font-display text-[24px] leading-none">{value}</span>
        <Delta value={delta} invert={invert} />
      </div>
    </div>
  )
}

/** Ряд метрик — сетка без промежутков, разделители держат линейки. */
export function MetricRow({ children }: { children: ReactNode }) {
  return <div className="grid grid-cols-2 border-b border-rule lg:grid-cols-4">{children}</div>
}

/* ── Таблица ─────────────────────────────────────────────── */

export type Column = {
  key: string
  label: string
  align?: 'left' | 'right'
  /** цифровая колонка: моноширинный шрифт и выравнивание вправо */
  numeric?: boolean
}

export function DataTable({ columns, rows }: { columns: Column[]; rows: ReactNode[][] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[13px]">
        <thead>
          <tr className="border-b border-ink">
            {columns.map((c) => (
              <th
                key={c.key}
                className={`eyebrow pb-2 ${c.numeric || c.align === 'right' ? 'text-right' : 'text-left'}`}
              >
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-b border-rule last:border-b-0">
              {row.map((cell, j) => {
                const c = columns[j]
                const numeric = c?.numeric || c?.align === 'right'
                return (
                  <td
                    key={j}
                    className={`py-2.5 ${numeric ? 'tnum text-right' : 'text-left text-ink'}`}
                  >
                    {cell}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Горизонтальный бар внутри таблиц. */
export function MiniBar({ value, max, tone = 'ink' }: {
  value: number; max: number; tone?: 'ink' | 'neg' | 'pos'
}) {
  const w = max > 0 ? Math.max(2, Math.round((value / max) * 100)) : 0
  const bg = tone === 'neg' ? 'bg-neg' : tone === 'pos' ? 'bg-pos' : 'bg-ink'
  return (
    <div className="h-1 w-full overflow-hidden bg-paper2">
      <div className={`h-full ${bg}`} style={{ width: `${w}%` }} />
    </div>
  )
}

/* ── Инсайты ─────────────────────────────────────────────── */

/**
 * Правило из «01 — Концепция»: нет числа в тенге — инсайт не показываем.
 * Поэтому `money` обязательное. Не делать его опциональным.
 */
export type Finding = {
  title: string
  detail: string
  money: number
  tone?: 'neg' | 'warn' | 'pos'
}

export function FindingRow({ finding }: { finding: Finding }) {
  const tone = finding.tone ?? 'neg'
  const color = tone === 'pos' ? 'text-pos' : tone === 'warn' ? 'text-warn' : 'text-neg'
  return (
    <div className="border-b border-rule py-4 last:border-b-0">
      <div className="flex items-baseline justify-between gap-4">
        <h3 className="text-[14px] font-semibold text-ink">{finding.title}</h3>
        <span className={`tnum shrink-0 text-[13px] font-semibold ${color}`}>
          {tenge(finding.money)}
        </span>
      </div>
      <p className="mt-1.5 text-[12.5px] leading-relaxed text-ink2">{finding.detail}</p>
    </div>
  )
}

/* ── Оценка ──────────────────────────────────────────────── */

export function Grade({ score, label }: { score: number; label: string }) {
  const letter = gradeOf(score)
  const tone = score >= 75 ? 'text-pos' : score >= 60 ? 'text-warn' : 'text-neg'
  return (
    <div className="px-5 py-4">
      <div className="eyebrow mb-2">{label}</div>
      <div className="flex items-baseline gap-3">
        <span className={`font-display text-[38px] leading-none ${tone}`}>{letter}</span>
        <span className="tnum text-[12px] text-muted">{score} из 100</span>
      </div>
    </div>
  )
}

/* ── Состояния ───────────────────────────────────────────── */

export function Loading({ label = 'Загрузка данных…' }: { label?: string }) {
  return (
    <div className="flex h-64 flex-col items-center justify-center gap-3 text-muted">
      <div className="h-5 w-5 animate-spin rounded-full border-2 border-rule border-t-ink" />
      <span className="text-sm">{label}</span>
    </div>
  )
}

export function ErrorBox({ msg }: { msg: string }) {
  return (
    <div className="border-l-2 border-neg bg-paper2 px-4 py-3 text-sm text-neg">
      Не удалось загрузить: {msg}
    </div>
  )
}

export function Empty({ msg }: { msg: string }) {
  return (
    <div className="flex h-40 items-center justify-center text-sm text-muted">{msg}</div>
  )
}
```

- [ ] **Step 4: Запустить тесты**

Run: `cd web && npm test`
Expected: PASS, все тесты `ui.test.tsx` зелёные

- [ ] **Step 5: Проверить типы**

Run: `cd web && npx tsc -b`
Expected: ошибки в восьми экранах — они импортируют `Card`, `Stat`, `SectionTitle`, `Bar`, которых больше нет. Это ожидаемо и чинится в Task 6–9.

- [ ] **Step 6: Коммит**

```bash
git add web/src/components/ui.tsx web/src/components/ui.test.tsx
git commit -m "feat(web): примитивы «Бумаги» вместо карточек"
```

---

### Task 5: Оболочка и сгруппированная навигация

**Files:**
- Modify: `web/src/App.tsx` (переписать целиком)

**Interfaces:**
- Consumes: `Period` из `lib/api`, экраны из `screens/*`
- Produces: `type Screen`, оболочка с группами навигации

- [ ] **Step 1: Переписать `web/src/App.tsx`**

Плоский список из восьми пунктов заменяется группами. Пункты `Цель`, `Соцсети`, `Персонал`, `Меню` в этой фазе не добавляются — под них заложены группы, но экранов ещё нет.

```tsx
import { useState } from 'react'
import type { ReactNode } from 'react'
import type { Period } from './lib/api'
import Insights from './screens/Insights'
import Dashboard from './screens/Dashboard'
import Comparison from './screens/Comparison'
import Foodcost from './screens/Foodcost'
import Expenses from './screens/Expenses'
import Shifts from './screens/Shifts'
import Anomalies from './screens/Anomalies'
import Reviews from './screens/Reviews'

type Screen = {
  id: string
  label: string
  group: string
  render: (p: Period, nav: (id: string) => void) => ReactNode
  periodic: boolean
}

const SCREENS: Screen[] = [
  { id: 'ai',     label: 'Аналитика',  group: 'Сводка',    periodic: false, render: (_p, nav) => <Insights onOpen={nav} /> },
  { id: 'dash',   label: 'Главная',    group: 'Сводка',    periodic: true,  render: (p) => <Dashboard period={p} /> },
  { id: 'fc',     label: 'Фудкост',    group: 'Деньги',    periodic: true,  render: (p) => <Foodcost period={p} /> },
  { id: 'exp',    label: 'Расходы',    group: 'Деньги',    periodic: true,  render: (p) => <Expenses period={p} /> },
  { id: 'yoy',    label: 'Год к году', group: 'Деньги',    periodic: false, render: () => <Comparison /> },
  { id: 'shifts', label: 'Смены',      group: 'Операции',  periodic: true,  render: (p) => <Shifts period={p} /> },
  { id: 'anom',   label: 'Аномалии',   group: 'Операции',  periodic: true,  render: (p) => <Anomalies period={p} /> },
  { id: 'rev',    label: 'Отзывы',     group: 'Оценки',    periodic: false, render: () => <Reviews /> },
]

const GROUPS = ['Сводка', 'Деньги', 'Операции', 'Оценки']

const PERIODS: { id: Period; label: string }[] = [
  { id: 'today', label: 'Сегодня' },
  { id: 'yesterday', label: 'Вчера' },
  { id: 'week', label: 'Неделя' },
  { id: 'month', label: 'Месяц' },
]

export default function App() {
  const [active, setActive] = useState('ai')
  const [period, setPeriod] = useState<Period>('month')
  const screen = SCREENS.find((s) => s.id === active)!

  return (
    <div className="flex min-h-screen bg-paper">
      <aside className="sticky top-0 hidden h-screen w-56 shrink-0 flex-col border-r border-rule md:flex">
        <div className="border-b border-ink px-5 py-5">
          <div className="font-display text-[17px] leading-tight">iiko Финдиректор</div>
          <div className="mt-0.5 text-[11px] text-muted">Демо Ресторан · Алматы</div>
        </div>

        <nav className="flex-1 overflow-y-auto px-3 py-4">
          {GROUPS.map((g) => {
            const items = SCREENS.filter((s) => s.group === g)
            if (items.length === 0) return null
            return (
              <div key={g} className="mb-5">
                <div className="eyebrow px-2 pb-2">{g}</div>
                {items.map((s) => (
                  <button
                    key={s.id}
                    onClick={() => setActive(s.id)}
                    className={`block w-full cursor-pointer px-2 py-1.5 text-left text-[13px] transition-colors ${
                      s.id === active
                        ? 'border-l-2 border-neg font-semibold text-ink'
                        : 'border-l-2 border-transparent text-ink2 hover:text-ink'
                    }`}
                  >
                    {s.label}
                  </button>
                ))}
              </div>
            )
          })}
        </nav>

        <div className="border-t border-rule px-5 py-4 text-[11px] text-muted">
          данные примерные · демо-режим
        </div>
      </aside>

      <main className="min-w-0 flex-1">
        <header className="sticky top-0 z-10 flex flex-wrap items-baseline justify-between gap-3 border-b-2 border-ink bg-paper px-8 py-4">
          <h1 className="font-display text-[19px]">{screen.label}</h1>
          {screen.periodic && (
            <div className="flex items-center gap-4">
              {PERIODS.map((p) => (
                <button
                  key={p.id}
                  onClick={() => setPeriod(p.id)}
                  className={`eyebrow cursor-pointer pb-0.5 transition-colors ${
                    period === p.id
                      ? 'border-b-2 border-neg text-ink'
                      : 'border-b-2 border-transparent hover:text-ink'
                  }`}
                >
                  {p.label}
                </button>
              ))}
            </div>
          )}
        </header>

        <div className="mx-auto max-w-4xl px-8 pb-16">{screen.render(period, setActive)}</div>
      </main>
    </div>
  )
}
```

- [ ] **Step 2: Проверить типы**

Run: `cd web && npx tsc -b`
Expected: ошибок в `App.tsx` нет; ошибки остаются только в экранах (Task 6–9)

- [ ] **Step 3: Коммит**

```bash
git add web/src/App.tsx
git commit -m "feat(web): оболочка «Бумаги» и группы навигации"
```

---

### Task 6: Экраны «Разбор» — Аналитика и Главная

**Files:**
- Modify: `web/src/screens/Dashboard.tsx`
- Modify: `web/src/screens/Insights.tsx`

**Interfaces:**
- Consumes: `Hero`, `Metric`, `MetricRow`, `Section`, `DataTable`, `FindingRow`, `Loading`, `ErrorBox` из `components/ui`; `CHART` из `lib/chartTheme`
- Produces: ничего для последующих задач

- [ ] **Step 1: Переписать `web/src/screens/Dashboard.tsx`**

Четыре одинаковые плитки заменяются на герой + ряд метрик. Цвета графика берутся из `CHART`, а не хардкодятся.

```tsx
import { useApi } from '../lib/useApi'
import type { Period } from '../lib/api'
import { Hero, Metric, MetricRow, Section, Loading, ErrorBox } from '../components/ui'
import { CHART } from '../lib/chartTheme'
import { tenge, tengeShort, num } from '../lib/format'
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid, Cell,
} from 'recharts'

type Dash = {
  revenue_today: number; revenue_change: number
  avg_check: number; avg_check_change: number
  guests: number; guests_change: number
  open_orders: number; forecast: number
  chart_7days: { labels: string[]; data: number[] }
}

export default function Dashboard({ period }: { period: Period }) {
  const { data, error, loading } = useApi<Dash>('dashboard', { period })
  if (loading) return <Loading />
  if (error || !data) return <ErrorBox msg={error || 'нет данных'} />

  const chart = data.chart_7days.labels.map((l, i) => ({ day: l, rev: data.chart_7days.data[i] }))
  const maxRev = Math.max(...data.chart_7days.data)
  const avg7 = Math.round(
    data.chart_7days.data.reduce((a, b) => a + b, 0) / data.chart_7days.data.length,
  )

  return (
    <div>
      <Hero
        label="Выручка за период"
        value={tenge(data.revenue_today)}
        delta={data.revenue_change}
        note={`Средняя за 7 дней — ${tenge(avg7)}. Прогноз месяца — ${tengeShort(data.forecast)}.`}
      />

      <MetricRow>
        <Metric label="Средний чек" value={tenge(data.avg_check)} delta={data.avg_check_change} />
        <Metric label="Гостей" value={num(data.guests)} delta={data.guests_change} />
        <Metric label="Открытые заказы" value={num(data.open_orders)} />
        <Metric label="Прогноз месяца" value={tengeShort(data.forecast)} />
      </MetricRow>

      <Section title="Динамика за 7 дней" hint="выручка по кассовым сменам">
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chart} margin={{ top: 8, right: 4, left: 4, bottom: 0 }}>
              <CartesianGrid stroke={CHART.grid.stroke} vertical={false} />
              <XAxis dataKey="day" tick={CHART.axis} axisLine={false} tickLine={false} />
              <YAxis
                tick={CHART.axis} axisLine={false} tickLine={false}
                tickFormatter={(v) => `${Math.round(v / 1000)}k`} width={40}
              />
              <Tooltip
                cursor={{ fill: CHART.paper2 }}
                contentStyle={CHART.tooltip}
                formatter={(v: number) => [tenge(v), 'Выручка']}
              />
              <Bar dataKey="rev" maxBarSize={46}>
                {chart.map((c, i) => (
                  <Cell key={i} fill={c.rev === maxRev ? CHART.neg : CHART.ink} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Section>
    </div>
  )
}
```

- [ ] **Step 2: Переписать `web/src/screens/Insights.tsx`**

Прочитай текущий файл целиком перед правкой — у него собственная структура данных от `insights_service.py`. Задача: заменить `Card`/`Stat`/`SectionTitle` на `Hero`/`Section`/`FindingRow`, сохранив кликабельность инсайтов (`onOpen`). Каждый инсайт обязан иметь денежное значение — если бэкенд его не отдаёт, инсайт не рендерится, а не показывается без суммы.

- [ ] **Step 3: Проверить типы и тесты**

Run: `cd web && npx tsc -b && npm test`
Expected: ошибок в `Dashboard.tsx` и `Insights.tsx` нет; тесты зелёные

- [ ] **Step 4: Коммит**

```bash
git add web/src/screens/Dashboard.tsx web/src/screens/Insights.tsx web/src/lib/chartTheme.ts
git commit -m "feat(web): Аналитика и Главная на шаблоне «Разбор»"
```

---

### Task 7: Экраны «Реестр» — Фудкост и Расходы

**Files:**
- Modify: `web/src/screens/Foodcost.tsx`
- Modify: `web/src/screens/Expenses.tsx`

**Interfaces:**
- Consumes: `Hero`, `Metric`, `MetricRow`, `Section`, `DataTable`, `MiniBar`, `Loading`, `ErrorBox`, `Column`; `CHART`
- Produces: ничего

- [ ] **Step 1: Переписать `web/src/screens/Foodcost.tsx`**

```tsx
import { useApi } from '../lib/useApi'
import type { Period } from '../lib/api'
import {
  Hero, Metric, MetricRow, Section, DataTable, MiniBar, Loading, ErrorBox,
} from '../components/ui'
import type { Column } from '../components/ui'
import { CHART } from '../lib/chartTheme'
import { tenge, pct } from '../lib/format'
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid,
} from 'recharts'

type Dish = { name: string; category: string; revenue: number; count: number; cost_pct: number }
type FC = {
  norm_pct: number; fact_pct: number; diff_pct: number
  norm_sum: number; fact_sum: number; warning?: string
  trend: { month: string; fact: number; norm: number }[]
  dishes: Dish[]
}

const COLUMNS: Column[] = [
  { key: 'name', label: 'Блюдо' },
  { key: 'category', label: 'Категория' },
  { key: 'revenue', label: 'Выручка', numeric: true },
  { key: 'cost', label: 'Фудкост', numeric: true },
]

export default function Foodcost({ period }: { period: Period }) {
  const { data, error, loading } = useApi<FC>('foodcost', { period })
  if (loading) return <Loading />
  if (error || !data) return <ErrorBox msg={error || 'нет данных'} />

  const overspend = data.fact_sum - data.norm_sum
  const dishes = [...data.dishes].sort((a, b) => b.cost_pct - a.cost_pct)
  const maxCost = Math.max(...dishes.map((d) => d.cost_pct), data.norm_pct)

  const rows = dishes.map((d) => {
    const bad = d.cost_pct > data.norm_pct
    return [
      d.name,
      <span className="text-ink2">{d.category}</span>,
      tenge(d.revenue),
      <div className="flex items-center justify-end gap-3">
        <div className="w-20"><MiniBar value={d.cost_pct} max={maxCost} tone={bad ? 'neg' : 'ink'} /></div>
        <span className={bad ? 'text-neg' : 'text-ink'}>{d.cost_pct}%</span>
      </div>,
    ]
  })

  return (
    <div>
      <Hero
        label="Переплата по себестоимости"
        value={tenge(overspend)}
        note={
          `Фактический фудкост ${pct(data.fact_pct, false)} против нормы ${pct(data.norm_pct, false)}. ` +
          `Расхождение ${pct(data.diff_pct, false)}.` + (data.warning ? ` ${data.warning}` : '')
        }
      />

      <MetricRow>
        <Metric label="Норма" value={pct(data.norm_pct, false)} />
        <Metric label="Факт" value={pct(data.fact_pct, false)} delta={data.diff_pct} invert />
        <Metric label="Норма, сумма" value={tenge(data.norm_sum)} />
        <Metric label="Факт, сумма" value={tenge(data.fact_sum)} />
      </MetricRow>

      <Section title="Тренд фудкоста" hint="факт против нормы по месяцам">
        <div className="h-56">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data.trend} margin={{ top: 8, right: 8, left: 4, bottom: 0 }}>
              <CartesianGrid stroke={CHART.grid.stroke} vertical={false} />
              <XAxis dataKey="month" tick={CHART.axis} axisLine={false} tickLine={false} />
              <YAxis tick={CHART.axis} axisLine={false} tickLine={false}
                tickFormatter={(v) => `${v}%`} width={36} domain={[0, 'dataMax + 4']} />
              <Tooltip
                contentStyle={CHART.tooltip}
                formatter={(v: number, n) => [`${v}%`, n === 'fact' ? 'Факт' : 'Норма']}
              />
              <Line type="monotone" dataKey="norm" stroke={CHART.muted} strokeWidth={1.5} strokeDasharray="4 4" dot={false} />
              <Line type="monotone" dataKey="fact" stroke={CHART.neg} strokeWidth={2} dot={{ r: 2.5, fill: CHART.neg }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </Section>

      <Section title="Блюда под контролем" hint="отсортировано по себестоимости">
        <DataTable columns={COLUMNS} rows={rows} />
      </Section>
    </div>
  )
}
```

- [ ] **Step 2: Переписать `web/src/screens/Expenses.tsx`**

Прочитай текущий файл целиком перед правкой. Задача: герой — общая сумма расходов за период; ряд метрик по крупнейшим категориям; `DataTable` со списком расходов, где денежные колонки помечены `numeric: true`. Все цвета графиков — только из `CHART`.

- [ ] **Step 3: Проверить типы и тесты**

Run: `cd web && npx tsc -b && npm test`
Expected: ошибок в этих двух экранах нет; тесты зелёные

- [ ] **Step 4: Коммит**

```bash
git add web/src/screens/Foodcost.tsx web/src/screens/Expenses.tsx
git commit -m "feat(web): Фудкост и Расходы на шаблоне «Реестр»"
```

---

### Task 8: Экраны «Реестр» — Смены, Аномалии, Год к году

**Files:**
- Modify: `web/src/screens/Shifts.tsx`
- Modify: `web/src/screens/Anomalies.tsx`
- Modify: `web/src/screens/Comparison.tsx`

**Interfaces:**
- Consumes: `Hero`, `Metric`, `MetricRow`, `Section`, `DataTable`, `FindingRow`, `MiniBar`, `Loading`, `ErrorBox`, `Column`; `CHART`
- Produces: ничего

- [ ] **Step 1: Переписать три экрана**

Прочитай каждый файл целиком перед правкой. Для всех трёх:

- `Card` → `Section`, `Stat` → `Metric` внутри `MetricRow`, `SectionTitle` → параметр `title` у `Section`, `Bar` → `MiniBar`.
- Собственные `<table>` заменить на `DataTable`, денежные и процентные колонки пометить `numeric: true`.
- Все цвета recharts брать из `CHART`. В JSX не должно остаться ни одного строкового hex-цвета.
- `Anomalies` — каждая аномалия это `Finding`, у неё обязана быть сумма в тенге. Аномалия без суммы не рендерится.
- `Comparison` — герой это разница год к году в тенге, а не процент. Процент идёт дельтой.

- [ ] **Step 2: Убедиться, что hex-цветов в экранах не осталось**

Run: `cd web && grep -rn "#[0-9a-fA-F]\{6\}" src/screens/`
Expected: пустой вывод

- [ ] **Step 3: Проверить типы и тесты**

Run: `cd web && npx tsc -b && npm test`
Expected: без ошибок, тесты зелёные

- [ ] **Step 4: Коммит**

```bash
git add web/src/screens/Shifts.tsx web/src/screens/Anomalies.tsx web/src/screens/Comparison.tsx
git commit -m "feat(web): Смены, Аномалии и Год к году на шаблоне «Реестр»"
```

---

### Task 9: Экран «Оценка» — Отзывы, и финальная проверка

**Files:**
- Modify: `web/src/screens/Reviews.tsx`

**Interfaces:**
- Consumes: `Grade`, `Hero`, `Section`, `DataTable`, `FindingRow`, `Loading`, `ErrorBox`
- Produces: ничего

- [ ] **Step 1: Переписать `web/src/screens/Reviews.tsx`**

Прочитай текущий файл целиком. Это первый экран шаблона «Оценка», по нему потом будут делаться Соцсети и Персонал:

- Сверху `Grade` — балл площадки, переведённый в букву. Если бэкенд отдаёт рейтинг 0–5, привести к 100-балльной шкале умножением на 20 перед передачей в `Grade`.
- Ниже `Section` «Из чего сложилось» — составляющие балла.
- Ниже `Section` «Доказательства» — список отзывов через `DataTable`.

- [ ] **Step 2: Проверить всё разом**

Run: `cd web && npx tsc -b && npm test && npm run lint && npm run build`
Expected: все четыре команды проходят без ошибок

- [ ] **Step 3: Поднять приложение и посмотреть глазами**

```bash
cd /Users/kiluazoldik/Desktop/Work/iiiko
uvicorn api:app --port 8000 &
cd web && npm run dev
```

Открыть выданный Vite адрес. Пройти по всем восьми экранам и проверить:
- нигде не осталось тёмного фона и синих акцентов;
- Playfair нигде не стоит в таблицах;
- колонки цифр выстраиваются столбиком;
- ни один инсайт не показан без суммы в тенге.

- [ ] **Step 4: Коммит**

```bash
git add web/src/screens/Reviews.tsx
git commit -m "feat(web): Отзывы на шаблоне «Оценка»"
```

---

## Самопроверка плана

**Покрытие спеки.** Токены — Task 2. Типографика и её роли — Task 2 + Global Constraints. Отказ от карточек — Task 4. Перекраска графиков — Task 3 (тема) + Task 6–8 (применение). Информационная архитектура — Task 5. Шаблон «Разбор» — Task 6. «Реестр» — Task 7–8. «Оценка» — Task 9. Правило тенге — Task 4 (тип `Finding`) + Task 6, 8.

**Шаблон «Табло» из спеки в этой фазе не реализуется** — он обслуживает экран «Цель» и виджеты, а это фазы 3 и 4. Здесь его строить не из чего.

**Не покрыто намеренно:** отвязка от `demo-org-1` (фаза 2), движок целей (фаза 3), виджеты (фаза 4), оценки соцсетей и персонала (за пределами спеки).
