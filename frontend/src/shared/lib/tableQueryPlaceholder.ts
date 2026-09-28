import type { QueryKey } from "@tanstack/react-query";

/**
 * Данные прошлого ключа — только пока не сменился объект списка.
 *
 * `keepPreviousData` безусловно отдаёт прошлые строки на любую смену ключа, а
 * ключ списка часто начинается с того, ЧТО именно перечисляют: `sectionId` на
 * доске участка, `spgId` в передачах, `locationId` в остатках. Смена такого
 * объекта идёт без размонтирования (плитки участка, селект ГХП), и оператор
 * увидел бы строки прежнего объекта под шапкой нового — вместе с кнопкой
 * «Завершить» над заданиями чужого участка. Показывать чужие строки хуже
 * размонтирования, поэтому через смену объекта placeholder не переносится
 * (ADR-0044).
 *
 * `scopeOf` читает объект из чужого ключа, `scope` — из текущего: экран
 * называет, что для него является объектом, и не пишет сравнение руками.
 */
export function keepPreviousDataForScope<TData>(
  scopeOf: (queryKey: QueryKey) => unknown,
  scope: unknown,
) {
  return (previousData: TData | undefined, previousQuery?: { queryKey: QueryKey }) =>
    previousQuery && scopeOf(previousQuery.queryKey) === scope ? previousData : undefined;
}

/**
 * Заглушка загрузки — только пока строк на экране не было ни разу.
 *
 * Дальше дерево остаётся на месте, а смену параметров показывает `isFetching`:
 * гейт по `isLoading` уносил таблицу вместе с открытым поповером и набранным в
 * нём текстом (ADR-0044). Правило общее для всех таблиц приложения, поэтому
 * живёт здесь, а не в тринадцати копиях выражения на экранах.
 */
export function isFirstRowsLoad<T>(isPending: boolean, rows: readonly T[]): boolean {
  return isPending && rows.length === 0;
}
