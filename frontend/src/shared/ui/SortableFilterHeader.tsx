import React, { useState, useMemo, useCallback } from "react";
import { IconArrowUp, IconArrowDown, IconSelector } from "@tabler/icons-react";
import { Search, X } from "lucide-react";
import { cn } from "@/shared/utils/cn";
import { Popover, PopoverTrigger, PopoverContent } from "./popover";
import { Input } from "./input";
import { Button } from "./button";
import type { SortConfig } from "@/shared/hooks/useTableQueryEngine";
import { sortByPartialSearchMatch } from "@/shared/lib/columnFilterSearch";

/** Один на таблицу: колонке без фильтра нечего показывать в бейдже. */
const EMPTY_SET: Set<string> = new Set<string>();
const noopFilterChange = () => {};

export interface SortableFilterHeaderProps<Field extends string, SortField extends string = Field> {
  field: Field;
  label: React.ReactNode;
  currentSorts: SortConfig<SortField>[];
  onSortChange: (field: SortField) => void;
  values: string[];
  selectedValues?: Set<string>;
  onFilterChange?: (field: Field, selected: Set<string>) => void;
  valueLabel?: (value: string) => string;
  /**
   * false — колонка фильтруется, но не сортируется: сервер не умеет сортировать
   * по этому полю, а подставлять вместо него чужое поле молча нельзя.
   */
  sortable?: boolean;
  /**
   * false — колонка сортируется, но не фильтруется: сервер такого фильтра не
   * понимает, и показывать оператору попапер, который ничего не делает,
   * незачем. Подпись становится текстом, кнопка сортировки остаётся.
   */
  filterable?: boolean;
  /** Controlled search query for live table filtering */
  searchQuery?: string;
  onSearchChange?: (field: Field, query: string) => void;
  /**
   * Можно ли выбрать несколько значений. Да только у колонок, которые
   * фильтрует сам экран: сервер принимает на колонку одно значение, и второй
   * выбранный молча ушёл бы в никуда, оставив в шапке бейдж несуществующего
   * фильтра (ADR-0044).
   */
  multiSelect?: boolean;
  /**
   * Применить набранный текст немедленно, не дожидаясь паузы. Вызывается по
   * `Enter` и по кнопке «Готово»: оператор, нажавший «Готово», сказал «искать
   * сейчас», и ждать после этого полсекунды незачем.
   */
  onApplySearch?: () => void;
  /**
   * Текст в поповере фильтрует выборку (server-колонка): пока он введён,
   * список значений скрыт, а выбранное значение снимается.
   *
   * false у колонки, чей поиск сужает только список: у `exactMatch` текст не
   * уезжает в запрос, и скрывать единственный список, который он сужает, —
   * значит сломать поиск, ничего не дав взамен.
   */
  searchFiltersTable?: boolean;
}

/**
 * Unified column header with sort + filter:
 * - Click text → filter popover with clickable rows (filled when selected)
 * - Click sort icon → cycle sort (none → asc → desc)
 * - Search in popover: partial match + relevance sort; live table filter via
 *   onSearchChange
 *
 * Доступность (#204): значение фильтра — кнопка с `aria-pressed` (Tab
 * проходит по значениям, Enter/Space переключает), а `aria-label` кнопки
 * сортировки собирается из подписи колонки, порядка словами и приоритета
 * мультисортировки — машинного имени поля в нём нет.
 *
 * Пока в поповере серверной колонки введён текст, списка значений на экране
 * нет: одно поле — одно действие, и «ищу подстроку» с «выбираю значение» не
 * должны быть двумя молчащими режимами одного контрола. Текст приоритетнее
 * выбора, поэтому непустой текст снимает выбранное значение, а не оставляет
 * его жить в состоянии невидимым. У колонки, чей поиск сужает только список
 * (`searchFiltersTable: false`), список остаётся: там текст — это поиск по
 * списку, и скрывать нечего, кроме самого поиска.
 */
export function SortableFilterHeader<Field extends string, SortField extends string = Field>({
  field,
  label,
  currentSorts,
  onSortChange,
  values = [],
  selectedValues = EMPTY_SET,
  onFilterChange = noopFilterChange,
  valueLabel,
  sortable = true,
  filterable = true,
  searchQuery: controlledSearchQuery,
  onSearchChange,
  multiSelect = false,
  onApplySearch,
  searchFiltersTable = true,
}: SortableFilterHeaderProps<Field, SortField>) {
  const [internalSearchQuery, setInternalSearchQuery] = useState("");
  const [open, setOpen] = useState(false);

  const isSearchControlled = controlledSearchQuery !== undefined;
  const searchQuery = isSearchControlled ? controlledSearchQuery : internalSearchQuery;

  const setSearchQuery = useCallback(
    (query: string) => {
      setInternalSearchQuery(query);
      onSearchChange?.(field, query);
      // Непустой текст забирает контрол себе: оставить при этом выбранное
      // значение значит показать в шапке фильтр, которого в запросе нет. У
      // колонки, чей текст сужает только список, выбранное значение — часть
      // этого списка, и снимать его незачем.
      if (searchFiltersTable && query.trim() && selectedValues.size > 0) {
        onFilterChange(field, new Set());
      }
    },
    [field, onSearchChange, onFilterChange, searchFiltersTable, selectedValues],
  );

  const applyAndClose = useCallback(() => {
    onApplySearch?.();
    setOpen(false);
  }, [onApplySearch]);

  // Поле фильтра и поле сортировки могут различаться по типу, но не по
  // значению: колонка сортируется по себе же, когда сервер её умеет.
  const activeSort = sortable
    ? currentSorts.find((s) => (s.field as string) === (field as string))
    : undefined;
  const sortPriority = activeSort ? currentSorts.indexOf(activeSort) + 1 : null;

  // `label` объявлен как `ReactNode`, но у колонок это строка: узел в
  // `aria-label` не превратить, а машинное имя поля оператору ничего не
  // говорит — скринридер читал «Сортировка по productSku» (#204).
  const columnLabel = typeof label === "string" ? label : String(field);
  const sortOrderLabel = activeSort
    ? activeSort.order === "asc"
      ? "по возрастанию"
      : "по убыванию"
    : "не задана";
  const sortPriorityLabel =
    sortPriority !== null && currentSorts.length > 1
      ? `, приоритет ${sortPriority} из ${currentSorts.length}`
      : "";
  const sortAriaLabel = `${columnLabel}, сортировка ${sortOrderLabel}${sortPriorityLabel}`;

  const hasSetFilter = selectedValues.size > 0;
  const hasSearchFilter = searchQuery.trim().length > 0;
  const hasFilter = hasSetFilter || hasSearchFilter;

  const displayLabel = useCallback(
    (v: string) => (valueLabel ? valueLabel(v) : v),
    [valueLabel],
  );

  const filteredValues = useMemo(
    () => sortByPartialSearchMatch(values, searchQuery, displayLabel),
    [values, searchQuery, displayLabel],
  );

  const toggleOne = (value: string) => {
    if (!multiSelect) {
      // Однозначная колонка: повторный клик снимает выбор, иначе выбрать
      // другое значение было бы нельзя.
      onFilterChange(field, selectedValues.has(value) ? new Set() : new Set([value]));
      return;
    }
    const newSelected = new Set(selectedValues);
    if (newSelected.has(value)) {
      newSelected.delete(value);
    } else {
      newSelected.add(value);
    }
    onFilterChange(field, newSelected);
  };

  const selectAll = () => {
    onFilterChange(field, new Set(filteredValues));
  };

  const clearAll = () => {
    onFilterChange(field, new Set());
    setSearchQuery("");
  };

  const handleOpenChange = (nextOpen: boolean) => {
    setOpen(nextOpen);
  };

  const sortIcon =
    activeSort?.order === "asc" ? (
      <IconArrowUp size={14} />
    ) : activeSort?.order === "desc" ? (
      <IconArrowDown size={14} />
    ) : (
      <IconSelector size={14} />
    );

  const filterBadge = hasSearchFilter ? (
    <Search className="h-2.5 w-2.5" aria-hidden />
  ) : hasSetFilter ? (
    String(selectedValues.size)
  ) : null;

  return (
    <div className="inline-flex items-center gap-1 max-w-full">
      {filterable ? (
        <Popover open={open} onOpenChange={handleOpenChange}>
        <PopoverTrigger asChild>
          <button
            type="button"
            className={cn(
              "inline-flex items-center gap-1 text-left font-medium text-xs tracking-normal text-muted-foreground hover:text-foreground transition-colors cursor-pointer select-none min-w-0",
              activeSort && "text-foreground",
            )}
          >
            <span className="truncate">{label}</span>
            <span className="shrink-0">
              {hasFilter && filterBadge && (
                <span
                  className={cn(
                    "inline-flex items-center justify-center h-3.5 min-w-[14px] px-0.5 rounded-full text-[8px] font-bold",
                    hasSearchFilter
                      ? "bg-primary/15 text-primary"
                      : "bg-primary text-primary-foreground",
                  )}
                >
                  {filterBadge}
                </span>
              )}
            </span>
          </button>
        </PopoverTrigger>
        <PopoverContent className="w-56 p-2" align="start" side="bottom">
          <div className="space-y-2">
            <Input
              placeholder="Поиск..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  applyAndClose();
                }
              }}
              className="h-7 text-xs"
              autoFocus
            />
            {searchFiltersTable && hasSearchFilter ? (
              <p className="px-1 text-[10px] text-muted-foreground">
                Список значений скрыт, пока идёт поиск. Сбросить — «Сбросить колонку».
              </p>
            ) : (
              <>
                {multiSelect && (
                  <div className="flex items-center justify-between px-1">
                    <button
                      type="button"
                      onClick={selectAll}
                      className="text-xs text-primary hover:underline"
                    >
                      Выбрать все
                    </button>
                  </div>
                )}
                <div className="max-h-52 overflow-y-auto rounded border">
                  {filteredValues.length === 0 && (
                    <p className="text-xs text-muted-foreground px-2 py-2">Нет значений</p>
                  )}
                  {filteredValues.map((value) => {
                    const isSelected = selectedValues.has(value);
                    return (
                      // Значение — кнопка, а не `div` с `onClick`: только так до
                      // него доходят Tab и Enter/Space, а `aria-pressed`
                      // объявляет скринридеру, выбрано значение или нет (#204).
                      <button
                        key={value}
                        type="button"
                        aria-pressed={isSelected}
                        className={cn(
                          "block w-full px-2 py-1 text-xs text-left cursor-pointer transition-colors truncate",
                          isSelected
                            ? "bg-primary text-primary-foreground"
                            : "hover:bg-accent text-foreground",
                        )}
                        onClick={() => toggleOne(value)}
                      >
                        {displayLabel(value)}
                      </button>
                    );
                  })}
                </div>
              </>
            )}
            <div className="flex justify-end gap-1 pt-1 border-t">
              {hasFilter && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 text-xs"
                  onClick={clearAll}
                >
                  <X className="h-3 w-3 mr-1" />
                  Сбросить колонку
                </Button>
              )}
              <Button
                variant="default"
                size="sm"
                className="h-6 text-xs"
                onClick={applyAndClose}
              >
                Готово
              </Button>
            </div>
          </div>
        </PopoverContent>
        </Popover>
      ) : (
        // Подпись без фильтра — обычный текст: делать её кнопкой без
        // действия незачем, иначе оператор кликает в никуда.
        <span
          className={cn(
            "inline-flex items-center gap-1 text-left font-medium text-xs tracking-normal text-muted-foreground min-w-0",
            activeSort && "text-foreground",
          )}
        >
          <span className="truncate">{label}</span>
        </span>
      )}

      {sortable && (
        <button
          type="button"
          onClick={() => onSortChange(field as unknown as SortField)}
          aria-pressed={activeSort ? "true" : "false"}
          aria-label={sortAriaLabel}
          data-sort-order={activeSort?.order ?? "none"}
          data-sort-priority={sortPriority ?? undefined}
          // Машинное поле — только здесь: `aria-label` выше собирается из
          // подписи колонки, а тесты адресуют кнопку по полю (#204).
          data-sort-field={String(field)}
          className={cn(
            "inline-flex items-center shrink-0 text-muted-foreground hover:text-foreground transition-colors cursor-pointer",
            activeSort && "text-foreground",
          )}
        >
          {sortIcon}
          {sortPriority !== null && (
            <span className="inline-flex items-center justify-center w-4 h-4 rounded-full bg-primary/10 text-[10px] font-semibold text-primary ml-0.5">
              {sortPriority}
            </span>
          )}
        </button>
      )}
    </div>
  );
}
