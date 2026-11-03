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

/**
 * Строка выдачи — группа эквивалентов на осях склада:
 * `(group_key, location_id, dimensions, completed_operations)` (#396).
 *
 * Один `group_key` — ещё не строка: остатки группы на разных складах,
 * размерах или операциях — разные строки выдачи. Внутри строки кандидаты
 * идут по серверному `order`, строки — по минимальному `order` своих
 * кандидатов. Клиент ничего не переставляет и не пересчитывает: только
 * складывает уже посчитанные сервером `available`/`take`.
 */
export type IssueCandidateGroup = {
  /** Стабильный ключ строки для раскрытия. */
  key: string;
  groupKey: number;
  locationId: number;
  locationName: string;
  dimensions: Record<string, unknown> | null;
  completedOperations: string[] | null;
  opsCount: number;
  /** Кандидаты строки в серверном порядке `order`. */
  candidates: IssuePreviewCandidate[];
  /** Минимальный `order` строки — место строки в списке. */
  order: number;
  /** Сумма серверных `available` (уже в формате сервера). */
  available: string;
  /** Сумма серверных `take` (уже в формате сервера). */
  take: string;
  /** `null` — все строки без значения; иначе сумма не-null значений. */
  remainingAfter: string | null;
  balanceIds: number[];
  /** «A» или «A, B (эквиваленты)». */
  skuLabel: string;
  /** В строке есть артикул задания (эквивалент — не ошибка). */
  hasTaskProduct: boolean;
};

function stableDimensionsKey(dimensions: Record<string, unknown> | null): string {
  if (dimensions === null) return "null";
  return JSON.stringify(
    Object.entries(dimensions).sort(([left], [right]) => left.localeCompare(right)),
  );
}

function candidateGroupKey(candidate: IssuePreviewCandidate): string {
  const operations =
    candidate.completed_operations === null
      ? "null"
      : JSON.stringify([...candidate.completed_operations].sort());
  return [
    candidate.group_key,
    candidate.location_id,
    stableDimensionsKey(candidate.dimensions),
    operations,
  ].join("|");
}

function sumServerQty(values: readonly (string | null)[]): string {
  const total = values.reduce((sum, value) => sum + (parseServerQty(value) ?? 0), 0);
  return fmtServerQty(total);
}

/**
 * «Останется после» строки группы: `null`, только если `null` у всех строк.
 * Складываем лишь не-null значения — прочерк не превращается в ноль.
 */
export function groupRemainingAfter(
  candidates: readonly IssuePreviewCandidate[],
): string | null {
  const values = candidates
    .map((candidate) => parseServerQty(candidate.remaining_after))
    .filter((value): value is number => value !== null);
  if (values.length === 0) return null;
  return fmtServerQty(values.reduce((sum, value) => sum + value, 0));
}

/** Подпись артикулов строки: уникальные SKU по возрастанию `product_id`. */
function groupSkuLabel(candidates: readonly IssuePreviewCandidate[]): string {
  const seen = new Set<string>();
  const skus: string[] = [];
  for (const candidate of [...candidates].sort((left, right) => left.product_id - right.product_id)) {
    if (candidate.sku && !seen.has(candidate.sku)) {
      seen.add(candidate.sku);
      skus.push(candidate.sku);
    }
  }
  if (skus.length === 0) return "—";
  return skus.length === 1 ? skus[0] : `${skus.join(", ")} (эквиваленты)`;
}

/**
 * Свернуть плоский список кандидатов сервера в строки групп. Порядок
 * кандидатов внутри строки и порядок строк — только серверный `order`.
 */
export function buildIssueCandidateGroups(
  candidates: readonly IssuePreviewCandidate[],
  taskProductId?: number | null,
): IssueCandidateGroup[] {
  const groups = new Map<string, IssueCandidateGroup>();
  for (const candidate of candidates) {
    const key = candidateGroupKey(candidate);
    const existing = groups.get(key);
    if (existing) {
      existing.candidates.push(candidate);
      existing.order = Math.min(existing.order, candidate.order);
      continue;
    }
    groups.set(key, {
      key,
      groupKey: candidate.group_key,
      locationId: candidate.location_id,
      locationName: candidate.location_name,
      dimensions: candidate.dimensions,
      completedOperations: candidate.completed_operations,
      opsCount: candidate.ops_count,
      candidates: [candidate],
      order: candidate.order,
      available: "",
      take: "",
      remainingAfter: null,
      balanceIds: [],
      skuLabel: "",
      hasTaskProduct: false,
    });
  }

  return [...groups.values()]
    .map((group) => {
      const sorted = [...group.candidates].sort((left, right) => left.order - right.order);
      return {
        ...group,
        candidates: sorted,
        available: sumServerQty(sorted.map((candidate) => candidate.available)),
        take: sumServerQty(sorted.map((candidate) => candidate.take)),
        remainingAfter: groupRemainingAfter(sorted),
        balanceIds: groupBalanceIds(sorted),
        skuLabel: groupSkuLabel(sorted),
        hasTaskProduct:
          taskProductId != null &&
          sorted.some((candidate) => candidate.product_id === taskProductId),
      };
    })
    .sort((left, right) => left.order - right.order);
}

/** `balance_id` строки группы — для галочки всей строки. */
export function groupBalanceIds(
  candidates: readonly IssuePreviewCandidate[],
): number[] {
  return candidates.map((candidate) => candidate.balance_id);
}

/** Строка включена, пока снята не вся: сняты ВСЕ — галочка снята. */
export function isGroupChecked(
  balanceIds: readonly number[],
  excluded: readonly number[],
): boolean {
  return balanceIds.some((id) => !excluded.includes(id));
}

/** Снята часть строки — промежуточное состояние галочки группы. */
export function isGroupIndeterminate(
  balanceIds: readonly number[],
  excluded: readonly number[],
): boolean {
  const excludedCount = balanceIds.filter((id) => excluded.includes(id)).length;
  return excludedCount > 0 && excludedCount < balanceIds.length;
}

/** Состояние галочки группы для `Checkbox`. */
export function groupCheckState(
  balanceIds: readonly number[],
  excluded: readonly number[],
): boolean | "indeterminate" {
  if (isGroupIndeterminate(balanceIds, excluded)) return "indeterminate";
  return isGroupChecked(balanceIds, excluded);
}

/** Галочка группы: включить — убрать все её `balance_id`, выключить — добавить все. */
export function toggleGroupExcluded(
  excluded: readonly number[],
  balanceIds: readonly number[],
  checked: boolean,
): number[] {
  const groupIds = new Set(balanceIds);
  const without = excluded.filter((id) => !groupIds.has(id));
  if (checked) return without;
  return [...without, ...new Set(balanceIds)];
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
    return "Источник выдачи: ни на одном складе нет материала группы эквивалентов в нужном размере — выдавать нечего";
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
