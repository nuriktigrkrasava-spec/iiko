/* Ядро продукта-очереди: кейс = одна проблема · одна сумма ₸ · гипотеза · кнопки. */

export type Building = 'kitchen' | 'storage' | 'hall' | 'cash' | 'guests' | 'street'

export type GrowthNode = {
  node_id: string
  parent_id: string | null
  building: Building
  is_leaf: boolean
  label: string
}

export type CaseStatus = 'new' | 'accepted' | 'rejected' | 'auditing' | 'verifying' | 'closed'
export type Confidence = 'high' | 'medium' | 'low'

export type Evidence = { kind: 'receipts' | 'invoices' | 'shifts' | 'reviews'; label: string }

export type Case = {
  id: string
  node_id: string
  branch_id: string | null
  title: string          // одно предложение, активный залог, без % без ! без эмодзи
  body: string           // 1–2 предложения контекста и гипотезы
  amount_kzt: number     // оценка потерь/упущенной выгоды
  estimated: boolean     // true → оценка (показываем диапазоном и меткой)
  amount_low?: number
  amount_high?: number
  period_from: string
  period_to: string
  confidence: Confidence
  status: CaseStatus
  evidence: Evidence[]   // до первички: «показать чеки»
}
