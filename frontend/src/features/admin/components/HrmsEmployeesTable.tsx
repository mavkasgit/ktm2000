import { useMemo, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { Loader2, Search, Users } from "lucide-react"

import {
  DATA_TABLE_STYLES,
  Input,
  SortableFilterHeader,
  TableCornerResetCell,
  TableCornerResetHeader,
  TablePaginationFooter,
} from "@/shared/ui"
import { useFilterableTable } from "@/shared/hooks/useFilterableTable"
import { usePaginatedTableQuery } from "@/shared/hooks/usePaginatedTableQuery"
import { pickColumnApiValue } from "@/shared/lib/columnFilterSearch"
import { queryKeys } from "@/shared/api/queryKeys"
import { listEmployees, type Employee } from "../api"

export type EmployeeSortField = "hrmsId" | "name" | "tabNumber" | "position" | "department"

const headerCellClass = `${DATA_TABLE_STYLES.headerRow} ${DATA_TABLE_STYLES.headerCell}`

function mapSortFieldToApi(field: EmployeeSortField): string {
  switch (field) {
    case "hrmsId":
      return "hrms_id"
    case "tabNumber":
      return "tab_number"
    default:
      return field
  }
}

function buildColumnApiParams(
  columnFilters: Partial<Record<EmployeeSortField, Set<string>>>,
  columnSearchQueries: Partial<Record<EmployeeSortField, string>>,
): { department?: string } {
  const params: { department?: string } = {}

  const department = pickColumnApiValue(columnFilters, columnSearchQueries, "department", (value) =>
    value === "—" ? undefined : value,
  )
  if (department) params.department = department

  return params
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

  const {
    bindColumn,
    columnFilters,
    columnSearchQueries,
    sortConfigs,
    handleSort,
    resetAll,
    hasActiveFilters: hasTableFiltersActive,
  } = useFilterableTable<EmployeeSortField>({
    extraHasActive: search.trim().length > 0,
    onExtraReset: () => setSearch(""),
  })

  const columnApiParams = useMemo(
    () => buildColumnApiParams(columnFilters, columnSearchQueries),
    [columnFilters, columnSearchQueries],
  )

  const pagination = usePaginatedTableQuery({
    resetPageDeps: [
      search,
      columnFilters,
      columnSearchQueries,
      sortConfigs,
    ],
  })

  const activeSort = sortConfigs[0]
  const queryParams = useMemo(
    () => ({
      limit: pagination.limit,
      offset: pagination.offset,
      search: search.trim() || undefined,
      sort_by: activeSort ? mapSortFieldToApi(activeSort.field) : "name",
      sort_order: activeSort?.order ?? "asc",
      ...columnApiParams,
    }),
    [
      pagination.limit,
      pagination.offset,
      search,
      activeSort,
      columnApiParams,
    ],
  )

  const { data, isLoading } = useQuery({
    queryKey: queryKeys.employees.list(queryParams),
    queryFn: () => listEmployees(queryParams),
  })

  const employees = data?.employees ?? []
  const total = data?.total ?? 0
  const totalPages = pagination.getTotalPages(total)

  const uniqueValues = useMemo(
    () => ({
      hrmsId: [...new Set(employees.map((e) => String(e.hrms_id)))].sort((a, b) =>
        Number(a) - Number(b),
      ),
      name: [...new Set(employees.map((e) => e.name))].sort((a, b) =>
        a.localeCompare(b, "ru"),
      ),
      tabNumber: [...new Set(employees.map((e) => e.tab_number ?? "—"))].sort((a, b) =>
        a.localeCompare(b, "ru"),
      ),
      position: [...new Set(employees.map((e) => e.position ?? "—"))].sort((a, b) =>
        a.localeCompare(b, "ru"),
      ),
      department: [...new Set(employees.map((e) => e.department ?? "—"))].sort((a, b) =>
        a.localeCompare(b, "ru"),
      ),
    }),
    [employees],
  )

  if (!isLoading && total === 0 && !search.trim() && !hasTableFiltersActive) {
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
              <th className={`${headerCellClass} p-0 px-4 text-left w-24`}>
                <SortableFilterHeader<EmployeeSortField>
                  field="hrmsId"
                  label="HRMS ID"
                  currentSorts={sortConfigs}
                  onSortChange={handleSort}
                  values={uniqueValues.hrmsId}
                  {...bindColumn("hrmsId")}
                />
              </th>
              <th className={`${headerCellClass} p-0 px-4 text-left`}>
                <SortableFilterHeader<EmployeeSortField>
                  field="name"
                  label="ФИО"
                  currentSorts={sortConfigs}
                  onSortChange={handleSort}
                  values={uniqueValues.name}
                  {...bindColumn("name")}
                />
              </th>
              <th className={`${headerCellClass} p-0 px-4 text-left w-28`}>
                <SortableFilterHeader<EmployeeSortField>
                  field="tabNumber"
                  label="Таб. №"
                  currentSorts={sortConfigs}
                  onSortChange={handleSort}
                  values={uniqueValues.tabNumber}
                  {...bindColumn("tabNumber")}
                />
              </th>
              <th className={`${headerCellClass} p-0 px-4 text-left`}>
                <SortableFilterHeader<EmployeeSortField>
                  field="position"
                  label="Должность"
                  currentSorts={sortConfigs}
                  onSortChange={handleSort}
                  values={uniqueValues.position}
                  {...bindColumn("position")}
                />
              </th>
              <th className={`${headerCellClass} p-0 px-4 text-left`}>
                <SortableFilterHeader<EmployeeSortField>
                  field="department"
                  label="Подразделение"
                  currentSorts={sortConfigs}
                  onSortChange={handleSort}
                  values={uniqueValues.department}
                  {...bindColumn("department")}
                />
              </th>
              <TableCornerResetHeader
                hasActiveFilters={hasTableFiltersActive}
                onReset={resetAll}
                dataTableHeader
              />
            </tr>
          </thead>
          <tbody className="divide-y">
            {isLoading ? (
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
