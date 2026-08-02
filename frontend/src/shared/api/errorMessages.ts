import { errorPhraseTranslations } from "@/shared/lib/generated-labels";

/**
 * Словарь переводов серверных ошибок на русский.
 *
 * Бэкенд выбрасывает `raise ValueError(...)` и `raise HTTPException(detail=...)`
 * с английскими текстами. Чтобы не трогать сервер (логи, тесты, отладка остаются
 * на английском), переводим на клиенте.
 *
 * Ключи — точные английские строки или шаблоны с плейсхолдерами `{0}`, `{1}`, ...
 * Шаблон используется, когда бэкенд подставляет динамические значения через f-string.
 * `translateError` сам определяет, искать точное совпадение или нормализовать строку
 * в шаблон.
 */

/**
 * Нормализует строку с динамическими значениями в шаблон с плейсхолдерами `{0}`, `{1}`...
 * чтобы можно было искать в словаре по шаблону.
 *
 * Примеры:
 *   "Position 5 with status 'draft' cannot be approved"
 *     -> "Position {0} with status '{1}' cannot be approved"
 *   "Some positions not found or belong to a different plan"
 *     -> "Some positions not found or belong to a different plan"
 *   "Return quantity (1.5) exceeds available for return (2.0)"
 *     -> "Return quantity ({0}) exceeds available for return ({1})"
 */
function toTemplate(input: string): string {
  let out = input;
  // Числа (целые и дробные)
  out = out.replace(/-?\d+(?:[.,]\d+)?/g, "{N}");
  // Содержимое в кавычках
  out = out.replace(/'([^']*)'/g, "'{N}'");
  // Теперь заменим все {N} на инкрементные {0}, {1}, ...
  let counter = 0;
  out = out.replace(/\{N\}/g, () => `{${counter++}}`);
  return out;
}

/**
 * Переводит серверное сообщение на русский.
 * Если перевода нет — возвращает оригинал.
 */
export function translateError(message: string | null | undefined): string {
  if (!message) return message ?? "";
  const trimmed = message.trim();
  if (!trimmed) return message;

  // 1) Точное совпадение
  const exact = errorPhraseTranslations[trimmed];
  if (exact !== undefined) return exact;

  // 2) Шаблон по динамическим значениям
  const templated = toTemplate(trimmed);
  const tplMatch = errorPhraseTranslations[templated];
  if (tplMatch !== undefined) {
    // Подставим обратно динамические значения
    const values: string[] = [];
    let m = trimmed;
    m = m.replace(/-?\d+(?:[.,]\d+)?/g, (v) => {
      values.push(v);
      return `\u0000${values.length - 1}\u0000`;
    });
    m = m.replace(/'([^']*)'/g, (_full, v: string) => {
      values.push(v);
      return `'\u0000${values.length - 1}\u0000'`;
    });
    return tplMatch.replace(/\{(\d+)\}/g, (_full, idx: string) => {
      const i = Number(idx);
      return values[i] ?? "";
    });
  }

  return message;
}

/**
 * Переводит сообщения валидации импорта остатков (preview/import).
 * Обрабатывает обёртку «Row N: … (SKU=…)» и вложенные ошибки.
 */
export function translateImportError(message: string | null | undefined): string {
  if (!message) return message ?? "";
  const trimmed = message.trim();
  if (!trimmed) return message;

  const rowMatch = trimmed.match(/^Row (\d+): (.+) \(SKU=(.*)\)$/);
  if (rowMatch) {
    const [, row, errs, sku] = rowMatch;
    const translatedErrs = errs
      .split(", ")
      .map((part) => translateImportError(part.trim()))
      .join(", ");
    return `Строка ${row}: ${translatedErrs}${sku ? ` (артикул=${sku})` : ""}`;
  }

  return translateError(trimmed);
}
