import { useState, useMemo, Fragment, useEffect } from "react";
import {
  CheckCircle2,
  AlertCircle,
  Info,
  Search,
  X,
  Clock,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { getAuditLogs, type AuditLogEntry, type GetAuditLogsParams } from "@/shared/api/auditLogs";
import { queryKeys } from "@/shared/api/queryKeys";
import { pickColumnApiValue } from "@/shared/lib/columnFilterSearch";
import { SectionSelect, SortableFilterHeader, TableCornerResetCell, TableCornerResetHeader, DATA_TABLE_STYLES } from "@/shared/ui";
import type { Section } from "@/shared/api/sections";
import { listSections } from "@/shared/api/sections";
import { useFilterableTable } from "@/shared/hooks/useFilterableTable";

interface SessionLogModalProps {
  open: boolean;
  onClose: () => void;
  defaultSectionId?: number;
  sections?: Section[];
}

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

function highlightText(text: string, search: string) {
  if (!search.trim()) return text;
  const regex = new RegExp(`(${search.replace(/[-\/\\^$*+?.()|[\]{}]/g, "\\$&")})`, "gi");
  const parts = text.split(regex);
  return (
    <>
      {parts.map((part, i) =>
        regex.test(part) ? (
          <mark key={i} className="bg-amber-100 text-amber-950 px-0.5 rounded">
            {part}
          </mark>
        ) : (
          part
        )
      )}
    </>
  );
}

type LogField = "status" | "createdAt" | "sectionName" | "productSku" | "taskIds" | "operationName" | "qtyText";
type LogFilterField = "status" | "createdAt" | "sectionName" | "productSku" | "taskIds" | "operationName" | "qtyText";

function mapSortFieldToApi(field: LogFilterField): string {
  switch (field) {
    case "createdAt":
      return "created_at";
    case "sectionName":
      return "section_name";
    case "productSku":
      return "product_sku";
    case "operationName":
      return "operation_name";
    case "qtyText":
      return "qty_text";
    default:
      return field;
  }
}

function buildSessionColumnApiParams(
  columnFilters: Partial<Record<LogFilterField, Set<string>>>,
  columnSearchQueries: Partial<Record<LogFilterField, string>>,
): Pick<GetAuditLogsParams, "section_name" | "product_sku" | "status"> {
  const params: Pick<GetAuditLogsParams, "section_name" | "product_sku" | "status"> = {};

  const sectionName = pickColumnApiValue(columnFilters, columnSearchQueries, "sectionName", (v) =>
    v === "—" ? undefined : v,
  );
  if (sectionName) params.section_name = sectionName;

  const productSku = pickColumnApiValue(columnFilters, columnSearchQueries, "productSku", (v) =>
    v === "—" ? undefined : v,
  );
  if (productSku) params.product_sku = productSku;

  const status = pickColumnApiValue(columnFilters, columnSearchQueries, "status");
  if (status) params.status = status;

  return params;
}

export function SessionLogModal({
  open,
  onClose,
  defaultSectionId,
  sections,
}: SessionLogModalProps) {
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | "success" | "error" | "info">("all");
  const [selectedSectionId, setSelectedSectionId] = useState<string>(
    defaultSectionId ? String(defaultSectionId) : "all"
  );
  
  // Синхронизация выбранного участка с внешними пропсами при их изменении
  useEffect(() => {
    setSelectedSectionId(defaultSectionId ? String(defaultSectionId) : "all");
  }, [defaultSectionId]);

  const [page, setPage] = useState(1);
  const limit = 50;
  const offset = (page - 1) * limit;

  const {
    bindColumn,
    columnFilters,
    columnSearchQueries,
    sortConfigs,
    setSortConfigs,
    hasActiveColumnFilters,
    resetAll,
  } = useFilterableTable<LogFilterField, LogField>({
    extraHasActive: search.trim().length > 0 || statusFilter !== "all",
    onExtraReset: () => {
      setSearch("");
      setStatusFilter("all");
      setSortConfigs([{ field: "createdAt", order: "desc" }]);
    },
  });

  useEffect(() => {
    if (open) {
      setSortConfigs([{ field: "createdAt", order: "desc" }]);
    }
  }, [open, setSortConfigs]);

  const sortIsNonDefault =
    sortConfigs.length !== 1 ||
    sortConfigs[0]?.field !== "createdAt" ||
    sortConfigs[0]?.order !== "desc";

  const hasActiveFilters =
    search.trim().length > 0 ||
    statusFilter !== "all" ||
    hasActiveColumnFilters ||
    sortIsNonDefault;

  const handleResetFilters = resetAll;

  // Состояние раскрытых строк
  const [expandedRows, setExpandedRows] = useState<Set<number>>(new Set());

  const activeSort = sortConfigs[0] ?? { field: "createdAt" as LogFilterField, order: "desc" as const };

  const columnApiParams = useMemo(
    () => buildSessionColumnApiParams(columnFilters, columnSearchQueries),
    [columnFilters, columnSearchQueries],
  );

  // Сброс страницы при изменении фильтров
  useEffect(() => {
    setPage(1);
  }, [search, statusFilter, selectedSectionId, columnFilters, columnSearchQueries, sortConfigs]);

  // Запрос списка участков, если они не переданы
  const { data: queriedSections } = useQuery({
    queryKey: ["sections"],
    queryFn: listSections,
    enabled: open && !sections,
  });

  const auditQueryParams = useMemo(() => {
    const { status: columnStatus, ...restColumnParams } = columnApiParams;
    return {
      section_id: selectedSectionId === "all" ? undefined : Number(selectedSectionId),
      status: statusFilter === "all" ? columnStatus : statusFilter,
      search: search.trim() || undefined,
      sort_by: mapSortFieldToApi(activeSort.field),
      sort_order: activeSort.order,
      limit,
      offset,
      ...restColumnParams,
    };
  }, [
    selectedSectionId,
    statusFilter,
    columnApiParams,
    search,
    activeSort.field,
    activeSort.order,
    limit,
    offset,
  ]);

  // Запрос логов аудита с бэкенда
  const { data, isLoading } = useQuery({
    queryKey: queryKeys.auditLogs.list(auditQueryParams),
    queryFn: () => getAuditLogs(auditQueryParams),
    enabled: open,
  });

  const parsedLogs = data?.items ?? [];

  const total = data?.total || 0;
  const totalPages = Math.ceil(total / limit) || 1;

  // Группированные счетчики вкладок присылаются с бэкенда
  const counts = useMemo(() => {
    return data?.counts || { all: 0, success: 0, error: 0, info: 0 };
  }, [data]);

  const taskStatuses = useMemo(() => {
    return data?.task_statuses || {};
  }, [data]);

  const availableSections = sections || [];

  const uniqueValues = useMemo(() => ({
    status: [...new Set(parsedLogs.map((entry) => entry.status))].sort(),
    sectionName: [...new Set(parsedLogs.map((entry) => entry.section_name || "—"))].sort((a, b) =>
      a.localeCompare(b, "ru"),
    ),
    productSku: [...new Set(parsedLogs.map((entry) => entry.product_sku || "—"))].sort((a, b) =>
      a.localeCompare(b, "ru"),
    ),
    operationName: [...new Set(parsedLogs.map((entry) => entry.operation_name || "—"))].sort((a, b) =>
      a.localeCompare(b, "ru"),
    ),
    taskIds: [...new Set(parsedLogs.map((entry) =>
      entry.task_ids ? entry.task_ids.split(",")[0].trim() : "—",
    ))].sort((a, b) => {
      const numA = Number.parseInt(a, 10) || 0;
      const numB = Number.parseInt(b, 10) || 0;
      return numA - numB;
    }),
    createdAt: [...new Set(parsedLogs.map((entry) => formatDateTime(entry.created_at)))].sort((a, b) => {
      const getTime = (formatted: string) => {
        const entry = parsedLogs.find((item) => formatDateTime(item.created_at) === formatted);
        return entry ? new Date(entry.created_at).getTime() : 0;
      };
      return getTime(a) - getTime(b);
    }),
    qtyText: [...new Set(parsedLogs.map((entry) => entry.qty_text || "—"))].sort((a, b) =>
      a.localeCompare(b, "ru"),
    ),
  }), [parsedLogs]);

  const handleSortChange = (field: LogField) => {
    setSortConfigs((prev) => {
      const existing = prev.find((s) => s.field === field);
      if (!existing) {
        return [{ field, order: field === "createdAt" ? "desc" : "asc" }];
      }
      if (existing.order === "asc") {
        return [{ field, order: "desc" }];
      }
      return [{ field: "createdAt", order: "desc" }];
    });
  };

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

  const headerCellClass = `${DATA_TABLE_STYLES.headerRow} ${DATA_TABLE_STYLES.headerCell}`;

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-sm flex items-center justify-center p-4 animate-in fade-in duration-200"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        className="bg-white rounded-xl shadow-2xl max-w-[95vw] 2xl:max-w-[1400px] w-full h-[85vh] flex flex-col overflow-hidden border border-slate-100 animate-in zoom-in-95 duration-200"
        role="dialog"
        aria-modal="true"
      >
        <div className="h-1 w-full bg-gradient-to-r from-blue-500 via-indigo-500 to-emerald-500" />

        <div className="flex items-start justify-between p-5 border-b border-slate-100">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-xl font-bold text-slate-800">Общий журнал аудита событий</h2>
              <span className="bg-slate-100 text-slate-600 text-xs font-bold px-2 py-0.5 rounded-full">
                {counts.all}
              </span>
            </div>
            <p className="text-xs text-slate-500 mt-1">
              Централизованный лог действий. Поддерживается мгновенный поиск по тексту сообщений, названию операций, SKU и ID заданий.
            </p>
          </div>
          <button
            className="text-slate-400 hover:text-slate-600 transition-colors p-1 rounded-lg hover:bg-slate-50"
            onClick={onClose}
            aria-label="Закрыть"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="p-4 border-b border-slate-100 bg-slate-50/50 space-y-3">
          <div className="flex gap-3 items-center">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-2.5 h-4.5 w-4.5 text-slate-400" />
              <input
                type="text"
                placeholder="Поиск по ID задания, названию операции, SKU изделия или тексту..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-full pl-10 pr-9 py-2 text-sm rounded-lg border border-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 bg-white text-slate-800 placeholder-slate-400 transition-all"
              />
              {search && (
                <button
                  onClick={() => setSearch("")}
                  className="absolute right-3 top-2.5 text-slate-400 hover:text-slate-600 transition-colors"
                >
                  <X className="h-4.5 w-4.5" />
                </button>
              )}
            </div>

            <div className="shrink-0 flex items-center bg-white rounded-lg shadow-sm border border-slate-200">
              <SectionSelect
                sections={availableSections}
                value={selectedSectionId === "all" ? null : Number(selectedSectionId)}
                onValueChange={(val) => setSelectedSectionId(val === null ? "all" : String(val))}
                emptyLabel="Все участки"
                placeholder="Все участки"
                className="h-9 min-w-[200px] max-w-[280px] text-sm border-0"
              />
            </div>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
            <div className="flex flex-wrap gap-1.5">
              <button
                onClick={() => setStatusFilter("all")}
                className={`px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all flex items-center gap-1.5 ${
                  statusFilter === "all"
                    ? "bg-slate-800 text-white shadow-sm"
                    : "bg-white border border-slate-200 text-slate-600 hover:bg-slate-50"
                }`}
              >
                Все записи
                <span
                  className={`text-[10px] px-1.5 py-0.2 rounded-full ${
                    statusFilter === "all" ? "bg-white/20 text-white" : "bg-slate-100 text-slate-600"
                  }`}
                >
                  {counts.all}
                </span>
              </button>

              <button
                onClick={() => setStatusFilter("success")}
                className={`px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all flex items-center gap-1.5 ${
                  statusFilter === "success"
                    ? "bg-emerald-600 text-white shadow-sm"
                    : "bg-white border border-slate-200 text-slate-600 hover:border-emerald-200 hover:bg-emerald-50/20"
                }`}
              >
                Успешные
                <span
                  className={`text-[10px] px-1.5 py-0.2 rounded-full ${
                    statusFilter === "success" ? "bg-white/25 text-white" : "bg-emerald-50 text-emerald-700"
                  }`}
                >
                  {counts.success}
                </span>
              </button>

              <button
                onClick={() => setStatusFilter("error")}
                className={`px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all flex items-center gap-1.5 ${
                  statusFilter === "error"
                    ? "bg-red-600 text-white shadow-sm"
                    : "bg-white border border-slate-200 text-slate-600 hover:border-red-200 hover:bg-red-50/20"
                }`}
              >
                Ошибки
                <span
                  className={`text-[10px] px-1.5 py-0.2 rounded-full ${
                    statusFilter === "error" ? "bg-white/25 text-white" : "bg-red-50 text-red-700"
                  }`}
                >
                  {counts.error}
                </span>
              </button>

              <button
                onClick={() => setStatusFilter("info")}
                className={`px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all flex items-center gap-1.5 ${
                  statusFilter === "info"
                    ? "bg-blue-600 text-white shadow-sm"
                    : "bg-white border border-slate-200 text-slate-600 hover:border-blue-200 hover:bg-blue-50/20"
                }`}
              >
                Инфо
                <span
                  className={`text-[10px] px-1.5 py-0.2 rounded-full ${
                    statusFilter === "info" ? "bg-white/25 text-white" : "bg-blue-50 text-blue-700"
                  }`}
                >
                  {counts.info}
                </span>
              </button>
            </div>
          </div>
        </div>

        <div className="flex-1 overflow-auto bg-slate-50/30 flex flex-col">
          {parsedLogs.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full py-16 text-center">
              <div className="h-14 w-14 rounded-full bg-slate-100 flex items-center justify-center text-slate-400 mb-4">
                <Clock className="h-7 w-7" />
              </div>
              <p className="text-slate-600 font-semibold text-sm">Логи не найдены</p>
              <p className="text-xs text-slate-400 mt-1.5 max-w-sm px-4">
                {counts.all === 0
                  ? "История событий пуста."
                  : "Нет записей, соответствующих заданным фильтрам и поисковому запросу."}
              </p>
            </div>
          ) : (
            <div className={DATA_TABLE_STYLES.container}>
              <table className="w-full border-separate border-spacing-0 text-sm">
                <thead>
                  <tr>
                    <th className={`${headerCellClass} p-0 w-[10%] text-left`}>
                      <SortableFilterHeader<LogFilterField>
                        field="status"
                        label="Статус"
                        currentSorts={sortConfigs as { field: LogFilterField; order: "asc" | "desc" }[]}
                        onSortChange={(field) => handleSortChange(field as LogField)}
                        values={uniqueValues.status}
                        {...bindColumn("status")}
                        valueLabel={(val) => 
                          val === "success" ? "Успешно" : val === "error" ? "Ошибка" : "Информация"
                        }
                      />
                    </th>
                    <th className={`${headerCellClass} p-0 w-[16%] text-left`}>
                      <SortableFilterHeader<LogFilterField>
                        field="createdAt"
                        label="Дата и время"
                        currentSorts={sortConfigs as { field: LogFilterField; order: "asc" | "desc" }[]}
                        onSortChange={(field) => handleSortChange(field as LogField)}
                        values={uniqueValues.createdAt}
                        {...bindColumn("createdAt")}
                      />
                    </th>
                    <th className={`${headerCellClass} p-0 w-[13%] text-left`}>
                      <SortableFilterHeader<LogFilterField>
                        field="sectionName"
                        label="Участок"
                        currentSorts={sortConfigs as { field: LogFilterField; order: "asc" | "desc" }[]}
                        onSortChange={(field) => handleSortChange(field as LogField)}
                        values={uniqueValues.sectionName}
                        {...bindColumn("sectionName")}
                      />
                    </th>
                    <th className={`${headerCellClass} p-0 w-[10%] text-left`}>
                      <SortableFilterHeader<LogFilterField>
                        field="taskIds"
                        label="Задание"
                        currentSorts={sortConfigs as { field: LogFilterField; order: "asc" | "desc" }[]}
                        onSortChange={(field) => handleSortChange(field as LogField)}
                        values={uniqueValues.taskIds}
                        {...bindColumn("taskIds")}
                        valueLabel={(val) => `#${val}`}
                      />
                    </th>
                    <th className={`${headerCellClass} p-0 w-[13%] text-left`}>
                      <SortableFilterHeader<LogFilterField>
                        field="productSku"
                        label="Артикул"
                        currentSorts={sortConfigs as { field: LogFilterField; order: "asc" | "desc" }[]}
                        onSortChange={(field) => handleSortChange(field as LogField)}
                        values={uniqueValues.productSku}
                        {...bindColumn("productSku")}
                      />
                    </th>
                    <th className={`${headerCellClass} p-0 w-[16%] text-left`}>
                      <SortableFilterHeader<LogFilterField>
                        field="operationName"
                        label="Операция"
                        currentSorts={sortConfigs as { field: LogFilterField; order: "asc" | "desc" }[]}
                        onSortChange={(field) => handleSortChange(field as LogField)}
                        values={uniqueValues.operationName}
                        {...bindColumn("operationName")}
                      />
                    </th>
                    <th className={`${headerCellClass} p-0 w-[12%] text-left`}>
                      <SortableFilterHeader<LogFilterField>
                        field="qtyText"
                        label="Количество"
                        currentSorts={sortConfigs as { field: LogFilterField; order: "asc" | "desc" }[]}
                        onSortChange={(field) => handleSortChange(field as LogField)}
                        values={uniqueValues.qtyText}
                        {...bindColumn("qtyText")}
                      />
                    </th>
                    <th className={`${headerCellClass} w-[10%] text-left`}>
                      <span className="text-xs font-medium text-muted-foreground">Подробности</span>
                    </th>
                    <TableCornerResetHeader
                      hasActiveFilters={hasActiveFilters}
                      onReset={handleResetFilters}
                      dataTableHeader
                    />
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 bg-white">
                  {parsedLogs.map((entry) => {
                    const isSuccess = entry.status === "success";
                    const isError = entry.status === "error";
                    const isInfo = entry.status === "info";
                    const isExpanded = expandedRows.has(entry.id);
                    const taskIdsArray = entry.task_ids
                      ? entry.task_ids.split(",").map((id) => Number(id.trim())).filter((id) => !isNaN(id))
                      : [];

                    return (
                      <Fragment key={entry.id}>
                        <tr
                          className="hover:bg-slate-50/60 transition-colors group relative cursor-pointer"
                          onClick={() => toggleRow(entry.id)}
                        >
                          {/* Status Icon */}
                          <td className="p-3 text-left align-middle">
                            <span
                              className={`inline-flex items-center justify-center h-7 w-7 rounded-full border shadow-sm ${
                                isSuccess
                                  ? "border-emerald-50 bg-emerald-500 text-white"
                                  : isError
                                  ? "border-red-50 bg-red-500 text-white"
                                  : "border-blue-50 bg-blue-500 text-white"
                              }`}
                              title={isSuccess ? "Успешно" : isError ? "Ошибка" : "Информация"}
                            >
                              {isSuccess && <CheckCircle2 className="h-4 w-4" />}
                              {isError && <AlertCircle className="h-4 w-4" />}
                              {isInfo && <Info className="h-4 w-4" />}
                            </span>
                          </td>

                          {/* Timestamp */}
                          <td className="p-3 text-xs font-mono font-medium text-slate-600 align-middle">
                            {formatDateTime(entry.created_at)}
                          </td>

                          {/* Section Name */}
                          <td className="p-3 align-middle truncate">
                            {entry.section_name ? (
                              <span
                                className="inline-flex items-center rounded-md px-2.5 py-0.8 text-xs font-semibold bg-slate-100 text-slate-700 border border-slate-200/60 max-w-full truncate"
                                title={`${entry.section_name} (${entry.section_code})`}
                              >
                                {highlightText(entry.section_name, search)}
                              </span>
                            ) : (
                              <span className="text-slate-400 font-medium">—</span>
                            )}
                          </td>

                          {/* Task IDs */}
                          <td className="p-3 align-middle font-mono text-xs font-semibold text-slate-500 truncate">
                            {taskIdsArray.length > 0 ? (
                              <div className="flex flex-wrap gap-1">
                                {taskIdsArray.map((id) => {
                                  const isDeleted = taskStatuses[id] === "deleted";
                                  return (
                                    <span
                                      key={id}
                                      className={`px-1.5 py-0.5 rounded text-[10.5px] border ${
                                        isDeleted
                                          ? "bg-red-50 border-red-200 text-red-650 line-through font-normal opacity-80"
                                          : search.trim() && String(id).includes(search.trim())
                                          ? "bg-amber-100 border-amber-300 text-amber-950 font-bold"
                                          : "bg-slate-50 border-slate-200/80 text-slate-650"
                                      }`}
                                      title={isDeleted ? "Задание удалено и неактуально" : undefined}
                                    >
                                      #{id}
                                    </span>
                                  );
                                })}
                              </div>
                            ) : (
                              <span className="text-slate-400 font-medium">—</span>
                            )}
                          </td>

                          {/* Product SKU */}
                          <td className="p-3 align-middle font-mono text-xs font-semibold text-slate-600 truncate">
                            {entry.product_sku ? (
                              <span title={entry.product_sku}>
                                {highlightText(entry.product_sku, search)}
                              </span>
                            ) : (
                              <span className="text-slate-400 font-medium">—</span>
                            )}
                          </td>

                          {/* Operation Name */}
                          <td className="p-3 align-middle font-medium text-xs text-slate-700 truncate">
                            {entry.operation_name ? (
                              <span title={entry.operation_name}>
                                {highlightText(entry.operation_name, search)}
                              </span>
                            ) : (
                              <span className="text-slate-400 font-medium">—</span>
                            )}
                          </td>

                          {/* Quantity */}
                          <td className="p-3 align-middle font-semibold text-xs text-slate-600 truncate">
                            {entry.qty_text ? (
                              <span title={entry.qty_text}>{entry.qty_text}</span>
                            ) : (
                              <span className="text-slate-400 font-medium">—</span>
                            )}
                          </td>

                          {/* Compact Details Column */}
                          <td className="p-3 align-middle pr-10 relative">
                            <div className="flex items-center justify-between gap-2">
                               <div className="flex items-center gap-1.5 truncate max-w-[200px]">
                                {entry.user_name && (
                                  <span className="bg-slate-100 text-slate-600 text-[10px] px-1.5 py-0.5 rounded font-medium" title={`Пользователь: ${entry.user_name}`}>
                                    👤 {entry.user_name}
                                  </span>
                                )}
                                {entry.error_details ? (
                                  <span className="text-red-600 font-semibold text-xs truncate block" title={entry.error_details}>
                                    ⚠️ {highlightText(entry.error_details, search)}
                                  </span>
                                ) : entry.comment ? (
                                  <span className="text-slate-500 italic text-xs truncate block" title={entry.comment}>
                                    💬 {highlightText(entry.comment, search)}
                                  </span>
                                ) : (
                                  <span className="text-slate-400">—</span>
                                )}
                              </div>
                              
                              <button
                                type="button"
                                className="px-2 py-1 text-xs text-indigo-650 text-indigo-600 font-bold hover:bg-slate-100 rounded transition-colors shrink-0"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  toggleRow(entry.id);
                                }}
                              >
                                {isExpanded ? "Скрыть" : "Подробнее"}
                              </button>
                            </div>
                          </td>
                          <TableCornerResetCell />
                        </tr>
                        {isExpanded && (
                          <tr className="bg-slate-50/50">
                            <td colSpan={9} className="p-4 border-b border-slate-200">
                              <div className="bg-white rounded-lg border border-slate-200 p-4 shadow-sm space-y-3 text-xs text-slate-700">
                                <div className="flex items-center justify-between border-b border-slate-100 pb-2 mb-1">
                                  <div className="flex items-center gap-2">
                                    <span className="font-bold text-slate-800 text-sm">Детали события: {entry.title}</span>
                                  </div>
                                  <span className="text-slate-400 font-mono text-[10px]">ID: {entry.id}</span>
                                </div>
                                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                  <div className="space-y-3">
                                    <div>
                                      <p className="text-slate-400 uppercase font-bold text-[9px] tracking-wider">Полное сообщение</p>
                                      <p className="whitespace-pre-wrap leading-relaxed text-slate-700 font-medium bg-slate-50/50 p-2.5 rounded border border-slate-100">{entry.message}</p>
                                    </div>
                                    {entry.changes && (
                                      <div>
                                        <p className="text-slate-400 uppercase font-bold text-[9px] tracking-wider mb-1">Изменения полей (дифф)</p>
                                        <div className="bg-slate-50 border border-slate-100 rounded p-2.5 space-y-1.5 font-mono text-[11px] text-slate-700">
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
                                                <span className="font-semibold text-slate-600 truncate pr-1" title={key}>{key}</span>
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
                                        <p className="text-slate-700 font-semibold bg-slate-50 p-2 rounded border border-slate-100 mt-1">
                                          {entry.entity_type ? `${entry.entity_type} #${entry.entity_id}` : "—"}
                                        </p>
                                      </div>
                                      <div>
                                        <p className="text-slate-400 uppercase font-bold text-[9px] tracking-wider">Операция (код)</p>
                                        <p className="text-slate-700 font-semibold bg-slate-50 p-2 rounded border border-slate-100 mt-1">
                                          {entry.action || "—"}
                                        </p>
                                      </div>
                                    </div>
                                    <div>
                                      <p className="text-slate-400 uppercase font-bold text-[9px] tracking-wider">Пользователь</p>
                                      <p className="text-slate-700 font-semibold bg-slate-50 p-2 rounded border border-slate-100 mt-1">👤 {entry.user_name || "—"}</p>
                                    </div>
                                    {entry.comment && (
                                      <div>
                                        <p className="text-slate-400 uppercase font-bold text-[9px] tracking-wider">Комментарий исполнителя</p>
                                        <p className="text-slate-700 font-semibold italic bg-slate-50 p-2.5 rounded border border-slate-100 mt-1">💬 {entry.comment}</p>
                                      </div>
                                    )}
                                    {entry.error_details && (
                                      <div>
                                        <p className="text-slate-400 uppercase font-bold text-[9px] tracking-wider">Сведения об ошибке</p>
                                        <p className="text-red-600 font-semibold bg-red-50/40 p-2.5 rounded border border-red-100 mt-1">⚠️ {entry.error_details}</p>
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
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between p-4 border-t border-slate-100 bg-slate-50 shrink-0">
          <div className="flex items-center gap-2 text-xs text-slate-500 font-medium">
            {totalPages > 1 && (
              <>
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page === 1}
                  className="p-1.5 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 disabled:opacity-50 disabled:hover:bg-white transition-colors"
                  aria-label="Предыдущая страница"
                >
                  <ChevronLeft className="h-4 w-4" />
                </button>
                <span className="px-2">
                  Страница <strong className="text-slate-700">{page}</strong> из{" "}
                  <strong className="text-slate-700">{totalPages}</strong>
                </span>
                <button
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page === totalPages}
                  className="p-1.5 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 disabled:opacity-50 disabled:hover:bg-white transition-colors"
                  aria-label="Следующая страница"
                >
                  <ChevronRight className="h-4 w-4" />
                </button>
              </>
            )}
            <span className="ml-4">
              Показано {parsedLogs.length} из {total} записей
            </span>
          </div>
          <button
            className="px-5 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-white text-sm font-semibold transition-colors shadow-sm"
            onClick={onClose}
          >
            Закрыть
          </button>
        </div>
      </div>
    </div>
  );
}
