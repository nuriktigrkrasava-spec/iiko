import { useMemo } from 'react'
import type { ReactElement } from 'react'
import type { Case, Building } from '../cases/types'
import { buildingOf } from '../cases/nodes'
import { kzt } from '../cases/money'
import { haptic } from '../stories/tg'

/* ГОРОД — сцена по референсу «ночной квартал»: изометрический квартал,
   свет только из окон, единственный красный объект — здание с самой большой
   потерей (чем ярче, тем больше сумма). Люди в окнах и на улице, терраса
   с растениями, маркиза, павильон, фонари, курьер. Ни одной подписи на
   сцене; единственное число — сверху, поверх сцены. Тап по зданию — шторка. */

/* изометрия */
const iso = (x: number, y: number, z: number): [number, number] =>
  [(x - y) * 0.866, (x + y) * 0.5 - z]
const P = (list: [number, number, number][]): string =>
  list.map(([x, y, z]) => iso(x, y, z).map((n) => n.toFixed(1)).join(',')).join(' ')

/* палитра сцены (примитивы референса) */
const C = {
  ground: '#100E12', street: '#17151A', curb: '#1E1B20',
  faceL: '#1B1714', faceR: '#141114', top: '#221D1E', line: '#322A24',
  winDark: '#0B0A0E', winWarm: '#F1BA68', winPale: '#F7D9A4',
  winRed: '#EA4F10', redDeep: '#8A2A12',
  roofSlate: '#232030', roofRed: '#4C1F12',
  leafDark: '#2E4A1F', leaf: '#415119',
  awnA: '#2E5941', awnB: '#D8CFA8',
  skin: '#C8A882', body1: '#6B4E8C', body2: '#2F5D4A', body3: '#4A5D8C', body4: '#5D3A2E',
  scooter: '#8A2A12',
}

type Bld = {
  key: Building; label: string
  gx: number; gy: number; w: number; d: number; h: number
  cols: number; rows: number
  roof?: 'flat' | 'gable' | 'terrace'
  glass?: boolean
}

/* композиция по референсу: терраса сзади слева, тёмный блок сзади,
   стеклянный фасад справа, щипцовое здание в центре, павильон впереди */
const SCENE: Bld[] = [
  { key: 'storage', label: 'Склад', gx: 122, gy: 0, w: 92, d: 60, h: 64, cols: 4, rows: 2, roof: 'flat' },
  { key: 'hall', label: 'Зал', gx: 4, gy: 12, w: 82, d: 56, h: 100, cols: 4, rows: 4, roof: 'terrace' },
  { key: 'guests', label: 'Кабинет', gx: 234, gy: 26, w: 64, d: 52, h: 112, cols: 3, rows: 5, glass: true },
  { key: 'kitchen', label: 'Кухня', gx: 120, gy: 98, w: 72, d: 52, h: 62, cols: 3, rows: 2, roof: 'gable' },
  { key: 'cash', label: 'Касса', gx: 34, gy: 122, w: 48, d: 48, h: 34, cols: 3, rows: 1, roof: 'flat' },
]

export default function City({ cases, total, onOpenBuilding, onAsk, onReport, onFeed, embedded = false }: {
  cases: Case[]
  total: number
  onOpenBuilding: (b: Building, label: string) => void
  onAsk: () => void
  onReport: () => void
  onFeed: () => void
  embedded?: boolean
}) {
  const byBuilding = useMemo(() => {
    const m = new Map<Building, number>()
    for (const c of cases) {
      if (c.status === 'rejected' || c.status === 'closed') continue
      const b = buildingOf(c.node_id)
      m.set(b, (m.get(b) ?? 0) + c.amount_kzt)
    }
    return m
  }, [cases])
  const maxLoss = Math.max(1, ...byBuilding.values())

  return (
    <div className={`ct-root night ${embedded ? 'embedded' : ''}`}>
      <header className="ct-top">
        <div>
          <div className="ct-overline">На кону</div>
          <div className="ct-stake">{kzt(total)}</div>
        </div>
        <div className="ct-nav">
          <button className="ct-icon" onClick={onAsk} aria-label="Спросить">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="8" /><path d="m21 21-4.3-4.3" /></svg>
          </button>
          <button className="ct-icon" onClick={onReport} aria-label="Отчёт недели">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><rect x="3" y="3" width="7" height="18" rx="1" /><rect x="14" y="3" width="7" height="18" rx="1" /></svg>
          </button>
          <button className="ct-icon" onClick={onFeed} aria-label="Все дела">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M8 6h13" /><path d="M8 12h13" /><path d="M8 18h13" /><path d="M3 6h.01" /><path d="M3 12h.01" /><path d="M3 18h.01" /></svg>
          </button>
        </div>
      </header>

      <div className="ct-scene">
        <svg viewBox="-185 -75 555 425" role="group" aria-label="Квартал: здания отделов">
          <defs>
            <radialGradient id="ct-red-glow">
              <stop offset="0%" stopColor={C.redDeep} stopOpacity="0.9" />
              <stop offset="55%" stopColor="#561708" stopOpacity="0.45" />
              <stop offset="100%" stopColor="#561708" stopOpacity="0" />
            </radialGradient>
            <radialGradient id="ct-lamp-glow">
              <stop offset="0%" stopColor="#B88D53" stopOpacity="0.7" />
              <stop offset="100%" stopColor="#B88D53" stopOpacity="0" />
            </radialGradient>
          </defs>

          {/* площадка квартала и улица */}
          <polygon points={P([[-40, -35, 0], [340, -35, 0], [340, 195, 0], [-40, 195, 0]])} fill={C.ground} />
          <polygon points={P([[-40, 195, 0], [340, 195, 0], [340, 200, 0], [-40, 200, 0]])} fill={C.curb} />
          <polygon points={P([[-40, 200, 0], [340, 200, 0], [340, 262, 0], [-40, 262, 0]])} fill={C.street} />
          {/* разметка и переход */}
          {[0, 1, 2, 3, 4, 5, 6].map((i) => (
            <polygon key={`dash${i}`} points={P([[-20 + i * 52, 229, 0], [4 + i * 52, 229, 0], [4 + i * 52, 233, 0], [-20 + i * 52, 233, 0]])} fill="#2A272E" />
          ))}
          {[0, 1, 2, 3, 4].map((i) => (
            <polygon key={`zebra${i}`} points={P([[236 + i * 12, 202, 0], [243 + i * 12, 202, 0], [243 + i * 12, 258, 0], [236 + i * 12, 258, 0]])} fill="#2E2B33" shapeRendering="crispEdges" />
          ))}

          {/* здания в порядке глубины. Красный сигнал на сцене один,
              как на референсе: только самая большая потеря. Остальные
              проблемы ждут в шторках и в Ленте. */}
          {SCENE.map((b) => {
            const loss = byBuilding.get(b.key) ?? 0
            const heat = loss === maxLoss && loss > 0 ? 1 : 0
            return (
              <BuildingShape key={b.key} b={b} heat={heat}
                onOpen={() => { haptic('light'); onOpenBuilding(b.key, b.label) }} />
            )
          })}

          {/* маркиза-кафе у подножия Зала (декор, часть зала) */}
          <Awning gx={4} gy={68} w={62} />

          {/* деревья в кадках */}
          <Tree gx={100} gy={176} /> <Tree gx={218} gy={172} /> <Tree gx={-24} gy={168} />

          {/* фонари */}
          {[[-8, 210], [116, 214], [300, 208]].map(([x, y]) => {
            const [lx, ly] = iso(x, y, 30)
            const [bx, by] = iso(x, y, 0)
            return (
              <g key={`lamp${x}`} aria-hidden="true">
                <line x1={bx} y1={by} x2={lx} y2={ly} stroke={C.line} strokeWidth="2" />
                <circle cx={lx} cy={ly} r="15" fill="url(#ct-lamp-glow)" />
                <circle cx={lx} cy={ly} r="2.4" fill={C.winWarm} />
              </g>
            )
          })}

          {/* люди на площади и улице */}
          <Person gx={92} gy={150} c={C.body1} /> <Person gx={148} gy={166} c={C.body2} />
          <Person gx={196} gy={158} c={C.body3} /> <Person gx={252} gy={212} c={C.body4} />
          <Person gx={30} gy={186} c={C.body3} /> <Person gx={278} gy={244} c={C.body1} />

          {/* курьерский мопед с красным коробом */}
          <Scooter gx={-18} gy={238} />
        </svg>
      </div>

      <p className="ct-hint">Тапни по зданию, чтобы увидеть его проблемы</p>
    </div>
  )
}

/* ── здание ─────────────────────────────────────────────────────────────── */

function BuildingShape({ b, heat, onOpen }: { b: Bld; heat: number; onOpen: () => void }) {
  const { gx, gy, w, d, h } = b
  const X = (x: number) => gx + x
  const Y = (y: number) => gy + y
  const hot = heat > 0
  const litColor = hot ? (heat > 0.45 ? C.winRed : C.redDeep) : (b.glass ? C.winPale : C.winWarm)
  const litOpacity = hot ? 0.35 + heat * 0.65 : 0.88

  const top = P([[X(0), Y(0), h], [X(w), Y(0), h], [X(w), Y(d), h], [X(0), Y(d), h]])
  const right = P([[X(w), Y(0), 0], [X(w), Y(0), h], [X(w), Y(d), h], [X(w), Y(d), 0]])
  const front = P([[X(0), Y(d), 0], [X(0), Y(d), h], [X(w), Y(d), h], [X(w), Y(d), 0]])

  /* окна с людьми: часть окон горит, в некоторых — силуэты */
  const wins: ReactElement[] = []
  let n = 0
  const litEvery = hot ? 1 : b.glass ? 1 : 2 + (b.key.length % 2)
  const winH = b.glass ? 12 : 9
  for (let r = 0; r < b.rows; r++) {
    const wz = 10 + r * ((h - 18) / b.rows)
    const ww = (w - 14) / b.cols
    for (let c = 0; c < b.cols; c++) {
      const wx = 7 + c * ww
      const lit = n % litEvery === 0
      const withPerson = lit && (n * 7 + 3) % 4 === 0
      wins.push(
        <g key={`f${n}`}>
          <polygon points={P([[X(wx + 2), Y(d), wz], [X(wx + ww - 3), Y(d), wz], [X(wx + ww - 3), Y(d), wz + winH], [X(wx + 2), Y(d), wz + winH]])}
            fill={lit ? litColor : C.winDark} opacity={lit ? litOpacity : 1} shapeRendering="crispEdges" />
          {withPerson && (
            <polygon points={P([[X(wx + ww / 2 - 2), Y(d), wz], [X(wx + ww / 2 + 2), Y(d), wz], [X(wx + ww / 2 + 2), Y(d), wz + winH * 0.6], [X(wx + ww / 2 - 2), Y(d), wz + winH * 0.6]])}
              fill={C.winDark} opacity="0.85" shapeRendering="crispEdges" />
          )}
        </g>,
      )
      n++
    }
    const sideCols = Math.max(1, Math.round(b.cols * d / w))
    const dd = (d - 10) / sideCols
    for (let c = 0; c < sideCols; c++) {
      const wy = 5 + c * dd
      const lit = n % litEvery === 0
      wins.push(
        <polygon key={`s${n}`} points={P([[X(w), Y(wy + 2), wz], [X(w), Y(wy + dd - 2), wz], [X(w), Y(wy + dd - 2), wz + winH], [X(w), Y(wy + 2), wz + winH]])}
          fill={lit ? litColor : C.winDark} opacity={lit ? litOpacity * 0.8 : 1} shapeRendering="crispEdges" />,
      )
      n++
    }
  }

  const [cx, cy] = iso(X(w / 2), Y(d / 2), h / 2)

  return (
    <g className="ct-b" role="button" tabIndex={0} aria-label={`${b.label}: открыть проблемы`}
      onClick={onOpen}
      onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), onOpen())}>
      {hot && heat > 0.2 && (
        <ellipse cx={cx} cy={cy} rx={w * 1.15} ry={h * 0.95} fill="url(#ct-red-glow)" opacity={0.3 + heat * 0.55} />
      )}
      <polygon points={front} fill={C.faceL} stroke={C.line} strokeWidth="0.6" />
      <polygon points={right} fill={C.faceR} stroke={C.line} strokeWidth="0.6" />
      {b.roof !== 'gable' && <polygon points={top} fill={C.top} stroke={C.line} strokeWidth="0.6" />}

      {/* щипцовая крыша центрального здания */}
      {b.roof === 'gable' && (
        <>
          <polygon points={P([[X(0), Y(d), h], [X(w), Y(d), h], [X(w), Y(d / 2), h + 24], [X(0), Y(d / 2), h + 24]])}
            fill={heat > 0.45 ? C.roofRed : C.roofSlate} stroke={C.line} strokeWidth="0.6" />
          <polygon points={P([[X(w), Y(d), h], [X(w), Y(0), h], [X(w), Y(d / 2), h + 24]])}
            fill={C.faceR} stroke={C.line} strokeWidth="0.6" />
          {/* мансардное окно */}
          <polygon points={P([[X(w * 0.42), Y(d * 0.75), h + 8], [X(w * 0.58), Y(d * 0.75), h + 8], [X(w * 0.58), Y(d * 0.7), h + 17], [X(w * 0.42), Y(d * 0.7), h + 17]])}
            fill={hot ? C.winRed : C.winWarm} opacity={hot ? litOpacity : 0.85} shapeRendering="crispEdges" />
        </>
      )}

      {/* терраса на крыше: парапет, зелень, люди за столиками */}
      {b.roof === 'terrace' && (
        <>
          <polygon points={P([[X(0), Y(d), h], [X(0), Y(d), h + 5], [X(w), Y(d), h + 5], [X(w), Y(d), h]])} fill={C.faceL} />
          <polygon points={P([[X(w), Y(d), h], [X(w), Y(d), h + 5], [X(w), Y(0), h + 5], [X(w), Y(0), h]])} fill={C.faceR} />
          {[8, 26, 44, 62].map((px) => (
            <g key={`pl${px}`}>
              <polygon points={P([[X(px), Y(6), h + 4], [X(px + 12), Y(6), h + 4], [X(px + 12), Y(6), h + 10], [X(px), Y(6), h + 10]])} fill={C.leafDark} shapeRendering="crispEdges" />
              <polygon points={P([[X(px + 2), Y(6), h + 10], [X(px + 10), Y(6), h + 10], [X(px + 10), Y(6), h + 15], [X(px + 2), Y(6), h + 15]])} fill={C.leaf} shapeRendering="crispEdges" />
            </g>
          ))}
          {[[18, 30], [48, 34]].map(([px, py]) => (
            <g key={`tp${px}`}>
              <polygon points={P([[X(px), Y(py), h + 4], [X(px + 8), Y(py), h + 4], [X(px + 8), Y(py), h + 7], [X(px), Y(py), h + 7]])} fill={C.awnB} opacity="0.5" shapeRendering="crispEdges" />
              <polygon points={P([[X(px - 4), Y(py + 2), h + 4], [X(px - 1), Y(py + 2), h + 4], [X(px - 1), Y(py + 2), h + 12], [X(px - 4), Y(py + 2), h + 12]])} fill={C.body2} shapeRendering="crispEdges" />
              <polygon points={P([[X(px + 9), Y(py + 2), h + 4], [X(px + 12), Y(py + 2), h + 4], [X(px + 12), Y(py + 2), h + 12], [X(px + 9), Y(py + 2), h + 12]])} fill={C.body1} shapeRendering="crispEdges" />
            </g>
          ))}
        </>
      )}

      {/* вентблоки на плоских крышах */}
      {b.roof === 'flat' && b.h > 40 && (
        <>
          <polygon points={P([[X(10), Y(10), h], [X(24), Y(10), h], [X(24), Y(10), h + 8], [X(10), Y(10), h + 8]])} fill={C.faceR} />
          <polygon points={P([[X(10), Y(10), h + 8], [X(24), Y(10), h + 8], [X(24), Y(20), h + 8], [X(10), Y(20), h + 8]])} fill={C.top} />
        </>
      )}

      {wins}
    </g>
  )
}

/* ── декор ──────────────────────────────────────────────────────────────── */

function Awning({ gx, gy, w }: { gx: number; gy: number; w: number }) {
  const stripes: ReactElement[] = []
  const n = Math.floor(w / 8)
  for (let i = 0; i < n; i++) {
    stripes.push(
      <polygon key={i}
        points={P([[gx + i * 8, gy, 26], [gx + (i + 1) * 8, gy, 26], [gx + (i + 1) * 8, gy + 10, 20], [gx + i * 8, gy + 10, 20]])}
        fill={i % 2 === 0 ? C.awnA : C.awnB} shapeRendering="crispEdges" />,
    )
  }
  return <g aria-hidden="true">{stripes}</g>
}

function Tree({ gx, gy }: { gx: number; gy: number }) {
  return (
    <g aria-hidden="true">
      <polygon points={P([[gx, gy, 0], [gx + 10, gy, 0], [gx + 10, gy, 6], [gx, gy, 6]])} fill={C.curb} shapeRendering="crispEdges" />
      <polygon points={P([[gx + 4, gy, 6], [gx + 6, gy, 6], [gx + 6, gy, 12], [gx + 4, gy, 12]])} fill={C.line} shapeRendering="crispEdges" />
      <polygon points={P([[gx + 1, gy, 12], [gx + 9, gy, 12], [gx + 9, gy, 20], [gx + 1, gy, 20]])} fill={C.leafDark} shapeRendering="crispEdges" />
      <polygon points={P([[gx + 2.5, gy, 20], [gx + 7.5, gy, 20], [gx + 7.5, gy, 25], [gx + 2.5, gy, 25]])} fill={C.leaf} shapeRendering="crispEdges" />
    </g>
  )
}

function Person({ gx, gy, c }: { gx: number; gy: number; c: string }) {
  return (
    <g aria-hidden="true">
      <polygon points={P([[gx, gy, 0], [gx + 4, gy, 0], [gx + 4, gy, 8], [gx, gy, 8]])} fill={c} shapeRendering="crispEdges" />
      <polygon points={P([[gx + 0.5, gy, 8], [gx + 3.5, gy, 8], [gx + 3.5, gy, 11], [gx + 0.5, gy, 11]])} fill={C.skin} shapeRendering="crispEdges" />
    </g>
  )
}

function Scooter({ gx, gy }: { gx: number; gy: number }) {
  return (
    <g aria-hidden="true">
      <polygon points={P([[gx, gy, 2], [gx + 14, gy, 2], [gx + 14, gy, 6], [gx, gy, 6]])} fill="#26222A" shapeRendering="crispEdges" />
      <polygon points={P([[gx + 14, gy, 4], [gx + 22, gy, 4], [gx + 22, gy, 12], [gx + 14, gy, 12]])} fill={C.scooter} shapeRendering="crispEdges" />
      {(() => { const [x1, y1] = iso(gx + 3, gy, 1); const [x2, y2] = iso(gx + 12, gy, 1); return (<><circle cx={x1} cy={y1} r="2.4" fill={C.winDark} stroke={C.line} strokeWidth="0.8" /><circle cx={x2} cy={y2} r="2.4" fill={C.winDark} stroke={C.line} strokeWidth="0.8" /></>) })()}
      <polygon points={P([[gx + 2, gy, 6], [gx + 5, gy, 6], [gx + 5, gy, 13], [gx + 2, gy, 13]])} fill={C.body3} shapeRendering="crispEdges" />
      <polygon points={P([[gx + 2.5, gy, 13], [gx + 4.5, gy, 13], [gx + 4.5, gy, 15.5], [gx + 2.5, gy, 15.5]])} fill={C.skin} shapeRendering="crispEdges" />
    </g>
  )
}
