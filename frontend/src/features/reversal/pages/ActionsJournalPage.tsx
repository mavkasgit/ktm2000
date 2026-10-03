import { useMemo } from "react";
import { useInRouterContext } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import {
  AMENDABLE_ACTION_TYPES,
  type ActionStatus,
  type GetActionsParams,
  type JournalAction,
} from "@/shared/api/actions";
import { invalidateAfter } from "@/shared/api/cacheInvalidation";
import {
  BackButton,
  Badge,
  buildActiveFilterSummary,
  DATA_TABLE_STYLES,
  DataTableColumnHeader,
  FiltersPanel,
  JournalTabs,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  TableCornerResetCell,
  TableCornerResetHeader,
  TablePaginationFooter,
  TABLE_ROW_DENSE,
  type FiltersPanelField,
} from "@/shared/ui";
import { useFilterableTable } from "@/shared/hooks/useFilterableTable";
import { usePaginatedTableQuery } from "@/shared/hooks/usePaginatedTableQuery";
import { buildColumnApiParams } from "@/shared/lib/columnSpecs";
import { ROW_TONE_STRIPE, ROW_TONE_TEXT, rowToneFill } from "@/shared/lib/rowTones";
import { cn } from "@/shared/utils/cn";
import { useActionsList } from "../hooks/useActions";
import { JournalRowOperations } from "../components/JournalRowOperations";
import {
  actionColumns,
  actionTypeLabel,
  getActionTone,
  statusBadge,
  statusLabel,
  type ActionFilterField,
} from "../lib/actionColumns";

/**
 * Значения фильтра статуса: сервер их понимает все четыре, а страница не
 * должна показывать оператору только те, что попались на текущей странице.
 */
const ALL_STATUSES = ["active", "reversed", "amended", "purged"] as const;

function formatDateTime(value: string | null) {
  if (!value) return "—";
  const d = new Date(value);
  if (isNaN(d.getTime())) return value;
  return d.toLocaleString("ru-RU");
}

/**
 * Параметры запроса по отфильтрованным колонкам — из описания колонок, а не
 * перечислением: пока здесь стояло два имени колонок строкой, третья потребовала
 * бы правки этого кода.
 */
function buildActionsApiParams(
  columnFilters: Partial<Record<ActionFilterField, Set<string>>>,
  columnSearchQueries: Partial<Record<ActionFilterField, string>>,
): Pick<GetActionsParams, "action_type" | "status"> {
  const params = buildColumnApiParams(columnFilters, columnSearchQueries, actionColumns);
  return {
    action_type: params.action_type ?? null,
    status: (params.status as ActionStatus | undefined) ?? null,
  };
}

export function ActionsJournalPage() {
  const {
    bindColumn,
    columnFilters,
    columnSearchQueries,
    debouncedColumnSearchQueries,
    onColumnFilterChange,
    resetAll,
    hasActiveFilters,
  } = useFilterableTable<ActionFilterField>();

  const { page, setPage, limit, setLimit, limitOptions, getTotalPages, getRangeLabel } =
    usePaginatedTableQuery({
      resetPageDeps: [debouncedColumnSearchQueries],
    });
  const queryClient = useQueryClient();
  // `BackButton` зовёт `useNavigate`, который вне контекста роутера бросает
  // инвариант: в unit-тестах страницы роутера нет, а проверять там нечего.
  const inRouter = useInRouterContext();

  const { data, isLoading } = useActionsList({
    page,
    page_size: limit,
    ...buildActionsApiParams(columnFilters, debouncedColumnSearchQueries),
  });

  const items = data?.items ?? [];
  const total = data?.total ?? 0;

  const refresh = () => {
    // Домен `actions` покрывает и список журнала, и деревья цепочки —
    // точечный сброс ключа дерева не нужен.
    void invalidateAfter(queryClient, "actionReversed");
  };

  // Известные типы действий: текущая страница + базовый набор. Страница журнала
  // показывает все четыре статуса, а не только попавшиеся в выборку: иначе
  // фильтр предлагал бы оператору пустой список на второй странице.
  const knownTypes = useMemo(
    () =>
      Array.from(
        new Set([
          ...AMENDABLE_ACTION_TYPES,
          ...items.map((i: JournalAction) => i.action_type),
        ]),
      ).sort(),
    [items],
  );

  /**
   * Один выбор — один набор: панель пишет в то же состояние, что и попаперы
   * шапки, поэтому «тип действия» из панели и из шапки не могут разойтись, а
   * угол сброса в шапке гасит оба сразу.
   */
  const setSingleFilter = (field: ActionFilterField) => (value: string) =>
    onColumnFilterChange(field, value === "all" ? new Set() : new Set([value]));

  const typeFilterValue = [...(columnFilters.actionType ?? new Set())][0] ?? "all";
  const statusFilterValue = [...(columnFilters.status ?? new Set())][0] ?? "all";

  const filterFields: FiltersPanelField[] = [
    {
      // `FiltersPanel` не умеет `data-testid` в поле `select`, а на этом экране
      // их держат тесты: узел собственного `Select` в общем ряду панели.
      kind: "custom",
      key: "type",
      layoutSpan: "min-w-[200px] flex-shrink-0",
      node: (
        <Select value={typeFilterValue} onValueChange={setSingleFilter("actionType")}>
          <SelectTrigger className="h-9 w-full" data-testid="filter-type">
            <SelectValue placeholder="Тип действия" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Все типы</SelectItem>
            {knownTypes.map((t) => (
              <SelectItem key={t} value={t}>
                {actionTypeLabel(t)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      ),
    },
    {
      kind: "custom",
      key: "status",
      layoutSpan: "min-w-[180px] flex-shrink-0",
      node: (
        <Select value={statusFilterValue} onValueChange={setSingleFilter("status")}>
          <SelectTrigger className="h-9 w-full" data-testid="filter-status">
            <SelectValue placeholder="Статус" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Все статусы</SelectItem>
            {ALL_STATUSES.map((s) => (
              <SelectItem key={s} value={s}>
                {statusLabel(s)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      ),
    },
  ];

  const activeSummary = buildActiveFilterSummary("", 0, {
    columnFilters,
    columnSearchQueries,
    columnLabels: { actionType: "Действие", status: "Статус" },
  });

  const headerCellClass = cn(
    DATA_TABLE_STYLES.headerRow,
    DATA_TABLE_STYLES.headerCell,
    TABLE_ROW_DENSE.headerCell,
  );

  // Значения попаперов — из текущей страницы: список фильтра показывает то,
  // что сервер уже отдал, иначе он врал бы про наличие таких действий.
  const columnValues = useMemo(
    () => ({
      actionType: knownTypes,
      status: [...ALL_STATUSES],
    }),
    [knownTypes],
  );

  return (
    <div className="space-y-6" data-testid="actions-journal-page">
      <header className="page-header">
        <div className="flex items-start gap-2">
          {inRouter && <BackButton to="/audit-logs" title="К журналу действий" />}
          <div>
            <h1 className="page-title">Отмена действий</h1>
            <p className="page-subtitle">Журнал обратимых операций (ADR-0019)</p>
            <div className="mt-3">
              <JournalTabs />
            </div>
          </div>
        </div>
      </header>

      <FiltersPanel
        compact
        fields={filterFields}
        onReset={resetAll}
        hasActiveFilters={hasActiveFilters}
        activeSummary={activeSummary}
      />

      <div className={cn(DATA_TABLE_STYLES.container, "bg-white")}>
        <table className="w-full border-separate border-spacing-0 text-sm">
          <thead>
            <tr>
              {actionColumns.map((column) => (
                <th
                  key={column.id}
                  className={cn(headerCellClass, column.headerClassName)}
                >
                  <DataTableColumnHeader
                    column={column}
                    bindColumn={bindColumn}
                    values={column.filterField ? columnValues[column.filterField] : undefined}
                  />
                </th>
              ))}
              <TableCornerResetHeader
                hasActiveFilters={hasActiveFilters}
                onReset={resetAll}
                dataTableHeader
              />
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {isLoading && items.length === 0 ? (
              <tr>
                <td
                  colSpan={actionColumns.length + 1}
                  className={cn(TABLE_ROW_DENSE.cell, "py-6 text-center text-sm text-muted-foreground")}
                >
                  Загрузка…
                </td>
              </tr>
            ) : items.length === 0 ? (
              <tr>
                <td
                  colSpan={actionColumns.length + 1}
                  className={cn(TABLE_ROW_DENSE.cell, "py-6 text-center text-sm text-muted-foreground")}
                >
                  Действия не найдены
                </td>
              </tr>
            ) : (
              items.map((action: JournalAction) => {
                const tone = getActionTone(action.status);
                const badge = statusBadge(action.status);
                return (
                  <tr
                    key={action.id}
                    data-testid={`action-row-${action.id}`}
                    style={{ height: TABLE_ROW_DENSE.rowHeightPx }}
                    className={cn(rowToneFill(tone), ROW_TONE_TEXT[tone], "transition-colors")}
                  >
                    <td className={cn(TABLE_ROW_DENSE.cell, ROW_TONE_STRIPE[tone], "font-mono text-xs")}>
                      {action.id}
                    </td>
                    <td className={cn(TABLE_ROW_DENSE.cell, "font-medium")}>
                      {actionTypeLabel(action.action_type)}
                    </td>
                    <td className={cn(TABLE_ROW_DENSE.cell, "font-mono text-xs text-muted-foreground")}>
                      {action.ref_id != null ? `#${action.ref_id}` : "—"}
                    </td>
                    <td className={cn(TABLE_ROW_DENSE.cell, "text-xs")}>
                      {action.actor ?? "—"}
                    </td>
                    <td className={TABLE_ROW_DENSE.cell}>
                      <Badge className={TABLE_ROW_DENSE.badge} variant={badge.variant}>
                        {badge.label}
                      </Badge>
                    </td>
                    <td
                      className={cn(
                        TABLE_ROW_DENSE.cell,
                        "whitespace-nowrap text-xs text-muted-foreground",
                      )}
                    >
                      {formatDateTime(action.created_at)}
                    </td>
                    <td className={cn(TABLE_ROW_DENSE.cell, "text-right")}>
                      <JournalRowOperations action={action} onChanged={refresh} />
                    </td>
                    <TableCornerResetCell />
                  </tr>
                );
              })
            )}
          </tbody>
        </table>

        <TablePaginationFooter
          page={page}
          totalPages={getTotalPages(total)}
          total={total}
          shownCount={items.length}
          limit={limit}
          limitOptions={[...limitOptions]}
          onPageChange={setPage}
          onLimitChange={setLimit}
          rangeLabel={getRangeLabel(items.length, total)}
        />
      </div>
    </div>
  );
}
