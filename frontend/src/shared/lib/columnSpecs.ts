/**
 * Описание колонки таблицы — единственное место, где объявляется, как эта
 * колонка фильтруется, сортируется и как подписываются её значения
 * (#197, ADR-0037).
 *
 * Пока описание жило в шапке и в параметрах запроса, одна колонка «Размер»
 * была названа в четырёх файлах: в рендере шапки тернарником и в параметрах
 * запроса вызовом с именем поля. Добавление второй колонки с особым
 * фильтром требовало правки в каждом из этих мест.
 */

/** Что таблица знает о своей колонке. Всё остальное — производное. */
export type ColumnSpec<
  Field extends string,
  SortField extends string = Field,
> = {
  /** Поле фильтра колонки. Отсутствует — колонка без фильтра. */
  filterField?: Field;
  /**
   * Поле сортировки. Отсутствует — сервер не умеет сортировать по этой
   * колонке, и иконка сортировки в шапке не рисуется. Молчаливая подмена
   * другого поля запрещена: оператор кликнул и не увидел эффекта.
   */
  sortField?: SortField;
  /** Подпись значения в списке фильтра («Статус» → «Готово»). */
  valueLabel?: (value: string) => string;
  /**
   * Фильтр точным совпадением, а не по подстроке. Так работает «Размер»:
   * оператор выбирает конкретный габарит из списка, а не ищет подстроку в
   * подписи. Признак объявлен здесь, а перечислен в параметрах запроса не
   * должен быть нигде.
   */
  exactMatch?: boolean;
};

/**
 * Параметры точного совпадения для всех колонок, которые объявили его в
 * описании. Экран отдаёт их в запрос целиком и не перечисляет колонки руками:
 * вторая колонка с точным совпадением появляется без правки этого кода.
 */
export function exactMatchColumnParams<Field extends string>(
  columnFilters: Partial<Record<Field, Set<string>>>,
  columns: ReadonlyArray<ColumnSpec<Field>>,
): Partial<Record<Field, string>> {
  const params: Partial<Record<Field, string>> = {};
  for (const column of columns) {
    if (!column.exactMatch || column.filterField === undefined) continue;
    const selected = columnFilters[column.filterField];
    if (!selected || selected.size === 0) continue;
    params[column.filterField] = [...selected][0];
  }
  return params;
}
