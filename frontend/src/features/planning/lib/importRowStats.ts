import { buildImportApplyStats, type ImportApplyStats } from "@/shared/api/imports";

import { isDuplicateRow, type DuplicateRowSignal } from "./duplicateRows";

/**
 * Строка импорта для клиентских агрегатов. Форма намеренно свободная: источник
 * бывает непровалидированным (`ImportLightItem` из API или строка превью
 * визарда), поэтому поля читаются с проверкой типа, а не кастом.
 */
export type ImportStatRow = {
  status?: unknown;
  errors?: unknown;
  warnings?: unknown;
  codes?: unknown;
  change_action?: unknown;
};

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string");
}

/**
 * Клиентское зеркало серверного `_item_aggregates` (`plan_import_service.py`):
 * те же счётчики по статусам, дубли — по общему предикату `isDuplicateRow`,
 * раскладка ошибок — только по `errors` (в `codes` они склеены с warnings).
 *
 * Дубли считаются по любому каналу, который видит чип «Дубли» в таблице
 * (`codes`/`errors`/`warnings`/`change_action`), а сервер — по `errors` и
 * `change_action` (`plan_import_item_is_duplicate`): сейчас это один и тот же
 * результат, потому что `duplicate_sku_due_date` парсер пишет только в
 * `errors`. Расхождение возможно лишь если код когда-нибудь переедет в
 * warnings — тогда чип и список сойдутся на этом предикате.
 *
 * Нужно там, где серверного `summary` нет: диалог применения из списка файлов
 * считается по лёгким строкам батча (спека §4.3, фолбэк).
 */
export function buildImportRowStats(rows: readonly ImportStatRow[]): ImportApplyStats {
  const errors: Record<string, number> = {};
  let valid = 0;
  let warning = 0;
  let invalid = 0;
  let duplicates = 0;

  for (const row of rows) {
    if (row.status === "invalid") invalid += 1;
    else if (row.status === "warning") warning += 1;
    else if (row.status === "pending") valid += 1;

    const duplicateSignal: DuplicateRowSignal = {
      change_action: typeof row.change_action === "string" ? row.change_action : null,
      codes: stringList(row.codes),
      errors: stringList(row.errors),
      warnings: stringList(row.warnings),
    };
    if (isDuplicateRow(duplicateSignal)) duplicates += 1;

    for (const code of stringList(row.errors)) {
      errors[code] = (errors[code] ?? 0) + 1;
    }
  }

  return buildImportApplyStats({
    total: rows.length,
    valid,
    warning,
    invalid,
    duplicates,
    errors,
  });
}
