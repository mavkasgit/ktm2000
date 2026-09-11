/** Сигнал строки-дубля в превью импорта (тикет #165): общий предикат для таблицы файла и визарда. */
export type DuplicateRowSignal = {
  change_action?: string | null
  codes?: string[] | null
  errors?: string[] | null
  warnings?: string[] | null
}

const DUPLICATE_CODE = "duplicate_sku_due_date"

/** Строка-дубль: либо действие mark_possible_duplicate, либо код duplicate_sku_due_date. */
export function isDuplicateRow(row: DuplicateRowSignal): boolean {
  if (row.change_action === "mark_possible_duplicate") return true
  return [row.codes, row.errors, row.warnings].some(
    (list) => Array.isArray(list) && list.includes(DUPLICATE_CODE),
  )
}
