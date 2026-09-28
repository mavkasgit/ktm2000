/**
 * Правило ввода количества в операциях (#192, ADR-0032).
 *
 * Количество задания — целое число штук: десятичная запятая, точка и минус
 * недопустимы. Зона действия — поля ввода факта на доске участков и поля
 * панели массовых операций. Передачи, правка позиции плана и правка факта в
 * журнале сюда не входят: там количество либо дробное по домену
 * (`Numeric(14,3)`), либо это исправление уже записанного факта.
 *
 * Отличие от `parseNumericInput`: тот читает строку в число для данных
 * (значения из БД, расчёты) и остаётся проницаемым, этот работает на вводе
 * оператора — отбрасывает недопустимые символы и возвращает причину, чтобы
 * поле показало её рядом с собой. Значит парсер в коде ничем не ограничен,
 * а видимое правило живёт в одном месте.
 */

/** Почему ввод в поле количества отклонён. */
export type QuantityInputIssueKind = "decimal" | "negative" | "non-digit";

export type QuantityInputIssue = {
  kind: QuantityInputIssueKind;
  /** Текст причины для показа под полем. */
  text: string;
};

export type NormalizedQuantityInput = {
  /** Оставшаяся часть ввода: только цифры. */
  value: string;
  /** Причина отклонения, если ввод содержал недопустимые символы. */
  issue: QuantityInputIssue | null;
};

export const QUANTITY_INPUT_ISSUE_TEXT: Record<QuantityInputIssueKind, string> = {
  decimal: "Количество — целое число штук. Запятая и точка не допускаются.",
  negative: "Количество не может быть отрицательным.",
  "non-digit": "Количество — только цифры.",
};

const DECIMAL_SEPARATOR = /[.,]/;
const DIGIT = /[0-9]/;

/**
 * Нормализует ввод в поле количества: оставляет цифры, отбрасывает
 * недопустимое и сообщает почему. Пустой ввод — это отсутствие ввода, а не
 * ноль, поэтому возвращается пустая строка без причины: ноль в поле допустим
 * (ADR-0032).
 *
 * Из нескольких недопустимых символов причина называется по первому — так
 * сообщение не меняется на ходу набора и остаётся предсказуемым.
 */
export function normalizeQuantityInput(raw: string): NormalizedQuantityInput {
  let value = "";
  let issue: QuantityInputIssueKind | null = null;

  for (const ch of raw) {
    if (DIGIT.test(ch)) {
      value += ch;
      continue;
    }
    if (issue !== null) continue;
    if (DECIMAL_SEPARATOR.test(ch)) issue = "decimal";
    else if (ch === "-") issue = "negative";
    else issue = "non-digit";
  }

  return {
    value,
    issue: issue === null ? null : { kind: issue, text: QUANTITY_INPUT_ISSUE_TEXT[issue] },
  };
}
