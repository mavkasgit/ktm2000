/**
 * Описание колонки таблицы — единственное место, где объявляется, как эта
 * колонка фильтруется, сортируется, подписывается и уезжает в запрос
 * (#197, ADR-0037; #198, ADR-0038).
 *
 * Пока описание жило в шапке и в параметрах запроса, одна колонка «Размер»
 * была названа в четырёх файлах: в рендере шапки тернарником и в параметрах
 * запроса вызовом с именем поля. Добавление второй колонки с особым
 * фильтром требовало правки в каждом из этих мест.
 */

import { pickColumnApiValue, pickExactMatchColumnValue } from "./columnFilterSearch";

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
  /**
   * Имя параметра запроса, если сервер ждёт не то же слово, что имя поля
   * колонки: «Артикул» на плане — это `source_sku`, на аудите —
   * `product_sku`. Без этого объявления колонка знает своё имя, а сборщик
   * параметров обязан знать серверное, и эти два слова живут в разных
   * файлах.
   */
  apiParam?: string;
  /**
   * Перекодировка значения колонки в значение параметра. Нужна там, где
   * сервер понимает не то, что видит оператор: «Не назначен» → `no`, а
   * «—» → ничего. Возвращённый `undefined` означает «не отправлять».
   */
  mapValue?: (value: string) => string | undefined;
  /**
   * Колонка, дающая сразу несколько параметров. Случай редкий, но
   * настоящий: «Следующий» на передачах — это и операция, и участок.
   */
  toParams?: (value: string) => Record<string, string>;
  /**
   * Фильтруется на клиенте и в запрос не уезжает. Объявлено, чтобы список
   * клиентских колонок не расходился с шапкой.
   */
  clientOnly?: boolean;
};

/**
 * Параметры точного совпадения для всех колонок, которые объявили его в
 * описании. Экран отдаёт их в запрос целиком и не перечисляет колонки руками:
 * вторая колонка с точным совпадением появляется без правки этого кода.
 *
 * Значение читается тем же `pickExactMatchColumnValue`, что и в
 * `buildColumnApiParams`, — иначе один и тот же клик по «Выбрать все» в
 * поповере габаритов отправлял бы на доске первое значение, а на плане не
 * отправлял ничего. Точный фильтр по определению не мультизначный: «Размер»
 * — это один габарит, и несколько выбранных значений запросу не
 * соответствуют.
 */
export function exactMatchColumnParams<Field extends string>(
  columnFilters: Partial<Record<Field, Set<string>>>,
  columns: ReadonlyArray<ColumnSpec<Field>>,
): Partial<Record<Field, string>> {
  const params: Partial<Record<Field, string>> = {};
  for (const column of columns) {
    if (!column.exactMatch || column.filterField === undefined) continue;
    const value = pickExactMatchColumnValue(columnFilters, column.filterField);
    if (value === undefined) continue;
    params[column.filterField] = value;
  }
  return params;
}

/**
 * Параметры запроса для всех отфильтрованных колонок.
 *
 * Экраны собирали их одинаково и в пяти местах: пять функций
 * `buildXColumnApiParams`, в каждой — перечисление колонок строкой. Колонка
 * попадала в список дважды: в разметке шапки и в сборке параметров. Здесь
 * перечисления нет — оно берётся из описания колонки, поэтому шестая
 * колонка не требует правки кода, который собирает параметры.
 */
export function buildColumnApiParams<Field extends string>(
  columnFilters: Partial<Record<Field, Set<string>>>,
  columnSearchQueries: Partial<Record<Field, string>>,
  columns: ReadonlyArray<ColumnSpec<Field>>,
): Record<string, string> {
  const params: Record<string, string> = {};
  for (const column of columns) {
    if (!column.filterField || column.clientOnly) continue;

    const value = column.exactMatch
      ? pickExactMatchColumnValue(columnFilters, column.filterField)
      : pickColumnApiValue(columnFilters, columnSearchQueries, column.filterField);
    if (value === undefined) continue;

    if (column.toParams) {
      Object.assign(params, column.toParams(value));
      continue;
    }

    const mapped = column.mapValue ? column.mapValue(value) : value;
    if (mapped === undefined) continue;
    params[column.apiParam ?? column.filterField] = mapped;
  }
  return params;
}
