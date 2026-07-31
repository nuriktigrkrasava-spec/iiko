/* Команда для назначения задач. В бэкенд-фазе список ведёт владелец вручную,
   без ссылок-приглашений. Сообщение назначенному шлёт бот лично, не в общий чат. */

export type TeamMember = { id: string; name: string; role: string }

export const TEAM: TeamMember[] = [
  { id: 'chef-marat', name: 'Марат', role: 'шеф-повар' },
  { id: 'mgr-aigul', name: 'Айгуль', role: 'управляющая' },
  { id: 'acc-saltanat', name: 'Салтанат', role: 'бухгалтер' },
]
