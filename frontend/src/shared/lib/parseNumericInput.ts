export type ParseNumericInputOptions = {
  /** Поддержка запятой как десятичного разделителя: "12,5" → 12.5. */
  allowComma?: boolean;
};

/**
 * Единый парсер «строка → число» (#80).
 * Читает число из строки и возвращает его или null. Валидация «>0» — у вызывающих.
 */
export function parseNumericInput(
  text: string,
  options: ParseNumericInputOptions = {},
): number | null {
  const { allowComma = false } = options;
  const trimmed = text.trim();
  if (!trimmed) return null;
  const normalized = allowComma ? trimmed.replace(",", ".") : trimmed;
  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? parsed : null;
}
