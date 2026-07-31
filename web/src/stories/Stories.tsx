import { useCallback, useEffect, useMemo, useState } from 'react'
import './stories.css'
import { useCases } from '../cases/generate'
import { buildFrames, type Frame } from './frames'
import { kztNum } from '../cases/money'
import { tgInit, haptic, canShareStory, shareStory, mainButton, hasMainButton } from './tg'

export default function Stories({ onExit }: { onExit?: () => void }) {
  const { cases, loading } = useCases()
  const frames = useMemo(() => buildFrames(cases), [cases])
  const [i, setI] = useState(0)

  useEffect(() => { tgInit() }, [])
  // клампим индекс, когда кадры пришли
  useEffect(() => { if (i > frames.length - 1) setI(Math.max(0, frames.length - 1)) }, [frames.length, i])

  const go = useCallback((dir: 1 | -1) => {
    setI((prev) => {
      const next = prev + dir
      if (next < 0 || next > frames.length - 1) return prev
      haptic('selection')
      return next
    })
  }, [frames.length])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'ArrowRight' || e.key === ' ') { e.preventDefault(); go(1) }
      if (e.key === 'ArrowLeft') { e.preventDefault(); go(-1) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [go])

  const last = i === frames.length - 1

  // основное действие — родная кнопка телеграма, не своя
  useEffect(() => {
    if (frames.length === 0) return
    if (last) return mainButton('Открыть дела', () => { if (onExit) onExit(); else window.location.href = '/' })
    return mainButton('Дальше', () => go(1))
  }, [last, go, frames.length, onExit])

  if (loading && frames.length === 0) return <StorySkeleton />
  if (frames.length === 0) {
    return (
      <div className="st-root night" data-tone="neutral">
        <div className="st-frame"><div className="st-bottom"><p className="st-sentence">Отчёт соберётся, как только появятся кейсы</p></div></div>
      </div>
    )
  }

  const frame = frames[i]
  const tone = frame.kind === 'tasks' ? 'neutral' : frame.tone

  return (
    <div className="st-root night" data-tone={tone}>
      {/* сегментированный индикатор */}
      <div className="st-segs" role="progressbar" aria-valuenow={i + 1} aria-valuemin={1} aria-valuemax={frames.length} aria-label="Прогресс отчёта">
        {frames.map((_, k) => (
          <span key={k} className={`st-seg ${k < i ? 'done' : k === i ? 'now' : ''}`} />
        ))}
      </div>

      {/* кадр — key меняется → CSS-анимация появления проигрывается заново */}
      <div className="st-frame" key={i}>
        <FrameView frame={frame} />
      </div>

      {/* зоны тапа: слева назад, справа вперёд */}
      <button className="st-tap left" onClick={() => go(-1)} aria-label="Предыдущий кадр" disabled={i === 0} />
      <button className="st-tap right" onClick={() => go(1)} aria-label="Следующий кадр" disabled={last} />

      {/* в телеграме основное действие живёт в родной нижней кнопке;
          в браузере — тихий fallback */}
      {!hasMainButton() && (
        <div className="st-actions">
          {canShareStory() && !last && (
            <button className="st-link" onClick={() => shareStory('', frame.kind === 'leak' ? frame.sentence : undefined)}>В сторис</button>
          )}
          {last
            ? (onExit
                ? <button className="st-cta" onClick={onExit}>Открыть дела</button>
                : <a className="st-cta" href="/">Открыть дела</a>)
            : <button className="st-cta" onClick={() => go(1)}>Дальше</button>}
        </div>
      )}
    </div>
  )
}

function FrameView({ frame }: { frame: Frame }) {
  if (frame.kind === 'tasks') {
    return (
      <>
        <div className="st-overline">{frame.overline}</div>
        <div className="st-bottom">
          <ol className="st-tasks">
            {frame.items.map((it, k) => (
              <li key={k} className="st-task">
                <span className="st-task-n tnum">{String(k + 1).padStart(2, '0')}</span>
                <span className="st-task-title">{it.title}</span>
                <span className="st-task-amt tnum">{kztNum(it.amount)}<i>₸</i></span>
              </li>
            ))}
          </ol>
          <p className="st-sentence">{frame.sentence}</p>
        </div>
      </>
    )
  }

  const showNumber = 'amount' in frame && frame.amount != null
  const count = frame.kind === 'worked' ? frame.count : undefined

  return (
    <>
      <div className="st-overline">{frame.overline}</div>
      <div className="st-bottom">
        <div className="st-figure">
          {showNumber
            ? <span className={`st-number tone-${frame.tone}`}>{kztNum(frame.amount as number)}<i className="st-unit">₸</i></span>
            : <span className="st-number compact tone-neutral">{count ?? 0}<i className="st-unit">{count === 1 ? 'кейс' : 'в работе'}</i></span>}
        </div>
        <p className="st-sentence">{frame.sentence}</p>
        {frame.sub && <p className="st-sub">{frame.sub}</p>}
      </div>
    </>
  )
}

function StorySkeleton() {
  return (
    <div className="st-root night" data-tone="neutral">
      <div className="st-segs">{[0, 1, 2, 3, 4, 5, 6].map((k) => <span key={k} className="st-seg" />)}</div>
      <div className="st-frame">
        <div className="st-overline"><span className="st-sk st-sk-overline" /></div>
        <div className="st-bottom">
          <div className="st-sk st-sk-number" />
          <div className="st-sk st-sk-line" />
          <div className="st-sk st-sk-line short" />
        </div>
      </div>
    </div>
  )
}
