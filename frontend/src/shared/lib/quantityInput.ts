/**
 * Правило ввода количества в операциях (#192, ADR-0032).
 *
 * Количество задания — целое число штук: десятичная запятая, точка и минус
 * недопустимы. Зона действия — поля ввода факта на доске участков (диалог,
 * массовый ввод в ячейках строки и в шапке группы). Передачи, правка позиции
 * плана и правка факта в журнале сюда не входят: там количество либо дробное по
 * домену (`Numeric(14,3)`), либо это исправление уже записанного факта.
 *
 * **Ведущий `+` — признак режима, а не знак числа**: «+100» значит «добавить
 * 100», «500» — «факт станет 500» (разбирает `resolveFactQuantity` в
 * `features/sections/lib`). Знак остаётся в значении: поле показывает то, что
 * набрал оператор, а не переписывает ввод. `+` не первым символом — тот же
 * недопустимый символ, что и буква.
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

/** Режим ввода: «+100» — добавить, «500» — задать факт. */
export type QuantityInputMode = "add" | "set";

export type NormalizedQuantityInput = {
  /** Оставшаяся часть ввода: ведущий «+» (если набран) и цифры. */
  value: string;
  /** Режим: набран ведущий «+» — добавление, иначе установка факта. */
  mode: QuantityInputMode;
  /** Причина отклонения, если ввод содержал недопустимые символы. */
  issue: QuantityInputIssue | null;
};

export const QUANTITY_INPUT_ISSUE_TEXT: Record<QuantityInputIssueKind, string> = {
  decimal: "Количество — целое число штук. Запятая и точка не допускаются.",
  negative: "Количество не может быть отрицательным.",
  "non-digit": "Количество — только цифры; «+» — первым символом, чтобы добавить.",
};

const DECIMAL_SEPARATOR = /[.,]/;
const DIGIT = /[0-9]/;
/** Ведущий «+»: режим «добавить». */
const ADD_MARKER = "+";

/**
 * Нормализует ввод в поле количества: оставляет цифры и ведущий «+», отбрасывает
 * недопустимое и сообщает почему. Пустой ввод — это отсутствие ввода, а не
 * ноль, поэтому возвращается пустая строка без причины: ноль в поле допустим
 * (ADR-0032).
 *
 * Из нескольких недопустимых символов причина называется по первому — так
 * сообщение не меняется на ходу набора и остаётся предсказуемым.
 */
export function normalizeQuantityInput(raw: string): NormalizedQuantityInput {
  let value = "";
  let mode: QuantityInputMode = "set";
  let issue: QuantityInputIssueKind | null = null;

  for (const ch of raw) {
    if (DIGIT.test(ch)) {
      value += ch;
      continue;
    }
    if (issue !== null) continue;
    if (ch === ADD_MARKER && value === "") {
      mode = "add";
      value += ch;
      continue;
    }
    if (DECIMAL_SEPARATOR.test(ch)) issue = "decimal";
    else if (ch === "-") issue = "negative";
    else issue = "non-digit";
  }

  return {
    value,
    mode,
    issue: issue === null ? null : { kind: issue, text: QUANTITY_INPUT_ISSUE_TEXT[issue] },
  };
}

/**
 * Разбор сохранённого ввода: режим и число (`null` — числа в поле нет).
 * Синтаксис разбирается здесь же, где объявлен: второй разбор строки рядом с
 * потребителем разошёлся бы с правилом ввода.
 */
export function parseQuantityInput(value: string): {
  mode: QuantityInputMode;
  quantity: number | null;
} {
  const mode: QuantityInputMode = value.startsWith(ADD_MARKER) ? "add" : "set";
  const digits = mode === "add" ? value.slice(ADD_MARKER.length) : value;
  if (digits === "") return { mode, quantity: null };
  const quantity = Number(digits);
  return { mode, quantity: Number.isFinite(quantity) ? quantity : null };
}
