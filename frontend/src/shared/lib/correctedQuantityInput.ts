/**
 * Правило ввода количества при **правке записанного факта** (#200).
 *
 * Это не то же правило, что `normalizeQuantityInput` (ADR-0032), и наоборот.
 * Там количество задания — целые штуки: ноль допустим, дробь запрещена. Здесь
 * правило другое, потому что правка факта и ввод нового количества — разные
 * вещи:
 *
 * - **Дробь законна.** Правка применяется к `transfer_send`, а передачи по
 *   домену дробные (`Numeric(14,3)`, `QTY_SCALE = 1000`). Запрет дробного
 *   здесь был бы регрессом: половину штуки передать можно.
 * - **Ноль запрещён.** Сервер читает `Decimal(str(quantity))` и требует
 *   строго больше нуля, поэтому ноль — не «отсутствие ввода», а ошибка.
 * - **Разделитель дробный равноценен.** `Decimal("5,5")` бросает
 *   исключение, но ругать оператора за запятую нельзя: он набрал то, что
 *   набирают все. Значение уходит на сервер числом, в поле остаётся то, что
 *   оператор набрал.
 * - **Точность ограничена тремя знаками** — ровно то, что вмещает
 *   `Numeric(14,3)`. Больше — молчаливое округление на сервере.
 *
 * Верхнего лимита здесь нет и быть не должно: сервер проверяет покрытие
 * склада в предпросмотре (`forward_coverage_deficit` → блокер `coverage`),
 * а лимит «не больше, чем transferable задания» однажды уже попробовали и
 * отключили — на трансформирующих этапах задача списала старое количество в
 * `produced`, и проверка давала ложный отказ (`allow_over_plan=True`).
 *
 * Пустой ввод — отсутствие ввода, а не ноль: поле не отправляет значение.
 */

/** Почему ввод количества при правке факта отклонён. */
export type CorrectedQuantityIssueKind =
  | "negative"
  | "non-numeric"
  | "decimal"
  | "precision"
  | "zero";

export type CorrectedQuantityIssue = {
  kind: CorrectedQuantityIssueKind;
  /** Текст причины для показа под полем. */
  text: string;
};

export type NormalizedCorrectedQuantity = {
  /** Ввод в том виде, в каком его набрал оператор. */
  value: string;
  /** Число для отправки; `null`, пока ввод недопустим или пуст. */
  number: number | null;
  /** Причина отклонения, если ввод недопустим. */
  issue: CorrectedQuantityIssue | null;
};

export const CORRECTED_QUANTITY_ISSUE_TEXT: Record<CorrectedQuantityIssueKind, string> = {
  negative: "Количество не может быть отрицательным.",
  "non-numeric": "Количество — только цифры.",
  decimal: "Дробная часть — одна запятая или точка.",
  precision: "Не больше трёх знаков после запятой.",
  zero: "Количество должно быть больше нуля.",
};

/** Знаков после запятой, которые вмещает домен передач (`Numeric(14,3)`). */
const MAX_DECIMALS = 3;

const DIGIT = /[0-9]/;
const DECIMAL_SEPARATOR = /[.,]/;

/**
 * Нормализует ввод количества в правке факта: возвращает то, что показать
 * в поле, число для отправки и причину отклонения, если она есть.
 *
 * Причина называется по первому недопустимому символу — так сообщение не
 * меняется на ходу набора и остаётся предсказуемым.
 */
export function normalizeCorrectedQuantityInput(raw: string): NormalizedCorrectedQuantity {
  const issueKind = findIssue(raw);
  if (issueKind !== null) {
    return { value: raw, number: null, issue: { kind: issueKind, text: CORRECTED_QUANTITY_ISSUE_TEXT[issueKind] } };
  }

  const value = raw.trim();
  if (value === "") return { value: "", number: null, issue: null };

  // Здесь value уже проверен findIssue: только цифры и не более одного
  // разделителя, поэтому Number() даёт число, а не NaN.
  const normalized = value.replace(",", ".");
  const number = Number(normalized);
  if (number === 0) {
    return { value, number: null, issue: { kind: "zero", text: CORRECTED_QUANTITY_ISSUE_TEXT.zero } };
  }
  return { value, number, issue: null };
}

/** Первый недопустимый символ; `null`, если весь ввод допустим. */
function findIssue(raw: string): CorrectedQuantityIssueKind | null {
  let separators = 0;
  let decimals = 0;
  let seenSeparator = false;

  for (const ch of raw.trim()) {
    if (DIGIT.test(ch)) {
      if (seenSeparator) decimals += 1;
      continue;
    }
    if (DECIMAL_SEPARATOR.test(ch)) {
      separators += 1;
      if (separators > 1) return "decimal";
      seenSeparator = true;
      continue;
    }
    if (ch === "-") return "negative";
    return "non-numeric";
  }

  if (decimals > MAX_DECIMALS) return "precision";
  return null;
}
