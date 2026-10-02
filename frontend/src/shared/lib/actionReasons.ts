/**
 * Словарь причин недоступности действия (#193).
 *
 * Одна причина — один текст на всех экранах: доска участка (строка и футер
 * массового ввода), дневные планы и передачи. Раньше формулировки жили рядом с
 * кнопками (`title` тултипа, текст баннера, текст тоста) и разошлись: одно и то
 * же «сырьё не поступило» называлось тремя способами, а на сенсорном экране и
 * при первом открытии страницы половина причин не была видна вовсе — только под
 * наведением.
 *
 * Отличие от подсказки: причина обязана читаться текстом на экране рядом с
 * кнопкой, поэтому текст короткий и самодостаточный. Словарь отдаёт код
 * причины, а не строку: экран решает, где показать, формулировка остаётся здесь.
 *
 * Временные состояния (`pending`, «Отправка...») причиной недоступности не
 * являются: о них говорит сама надпись на кнопке, второй текст рядом был бы
 * шумом.
 */

/** Причина, по которой действие недоступно оператору. */
export type ActionReasonCode =
  // Завершение задания — строка доски и футер массового ввода.
  | "awaiting_raw"
  | "raw_not_received"
  | "cancelled"
  | "stage_skipped"
  | "already_completed"
  | "fact_entered"
  | "bulk_nothing_to_complete"
  | "bulk_no_quantity"
  | "no_shortage_strategy"
  | "fact_below_recorded"
  // Передачи.
  | "zero_quantity"
  | "row_in_flight"
  | "final_release_not_in_bulk"
  | "no_tasks_selected"
  | "no_executor";

/**
 * Текст причины по коду. Одинаковая причина читается одинаково на всех
 * экранах — отсюда и словарь, а не константы рядом с кнопками.
 */
export const ACTION_REASON_TEXT: Record<ActionReasonCode, string> = {
  awaiting_raw: "Ждёт сырьё с предыдущего участка",
  raw_not_received: "Сырьё ещё не поступило",
  already_completed: "Задание уже завершено",
  fact_entered: "Факт уже внесён",
  bulk_nothing_to_complete: "Нет заданий для завершения",
  bulk_no_quantity: "Введите количество",
  no_shortage_strategy: "Выберите, что делать с излишком",
  fact_below_recorded: "Факт можно только увеличить: введено меньше записанного. Уменьшение — через отмену действия",
  cancelled: "Задание отменено",
  stage_skipped: "Этап пропущен",
  zero_quantity: "Укажите количество",
  row_in_flight: "Строка уже отправляется",
  final_release_not_in_bulk: "Финальный выпуск не в группу",
  no_tasks_selected: "Выберите задания",
  no_executor: "Выберите исполнителя",
};

/**
 * Текст причины. Перегрузка без `null` — для мест, где код уже известен
 * (подпись кнопки, тост, баннер): там пустого текста быть не может.
 */
export function actionReasonText(code: ActionReasonCode): string;
export function actionReasonText(code: ActionReasonCode | null | undefined): string | null;
export function actionReasonText(code: ActionReasonCode | null | undefined): string | null {
  return code ? ACTION_REASON_TEXT[code] : null;
}
