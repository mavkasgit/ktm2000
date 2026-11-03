/**
 * Чистая логика окна «Взять в работу» с автоподбором источника (#282).
 *
 * Правило, ради которого модуль выделен: порядок строк, количества и дефицит
 * считает сервер (`issue-preview`), а UI обязан честно показать разницу между
 * «не доходила очередь» (прочерк) и «склад вычерпан целиком» (ноль). Оба
 * состояния в разметке выглядят одной цифрой, если их не разделять явно, —
 * поэтому разбор живёт здесь и покрыт тестами, а не в JSX окна.
 */
import type {
  IssueAutoSelection,
  IssueManualSelection,
  IssuePreviewCandidate,
  IssuePreviewHint,
  IssuePreviewOut,
  IssueSummary,
} from "@/shared/api/productionPlans";
import type { ShortageStrategy } from "@/shared/api/shopfloor";
import { QTY_EMPTY, fmtServerQty, parseServerQty } from "@/shared/lib/quantityFormat";

/**
 * Снятая галочка → `excluded_balance_ids` этого вызова. Снятие живёт ровно
 * один вызов: ничего не сохраняется и не переносится на следующую выдачу,
 * поэтому состояние — массив id, а не «вычеркнутый склад».
 */
export function toggleBalanceExcluded(
  excluded: readonly number[],
  balanceId: number,
  checked: boolean,
): number[] {
  const without = excluded.filter((id) => id !== balanceId);
  return checked ? without : [...without, balanceId];
}

/** Галочка строки: склад включён, если оператор его не снял. */
export function isCandidateChecked(
  candidate: IssuePreviewCandidate,
  excluded: readonly number[],
): boolean {
  return !excluded.includes(candidate.balance_id);
}

export type RemainingAfterCell = {
  /** «—» — значения нет; «0» — ноль. Никогда не одна и та же печать. */
  text: string;
  /** Склад вычерпан целиком (`"0"`), а не «очередь не дошла» (`null`). */
  drawnOut: boolean;
  /** Очередь не дошла до склада или галочка снята. */
  notReached: boolean;
};

/**
 * Ячейка «останется после»: `null` → прочерк, `"0"` → ноль с пометкой
 * «вычерпан». Различие обязательное (#282): пустеющий склад и склад, до
 * которого очередь не дошла, — разные решения оператора.
 */
export function remainingAfterCell(value: string | null): RemainingAfterCell {
  if (value === null) return { text: QTY_EMPTY, drawnOut: false, notReached: true };
  const quantity = parseServerQty(value);
  if (quantity === null) return { text: QTY_EMPTY, drawnOut: false, notReached: true };
  return {
    text: fmtServerQty(value),
    drawnOut: quantity === 0,
    notReached: false,
  };
}

/**
 * Подсказки показываем только по включённым складам. Сервер их уже фильтрует
 * (`_build_hints`), но снятая галочка в этом окне — намерение оператора,
 * которое прилетит в следующем ответе: печатать подсказку по складу, который
 * уже снят, значит показать материал, который брать не будут.
 */
export function visibleIssueHints(
  hints: readonly IssuePreviewHint[],
  candidates: readonly IssuePreviewCandidate[],
): IssuePreviewHint[] {
  const checkedLocations = new Set(
    candidates.filter((c) => c.included).map((c) => c.location_id),
  );
  return hints.filter((hint) => checkedLocations.has(hint.location_id));
}

/** «Собрано X из Y шт., дефицит Z шт.» — одна строка на предпросмотр и итог. */
export function issueCollectLine(values: {
  required: string | number | null | undefined;
  collected: string | number | null | undefined;
  deficit: string | number | null | undefined;
}): string {
  return `Собрано ${fmtServerQty(values.collected)} из ${fmtServerQty(values.required)} шт., дефицит ${fmtServerQty(values.deficit)} шт.`;
}

export function previewCollectLine(preview: IssuePreviewOut): string {
  return issueCollectLine(preview);
}

export function summaryCollectLine(summary: IssueSummary): string {
  return issueCollectLine(summary);
}

/**
 * Причина, по которой «Взять в работу» недоступна, или `null`, когда доступна.
 * Формулировки — серверные (текст отказа из `issue-preview` или слова
 * `execute_issue` про «выдавать нечего»), своих не выдумываем: оператор
 * должен читать то же, что увидит в журнале, если всё-таки нажмёт.
 */
export function issueConfirmBlockReason(args: {
  preview: IssuePreviewOut | null;
  isLoading: boolean;
  /** Уже разобранный текст ошибки сервера (`getErrorMessage`). */
  errorText: string | null;
}): string | null {
  if (args.isLoading && !args.preview) return "Считаем подбор склада…";
  if (args.errorText) return args.errorText;
  if (!args.preview) return "Подбор склада не посчитан";
  if (args.preview.candidates.length === 0) {
    return "Источник выдачи: ни на одном складе нет этого артикула в нужном размере — выдавать нечего";
  }
  const collected = parseServerQty(args.preview.collected);
  if (collected === null || collected <= 0) {
    return "Собрано 0 шт. — выдавать нечего";
  }
  return null;
}

/** Выбор одной позиции: снятые галочки + стратегия недостачи. */
export function buildIssueSelection(args: {
  excludedBalanceIds: readonly number[];
  strategy: ShortageStrategy;
  idempotencyKey: string;
}): IssueManualSelection {
  return {
    excluded_balance_ids: [...args.excludedBalanceIds],
    shortage_strategy: args.strategy,
    auto: false,
    idempotency_key: args.idempotencyKey,
  };
}

/**
 * Групповой запуск: подбор без галочек (`auto`), итог — один общий
 * (`issue_no === null`). Галочки принадлежат конкретной позиции, поэтому их в
 * payload нет вовсе.
 */
export function buildAutoIssueSelection(idempotencyKey: string): IssueAutoSelection {
  return { auto: true, idempotency_key: idempotencyKey };
}

/**
 * Стратегия недостачи — три значения серверной схемы (`ShortageStrategy`).
 * Порядок — от дефолта сервера (`partial`), подписи объясняют, что произойдёт
 * с нехваткой, а не пересказывают имя поля.
 */
export const ISSUE_SHORTAGE_OPTIONS: { value: ShortageStrategy; label: string; hint: string }[] = [
  {
    value: "partial",
    label: "Выдать, что есть",
    hint: "Собирается доступное, задача остаётся частично обеспеченной.",
  },
  {
    value: "fail",
    label: "Отказ при недостаче",
    hint: "Выдача не оформляется: сервер вернёт, чего не хватает.",
  },
  {
    value: "negative_remainder",
    label: "Добрать в минус склада",
    hint: "Недостача дописывается последней передачей со списанием в минус (#133).",
  },
];

export const ISSUE_DEFAULT_STRATEGY: ShortageStrategy = "partial";
