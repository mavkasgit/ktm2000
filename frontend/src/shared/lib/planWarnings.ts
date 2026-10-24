/**
 * Предупреждения позиции плана (#328, #334).
 *
 * Источник — `validation_warnings` самой позиции: он пишется при применении
 * change-set (`item.warnings`) и переживает любые дальнейшие изменения
 * элементов сета. Позиции, созданные до миграции 079, закрыл бэкфилл 082 —
 * legacy-поле `warnings` из последнего `PlanChangeItem` API больше не отдаёт,
 * поэтому фолбэка нет, и читается ровно одно поле.
 *
 * Живёт в shared: одно правило читают и features/planning, и
 * entities/planning (карточка строки), а entities не может импортировать
 * features.
 *
 * Статус позиции от этих списков не зависит: `validation_status` считается
 * только по ошибкам — предупреждение остаётся предупреждением.
 */
type WarningsSource = {
  validation_warnings?: string[] | null;
};

export function positionWarnings(pos: WarningsSource): string[] {
  return pos.validation_warnings ?? [];
}
