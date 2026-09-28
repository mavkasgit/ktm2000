import { useMemo, useState } from "react"
import { keepPreviousData, useQuery } from "@tanstack/react-query"
import { Loader2, Search, Users } from "lucide-react"

import {
  DATA_TABLE_STYLES,
  DataTableColumnHeader,
  Input,
  TableCornerResetCell,
  TableCornerResetHeader,
  TablePaginationFooter,
} from "@/shared/ui"
import { useFilterableTable } from "@/shared/hooks/useFilterableTable"
import { usePaginatedTableQuery } from "@/shared/hooks/usePaginatedTableQuery"
import type { SortConfig } from "@/shared/hooks/useTableQueryEngine"
import { buildColumnApiParams } from "@/shared/lib/columnSpecs"
import { useDebouncedValue } from "@/shared/lib/useDebouncedValue"
import { buildSortParam } from "@/shared/lib/sortQueryParam"
import { queryKeys } from "@/shared/api/queryKeys"
import { listEmployees, type Employee, type ListEmployeesParams } from "../api"
import {
  employeeColumns,
  EMPLOYEE_SORT_FIELD_TO_API,
  type EmployeeSortField,
} from "../lib/employeeColumns"

const headerCellClass = `${DATA_TABLE_STYLES.headerRow} ${DATA_TABLE_STYLES.headerCell}`
/**
 * Порядок строк по умолчанию — по имени по возрастанию. Он объявлен хуку, а
 * не подставляется сравнением строк вручную: условие «сортировка
 * нестандартная» расходилось между экранами, а сброс возвращал пустоту вместо
 * этого порядка. Тем же полем сервер сортирует по умолчанию
 * (`_SORT_DEFAULT` в `hrms_employees.py`), поэтому снятая сортировка и пустая
 * строка `sort` дают один и тот же порядок строк.
 */
const DEFAULT_SORT: SortConfig<EmployeeSortField>[] = [{ field: "name", order: "asc" }]

/**
 * Параметры запроса по отфильтрованным колонкам — из описания колонок, а не
 * перечислением: пока здесь стоял один вызов `pickColumnApiValue` с именем
 * `department`, шестая колонка потребовала бы правки этого кода.
 */
function buildEmployeeColumnApiParams(
  columnFilters: Partial<Record<EmployeeSortField, Set<string>>>,
  columnSearchQueries: Partial<Record<EmployeeSortField, string>>,
): Pick<ListEmployeesParams, "department"> {
  return buildColumnApiParams(columnFilters, columnSearchQueries, employeeColumns)
}

export interface HrmsEmployeesTableProps {
  maxHeightClass?: string
  emptyMessage?: string
}

export function HrmsEmployeesTable({
  maxHeightClass = "max-h-[min(50vh,28rem)]",
  emptyMessage = "Кеш пуст. Запустите синхронизацию, чтобы загрузить сотрудников из HRMS.",
}: HrmsEmployeesTableProps) {
  const [search, setSearch] = useState("")
  // Поиск уходит на сервер: без паузы каждый символ — отдельный запрос. В
  // задержке только запрос, само поле отвечает на ввод сразу.
  const debouncedSearch = useDebouncedValue(search);

  const {
    bindColumn,
    columnFilters,
    columnSearchQueries,
    debouncedColumnSearchQueries,
    sortConfigs,
    handleSort,
    resetAll,
    hasActiveFilters: hasTableFiltersActive,
  } = useFilterableTable<EmployeeSortField>({
    defaultSort: DEFAULT_SORT,
    extraHasActive: search.trim().length > 0,
    onExtraReset: () => setSearch(""),
  })


  const columnApiParams = useMemo(
    () => buildEmployeeColumnApiParams(columnFilters, debouncedColumnSearchQueries),
    [columnFilters, debouncedColumnSearchQueries],
  )


  const pagination = usePaginatedTableQuery({
    resetPageDeps: [
      debouncedSearch,
      columnFilters,
      debouncedColumnSearchQueries,
      sortConfigs,
    ],
  })

  const sort = useMemo(
    () => buildSortParam(sortConfigs, (field) => EMPLOYEE_SORT_FIELD_TO_API[field]),
    [sortConfigs],
  )

  const queryParams = useMemo(
    () => ({
      limit: pagination.limit,
      offset: pagination.offset,
      search: debouncedSearch.trim() || undefined,
      sort,
      ...columnApiParams,
    }),
    [
      pagination.limit,
      pagination.offset,
      debouncedSearch,
      sort,
      columnApiParams,
    ],
  )

  // `placeholderData: keepPreviousData` держит дерево на смене параметров: без
  // него гейт загрузки ниже гасит строки и шапку вместе с открытым поповером
  // фильтра, и набранный текст теряется на ровном месте.
  const { data, isPending } = useQuery({
    queryKey: queryKeys.employees.list(queryParams),
    queryFn: () => listEmployees(queryParams),
    placeholderData: keepPreviousData,
  })

  const employees = data?.employees ?? []
  const total = data?.total ?? 0
  const totalPages = pagination.getTotalPages(total)

  /**
   * Значения поповера — только для фильтруемых колонок, и берутся из описания:
   * остальные четыре колонки сервер не фильтрует (см. `employeeColumns`), и
   * список их значений был бы посчитан и ни разу не показан.
   */
  const uniqueValues = useMemo<Partial<Record<EmployeeSortField, string[]>>>(
    () => ({
      department: [...new Set(employees.map((e) => e.department ?? "—"))].sort((a, b) =>
        a.localeCompare(b, "ru"),
      ),
    }),
    [employees],
  )

  if (!isPending && total === 0 && !search.trim() && !hasTableFiltersActive) {
    return (
      <div className="rounded-lg border border-dashed bg-muted/10 px-4 py-10 text-center">
        <Users className="h-8 w-8 text-muted-foreground/40 mx-auto mb-2" />
        <p className="text-sm text-muted-foreground">{emptyMessage}</p>
      </div>
    )
  }

  return (
    <div className="space-y-3 min-h-0 flex flex-col">
      <div className="flex flex-col sm:flex-row sm:items-center gap-2 sm:justify-between">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Поиск по ID, ФИО, табельному, должности..."
            className="pl-9 h-9 bg-card text-sm"
          />
        </div>
        <button
          type="button"
          onClick={resetAll}
          disabled={!hasTableFiltersActive}
          className="text-xs text-muted-foreground hover:text-foreground disabled:opacity-50 shrink-0"
        >
          Сбросить фильтры
        </button>
      </div>

      <div className={`${DATA_TABLE_STYLES.container} ${maxHeightClass}`}>
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr>
              {employeeColumns.map((column) => (
                <th
                  key={column.id}
                  className={`${headerCellClass} ${column.headerClassName ?? "text-left"}`}
                >
                  <DataTableColumnHeader<EmployeeSortField>
                    column={column}
                    bindColumn={bindColumn}
                    values={uniqueValues[column.id]}
                    currentSorts={sortConfigs}
                    onSortChange={handleSort}
                  />
                </th>
              ))}
              <TableCornerResetHeader
                hasActiveFilters={hasTableFiltersActive}
                onReset={resetAll}
                dataTableHeader
              />
            </tr>
          </thead>
          <tbody className="divide-y">
            {isPending && employees.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-sm text-muted-foreground">
                  <Loader2 className="h-5 w-5 animate-spin inline-block mr-2" />
                  Загрузка сотрудников...
                </td>
              </tr>
            ) : employees.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-sm text-muted-foreground">
                  Нет сотрудников по текущим фильтрам
                </td>
              </tr>
            ) : (
              employees.map((employee) => (
                <tr key={employee.id} className="hover:bg-muted/30 transition-colors">
                  <td className="px-4 py-3 text-muted-foreground font-mono text-xs tabular-nums">
                    {employee.hrms_id}
                  </td>
                  <td className="px-4 py-3">
                    <div className="font-medium text-foreground">{employee.name}</div>
                  </td>
                  <td className="px-4 py-3 text-muted-foreground font-mono text-xs">
                    {employee.tab_number ?? "—"}
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">
                    {employee.position ?? "—"}
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">
                    {employee.department ?? "—"}
                  </td>
                  <TableCornerResetCell />
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <TablePaginationFooter
        page={pagination.page}
        totalPages={totalPages}
        total={total}
        shownCount={employees.length}
        limit={pagination.limit}
        onPageChange={pagination.setPage}
        onLimitChange={pagination.setLimit}
        rangeLabel={pagination.getRangeLabel(employees.length, total, { onPage: true })}
      />
    </div>
  )
}
