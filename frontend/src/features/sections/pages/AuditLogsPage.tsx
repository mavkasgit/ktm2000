import { useState, useMemo, Fragment } from "react";
import { Clock } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { getAuditLogs, type AuditLogEntry, type GetAuditLogsParams } from "@/shared/api/auditLogs";
import { queryKeys } from "@/shared/api/queryKeys";
import { DateRangePicker, DataTableColumnHeader, TableCornerResetHeader, TableCornerResetCell, TablePaginationFooter, DATA_TABLE_STYLES, FiltersPanel, JournalTabs, Badge, Button, TABLE_ROW_DENSE, type FiltersPanelField } from "@/shared/ui";
import type { BadgeProps } from "@/shared/ui/badge";
import { useFilterableTable } from "@/shared/hooks/useFilterableTable";
import { usePaginatedTableQuery } from "@/shared/hooks/usePaginatedTableQuery";
import type { SortConfig } from "@/shared/hooks/useTableQueryEngine";
import { buildSortParam } from "@/shared/lib/sortQueryParam";
import { buildColumnApiParams } from "@/shared/lib/columnSpecs";
import { getAriaSort } from "@/shared/lib/multiSort";
import { useDebouncedValue } from "@/shared/lib/useDebouncedValue";
import { keepPreviousData } from "@tanstack/react-query";
import { isFirstRowsLoad } from "@/shared/lib/tableQueryPlaceholder";
import { TABLE_ROW_STYLES } from "@/shared/lib/tableRowStyles";
import { rowToneFill, ROW_TONE_STRIPE, type RowTone } from "@/shared/lib/rowTones";
import { cn } from "@/shared/utils/cn";
import { auditColumns, entityLabel, type AuditFilterField } from "../lib/auditColumns";

type LogFilterField = AuditFilterField;
type LogField = LogFilterField;

type AuditStatus = AuditLogEntry["status"];

/**
 * Статус записи журнала — одним местом в три вида: подпись бейджа, его тон и
 * тон строки. Раньше это были три независимые тернарника в разметке, и
 * подпись («Успешно») жила ещё и в `auditColumns` для попапера фильтра.
 *
 * Тон строки `success` — `ok`, а не `completed`: у `completed` зачёркивание
 * значит «дело закрыто и неактуально», а успешная запись журнала — живое
 * подтверждение, к которому возвращаются. `info` — обычная строка: отметка о
 * ходе работы, а не состояние, требующее внимания.
 */
const STATUS_PRESENTATION: Record<
  AuditStatus,
  { label: string; badgeVariant: BadgeProps["variant"]; rowTone: RowTone }
> = {
  success: { label: "Успешно", badgeVariant: "success", rowTone: "ok" },
  error: { label: "Ошибка", badgeVariant: "destructive", rowTone: "scrap" },
  info: { label: "Информация", badgeVariant: "outline", rowTone: "plain" },
};

function formatDateTime(dateStr: string) {
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return dateStr;
  const date = d.toLocaleDateString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
  const time = d.toLocaleTimeString("ru-RU", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
  return `${date} ${time}`;
}


/**
 * Порядок строк по умолчанию: «сначала свежие». Сервер сортирует по нему,
 * пока оператор не выбрал колонку, и сброс возвращает его, а не пустоту.
 */
const LOG_DEFAULT_SORT: SortConfig<LogFilterField>[] = [{ field: "createdAt", order: "desc" }];


function mapSortFieldToApi(field: LogFilterField): string {
  switch (field) {
    case "createdAt":
      return "created_at";
    case "sectionName":
      return "section_name";
    case "productSku":
      return "product_sku";
    case "entityType":
      return "entity_type";
    default:
      return field;
  }
}

/**
 * Параметры запроса по отфильтрованным колонкам — из описания колонок, а не
 * перечислением: пока здесь стояло пять строк с именами колонок, шестая
 * потребовала бы правки этого кода.
 */
function buildAuditColumnApiParams(
  columnFilters: Partial<Record<AuditFilterField, Set<string>>>,
  columnSearchQueries: Partial<Record<AuditFilterField, string>>,
): Pick<
  GetAuditLogsParams,
  "section_name" | "product_sku" | "action" | "entity_type" | "status"
> {
  return buildColumnApiParams(columnFilters, columnSearchQueries, auditColumns);
}


export function AuditLogsPage() {
  // Поиск и базовые фильтры
  const [search, setSearch] = useState("");
  // Поиск по журналу уходит на сервер: без паузы каждый символ — отдельный
  // запрос. В задержке только запрос, само поле отвечает на ввод сразу.
  const debouncedSearch = useDebouncedValue(search);
  const [statusFilter, setStatusFilter] = useState<"all" | "success" | "error" | "info">("all");
  const [dateFrom, setDateFrom] = useState<string>("");
  const [dateTo, setDateTo] = useState<string>("");

  // Раскрытие строк
  const [expandedRows, setExpandedRows] = useState<Set<number>>(new Set());

  const hasActiveExtraFilters = dateFrom !== "" || dateTo !== "";

  const {
    bindColumn,
    columnFilters,
    columnSearchQueries,
    debouncedColumnSearchQueries,
    sortConfigs,
    handleSort: handleSortChange,
    resetAll,
    hasActiveFilters,
  } = useFilterableTable<LogFilterField>({
    defaultSort: LOG_DEFAULT_SORT,
    extraHasActive:
      search.trim().length > 0 ||
      statusFilter !== "all" ||
      hasActiveExtraFilters,
    onExtraReset: () => {
      setSearch("");
      setStatusFilter("all");
      setDateFrom("");
      setDateTo("");
    },
  });

  // Сортировку можно снять целиком, а сервер по умолчанию сортирует «сначала
  // свежие»: без этой подстановки строки приедут в произвольном порядке.
  // Цикл клика — общий (нет → убыв. → возр. → снять), поэтому третий клик
  // действительно снимает колонку и подстановка вступает в дело. Свой цикл
  // (нет → убыв. → возр. → возр.) этого не давал, и строка была мёртвой
  // веткой: снять сортировку было нечем.
  const effectiveSortConfigs = sortConfigs.length > 0 ? sortConfigs : LOG_DEFAULT_SORT;

  const pagination = usePaginatedTableQuery({
    limitOptions: [50, 100],
    resetPageDeps: [debouncedSearch, statusFilter, dateFrom, dateTo, columnFilters, debouncedColumnSearchQueries, sortConfigs],
  });
  const { page, setPage, limit, setLimit, limitOptions, offset, getTotalPages, getRangeLabel } = pagination;

  const columnApiParams = useMemo(
    () => buildAuditColumnApiParams(columnFilters, debouncedColumnSearchQueries),
    [columnFilters, debouncedColumnSearchQueries],
  );

  const auditQueryParams = useMemo(() => {
    const { status: columnStatus, ...restColumnParams } = columnApiParams;
    return {
      status: statusFilter === "all" ? columnStatus : statusFilter,
      search: debouncedSearch.trim() || undefined,
      date_from: dateFrom ? `${dateFrom}T00:00:00` : undefined,
      date_to: dateTo ? `${dateTo}T23:59:59` : undefined,
      sort: buildSortParam(effectiveSortConfigs, mapSortFieldToApi),
      limit,
      offset,
      ...restColumnParams,
    };
  },
    [
      statusFilter,
      columnApiParams,
      debouncedSearch,
      dateFrom,
      dateTo,
      effectiveSortConfigs,
      limit,
      offset,
    ],
  );

  // `placeholderData: keepPreviousData` держит дерево на смене параметров
  // запроса: без него `isLoading` гасит журнал целиком вместе с открытым
  // поповером фильтра, и оператор теряет набор текста на ровном месте.
  const { data, isPending } = useQuery({
    queryKey: queryKeys.auditLogs.list(auditQueryParams),
    queryFn: () => getAuditLogs(auditQueryParams),
    placeholderData: keepPreviousData,
  });

  const parsedLogs = data?.items || [];
  const total = data?.total || 0;
  const totalPages = getTotalPages(total);
  const counts = data?.counts || { all: 0, success: 0, error: 0, info: 0 };
  const taskStatuses = data?.task_statuses || {};
  const uniqueValues: Partial<Record<AuditFilterField, string[]>> = useMemo(
    () => ({
      status: [...new Set(parsedLogs.map((entry) => entry.status))].sort(),
      sectionName: [...new Set(parsedLogs.map((entry) => entry.section_name || "—"))].sort((a, b) =>
        a.localeCompare(b, "ru"),
      ),
      productSku: [...new Set(parsedLogs.map((entry) => entry.product_sku || "—"))].sort((a, b) =>
        a.localeCompare(b, "ru"),
      ),
      action: [...new Set(parsedLogs.map((entry) => entry.action || "—"))].sort((a, b) =>
        a.localeCompare(b, "ru"),
      ),
      entityType: [
        ...new Set(
          parsedLogs.map((entry) => entityLabel(entry.entity_type, entry.entity_id)),
        ),
      ].sort((a, b) => a.localeCompare(b, "ru")),
    }),
    [parsedLogs],
  );

  const toggleRow = (id: number) => {
    setExpandedRows((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  /**
   * Панель фильтров журнала: поиск → период → четыре переключателя статуса со
   * счётчиками. Раньше это был свой блок на своих классах; тот же ряд на общих
   * полях читается как остальные таблицы приложения, а «Сбросить период» ушёл
   * в общий сброс — отдельная кнопка сбрасывала половину фильтров и оставляла
   * оператора гадать, почему список не тот.
   */
  const filterFields = useMemo((): FiltersPanelField[] => {
    const countOf = (key: string) => Number(counts[key] ?? 0);
    return [
      {
        kind: "search",
        key: "search",
        value: search,
        onChange: setSearch,
        placeholder: "Поиск по сообщениям, операциям, SKU и ID заданий…",
        layoutSpan: "min-w-[280px]",
      },
      {
        kind: "custom",
        key: "date-range",
        node: (
          <DateRangePicker
            from={dateFrom}
            to={dateTo}
            onChange={(range) => {
              setDateFrom(range.from || "");
              setDateTo(range.to || "");
            }}
            placeholder="Выберите период логов"
            align="start"
          />
        ),
        layoutSpan: "min-w-[260px]",
      },
      {
        kind: "toggle",
        key: "status-all",
        label: "Все записи",
        checked: statusFilter === "all",
        onChange: () => setStatusFilter("all"),
        badgeCount: countOf("all"),
        hideIcon: true,
      },
      {
        kind: "toggle",
        key: "status-success",
        label: "Успешные",
        checked: statusFilter === "success",
        onChange: () => setStatusFilter("success"),
        badgeCount: countOf("success"),
        tone: "emerald",
        hideIcon: true,
      },
      {
        kind: "toggle",
        key: "status-error",
        label: "Ошибки",
        checked: statusFilter === "error",
        onChange: () => setStatusFilter("error"),
        badgeCount: countOf("error"),
        tone: "red",
        hideIcon: true,
      },
      {
        kind: "toggle",
        key: "status-info",
        label: "Инфо",
        checked: statusFilter === "info",
        onChange: () => setStatusFilter("info"),
        badgeCount: countOf("info"),
        tone: "neutral",
        hideIcon: true,
      },
    ];
  }, [search, dateFrom, dateTo, statusFilter, counts]);

  /** Шапка таблицы — плотная, как тело: 32px обе. */
  const headerCellClass = cn(DATA_TABLE_STYLES.headerRow, DATA_TABLE_STYLES.headerCell, TABLE_ROW_DENSE.headerCell);

  /** Число колонок журнала + служебный угол сброса — для строк `colSpan`. */
  const columnCount = auditColumns.length + 1;

  return (
    <div className="space-y-3">
      <header className="page-header">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="page-title">Журнал действий</h1>
            <span className="bg-slate-100 text-slate-650 text-xs font-bold px-2 py-0.5 rounded-full">
              {counts.all}
            </span>
          </div>
          <p className="page-subtitle">
            Централизованный лог действий. Поддерживается мгновенный поиск по тексту сообщений, названию операций, SKU и ID заданий.
          </p>
          <div className="mt-3">
            <JournalTabs />
          </div>
        </div>
      </header>

      <FiltersPanel
        compact
        fields={filterFields}
        onReset={resetAll}
        hasActiveFilters={hasActiveFilters}
      />
      {/* Таблица. Пусто и загрузка — строками `tbody`: колонки журнала заданы
          описанием, и поплавок над таблицей убирал бы шапку целиком. */}
      <div className={DATA_TABLE_STYLES.container}>
        <table className="w-full border-separate border-spacing-0 text-sm">
          <thead>
            <tr>
              {auditColumns.map((column) => (
                <th
                  key={column.id}
                  className={`${headerCellClass} ${column.headerClassName ?? "text-left"}`}
                  aria-sort={column.sortField ? getAriaSort(sortConfigs, column.sortField) : undefined}
                >
                  <DataTableColumnHeader
                    column={column}
                    bindColumn={bindColumn}
                    values={column.filterField ? uniqueValues[column.filterField] : undefined}
                    currentSorts={sortConfigs}
                    onSortChange={handleSortChange}
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
          <tbody>
            {isFirstRowsLoad(isPending, parsedLogs) ? (
              <tr>
                <td colSpan={columnCount} className={cn(TABLE_ROW_DENSE.cell, "text-center text-slate-400")}>
                  Загрузка журнала аудита...
                </td>
              </tr>
            ) : parsedLogs.length === 0 ? (
              <tr>
                <td colSpan={columnCount} className={cn(TABLE_ROW_DENSE.cell, "py-10 text-center")}>
                  <div className="flex flex-col items-center justify-center text-center">
                    <div className="h-14 w-14 rounded-full bg-slate-100 flex items-center justify-center text-slate-400 mb-4">
                      <Clock className="h-7 w-7" />
                    </div>
                    <p className="text-slate-600 font-semibold text-sm">Логи не найдены</p>
                    {/* Два разных текста: «пусто» и «ничего не подошло» отвечают
                        на разные вопросы, и подмена одного другим сбивала бы с толку. */}
                    <p className="text-xs text-slate-400 mt-1.5 max-w-sm px-4">
                      {counts.all === 0
                        ? "История событий пуста."
                        : "Нет записей, соответствующих заданным фильтрам и поисковому запросу."}
                    </p>
                  </div>
                </td>
              </tr>
            ) : (
              parsedLogs.map((entry) => {
                const status = STATUS_PRESENTATION[entry.status];
                const isExpanded = expandedRows.has(entry.id);
                const taskIdsArray = entry.task_ids
                  ? entry.task_ids.split(",").map((id) => Number(id.trim())).filter((id) => !isNaN(id))
                  : [];

                return (
                  <Fragment key={entry.id}>
                    <tr
                      data-testid={`audit-row-${entry.id}`}
                      style={{ height: TABLE_ROW_DENSE.rowHeightPx }}
                      className={cn(rowToneFill(status.rowTone), TABLE_ROW_STYLES.defaultRow, "cursor-pointer")}
                      onClick={() => toggleRow(entry.id)}
                    >
                      {/* Статус — бейджем: кружок-иконка 28px в строку 32px не
                          влезал, а без подписи журнал читался по одному цвету. */}
                      {/* Полоса тона — на этой же ячейке: таблица на
                          `border-separate`, границы строк в ней не рисуются,
                          и на `<tr>` полоса была бы не видна. */}
                      <td className={cn(TABLE_ROW_DENSE.cell, ROW_TONE_STRIPE[status.rowTone], "align-middle")}>
                        <Badge variant={status.badgeVariant} className={TABLE_ROW_DENSE.badge}>
                          {status.label}
                        </Badge>
                      </td>

                      {/* Время */}
                      <td className={cn(TABLE_ROW_DENSE.cell, "align-middle font-mono text-xs text-slate-500")}>
                        {formatDateTime(entry.created_at)}
                      </td>

                      {/* Участок */}
                      <td className={cn(TABLE_ROW_DENSE.cell, "align-middle truncate")}>
                        {entry.section_name ? (
                          <span
                            className="inline-flex items-center rounded-md px-2 py-0.5 text-xs font-semibold bg-slate-100 text-slate-700 border border-slate-200/60 max-w-full truncate"
                            title={entry.section_name}
                          >
                            {entry.section_name}
                          </span>
                        ) : (
                          <span className="text-slate-400">—</span>
                        )}
                      </td>

                      {/* Задания */}
                      <td className={cn(TABLE_ROW_DENSE.cell, "align-middle truncate")}>
                        {taskIdsArray.length > 0 ? (
                          <div className="flex flex-wrap gap-1">
                            {taskIdsArray.map((id) => {
                              const isDeleted = taskStatuses[id] === "deleted";
                              return (
                                <span
                                  key={id}
                                  className={`px-1.5 py-0.5 rounded text-[10.5px] border font-mono ${
                                    isDeleted
                                      ? "bg-red-50 border-red-200 text-red-600 line-through font-normal opacity-85"
                                      : "bg-slate-50 border-slate-200 text-slate-600"
                                  }`}
                                  title={isDeleted ? "Задание удалено и неактуально" : undefined}
                                >
                                  #{id}
                                </span>
                              );
                            })}
                          </div>
                        ) : (
                          <span className="text-slate-400">—</span>
                        )}
                      </td>

                      {/* SKU */}
                      <td className={cn(TABLE_ROW_DENSE.cell, "align-middle truncate font-mono text-xs text-slate-600")}>
                        {entry.product_sku || <span className="text-slate-400">—</span>}
                      </td>

                      {/* Действие (action) */}
                      <td className={cn(TABLE_ROW_DENSE.cell, "align-middle truncate")}>
                        {entry.action ? (
                          <span className="px-1.5 py-0.5 rounded bg-indigo-50 border border-indigo-100 text-indigo-700 text-[10px] uppercase truncate inline-block max-w-full align-middle">
                            {entry.action}
                          </span>
                        ) : (
                          <span className="text-slate-400">—</span>
                        )}
                      </td>

                      {/* Сущность (entity_type) */}
                      <td className={cn(TABLE_ROW_DENSE.cell, "align-middle truncate text-xs text-slate-600")}>
                        {entry.entity_type ? (
                          <span title={entityLabel(entry.entity_type, entry.entity_id)}>
                            {entityLabel(entry.entity_type, entry.entity_id)}
                          </span>
                        ) : (
                          <span className="text-slate-400">—</span>
                        )}
                      </td>

                      {/* Описание / действия */}
                      <td className={cn(TABLE_ROW_DENSE.cell, "align-middle relative")}>
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-slate-500 text-xs truncate" title={`${entry.title}: ${entry.message}`}>
                            {entry.title}: {entry.message}
                          </span>
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            className={cn(TABLE_ROW_DENSE.actionButton, "shrink-0")}
                            onClick={(e) => {
                              e.stopPropagation();
                              toggleRow(entry.id);
                            }}
                          >
                            {isExpanded ? "Скрыть" : "Подробнее"}
                          </Button>
                        </div>
                      </td>
                      <TableCornerResetCell />
                    </tr>

                    {/* Детали раскрытой строки: высота по содержимому, а основная
                        строка при этом остаётся 32px. */}
                    {isExpanded && (
                      <tr data-testid={`audit-detail-row-${entry.id}`} className="bg-muted/30">
                        <td colSpan={columnCount} className="border-b border-slate-200 p-4">
                          <div className="space-y-3 text-xs text-slate-700">
                            <div className="flex items-center justify-between border-b border-slate-100 pb-2 mb-1">
                              <span className="text-sm text-slate-800">Детали события: {entry.title}</span>
                              <span className="text-slate-400 font-mono text-[10px]">ID: {entry.id}</span>
                            </div>
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                              <div className="space-y-3">
                                <div>
                                  <p className="text-slate-400 uppercase font-bold text-[9px] tracking-wider">Полное сообщение</p>
                                  <p className="whitespace-pre-wrap leading-relaxed text-slate-700 bg-muted/30 p-2.5 rounded border border-slate-100">{entry.message}</p>
                                </div>
                                {entry.changes && (
                                  <div>
                                    <p className="text-slate-400 uppercase font-bold text-[9px] tracking-wider mb-1">Изменения полей (дифф)</p>
                                    <div className="bg-muted/30 border border-slate-100 rounded p-2.5 space-y-1.5 font-mono text-[11px] text-slate-700">
                                      <div className="grid grid-cols-3 font-bold border-b border-slate-200/60 pb-1 text-[9px] uppercase tracking-wider text-slate-400">
                                        <span>Поле</span>
                                        <span>Было</span>
                                        <span>Стало</span>
                                      </div>
                                      {Object.keys({ ...(entry.changes.before || {}), ...(entry.changes.after || {}) }).map((key) => {
                                        const valBefore = entry.changes?.before?.[key] !== undefined ? String(entry.changes.before[key]) : "—";
                                        const valAfter = entry.changes?.after?.[key] !== undefined ? String(entry.changes.after[key]) : "—";
                                        return (
                                          <div key={key} className="grid grid-cols-3 py-0.5 border-b border-slate-100/60 last:border-0 items-center">
                                            <span className="text-slate-600 truncate pr-1" title={key}>{key}</span>
                                            <span className="text-red-650 bg-red-50 px-1 rounded truncate mr-1" title={valBefore}>{valBefore}</span>
                                            <span className="text-emerald-700 bg-emerald-50 px-1 rounded truncate" title={valAfter}>{valAfter}</span>
                                          </div>
                                        );
                                      })}
                                    </div>
                                  </div>
                                )}
                              </div>
                              <div className="space-y-3 md:border-l md:border-slate-100 md:pl-4">
                                <div className="grid grid-cols-2 gap-2">
                                  <div>
                                    <p className="text-slate-400 uppercase font-bold text-[9px] tracking-wider">Сущность</p>
                                    <p className="text-slate-700 bg-muted/30 p-2 rounded border border-slate-100 mt-1">
                                      {entityLabel(entry.entity_type, entry.entity_id)}
                                    </p>
                                  </div>
                                  <div>
                                    <p className="text-slate-400 uppercase font-bold text-[9px] tracking-wider">Действие</p>
                                    <p className="text-slate-700 bg-muted/30 p-2 rounded border border-slate-100 mt-1">
                                      {entry.action || "—"}
                                    </p>
                                  </div>
                                </div>
                                <div>
                                  <p className="text-slate-400 uppercase font-bold text-[9px] tracking-wider">Пользователь</p>
                                  <p className="text-slate-700 bg-muted/30 p-2 rounded border border-slate-100 mt-1">👤 {entry.user_name || "—"}</p>
                                </div>
                                {entry.comment && (
                                  <div>
                                    <p className="text-slate-400 uppercase font-bold text-[9px] tracking-wider">Комментарий исполнителя</p>
                                    <p className="text-slate-700 italic bg-muted/30 p-2.5 rounded border border-slate-100 mt-1">💬 {entry.comment}</p>
                                  </div>
                                )}
                                {entry.error_details && (
                                  <div>
                                    <p className="text-slate-400 uppercase font-bold text-[9px] tracking-wider">Сведения об ошибке</p>
                                    <p className="text-red-600 bg-red-50/40 p-2.5 rounded border border-red-100 mt-1">⚠️ {entry.error_details}</p>
                                  </div>
                                )}
                              </div>
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      <TablePaginationFooter
        page={page}
        totalPages={totalPages}
        total={total}
        shownCount={parsedLogs.length}
        limit={limit}
        limitOptions={[...limitOptions]}
        onPageChange={setPage}
        onLimitChange={setLimit}
        rangeLabel={getRangeLabel(parsedLogs.length, total)}
      />
    </div>
  );
}