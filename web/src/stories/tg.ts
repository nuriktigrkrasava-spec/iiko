/* Тонкая обёртка над Telegram.WebApp. Всё через feature-detect и
   isVersionAtLeast — метод, которого нет в клиенте пользователя, роняет
   webview. В обычном браузере (прототип) всё это no-op. */

/* eslint-disable @typescript-eslint/no-explicit-any */
function wa(): any | null {
  return (typeof window !== 'undefined' && (window as any).Telegram?.WebApp) || null
}

function atLeast(v: string): boolean {
  const w = wa()
  try { return !!w?.isVersionAtLeast?.(v) } catch { return false }
}

export function inTelegram(): boolean {
  return !!wa()?.initData
}

/** Старт: ready → expand → снять вертикальные свайпы, чтобы свайп по сторис
    не закрывал приложение. Вызывается один раз при монтировании. */
export function tgInit(): void {
  const w = wa()
  if (!w) return
  try {
    w.ready?.()
    w.expand?.()
    if (atLeast('7.7')) w.disableVerticalSwipes?.()
  } catch { /* старый клиент — молча */ }
}

export type Haptic = 'selection' | 'light' | 'medium' | 'success' | 'error' | 'warning'

export function haptic(kind: Haptic = 'selection'): void {
  const h = wa()?.HapticFeedback
  if (!h) return
  try {
    if (kind === 'selection') h.selectionChanged?.()
    else if (kind === 'success' || kind === 'error' || kind === 'warning') h.notificationOccurred?.(kind)
    else h.impactOccurred?.(kind)
  } catch { /* no-op */ }
}

/** Родная нижняя кнопка телеграма. Своя нижняя навигация не рисуется —
    основное действие всегда здесь. В браузере no-op (рисуется fallback). */
export function mainButton(text: string, onClick: () => void): () => void {
  const b = inTelegram() ? wa()?.MainButton : null
  if (!b) return () => {}
  try {
    b.setParams?.({ text, is_visible: true })
    b.onClick?.(onClick)
  } catch { /* старый клиент */ }
  return () => { try { b.offClick?.(onClick) } catch { /* no-op */ } }
}

export function hideMainButton(): void {
  try { wa()?.MainButton?.hide?.() } catch { /* no-op */ }
}

export function hasMainButton(): boolean {
  // сам объект есть и в браузере (скрипт загружен), но кнопка рисуется
  // только внутри телеграма — поэтому проверяем initData
  return inTelegram() && !!wa()?.MainButton
}

/** Родная стрелка возврата телеграма. Возвращает cleanup. */
export function backButton(onClick: () => void): () => void {
  const b = inTelegram() ? wa()?.BackButton : null
  if (!b) return () => {}
  try {
    b.onClick?.(onClick)
    b.show?.()
  } catch { /* старый клиент */ }
  return () => { try { b.offClick?.(onClick); b.hide?.() } catch { /* no-op */ } }
}

/** Тема пользователя: обычные экраны красятся из неё и меняются вместе с ней. */
export function colorScheme(): 'light' | 'dark' {
  const s = wa()?.colorScheme
  if (s === 'dark' || s === 'light') return s
  return typeof window !== 'undefined' && window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function onThemeChange(fn: () => void): () => void {
  const w = wa()
  if (!w?.onEvent) return () => {}
  try { w.onEvent('themeChanged', fn) } catch { return () => {} }
  return () => { try { w.offEvent?.('themeChanged', fn) } catch { /* no-op */ } }
}

export function canShareStory(): boolean {
  return !!wa()?.shareToStory && atLeast('8.0')
}

/** Публикация кадра в сторис владельца. Требует картинку кадра —
    в прототипе media ещё нет, поэтому guarded. */
export function shareStory(mediaUrl: string, text?: string): void {
  const w = wa()
  if (!w?.shareToStory) return
  try { w.shareToStory(mediaUrl, text ? { text } : undefined) } catch { /* no-op */ }
}
