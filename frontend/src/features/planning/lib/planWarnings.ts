/**
 * Предупреждения позиции, которые показывает страница плана (#328).
 *
 * Источник — `validation_warnings` самой позиции: он пишется при применении
 * change-set (`item.warnings`) и переживает любые дальнейшие изменения
 * элементов сета. `warnings` — прежнее поле из последнего `PlanChangeItem`;
 * фолбэк на него нужен только позициям, созданным до миграции 079: бэкфилла
 * по тикету нет, и у старых строк колонка пуста, хотя предупреждение было.
 *
 * Статус позиции от этих списков не зависит: `validation_status` считается
 * только по ошибкам — предупреждение остаётся предупреждением.
 */
type WarningsSource = {
  validation_warnings?: string[] | null;
  warnings?: string[] | null;
};

export function positionWarnings(pos: WarningsSource): string[] {
  if (pos.validation_warnings && pos.validation_warnings.length > 0) {
    return pos.validation_warnings;
  }
  return pos.warnings ?? [];
}
