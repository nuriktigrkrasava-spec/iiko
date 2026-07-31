import { useMemo, useRef, useState, useEffect } from 'react'
import type { ReactNode } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import { OrbitControls, Html, ContactShadows, Environment, Lightformer } from '@react-three/drei'
import * as THREE from 'three'
import { motion, AnimatePresence } from 'framer-motion'
import { Dash, FC, Exp, YoY, Staff, Anom } from './screens'
import Analytics from './Analytics'
import Supply from './Supply'
import Reputation from './Reputation'
import Seating from './Seating'
import { Icon } from './icons'

/* ─────────────────────────────────────────────────────────────
   Ресторанный город iiko — острова-департаменты в настоящем 3D.
   Каждый департамент = парящий остров с детальным тематическим
   зданием и подписью «за что отвечает». Острова связаны мостами,
   по которым бегают человечки. В центре — башня iiko (лендмарк).
   Крути сцену мышкой, клик по острову → снизу выезжает отчёт.
   ───────────────────────────────────────────────────────────── */

type Kind = 'tower' | 'bank' | 'restaurant' | 'warehouse' | 'antenna' | 'watchtower' | 'pavilion' | 'house' | 'kiosk' | 'obelisk'

type Dept = {
  id: string; name: string; role: string; emoji: string; kind: Kind; tone: string
  sev: number // 0..1 — острота проблемы/статуса; задаёт высоту башни
  commuters?: number // сколько людей идёт в здание (напр. занятые столы)
  courier?: boolean // курьер с коробкой (пришла накладная)
  grow?: string // «перекрыл планку» → стройка нового здания; текст = почему
  render: () => ReactNode
  pin?: { tone: string; text: string } // уведомление, которое «говорит» человечек
}

// тёплый вечерний квартал: природный мир (трава + тёплый камень), приглушённые крыши
const M = { body: '#efe9df', mid: '#d8cfc0', dark: '#5b5249', roof: '#3a342d', islandTop: '#7f8a5e', islandInner: '#c7bda9', islandLow: '#463d34', wood: '#b98a55', glass: '#bcd2e2', warm: '#ffcf9b' }

// статус-цвета (по методичке дашбордов: зелёный/янтарь/красный)
const S = { up: '#22a565', warn: '#e0972f', bad: '#e0524b' }

// каждому департаменту — свой чёткий отличимый цвет (категориальная палитра), чтобы не путать
const CENTER: Dept = { id: 'ai', name: 'ИИ-советник', role: 'мозг сети — сводит все данные', emoji: '🏛', kind: 'tower', tone: '#4a6fe3', sev: 0.95, render: Analytics, pin: { tone: S.bad, text: '1,8 млн потерь' } }

const RING: Dept[] = [
  { id: 'dash', name: 'Выручка', role: 'деньги и продажи', emoji: '🏦', kind: 'bank', tone: '#22a565', sev: 0.28, render: Dash, pin: { tone: S.up, text: 'выручка ▲19%' } },
  { id: 'fc', name: 'Кухня · фудкост', role: 'себестоимость блюд', emoji: '🍳', kind: 'restaurant', tone: '#e0972f', sev: 0.62, render: FC, pin: { tone: S.warn, text: 'фудкост 36%' } },
  { id: 'inv', name: 'Склад · закупки', role: 'запасы и накладные', emoji: '📦', kind: 'warehouse', tone: '#ef7a43', sev: 0.68, courier: true, render: Supply, pin: { tone: S.warn, text: 'говядина +18%' } },
  { id: 'soc', name: 'Соцсети', role: 'контент и охваты', emoji: '📡', kind: 'antenna', tone: '#58a7e8', sev: 0.32, render: Reputation },
  { id: 'anom', name: 'Аномалии', role: 'сигналы о проблемах', emoji: '🚨', kind: 'watchtower', tone: '#e0524b', sev: 0.8, render: Anom, pin: { tone: S.warn, text: 'сирена' } },
  { id: 'seat', name: 'Посадка зала', role: 'загрузка столов', emoji: '🍽', kind: 'pavilion', tone: '#16b8a0', sev: 0.3, commuters: 6, render: Seating, pin: { tone: S.up, text: 'занято 63%' } },
  { id: 'staff', name: 'Персонал', role: 'смены и люди', emoji: '🏠', kind: 'house', tone: '#6d6fe0', sev: 0.26, grow: 'Смены укомплектованы — расширяем команду', render: Staff },
  { id: 'exp', name: 'Расходы', role: 'платежи и счета', emoji: '💳', kind: 'kiosk', tone: '#9b6ae0', sev: 0.34, render: Exp },
  { id: 'yoy', name: 'Год к году', role: 'динамика и тренды', emoji: '📈', kind: 'obelisk', tone: '#24b0c4', sev: 0.3, grow: 'Тренд вверх 3 месяца — запускаем новый проект', render: YoY },
]

/* тёмная/светлая тема — читаем data-theme и реагируем на переключение */
function useThemeDark() {
  const [dark, setDark] = useState(() => document.documentElement.getAttribute('data-theme') !== 'light')
  useEffect(() => {
    const el = document.documentElement
    const obs = new MutationObserver(() => setDark(el.getAttribute('data-theme') !== 'light'))
    obs.observe(el, { attributes: true, attributeFilter: ['data-theme'] })
    return () => obs.disconnect()
  }, [])
  return dark
}

/* ─── переиспользуемые детали ─── */
function Emissive({ color, i = 0.9 }: { color: string; i?: number }) {
  return <meshStandardMaterial color={color} emissive={color} emissiveIntensity={i} roughness={0.4} />
}



/* текстура светлого мрамора (Carrara): белая база + мягкие серые прожилки */
let _marbleTex: THREE.Texture | null = null
function marbleTexture() {
  if (_marbleTex) return _marbleTex
  const s = 256, c = document.createElement('canvas'); c.width = c.height = s
  const g = c.getContext('2d')!
  g.fillStyle = '#eef0f1'; g.fillRect(0, 0, s, s)
  const rnd = (n: number) => { const x = Math.sin(n * 91.7) * 43758.5; return x - Math.floor(x) }
  const vein = (col: string, wMax: number, count: number, seed: number) => {
    for (let k = 0; k < count; k++) {
      g.strokeStyle = col; g.lineWidth = 0.6 + rnd(seed + k) * wMax
      g.beginPath()
      let x = rnd(seed + k + 1) * s, y = rnd(seed + k + 2) * s
      g.moveTo(x, y)
      const steps = 5 + Math.floor(rnd(seed + k + 3) * 4)
      for (let j = 0; j < steps; j++) {
        const nx = x + (rnd(seed + k * 5 + j) - 0.5) * 90, ny = y + (rnd(seed + k * 7 + j) - 0.5) * 90
        g.quadraticCurveTo(x + (rnd(k + j) - 0.5) * 40, y + (rnd(k - j) - 0.5) * 40, nx, ny); x = nx; y = ny
      }
      g.stroke()
    }
  }
  vein('rgba(150,160,172,0.30)', 2.4, 12, 10)   // основные серые прожилки
  vein('rgba(120,132,146,0.16)', 1.3, 22, 200)  // тонкая паутина
  vein('rgba(196,180,150,0.12)', 1.0, 3, 500)   // едва тёплые жилки
  _marbleTex = new THREE.CanvasTexture(c); _marbleTex.colorSpace = THREE.SRGBColorSpace
  return _marbleTex
}

/* ─ реквизит мраморной площади: латунные фонари, мраморные тумбы с акцентной сферой ─ */
function Lamppost({ position }: { position: [number, number, number] }) {
  return (
    <group position={position}>
      <mesh castShadow position={[0, 0.22, 0]}><cylinderGeometry args={[0.028, 0.04, 0.44, 10]} /><meshStandardMaterial color="#b9975b" metalness={0.7} roughness={0.34} /></mesh>
      <mesh position={[0, 0.47, 0]}><sphereGeometry args={[0.058, 14, 14]} /><Emissive color="#ffe6b0" i={1.1} /></mesh>
    </group>
  )
}
function Pedestal({ position, tone }: { position: [number, number, number]; tone: string }) {
  return (
    <group position={position}>
      <mesh castShadow position={[0, 0.1, 0]}><boxGeometry args={[0.22, 0.2, 0.22]} /><meshStandardMaterial color={MARBLE} map={marbleTexture()} roughness={0.3} metalness={0.05} /></mesh>
      <mesh position={[0, 0.205, 0]}><boxGeometry args={[0.25, 0.03, 0.25]} /><meshStandardMaterial color="#b9975b" metalness={0.6} roughness={0.35} /></mesh>
      <mesh castShadow position={[0, 0.3, 0]}><sphereGeometry args={[0.085, 20, 20]} /><meshStandardMaterial color={tone} roughness={0.32} metalness={0.2} /></mesh>
    </group>
  )
}
function Urn({ position, s = 1, rot = 0 }: { position: [number, number, number]; s?: number; rot?: number }) {
  return (
    <group position={position} scale={s} rotation={[0, rot, 0]}>
      <mesh castShadow position={[0, 0.09, 0]}><cylinderGeometry args={[0.075, 0.05, 0.18, 14]} /><meshStandardMaterial color={MARBLE} map={marbleTexture()} roughness={0.32} metalness={0.05} /></mesh>
      <mesh position={[0, 0.19, 0]}><torusGeometry args={[0.07, 0.014, 8, 16]} /><meshStandardMaterial color="#b9975b" metalness={0.6} roughness={0.35} /></mesh>
    </group>
  )
}

/* реквизит мраморной площади: фонари, тумбы-скульптуры, вазоны, инкрустированная дорожка */
function IsleDressing({ r, seed, tone }: { r: number; seed: number; tone: string }) {
  const items = useMemo(() => {
    const plaza = r * 0.72
    const out: ReactNode[] = []
    const n = Math.round(r * 2.6)
    for (let i = 0; i < n; i++) {
      const a = seed * 1.7 + i * 2.399963 // золотой угол — равномерный разброс
      const rad = plaza * (0.82 + ((i * 7) % 5) / 5 * 0.14)
      const x = Math.cos(a) * rad, z = Math.sin(a) * rad
      const t = (i + Math.round(seed)) % 4
      if (t === 1) out.push(<Pedestal key={i} position={[x, 0.03, z]} tone={tone} />)
      else if (t === 2) out.push(<Urn key={i} position={[x, 0.03, z]} s={0.85 + (i % 3) * 0.2} rot={a} />)
      else out.push(<Lamppost key={i} position={[x, 0.03, z]} />)
    }
    // инкрустированная дорожка к входу (+z) — акцент отдела на мраморе
    for (let k = 0; k < 4; k++) {
      const pz = plaza * 0.9 - k * (plaza * 0.22)
      out.push(<mesh key={`p${k}`} position={[0, 0.045, pz]} rotation={[-Math.PI / 2, 0, 0]}><planeGeometry args={[0.26, 0.13]} /><meshStandardMaterial color={tone} roughness={0.45} metalness={0.15} /></mesh>)
    }
    return out
  }, [r, seed, tone])
  return <group>{items}</group>
}

/* парящий МРАМОРНЫЙ ПОСТАМЕНТ (Carrara): полир. плита + золотая обводка + акцентная инкрустация отдела */
const MARBLE = '#e9ebed', MARBLE_DK = '#d6d9dc', GOLD = '#c2a568'
function IsleBase({ r, tone }: { r: number; tone: string }) {
  return (
    <group>
      {/* верхняя плита (полир. мрамор) */}
      <mesh castShadow receiveShadow position={[0, -0.13, 0]}>
        <cylinderGeometry args={[r, r * 0.98, 0.26, 6]} />
        <meshStandardMaterial color={MARBLE} map={marbleTexture()} roughness={0.24} metalness={0.08} />
      </mesh>
      {/* золотая обводка по верхнему краю */}
      <mesh position={[0, 0.02, 0]}><cylinderGeometry args={[r * 1.008, r * 1.008, 0.035, 6]} /><meshStandardMaterial color={GOLD} metalness={0.75} roughness={0.3} /></mesh>
      {/* акцентная инкрустация департамента — тонкая полоса чуть ниже золота */}
      <mesh position={[0, -0.03, 0]}><cylinderGeometry args={[r * 1.012, r * 1.012, 0.05, 6]} /><meshStandardMaterial color={tone} roughness={0.45} metalness={0.15} emissive={tone} emissiveIntensity={0.12} /></mesh>
      {/* приподнятая площадка под здание */}
      <mesh receiveShadow position={[0, 0.02, 0]}><cylinderGeometry args={[r * 0.7, r * 0.7, 0.04, 6]} /><meshStandardMaterial color={MARBLE} map={marbleTexture()} roughness={0.22} metalness={0.08} /></mesh>
      {/* тело-пьедестал (мрамор темнее, сужается) */}
      <mesh castShadow position={[0, -0.62, 0]}><cylinderGeometry args={[r * 0.86, r * 0.6, 0.75, 6]} /><meshStandardMaterial color={MARBLE_DK} map={marbleTexture()} roughness={0.3} metalness={0.06} /></mesh>
      {/* золотой поясок по телу */}
      <mesh position={[0, -0.38, 0]}><cylinderGeometry args={[r * 0.81, r * 0.81, 0.03, 6]} /><meshStandardMaterial color={GOLD} metalness={0.7} roughness={0.34} /></mesh>
      {/* база-подножие */}
      <mesh castShadow position={[0, -1.12, 0]}><cylinderGeometry args={[r * 0.62, r * 0.44, 0.34, 6]} /><meshStandardMaterial color={MARBLE} map={marbleTexture()} roughness={0.32} metalness={0.06} /></mesh>
      {/* остриё-низ вниз (парящий постамент) */}
      <mesh position={[0, -1.62, 0]} rotation={[Math.PI, 0, 0]}><coneGeometry args={[r * 0.44, 0.86, 6]} /><meshStandardMaterial color={MARBLE_DK} map={marbleTexture()} roughness={0.34} metalness={0.05} flatShading /></mesh>
    </group>
  )
}

/* ─── здания-скайлайн + утилиты ─── */
const BLACK = '#141519' // корпус стройки
// высота акцентной башни: чем острее статус/проблема (sev 0..1), тем выше
const accentHeight = (sev: number, landmark?: boolean) => (landmark ? 1.3 + sev * 2.4 : 0.7 + sev * 2.0)
const mix = (a: string, b: string, t: number) => new THREE.Color(a).lerp(new THREE.Color(b), t).getStyle()

// окна GitHub-городка: тёмный фасад + тесная сетка жёлтых окон + карта свечения
let _winTex: { map: THREE.Texture; emis: THREE.Texture } | null = null
function windowTextures() {
  if (_winTex) return _winTex
  const S = 128, cols = 6, rows = 11, pad = 6, gap = 4
  const cw = (S - pad * 2 - gap * (cols - 1)) / cols, rh = (S - pad * 2 - gap * (rows - 1)) / rows
  const mk = () => { const c = document.createElement('canvas'); c.width = c.height = S; return c }
  const fc = mk(), ec = mk(), g = fc.getContext('2d')!, eg = ec.getContext('2d')!
  g.fillStyle = '#333941'; g.fillRect(0, 0, S, S)        // тёмный фасад
  eg.fillStyle = '#000000'; eg.fillRect(0, 0, S, S)
  for (let r = 0; r < rows; r++) for (let col = 0; col < cols; col++) {
    const x = pad + col * (cw + gap), y = pad + r * (rh + gap)
    const lit = (r * 7 + col * 5 + ((r * col) % 3)) % 4 < 3   // большинство окон горит
    g.fillStyle = lit ? '#ffd15e' : '#3f4650'                 // жёлтое / тёмное окно
    g.fillRect(x, y, cw, rh)
    if (lit) { eg.fillStyle = '#ffbe3d'; eg.fillRect(x, y, cw, rh) }
  }
  const map = new THREE.CanvasTexture(fc), emis = new THREE.CanvasTexture(ec)
  map.colorSpace = THREE.SRGBColorSpace
  _winTex = { map, emis }
  return _winTex
}

/* униформа человечка — своя для каждого департамента (роль читается по одежде) */
type Outfit = { shirt: string; pants?: string; skin?: string; hair?: string; apron?: string; vest?: string; hat?: string }
const OUTFITS: Record<string, Outfit> = {
  ai: { shirt: '#2f3a52', pants: '#20263a', hat: '#1c2334' },                          // аналитик — тёмный костюм
  dash: { shirt: '#f0f2f5', pants: '#2b3038', vest: '#22a565' },                       // финансист — рубашка + зелёный жилет
  fc: { shirt: '#f4f2ec', pants: '#3a3d42', apron: '#b0663a', hat: '#f4f2ec' },        // повар — белый китель + колпак
  inv: { shirt: '#d7d1c4', pants: '#3a4048', vest: '#e0972f', hat: '#c7bdac' },        // склад — янтарный жилет + кепка
  soc: { shirt: '#58a7e8', pants: '#2f3644', hat: '#39445a' },                         // соцсети — синее худи + шапка
  anom: { shirt: '#3a3f4a', pants: '#2a2e36', vest: '#e0524b', hat: '#2b2f36' },       // охрана — тёмная форма + красный жилет
  seat: { shirt: '#eef1f4', pants: '#2b3038', apron: '#2f3a44', hair: '#3a2f27' },     // официант — фартук
  staff: { shirt: '#6d6fe0', pants: '#33385a' },                                       // персонал — индиго
  exp: { shirt: '#f0eef6', pants: '#33304a', vest: '#9b6ae0' },                         // бухгалтер — фиолетовый жилет
  yoy: { shirt: '#24b0c4', pants: '#243a44' },                                          // аналитик трендов — циан
}
function outfitFor(dept: Dept): Outfit {
  return OUTFITS[dept.id] ?? { shirt: mix(dept.tone, '#dcd6ca', 0.42), pants: '#39414d' }
}

/* низкополигональный человечек в одежде: ноги(штаны), торс(рубашка)+жилет/фартук, руки+кисти, голова+волосы/шапка */
function Human({ shirt = '#8bb0cf', pants = '#39414d', skin = '#f0c6a0', hair = '#3a2f27', apron, vest, hat, walk = true, scale = 1 }: Outfit & { walk?: boolean; scale?: number }) {
  const ll = useRef<THREE.Group>(null), rl = useRef<THREE.Group>(null)
  const la = useRef<THREE.Group>(null), ra = useRef<THREE.Group>(null)
  const ph = useMemo(() => Math.random() * 10, [])
  useFrame(({ clock }) => {
    const s = walk ? Math.sin(clock.elapsedTime * 8 + ph) * 0.5 : Math.sin(clock.elapsedTime * 2 + ph) * 0.05
    if (ll.current) ll.current.rotation.x = s
    if (rl.current) rl.current.rotation.x = -s
    if (la.current) la.current.rotation.x = -s
    if (ra.current) ra.current.rotation.x = s
  })
  return (
    <group scale={scale}>
      {/* ноги + ботинки */}
      <group ref={ll} position={[-0.045, 0.2, 0]}>
        <mesh position={[0, -0.1, 0]}><boxGeometry args={[0.05, 0.2, 0.05]} /><meshStandardMaterial color={pants} roughness={0.85} /></mesh>
        <mesh position={[0, -0.205, 0.012]}><boxGeometry args={[0.056, 0.03, 0.082]} /><meshStandardMaterial color="#26262a" /></mesh>
      </group>
      <group ref={rl} position={[0.045, 0.2, 0]}>
        <mesh position={[0, -0.1, 0]}><boxGeometry args={[0.05, 0.2, 0.05]} /><meshStandardMaterial color={pants} roughness={0.85} /></mesh>
        <mesh position={[0, -0.205, 0.012]}><boxGeometry args={[0.056, 0.03, 0.082]} /><meshStandardMaterial color="#26262a" /></mesh>
      </group>
      {/* торс + жилет/фартук */}
      <mesh position={[0, 0.32, 0]}><boxGeometry args={[0.14, 0.24, 0.1]} /><meshStandardMaterial color={shirt} roughness={0.75} /></mesh>
      {vest && <mesh position={[0, 0.33, 0.006]}><boxGeometry args={[0.152, 0.2, 0.106]} /><meshStandardMaterial color={vest} roughness={0.55} emissive={vest} emissiveIntensity={0.12} /></mesh>}
      {apron && <mesh position={[0, 0.25, 0.056]}><boxGeometry args={[0.12, 0.22, 0.016]} /><meshStandardMaterial color={apron} roughness={0.8} /></mesh>}
      {/* руки + кисти */}
      <group ref={la} position={[-0.09, 0.43, 0]}>
        <mesh position={[0, -0.085, 0]}><boxGeometry args={[0.036, 0.17, 0.036]} /><meshStandardMaterial color={shirt} roughness={0.75} /></mesh>
        <mesh position={[0, -0.185, 0]}><sphereGeometry args={[0.026, 8, 8]} /><meshStandardMaterial color={skin} /></mesh>
      </group>
      <group ref={ra} position={[0.09, 0.43, 0]}>
        <mesh position={[0, -0.085, 0]}><boxGeometry args={[0.036, 0.17, 0.036]} /><meshStandardMaterial color={shirt} roughness={0.75} /></mesh>
        <mesh position={[0, -0.185, 0]}><sphereGeometry args={[0.026, 8, 8]} /><meshStandardMaterial color={skin} /></mesh>
      </group>
      {/* голова + волосы/шапка */}
      <mesh position={[0, 0.5, 0]}><sphereGeometry args={[0.062, 14, 14]} /><meshStandardMaterial color={skin} roughness={0.6} /></mesh>
      {!hat && <mesh position={[0, 0.525, -0.008]}><sphereGeometry args={[0.066, 14, 12, 0, Math.PI * 2, 0, Math.PI * 0.62]} /><meshStandardMaterial color={hair} roughness={0.9} /></mesh>}
      {hat && <mesh position={[0, 0.555, 0]}><cylinderGeometry args={[0.058, 0.066, 0.055, 12]} /><meshStandardMaterial color={hat} roughness={0.7} /></mesh>}
    </group>
  )
}

/* Одно здание на остров (второе появляется как стройка при росте показателей).
   Тёмный корпус в тесных жёлтых окнах (GitHub-городок) + акцентная отделка отдела; высота = статус. */
function Building({ tone, r, sev, landmark }: { tone: string; r: number; sev: number; landmark?: boolean }) {
  const tex = windowTextures()
  const h = accentHeight(sev, landmark)
  const w = r * (landmark ? 0.5 : 0.42)
  const plinthH = 0.16
  const capH = landmark ? 0.44 : 0.26
  const bodyH = Math.max(0.4, h - capH)
  const plinth = mix(tone, '#2f343c', 0.5)
  const cap = mix(tone, '#2c2f37', 0.28)
  const topY = plinthH + bodyH
  const hw = w / 2
  return (
    <group>
      {/* цоколь */}
      <mesh castShadow receiveShadow position={[0, plinthH / 2, 0]}>
        <boxGeometry args={[w * 1.18, plinthH, w * 1.18]} />
        <meshStandardMaterial color={plinth} roughness={0.9} />
      </mesh>
      {/* корпус с окнами */}
      <mesh castShadow receiveShadow position={[0, plinthH + bodyH / 2, 0]}>
        <boxGeometry args={[w, bodyH, w]} />
        <meshStandardMaterial color="#ffffff" map={tex.map} emissiveMap={tex.emis} emissive="#ffcf8f" emissiveIntensity={0.9} roughness={0.82} />
      </mesh>
      {/* угловые пилястры */}
      {[[-1, -1], [1, -1], [-1, 1], [1, 1]].map(([sx, sz], i) => (
        <mesh key={i} position={[sx * hw, plinthH + bodyH / 2, sz * hw]}>
          <boxGeometry args={[0.05, bodyH, 0.05]} /><meshStandardMaterial color={cap} roughness={0.7} />
        </mesh>
      ))}
      {/* межэтажный карниз */}
      <mesh position={[0, plinthH + bodyH * 0.5, 0]}>
        <boxGeometry args={[w * 1.05, 0.04, w * 1.05]} /><meshStandardMaterial color={plinth} roughness={0.85} />
      </mesh>
      {/* входная группа спереди (+z): дверь + козырёк на опорах */}
      <mesh position={[0, plinthH + 0.17, hw + 0.001]}>
        <boxGeometry args={[w * 0.3, 0.34, 0.02]} /><meshStandardMaterial color={mix(tone, '#20232a', 0.5)} roughness={0.45} metalness={0.2} />
      </mesh>
      <mesh castShadow position={[0, plinthH + 0.37, hw + 0.13]}>
        <boxGeometry args={[w * 0.46, 0.03, 0.26]} /><meshStandardMaterial color={cap} roughness={0.7} />
      </mesh>
      {[-w * 0.2, w * 0.2].map((x, i) => (
        <mesh key={i} position={[x, plinthH + 0.18, hw + 0.24]}><boxGeometry args={[0.02, 0.36, 0.02]} /><meshStandardMaterial color={M.dark} /></mesh>
      ))}
      {/* крыша-ступень */}
      <mesh castShadow position={[0, topY + capH / 2, 0]}>
        <boxGeometry args={[w * 0.66, capH, w * 0.66]} /><meshStandardMaterial color={cap} roughness={0.68} />
      </mesh>
      {/* парапет по краю крыши */}
      {[[0, 1], [0, -1], [1, 0], [-1, 0]].map(([sx, sz], i) => (
        <mesh key={i} position={[sx * hw, topY + 0.04, sz * hw]}>
          <boxGeometry args={[sx ? 0.045 : w, 0.08, sz ? 0.045 : w]} /><meshStandardMaterial color={plinth} roughness={0.85} />
        </mesh>
      ))}
      {/* кровельный инвентарь: водяной бак, кондиционер, вентиляция */}
      <mesh castShadow position={[w * 0.18, topY + capH + 0.09, w * 0.16]}>
        <cylinderGeometry args={[0.07, 0.07, 0.18, 10]} /><meshStandardMaterial color={M.mid} roughness={0.7} />
      </mesh>
      <mesh castShadow position={[-w * 0.2, topY + 0.07, -w * 0.14]}>
        <boxGeometry args={[0.14, 0.1, 0.1]} /><meshStandardMaterial color="#9aa0a8" roughness={0.6} metalness={0.3} />
      </mesh>
      <mesh position={[-w * 0.04, topY + 0.11, w * 0.2]}>
        <cylinderGeometry args={[0.02, 0.02, 0.22, 6]} /><meshStandardMaterial color={M.dark} />
      </mesh>
      {/* лендмарк iiko — тёплый шпиль с маяком */}
      {landmark && (
        <group position={[0, topY + capH, 0]}>
          <mesh position={[0, 0.36, 0]}><cylinderGeometry args={[0.025, 0.025, 0.72, 6]} /><meshStandardMaterial color={M.warm} roughness={0.4} /></mesh>
          <mesh position={[0, 0.78, 0]}><sphereGeometry args={[0.075, 14, 14]} /><Emissive color={M.warm} i={1.3} /></mesh>
        </group>
      )}
    </group>
  )
}

/* посетитель/курьер: идёт с края острова в здание, у двери исчезает и заходит заново */
function Commuter({ idx, count, outfit, r, box }: { idx: number; count: number; outfit: Outfit; r: number; box?: boolean }) {
  const g = useRef<THREE.Group>(null)
  const cfg = useMemo(() => ({ ang: (idx / count) * Math.PI * 2 + 0.5, speed: 0.09 + (idx % 3) * 0.025, off: idx / count }), [idx, count])
  useFrame(({ clock }) => {
    if (!g.current) return
    const t = (clock.elapsedTime * cfg.speed + cfg.off) % 1
    const edge = r * 0.9
    const ex = Math.cos(cfg.ang) * edge, ez = Math.sin(cfg.ang) * edge
    const dz = r * 0.2
    const x = ex * (1 - t), z = ez + (dz - ez) * t
    g.current.position.set(x, 0.05, z)
    g.current.rotation.y = Math.atan2(-ex, dz - ez)
    const fade = t > 0.82 ? Math.max(0.001, 1 - (t - 0.82) / 0.18) : 1
    g.current.scale.setScalar(fade * 0.85)
    g.current.visible = fade > 0.03
  })
  return (
    <group ref={g}>
      <Human {...outfit} walk scale={0.85} />
      {box && <mesh position={[0, 0.4, 0.14]}><boxGeometry args={[0.16, 0.14, 0.16]} /><meshStandardMaterial color={M.wood} roughness={0.9} /></mesh>}
    </group>
  )
}

/* диктор уведомления: человек в цвете статуса у фронта острова + речевой пузырь */
function Announcer({ tone, text, r }: { tone: string; text: string; r: number }) {
  return (
    <group position={[0, 0.05, r * 0.64]}>
      <Human shirt={tone} walk={false} scale={0.95} />
      <Html position={[0, 0.9, 0]} center distanceFactor={8} style={{ pointerEvents: 'none' }}>
        <div className="iso3d-say" style={{ ['--pin' as string]: tone }}>{text}</div>
      </Html>
    </group>
  )
}

/* стройка нового здания (автоматом у растущих) + тултип «почему» при наведении */
function Construction({ tone, why, r }: { tone: string; why: string; r: number }) {
  const jib = useRef<THREE.Group>(null)
  const [hv, setHv] = useState(false)
  useFrame(({ clock }) => { if (jib.current) jib.current.rotation.y = clock.elapsedTime * 0.3 })
  return (
    <group position={[r * 0.44, 0, -r * 0.28]}
      onPointerOver={(e) => { e.stopPropagation(); setHv(true); document.body.style.cursor = 'help' }}
      onPointerOut={() => { setHv(false); document.body.style.cursor = '' }}>
      <mesh castShadow position={[0, 0.32, 0]}><boxGeometry args={[0.5, 0.64, 0.5]} /><meshStandardMaterial color={BLACK} roughness={0.7} /></mesh>
      {[[-0.28, -0.28], [0.28, -0.28], [-0.28, 0.28], [0.28, 0.28]].map(([x, z], i) => (
        <mesh key={i} position={[x, 0.4, z]}><boxGeometry args={[0.03, 0.82, 0.03]} /><meshStandardMaterial color={tone} /></mesh>
      ))}
      {[0.25, 0.55].map((y, i) => <mesh key={i} position={[0, y, 0.3]}><boxGeometry args={[0.6, 0.02, 0.02]} /><meshStandardMaterial color={tone} /></mesh>)}
      <mesh position={[0.46, 0.75, 0.1]}><boxGeometry args={[0.045, 1.5, 0.045]} /><meshStandardMaterial color="#d8c14a" /></mesh>
      <group ref={jib} position={[0.46, 1.5, 0.1]}>
        <mesh position={[0.28, 0, 0]}><boxGeometry args={[0.75, 0.045, 0.045]} /><meshStandardMaterial color="#d8c14a" /></mesh>
        <mesh position={[0.6, -0.22, 0]}><boxGeometry args={[0.008, 0.44, 0.008]} /><meshStandardMaterial color="#666" /></mesh>
        <mesh position={[0.6, -0.46, 0]}><boxGeometry args={[0.09, 0.07, 0.09]} /><meshStandardMaterial color="#555" /></mesh>
      </group>
      {hv && (
        <Html position={[0, 1.8, 0]} center distanceFactor={8} style={{ pointerEvents: 'none' }}>
          <div className="iso3d-why">{why}</div>
        </Html>
      )}
    </group>
  )
}

/* департамент = остров + здание + подпись, с ховер-подъёмом и покачиванием */
function DepartmentIsle({ dept, pos, r, phase, landmark, onSelect }: { dept: Dept; pos: [number, number, number]; r: number; phase: number; landmark?: boolean; onSelect: () => void }) {
  const g = useRef<THREE.Group>(null)
  const [hover, setHover] = useState(false)
  useFrame(({ clock }) => {
    if (!g.current) return
    const target = Math.sin(clock.elapsedTime * 0.7 + phase) * 0.05 + (hover ? 0.34 : 0)
    g.current.position.y = THREE.MathUtils.lerp(g.current.position.y, pos[1] + target, 0.12)
  })
  return (
    <group
      ref={g}
      position={pos}
      onClick={(e) => { e.stopPropagation(); onSelect() }}
      onPointerOver={(e) => { e.stopPropagation(); setHover(true); document.body.style.cursor = 'pointer' }}
      onPointerOut={() => { setHover(false); document.body.style.cursor = '' }}
    >
      <IsleBase r={r} tone={dept.tone} />
      <IsleDressing r={r} seed={phase} tone={dept.tone} />
      <Building tone={dept.tone} sev={dept.sev} r={r} landmark={landmark} />
      {/* житель острова в своей униформе — стоит у входа, чтобы форма была видна */}
      {[0, 1].map((i) => {
        const a = i * 2.1 + 1.1
        const rad = r * 0.46
        return (
          <group key={`res${i}`} position={[Math.cos(a) * rad, 0.05, Math.sin(a) * rad + r * 0.28]} rotation={[0, Math.PI + a * 0.2, 0]}>
            <Human {...outfitFor(dept)} walk={false} scale={0.82} />
          </group>
        )
      })}
      {/* люди идут в здание: занятые столы / курьер с накладной — одежда по роли */}
      {dept.commuters ? Array.from({ length: dept.commuters }).map((_, i) => (
        <Commuter key={`c${i}`} idx={i} count={dept.commuters!} outfit={outfitFor(dept)} r={r} />
      )) : null}
      {dept.courier && [0, 1].map((i) => <Commuter key={`k${i}`} idx={i} count={2} outfit={outfitFor(dept)} r={r} box />)}
      {/* уведомление говорит человечек в цвете статуса */}
      {dept.pin && <Announcer tone={dept.pin.tone} text={dept.pin.text} r={r} />}
      {/* улучшил показатели → стройка нового здания */}
      {dept.grow && <Construction tone={dept.tone} why={dept.grow} r={r} />}
      {/* подпись: за что отвечает департамент */}
      <Html position={[0, accentHeight(dept.sev, landmark) + 0.55, 0]} center distanceFactor={9} style={{ pointerEvents: 'none' }}>
        <div className="iso3d-name">
          <span className="iso3d-key" style={{ ['--pin' as string]: dept.tone }} />
          <span className="iso3d-txt"><b>{dept.name}</b><i>{dept.role}</i></span>
        </div>
      </Html>
    </group>
  )
}

/* геометрия дороги-ленты вдоль кривой (с боковым сдвигом и подъёмом для бордюров) */
const UP = new THREE.Vector3(0, 1, 0)
function roadGeometry(curve: THREE.QuadraticBezierCurve3, width: number, segs = 20, lateral = 0, rise = 0) {
  const half = width / 2
  const pos: number[] = [], uv: number[] = [], idx: number[] = []
  for (let i = 0; i <= segs; i++) {
    const t = i / segs
    const p = curve.getPoint(t), tan = curve.getTangent(t)
    const side = new THREE.Vector3().crossVectors(tan, UP).normalize()
    const cx = p.x + side.x * lateral, cy = p.y + rise, cz = p.z + side.z * lateral
    pos.push(cx - side.x * half, cy, cz - side.z * half, cx + side.x * half, cy, cz + side.z * half)
    uv.push(0, t * segs, 1, t * segs)
  }
  for (let i = 0; i < segs; i++) {
    const a = i * 2, b = a + 1, c = a + 2, d = a + 3
    idx.push(a, b, c, c, b, d)
  }
  const geo = new THREE.BufferGeometry()
  geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
  geo.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2))
  geo.setIndex(idx)
  geo.computeVertexNormals()
  return geo
}

/* мост между островами: толстый настил + перила со стойками + опоры снизу */
const DECK = '#c9bda3', DECK_UNDER = '#6f6553', RAIL = '#8a7f6b', POST = '#726753'
function Bridge({ from, to, dip, width = 0.62 }: { from: [number, number, number]; to: [number, number, number]; dip: number; width?: number }) {
  const curve = useMemo(() => {
    const a = new THREE.Vector3(...from), b = new THREE.Vector3(...to)
    const mid = a.clone().add(b).multiplyScalar(0.5); mid.y -= dip
    return new THREE.QuadraticBezierCurve3(a, mid, b)
  }, [from, to, dip])
  const deck = useMemo(() => roadGeometry(curve, width, 24), [curve, width])
  const under = useMemo(() => roadGeometry(curve, width * 0.92, 24, 0, -0.09), [curve, width]) // низ настила → толщина
  const railTopL = useMemo(() => roadGeometry(curve, 0.035, 24, width / 2, 0.24), [curve, width])
  const railTopR = useMemo(() => roadGeometry(curve, 0.035, 24, -width / 2, 0.24), [curve, width])
  // стойки перил + опоры моста в выборочных точках кривой
  const samples = useMemo(() => [0.12, 0.3, 0.5, 0.7, 0.88].map((t) => ({ p: curve.getPoint(t), tan: curve.getTangent(t) })), [curve])
  return (
    <group>
      {/* настил (верх + низ для толщины) */}
      <mesh geometry={deck} receiveShadow><meshStandardMaterial color={DECK} roughness={0.9} side={THREE.DoubleSide} /></mesh>
      <mesh geometry={under}><meshStandardMaterial color={DECK_UNDER} roughness={0.95} side={THREE.DoubleSide} /></mesh>
      {/* верхние поручни */}
      <mesh geometry={railTopL}><meshStandardMaterial color={RAIL} roughness={0.7} side={THREE.DoubleSide} /></mesh>
      <mesh geometry={railTopR}><meshStandardMaterial color={RAIL} roughness={0.7} side={THREE.DoubleSide} /></mesh>
      {samples.map(({ p, tan }, i) => {
        const side = new THREE.Vector3().crossVectors(tan, UP).normalize().multiplyScalar(width / 2)
        return (
          <group key={i}>
            {/* стойки перил слева/справа */}
            <mesh castShadow position={[p.x + side.x, p.y + 0.12, p.z + side.z]}><boxGeometry args={[0.028, 0.26, 0.028]} /><meshStandardMaterial color={POST} roughness={0.85} /></mesh>
            <mesh castShadow position={[p.x - side.x, p.y + 0.12, p.z - side.z]}><boxGeometry args={[0.028, 0.26, 0.028]} /><meshStandardMaterial color={POST} roughness={0.85} /></mesh>
            {/* опора вниз (у промежуточных точек) */}
            {i % 2 === 1 && <mesh castShadow position={[p.x, p.y - 0.34, p.z]}><boxGeometry args={[0.06, 0.6, 0.06]} /><meshStandardMaterial color={POST} roughness={0.9} /></mesh>}
          </group>
        )
      })}
    </group>
  )
}

/* текстура лунного диска: светлая база + моря/кратеры */
let _moonTex: THREE.Texture | null = null
function moonTexture() {
  if (_moonTex) return _moonTex
  const s = 256, c = document.createElement('canvas'); c.width = c.height = s
  const g = c.getContext('2d')!
  const grd = g.createRadialGradient(s * 0.42, s * 0.4, s * 0.1, s * 0.5, s * 0.5, s * 0.6)
  grd.addColorStop(0, '#f3f5fa'); grd.addColorStop(1, '#c7cedd')
  g.fillStyle = grd; g.fillRect(0, 0, s, s)
  const rnd = (n: number) => { const x = Math.sin(n * 91.7) * 43758.5; return x - Math.floor(x) }
  // тёмные «моря»
  for (let i = 0; i < 6; i++) {
    g.beginPath(); g.arc(rnd(i + 1) * s, rnd(i + 9) * s, (0.06 + rnd(i + 3) * 0.1) * s, 0, Math.PI * 2)
    g.fillStyle = `rgba(150,160,180,${0.18 + rnd(i + 5) * 0.14})`; g.fill()
  }
  // кратеры
  for (let i = 0; i < 26; i++) {
    const x = rnd(i + 20) * s, y = rnd(i + 40) * s, rr = (0.012 + rnd(i + 60) * 0.03) * s
    g.beginPath(); g.arc(x, y, rr, 0, Math.PI * 2); g.fillStyle = `rgba(120,130,150,${0.15 + rnd(i + 80) * 0.2})`; g.fill()
    g.beginPath(); g.arc(x - rr * 0.3, y - rr * 0.3, rr * 0.7, 0, Math.PI * 2); g.fillStyle = 'rgba(255,255,255,.18)'; g.fill()
  }
  _moonTex = new THREE.CanvasTexture(c); _moonTex.colorSpace = THREE.SRGBColorSpace
  return _moonTex
}

/* небесное тело: сфера-диск + гало (доп. сфера ×1.3–2) — луна ночью, солнце днём */
function CelestialBody({ dark }: { dark: boolean }) {
  const map = useMemo(() => (dark ? moonTexture() : null), [dark])
  const pos: [number, number, number] = [-12, 9.5, -9]
  const core = dark ? '#eef2f8' : '#fff2bf'
  const halo1 = dark ? '#b3c2de' : '#ffdf8a'
  const halo2 = dark ? '#6f80a8' : '#ffcf6a'
  return (
    <group position={pos}>
      <mesh><sphereGeometry args={[1.7, 48, 48]} /><meshBasicMaterial map={map ?? undefined} color={core} toneMapped={false} fog={false} /></mesh>
      <mesh><sphereGeometry args={[2.2, 32, 32]} /><meshBasicMaterial color={halo1} transparent opacity={dark ? 0.26 : 0.34} blending={THREE.AdditiveBlending} depthWrite={false} fog={false} /></mesh>
      <mesh><sphereGeometry args={[dark ? 3.1 : 3.7, 32, 32]} /><meshBasicMaterial color={halo2} transparent opacity={dark ? 0.13 : 0.16} blending={THREE.AdditiveBlending} depthWrite={false} fog={false} /></mesh>
    </group>
  )
}

/* звёзды: два слоя (яркие + тусклые) с лёгким мерцанием */
function StarLayer({ count, size, base, speed }: { count: number; size: number; base: number; speed: number }) {
  const ref = useRef<THREE.Points>(null)
  const mat = useRef<THREE.PointsMaterial>(null)
  const geo = useMemo(() => {
    const pos = new Float32Array(count * 3)
    for (let i = 0; i < count; i++) {
      const rad = 12 + Math.random() * 13
      const th = Math.random() * Math.PI * 2
      pos[i * 3] = Math.cos(th) * rad
      pos[i * 3 + 1] = 4 + Math.random() * 16
      pos[i * 3 + 2] = Math.sin(th) * rad
    }
    const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.BufferAttribute(pos, 3)); return g
  }, [count])
  useFrame(({ clock }) => {
    if (ref.current) ref.current.rotation.y = clock.elapsedTime * 0.006
    if (mat.current) mat.current.opacity = base + Math.sin(clock.elapsedTime * speed) * 0.12
  })
  return (
    <points ref={ref} geometry={geo}>
      <pointsMaterial ref={mat} size={size} color="#dfe6f4" transparent opacity={base} fog={false} sizeAttenuation depthWrite={false} />
    </points>
  )
}
function Stars() {
  return (<><StarLayer count={90} size={0.12} base={0.75} speed={1.3} /><StarLayer count={150} size={0.05} base={0.42} speed={0.8} /></>)
}

/* ─── сцена ─── */
function City({ onSelect, dark }: { onSelect: (d: Dept) => void; dark: boolean }) {
  const R = 4.6
  // органичный разброс: угол, радиус, высота и размер — не ровное кольцо
  const ring = useMemo(() => RING.map((d, i) => {
    const rnd = (n: number) => { const x = Math.sin(i * 12.9898 + n * 78.233) * 43758.5453; return x - Math.floor(x) }
    const base = (i / RING.length) * Math.PI * 2 - Math.PI / 2
    const a = base + (rnd(1) - 0.5) * 0.5
    const rad = R + (rnd(2) - 0.5) * 1.7
    const y = (rnd(3) - 0.5) * 1.6
    const r = 1.3 + rnd(4) * 0.42
    return { d, a, y, r, pos: [Math.cos(a) * rad, y, Math.sin(a) * rad] as [number, number, number] }
  }), [])
  return (
    <>
      <fog attach="fog" args={[dark ? '#0b0d15' : '#cfe0ea', 16, 32]} />
      <CelestialBody dark={dark} />
      {dark && <Stars />}
      <ambientLight intensity={dark ? 0.52 : 0.9} />
      <hemisphereLight args={dark ? ['#ffe6c8', '#1a140e', 0.55] : ['#e2f1ff', '#cdc6b6', 0.95]} />
      <directionalLight position={[6, 12, 5]} intensity={dark ? 1.25 : 1.55} color={dark ? '#ffd9a8' : '#fff3da'} castShadow shadow-mapSize={[2048, 2048]} shadow-bias={-0.0004} shadow-normalBias={0.02}>
        <orthographicCamera attach="shadow-camera" args={[-11, 11, 11, -11, 0.1, 40]} />
      </directionalLight>
      <pointLight position={[0, 3.5, 0]} intensity={dark ? 16 : 6} distance={12} color="#ffcf8f" />

      {/* Процедурное студийное окружение (IBL): премиальные отражения на мраморе и золоте
          без внешних HDRI — три софт-бокса запекаются один раз, фон не трогаем. */}
      <Environment resolution={256} frames={1} background={false}>
        <Lightformer form="rect" intensity={dark ? 2.2 : 3.6} color={dark ? '#ffe7c9' : '#ffffff'} position={[7, 9, 5]} scale={[9, 9, 1]} target={[0, 0, 0]} />
        <Lightformer form="rect" intensity={dark ? 1.1 : 1.8} color={dark ? '#9cc0ff' : '#e6f0ff'} position={[-9, 5, -7]} scale={[7, 7, 1]} target={[0, 0, 0]} />
        <Lightformer form="ring" intensity={dark ? 1.8 : 2.4} color="#ffcf8f" position={[0, 11, 0]} scale={[3.2, 3.2, 1]} />
      </Environment>

      {/* мосты-спицы: от центральной башни iiko к каждому острову (хаб) */}
      {ring.map((it, i) => {
        const u = new THREE.Vector2(it.pos[0], it.pos[2])
        const len = u.length() || 1
        const n = u.clone().normalize()
        const from: [number, number, number] = [n.x * 2.0, -0.12, n.y * 2.0]
        const to: [number, number, number] = [n.x * (len - it.r * 0.82), it.pos[1] - 0.12, n.y * (len - it.r * 0.82)]
        return <Bridge key={`s${i}`} from={from} to={to} dip={0.18} width={0.62} />
      })}

      <DepartmentIsle dept={CENTER} pos={[0, 0, 0]} r={2.15} phase={0} landmark onSelect={() => onSelect(CENTER)} />
      {ring.map((it, i) => (
        <DepartmentIsle key={it.d.id} dept={it.d} pos={it.pos} r={it.r} phase={i * 1.3} onSelect={() => onSelect(it.d)} />
      ))}

      <ContactShadows position={[0, -2.6, 0]} scale={18} blur={2.4} opacity={0.42} far={9} resolution={1024} />
    </>
  )
}

export default function Island() {
  const [sel, setSel] = useState<Dept | null>(null)
  const dark = useThemeDark()
  return (
    <div style={{ gridColumn: '1 / -1', width: '100%' }}>
      <div style={{ marginBottom: 14 }}>
        <div style={{ fontSize: 11, letterSpacing: '.12em', textTransform: 'uppercase', color: 'var(--mute)', fontWeight: 600 }}>Ресторанный город iiko · демо</div>
        <p style={{ margin: '6px 0 0', fontSize: 13, color: 'var(--lo)', maxWidth: '62ch' }}>Каждый остров — департамент (подпись говорит, за что он отвечает), в центре — башня iiko. Острова связаны мостами, по ним бегают люди. Крути мышкой, тыкни по острову — снизу выедет отчёт.</p>
      </div>

      {/* во всю ширину экрана, без рамки — сцена слитна с сайтом; небо зависит от темы */}
      <div className="iso-sky" style={{ position: 'relative', width: '100vw', marginLeft: '50%', transform: 'translateX(-50%)', height: 'min(86vh, 800px)', minHeight: 480, overflow: 'hidden' }}>
        <Canvas shadows dpr={[1, 2]} gl={{ alpha: true, antialias: true, powerPreference: 'high-performance', toneMapping: THREE.ACESFilmicToneMapping, toneMappingExposure: 1.06 }} camera={{ position: [0.5, 6.4, 10.5], fov: 42 }}>
          <City onSelect={setSel} dark={dark} />
          <OrbitControls
            makeDefault
            enablePan={false}
            enableDamping
            dampingFactor={0.08}
            minDistance={6}
            maxDistance={14}
            minPolarAngle={0.5}
            maxPolarAngle={1.36}
            autoRotate
            autoRotateSpeed={0.4}
            target={[0, 0.5, 0]}
          />
        </Canvas>
      </div>

      {/* Отчёт-шторка снизу */}
      <AnimatePresence>
        {sel && (
          <>
            <motion.div className="iso-scrim" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setSel(null)} />
            <motion.div className="iso-sheet" initial={{ y: '100%' }} animate={{ y: 0 }} exit={{ y: '100%' }} transition={{ type: 'spring', stiffness: 260, damping: 30 }}>
              <div className="iso-sheet-head">
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <span style={{ width: 40, height: 40, borderRadius: '30%', flex: 'none', display: 'grid', placeItems: 'center', color: sel.tone, background: `color-mix(in srgb, ${sel.tone} 16%, transparent)`, border: `1px solid color-mix(in srgb, ${sel.tone} 38%, transparent)` }}>
                    <Icon k={sel.id} size={21} />
                  </span>
                  <div className="display" style={{ fontSize: 24 }}>{sel.name}</div>
                </div>
                <button className="iso-close" onClick={() => setSel(null)} aria-label="Закрыть">✕</button>
              </div>
              <div className="iso-sheet-body">
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(12,1fr)', gap: 16, alignItems: 'stretch' }} className="lg-bento">
                  {sel.render()}
                </div>
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </div>
  )
}
