import type { Building, GrowthNode } from './types'

/* Справочник узлов роста. Пользователь его не видит. Нужен для: подсветки
   здания на Острове, дедупликации кейсов, суммирования денег только по листьям. */

const N = (node_id: string, parent_id: string | null, building: Building, is_leaf: boolean, label: string): GrowthNode =>
  ({ node_id, parent_id, building, is_leaf, label })

export const GROWTH_NODES: GrowthNode[] = [
  // корни зданий
  N('kitchen', null, 'kitchen', false, 'Кухня'),
  N('storage', null, 'storage', false, 'Склад'),
  N('hall', null, 'hall', false, 'Зал'),
  N('cash', null, 'cash', false, 'Касса'),
  N('guests', null, 'guests', false, 'Гости'),
  N('street', null, 'street', false, 'Вывеска'),

  // листья (правила из спеки)
  N('foodcost.delta', 'kitchen', 'kitchen', true, 'Дельта списаний'),
  N('foodcost.delta.portion', 'foodcost.delta', 'kitchen', true, 'Дельта по сменам (рука)'),
  N('foodcost.delta.storage', 'storage', 'storage', true, 'Дельта по складу'),
  N('cash.fraud.discount', 'cash', 'cash', true, 'Скидки сотрудников'),
  N('cash.fraud.refund', 'cash', 'cash', true, 'Возвраты после закрытия'),
  N('cash.reconcile', 'cash', 'cash', true, 'Расхождение кассы'),
  N('revenue.menu.dogs', 'hall', 'hall', true, 'Собаки в меню'),
  N('revenue.menu.puzzles', 'hall', 'hall', true, 'Загадки в меню'),
  N('revenue.guests.return', 'guests', 'guests', true, 'Падение возвратов'),
  N('street.reviews', 'street', 'street', true, 'Отзыв без ответа'),
]

const BY_ID = new Map(GROWTH_NODES.map((n) => [n.node_id, n]))

export function nodeOf(id: string): GrowthNode | undefined {
  return BY_ID.get(id)
}

export function buildingOf(id: string): Building {
  return BY_ID.get(id)?.building ?? 'kitchen'
}

export function leafIds(): string[] {
  return GROWTH_NODES.filter((n) => n.is_leaf).map((n) => n.node_id)
}

/* здание в человекочитаемом виде */
export const BUILDING_LABEL: Record<Building, string> = {
  kitchen: 'Кухня', storage: 'Склад', hall: 'Зал', cash: 'Касса', guests: 'Гости', street: 'Вывеска',
}
