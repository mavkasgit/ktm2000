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

/**
 * Род значения, которое колонка кладёт в запрос.
 *
 * Значение колонки приходит из попапера строкой, а контракт запроса у части
 * экранов строгий: длина — `number`, флаг — `boolean`. Приводить это вручную
 * на экране нельзя (это перечисление полей, ради устранения которого описание
 * колонок и заведено), а ослаблять контракт до `number | string` — значит
 * перестать ловить мусор на границе с сервером. Поэтому род объявляет описание,
 * а приведение делает сборщик.
 */
export type ColumnParamKind = "string" | "number" | "boolean";

/** Значение параметра запроса в том виде, в каком его ждёт контракт. */
export type ColumnParamValue = string | number | boolean;

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
  mapValue?: (value: string) => ColumnParamValue | undefined;
  /**
   * Колонка, дающая сразу несколько параметров. Случай редкий, но
   * настоящий: «Следующий» на передачах — это и операция, и участок.
   */
  toParams?: (value: string) => Record<string, ColumnParamValue>;
  /**
   * Род значения параметра: строка (по умолчанию), число или флаг.
   *
   * Значение колонки всегда строка — оператор выбирает из списка. Но
   * контракт запроса у части экранов строгий: `length_from` — это `number`,
   * `is_paired_profile` — `boolean`. Ослаблять контракт до `number | string`
   * ради сборщика нельзя: он перестал бы ловить мусор на границе с сервером.
   * Поэтому род объявляет описание, а приведение делает общий сборщик —
   * иначе экран приводит значения руками, то есть возвращается к перечислению
   * полей, ради которого описание и заводилось.
   */
  paramKind?: ColumnParamKind;
  /**
   * Фильтруется на клиенте и в запрос не уезжает. Объявлено, чтобы список
   * клиентских колонок не расходился с шапкой.
   */
  clientOnly?: boolean;
};

/**
 * Параметры запроса для всех отфильтрованных колонок — строковые.
 *
 * Экраны собирали их одинаково и в пяти местах: пять функций
 * `buildXColumnApiParams`, в каждой — перечисление колонок строкой. Колонка
 * попадала в список дважды: в разметке шапки и в сборке параметров. Здесь
 * перечисления нет — оно берётся из описания колонки, поэтому шестая
 * колонка не требует правки кода, который собирает параметры.
 *
 * Колонки с нестроковым параметром (`paramKind`) сюда не попадают: их
 * значения собирает `buildTypedColumnApiParams`.
 *
 * Значения точного совпадения (`exactMatch`) собирает тоже этот файл, но
 * глубже — в `readColumnValue`, откуда их берут и `buildColumnApiParams`, и
 * `buildTypedColumnApiParams`. Отдельного сборщика точных параметров нет
 * намеренно: он был мёртвым экспортом без единого production-вызова, и в
 * нём не было проверки `clientOnly`, которую имеет `readColumnValue`. Экраны
 * зовут эти две функции.
 */
export function buildColumnApiParams<Field extends string>(
  columnFilters: Partial<Record<Field, Set<string>>>,
  columnSearchQueries: Partial<Record<Field, string>>,
  columns: ReadonlyArray<ColumnSpec<Field>>,
): Record<string, string> {
  const params: Record<string, string> = {};
  for (const column of columns) {
    if (!column.filterField) continue;
    const value = readColumnValue(column, columnFilters, columnSearchQueries);
    if (value === undefined) continue;

    if (column.toParams) {
      const multi = column.toParams(value);
      if (column.paramKind === "number" || column.paramKind === "boolean") {
        throw new Error(
          `Колонка «${column.filterField}» объявила paramKind, но toParams отдаёт строки — приведение делает buildTypedColumnApiParams`,
        );
      }
      for (const [name, multiValue] of Object.entries(multi)) {
        params[name] = String(multiValue);
      }
      continue;
    }

    const mapped = column.mapValue ? column.mapValue(value) : value;
    if (mapped === undefined) continue;
    if (column.paramKind !== undefined && column.paramKind !== "string") {
      throw new Error(
        `Колонка «${column.filterField}» объявила paramKind, но собрана строковым buildColumnApiParams — используйте buildTypedColumnApiParams`,
      );
    }
    params[column.apiParam ?? column.filterField] = String(mapped);
  }
  return params;
}

/**
 * Параметры запроса в типах, которые объявил контракт экрана: длина приходит
 * числом, флаг — булевым.
 *
 * Значение из попапера — строка, и приводить его на экране нельзя: это
 * перечисление полей, ради устранения которого описание колонок и заведено.
 * Ослаблять контракт до `number | string` тоже нельзя — он перестал бы ловить
 * мусор на границе с сервером. Поэтому род объявляет описание (`paramKind`),
 * а приведение делает сборщик. Экран получает ровно свой тип — `Pick` от
 * контракта запроса, без `as` и без послаблений.
 */
export function buildTypedColumnApiParams<Field extends string, Params>(
  columnFilters: Partial<Record<Field, Set<string>>>,
  columnSearchQueries: Partial<Record<Field, string>>,
  columns: ReadonlyArray<ColumnSpec<Field>>,
): Partial<Params> {
  const params: Record<string, ColumnParamValue> = {};
  for (const column of columns) {
    if (!column.filterField) continue;
    const value = readColumnValue(column, columnFilters, columnSearchQueries);
    if (value === undefined) continue;
    if (column.toParams) {
      for (const [name, multiValue] of Object.entries(column.toParams(value))) {
        const converted = toParamKind(multiValue, column.paramKind);
        if (converted === undefined) continue;
        params[name] = converted;
      }
      continue;
    }

    const mapped = column.mapValue ? column.mapValue(value) : value;
    if (mapped === undefined) continue;
    const converted = toParamKind(mapped, column.paramKind);
    if (converted === undefined) continue;
    params[column.apiParam ?? column.filterField] = converted;
  }
  return params as Partial<Params>;
}

/**
 * Значение колонки из состояния таблицы: выбранное значение, а для точной
 * колонки — только оно, без результата поиска в поповере.
 */
function readColumnValue<Field extends string>(
  column: ColumnSpec<Field>,
  columnFilters: Partial<Record<Field, Set<string>>>,
  columnSearchQueries: Partial<Record<Field, string>>,
): string | undefined {
  if (!column.filterField || column.clientOnly) return undefined;
  return column.exactMatch
    ? pickExactMatchColumnValue(columnFilters, column.filterField)
    : pickColumnApiValue(columnFilters, columnSearchQueries, column.filterField);
}

/**
 * Приводит значение к роду, объявленному в описании колонки.
 *
 * Значение, которое привести нельзя, не отправляется вовсе: мусор в запросе
 * сузил бы выборку до пустой, а 422 на границе с сервером хуже, чем тихий
 * пропуск фильтра.
 */
function toParamKind(
  value: ColumnParamValue,
  kind: ColumnParamKind | undefined,
): ColumnParamValue | undefined {
  if (kind === undefined || kind === "string") return value;
  if (kind === "number") {
    const num = typeof value === "number" ? value : Number(value);
    return Number.isFinite(num) ? num : undefined;
  }
  if (typeof value === "boolean") return value;
  if (value === "true") return true;
  if (value === "false") return false;
  return undefined;
}
