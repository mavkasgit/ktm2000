/**
 * Заголовок колонки, собранный из её описания — единственный способ
 * подключить к колонке фильтр и сортировку (#197, ADR-0037; #198,
 * ADR-0038).
 *
 * Экраны писали эту связку сами и расходились. Одни передавали в попапер
 * `onSearchChange`, другие нет, и разница была неосмысленной: поиск в
 * поповере сужает список значений, а колонка «Размер» выбирается кликом по
 * габариту. Экраны, где поиск писался в состояние таблицы, зажигали кнопку
 * сброса после того, как оператор просто посмотрел список.
 *
 * Описание решает все четыре случая, и экран не выбирает между ними
 * тернарником:
 *
 * | фильтр | сортировка | что рисуется                     |
 * |--------|------------|----------------------------------|
 * | да     | да         | попапер фильтра + кнопка сортировки |
 * | да     | нет        | попапер фильтра                  |
 * | нет    | да         | текст + кнопка сортировки         |
 * | нет    | нет        | текст                            |
 */
import type { SortConfig } from "@/shared/hooks/useTableQueryEngine";
import type { ColumnSpec } from "@/shared/lib/columnSpecs";

import { SortableFilterHeader } from "./SortableFilterHeader";

type BoundColumn<Field extends string> = {
  searchQuery?: string;
  selectedValues: Set<string>;
  onSearchChange?: (field: Field, query: string) => void;
  onFilterChange: (field: Field, selected: Set<string>) => void;
  /** Применить набранный текст сейчас, минуя паузу перед запросом. */
  onApplySearch?: () => void;
};

export interface DataTableColumnHeaderProps<Field extends string, SortField extends string = Field> {
  column: ColumnSpec<Field, SortField> & { label: React.ReactNode };
  /** Связь состояния таблицы с колонкой. Нужна только фильтруемым колонкам. */
  bindColumn?: (field: Field) => BoundColumn<Field>;
  /** Значения для списка фильтра. Только для фильтруемых колонок. */
  values?: string[];
  currentSorts?: SortConfig<SortField>[];
  onSortChange?: (field: SortField) => void;
}

export function DataTableColumnHeader<Field extends string, SortField extends string = Field>({
  column,
  bindColumn,
  values,
  currentSorts,
  onSortChange,
}: DataTableColumnHeaderProps<Field, SortField>) {
  const { filterField, sortField, exactMatch, clientOnly, valueLabel, label } = column;
  const filterable = filterField !== undefined;
  const sortable = sortField !== undefined;

  if (!filterable && !sortable) {
    return <span className="text-xs font-medium text-muted-foreground">{label}</span>;
  }

  const bound = filterable && bindColumn ? bindColumn(filterField) : undefined;

  // Точная колонка выбирается кликом, а не подстрокой: её поиск в поповере
  // остаётся локальным и не трогает состояние таблицы, иначе счётчик
  // активных фильтров врал бы.
  const searchBinding = !bound
    ? {}
    : exactMatch
      ? { selectedValues: bound.selectedValues, onFilterChange: bound.onFilterChange }
      : bound;
  // Поиск `exactMatch` сужает только список значений — он не уезжает в запрос
  // и не забирает контрол себе, поэтому приоритет текста на нём не действует.
  const searchFiltersTable = !exactMatch;
  // Несколько значений выбирает только колонка, которую фильтрует сам экран:
  // сервер принимает на колонку одно значение, и лишний выбор ушёл бы в
  // никуда, оставив бейдж несуществующего фильтра (ADR-0044).
  const multiSelect = clientOnly === true;

  return (
    <SortableFilterHeader<Field, SortField>
      field={(filterField ?? sortField) as Field}
      label={label}
      currentSorts={currentSorts ?? []}
      onSortChange={onSortChange ?? noopSortChange}
      sortable={sortable}
      filterable={filterable}
      values={values ?? []}
      valueLabel={valueLabel}
      multiSelect={multiSelect}
      searchFiltersTable={searchFiltersTable}
      {...searchBinding}
    />
  );
}

const noopSortChange = () => {};
