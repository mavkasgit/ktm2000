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
 * Подсказки оператору по канонической фразе отказа (#323).
 *
 * Ключ — та же каноническая английская фраза (или шаблон), что и в
 * `errorPhraseTranslations`: она приходит с сервера и переводится генератором
 * (`generate_frontend_labels.py`), поэтому вердикт «что делать» не зависит от
 * формулировки перевода — правка русского текста в словаре подсказку не ломает.
 *
 * Смысл разделён: `translateError` отвечает «что случилось», `getErrorHint` —
 * «что с этим делать». Экран показывает `hint ?? message`: доска — строкой под
 * формой подтверждения факта, передачи — текстом тоста.
 */
const errorPhraseHints: Record<string, string> = {
  // Отказы подтверждения факта на доске участка.
  "Complete quantity exceeds quantity in work":
    "Количество факта больше объема 'В работе'. Сначала уменьшите факт или довыдайте в работу.",
  "Return quantity ({0}) exceeds available for return ({1})":
    "Количество больше доступного для выдачи. Проверьте поле 'Доступно'.",
  "Section is locked to single-window context":
    "Режим одного окна разрешает работу только с текущим участком.",
  // Отказы отправки передачи и финального выпуска.
  "Transfer quantity exceeds transferable amount":
    "Количество больше доступного к передаче.",
  // Скорректированное количество — тот же класс отказа, что и строка выше:
  // в старой копии страницы первая ветвь перехватывала его раньше, и подсказка
  // была общей. Оставляем общую (поведение передач не меняется, #323 DoD).
  "Corrected quantity exceeds transferable amount of source task. Available to transfer: {0}":
    "Количество больше доступного к передаче.",
  "Transfer target must be next route step":
    "Передавать можно только на следующий этап маршрута.",
  "Transfer must be sent":
    "Передача уже обработана. Обновите список входящих передач.",
  "accepted + rejected exceeds sent quantity":
    "Сумма принятого и отклонённого превышает отправленное количество.",
  "Final release exceeds releasable quantity":
    "Количество больше доступного к выпуску.",
  "Final release allowed only for final route stage":
    "Финальный выпуск доступен только на финальном этапе маршрута.",
  "Target task has already consumed or issued parts. Cannot reduce transfer by {0} as target task only has {1} available stock":
    "Нельзя уменьшить передачу: целевая задача уже использовала материалы.",
};

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
 * Форма сообщения без конкретных значений: числа и плейсхолдеры словаря `{0}`,
 * `{1}` сводятся к одному маркеру `{N}`.
 *
 * Нужна потому, что одно и то же сообщение приходит в двух видах — сырым
 * английским текстом («... exceeds available for return (2.0)») и переводом
 * («... превышает доступное к возврату (2.0)») — и оба вида должны дать ту же
 * подсказку, что и каноническая фраза-владелец («... ({0}) ... ({1})»).
 */
function valueShape(input: string): string {
  return input
    .replace(/\{-?\d+\}/g, "{N}")
    .replace(/-?\d+(?:[.,]\d+)?/g, "{N}")
    .replace(/'([^']*)'/g, "'{N}'");
}

/**
 * Индекс подсказок по форме сообщения: каноническая фраза и её перевод дают одну
 * и ту же форму. Строится лениво, словарь неизменен.
 *
 * Фраза без ключа в `errorPhraseTranslations` остаётся достижимой только сырым
 * английским текстом — сторож на это стоит в тесте (`getErrorHint`).
 */
let hintIndex: Record<string, string> | null = null;

function getHintIndex(): Record<string, string> {
  if (!hintIndex) {
    const index: Record<string, string> = Object.create(null);
    for (const [key, hint] of Object.entries(errorPhraseHints)) {
      index[valueShape(key)] = hint;
      const translation = errorPhraseTranslations[key];
      if (translation !== undefined) index[valueShape(translation)] = hint;
    }
    hintIndex = index;
  }
  return hintIndex;
}

/**
 * Подсказка оператору: что делать при этом отказе. Принимает и сырое серверное
 * сообщение, и его перевод после `translateError` — сопоставление идёт по форме
 * канонической фразы, а не по подстроке, поэтому не рассыпается от правки текста.
 * `null` — подсказки нет, экран показывает сам текст ошибки.
 */
export function getErrorHint(message: string | null | undefined): string | null {
  if (!message) return null;
  const trimmed = message.trim();
  if (!trimmed) return null;
  return getHintIndex()[valueShape(trimmed)] ?? null;
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
