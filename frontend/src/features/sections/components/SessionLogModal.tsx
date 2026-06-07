import { useState, useMemo, Fragment } from "react";
import {
  CheckCircle2,
  AlertCircle,
  Info,
  Search,
  X,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  Clock,
} from "lucide-react";
import { SectionSelect, SortableFilterHeader } from "@/shared/ui";
import type { Section } from "@/shared/api/sections";

export interface ActionLogEntry {
  id: string;
  title: string;
  status: "success" | "error" | "info";
  message: string;
  createdAt: string;
  sectionId?: number;
  sectionName?: string;
  sectionCode?: string;
  taskIds?: number[];
  productSku?: string;
  operationName?: string;
  qtyText?: string;
  comment?: string;
  errorDetails?: string;
}

interface SessionLogModalProps {
  open: boolean;
  onClose: () => void;
  actionLog: ActionLogEntry[];
  sections?: Section[];
}

type LogField = "status" | "createdAt" | "sectionName" | "productSku" | "taskIds" | "operationName" | "qtyText";

// Регулярные выражения для парсинга старых записей
function parseLegacyEntry(entry: ActionLogEntry): ActionLogEntry {
  const parsed = { ...entry };

  if (!parsed.productSku) {
    const skuMatch = entry.message.match(/\(арт\.\s*([^)]+)\)/i) || entry.message.match(/арт\.\s*([a-zA-Z0-9_-]+)/i);
    if (skuMatch) {
      parsed.productSku = skuMatch[1].trim();
    }
  }

  if (!parsed.operationName) {
    const opMatch = entry.message.match(/для операции\s*"([^"]+)"/i) || entry.message.match(/для операций:\s*([^.]+)/i);
    if (opMatch) {
      parsed.operationName = opMatch[1].trim();
    }
  }

  if (!parsed.qtyText) {
    const goodMatch = entry.message.match(/годные\s*=\s*(\d+)/i) || entry.message.match(/годн:\s*(\d+)/i);
    const defectMatch = entry.message.match(/брак\s*=\s*(\d+)/i) || entry.message.match(/брак:\s*(\d+)/i);
    if (goodMatch || defectMatch) {
      const g = goodMatch ? goodMatch[1] : "0";
      const d = defectMatch ? defectMatch[1] : "0";
      parsed.qtyText = `годн: ${g}, брак: ${d}`;
    }
  }

  if (!parsed.comment) {
    const commentMatch = entry.message.match(/комментарий:\s*"([^"]+)"/i);
    if (commentMatch) {
      parsed.comment = commentMatch[1].trim();
    }
  }

  if (!parsed.errorDetails) {
    const errorMatch = entry.message.match(/Причина:\s*([^.]+)/i);
    if (errorMatch) {
      parsed.errorDetails = errorMatch[1].trim();
    }
  }

  return parsed;
}

export function SessionLogModal({
  open,
  onClose,
  actionLog,
  sections,
}: SessionLogModalProps) {
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | "success" | "error" | "info">("all");
  const [selectedSectionId, setSelectedSectionId] = useState<string>("all");
  
  // Состояния сортировки через системный формат SortConfig
  const [sortConfigs, setSortConfigs] = useState<{ field: LogField; order: "asc" | "desc" }[]>([
    { field: "createdAt", order: "desc" }
  ]);

  // Состояние колоночных фильтров
  const [columnFilters, setColumnFilters] = useState<Record<string, Set<string>>>({
    status: new Set(),
    sectionName: new Set(),
    productSku: new Set(),
    operationName: new Set(),
    taskIds: new Set(),
  });

  // Состояние раскрытых строк
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());

  // Парсинг старых логов для обеспечения совместимости
  const parsedLogs = useMemo(() => {
    return actionLog.map(parseLegacyEntry);
  }, [actionLog]);

  // Dynamically compute available sections from props or logs
  const availableSections = useMemo(() => {
    if (sections && sections.length > 0) {
      return sections;
    }
    const unique = new Map<number, Section>();
    parsedLogs.forEach((entry) => {
      if (entry.sectionId && entry.sectionName) {
        unique.set(entry.sectionId, {
          id: entry.sectionId,
          name: entry.sectionName,
          code: entry.sectionCode || "",
          description: null,
          is_active: true,
          icon: "lucide:Layers",
          icon_color: "#64748B",
          kind: "production",
        });
      }
    });
    return Array.from(unique.values());
  }, [parsedLogs, sections]);

  // Get status counts for badges based on the currently selected section
  const counts = useMemo(() => {
    return parsedLogs.reduce(
      (acc, entry) => {
        const matchesSection = selectedSectionId === "all" || entry.sectionId === Number(selectedSectionId);
        if (!matchesSection) return acc;

        acc.all++;
        if (entry.status === "success") acc.success++;
        if (entry.status === "error") acc.error++;
        if (entry.status === "info") acc.info++;
        return acc;
      },
      { all: 0, success: 0, error: 0, info: 0 }
    );
  }, [parsedLogs, selectedSectionId]);

  // Вычисление уникальных значений для колоночных фильтров
  const uniqueValues = useMemo(() => {
    const status = new Set<string>();
    const sectionName = new Set<string>();
    const productSku = new Set<string>();
    const operationName = new Set<string>();
    const taskIds = new Set<string>();

    parsedLogs.forEach((entry) => {
      if (entry.status) status.add(entry.status);
      if (entry.sectionName) sectionName.add(entry.sectionName);
      if (entry.productSku) {
        entry.productSku.split(", ").forEach(sku => {
          if (sku.trim()) productSku.add(sku.trim());
        });
      }
      if (entry.operationName) {
        entry.operationName.split(", ").forEach(op => {
          if (op.trim()) operationName.add(op.trim());
        });
      }
      if (entry.taskIds && entry.taskIds.length > 0) {
        entry.taskIds.forEach(id => {
          taskIds.add(String(id));
        });
      }
    });

    return {
      status: Array.from(status).sort(),
      sectionName: Array.from(sectionName).sort(),
      productSku: Array.from(productSku).sort(),
      operationName: Array.from(operationName).sort(),
      taskIds: Array.from(taskIds).sort((a, b) => Number(a) - Number(b)),
    };
  }, [parsedLogs]);

  // Filter and sort logs
  const processedLogs = useMemo(() => {
    let result = parsedLogs.filter((entry) => {
      // 1. Section Filter (сверху "Все участки")
      const matchesSection = selectedSectionId === "all" || entry.sectionId === Number(selectedSectionId);
      if (!matchesSection) return false;

      // 2. Status Filter (вкладки "Успешные/Ошибки/Инфо")
      const matchesStatus = statusFilter === "all" || entry.status === statusFilter;
      if (!matchesStatus) return false;

      // 3. Text & ID Search
      if (search.trim()) {
        const searchLower = search.toLowerCase().trim();
        const searchAsNumber = Number(searchLower);
        const matchesTaskId = !isNaN(searchAsNumber) && entry.taskIds?.includes(searchAsNumber);

        const matchesText =
          entry.title.toLowerCase().includes(searchLower) ||
          entry.message.toLowerCase().includes(searchLower) ||
          entry.sectionName?.toLowerCase().includes(searchLower) ||
          entry.sectionCode?.toLowerCase().includes(searchLower) ||
          entry.productSku?.toLowerCase().includes(searchLower) ||
          entry.operationName?.toLowerCase().includes(searchLower) ||
          entry.comment?.toLowerCase().includes(searchLower) ||
          entry.errorDetails?.toLowerCase().includes(searchLower);

        if (!matchesText && !matchesTaskId) return false;
      }

      // 4. Колоночные фильтры через SortableFilterHeader
      if (columnFilters.status.size > 0 && !columnFilters.status.has(entry.status)) {
        return false;
      }
      
      if (columnFilters.sectionName.size > 0 && (!entry.sectionName || !columnFilters.sectionName.has(entry.sectionName))) {
        return false;
      }

      if (columnFilters.taskIds.size > 0) {
        if (!entry.taskIds || entry.taskIds.length === 0) return false;
        const hasMatchedTaskId = entry.taskIds.some(id => columnFilters.taskIds.has(String(id)));
        if (!hasMatchedTaskId) return false;
      }

      if (columnFilters.productSku.size > 0) {
        if (!entry.productSku) return false;
        const entrySkus = entry.productSku.split(", ").map(s => s.trim());
        const hasMatchedSku = entrySkus.some(sku => columnFilters.productSku.has(sku));
        if (!hasMatchedSku) return false;
      }

      if (columnFilters.operationName.size > 0) {
        if (!entry.operationName) return false;
        const entryOps = entry.operationName.split(", ").map(o => o.trim());
        const hasMatchedOp = entryOps.some(op => columnFilters.operationName.has(op));
        if (!hasMatchedOp) return false;
      }

      return true;
    });

    const activeSort = sortConfigs[0];
    if (activeSort) {
      const { field, order } = activeSort;
      result.sort((a, b) => {
        let valA: any = "";
        let valB: any = "";

        switch (field) {
          case "createdAt":
            valA = new Date(a.createdAt).getTime();
            valB = new Date(b.createdAt).getTime();
            break;
          case "status":
            valA = a.status;
            valB = b.status;
            break;
          case "sectionName":
            valA = a.sectionName || "";
            valB = b.sectionName || "";
            break;
          case "productSku":
            valA = a.productSku || "";
            valB = b.productSku || "";
            break;
          case "operationName":
            valA = a.operationName || "";
            valB = b.operationName || "";
            break;
          case "qtyText":
            valA = a.qtyText || "";
            valB = b.qtyText || "";
            break;
          case "taskIds":
            valA = a.taskIds && a.taskIds.length > 0 ? a.taskIds[0] : 0;
            valB = b.taskIds && b.taskIds.length > 0 ? b.taskIds[0] : 0;
            break;
        }

        if (valA < valB) return order === "asc" ? -1 : 1;
        if (valA > valB) return order === "asc" ? 1 : -1;
        return 0;
      });
    }

    return result;
  }, [parsedLogs, search, statusFilter, selectedSectionId, columnFilters, sortConfigs]);

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

  const handleColumnFilterChange = (field: string, selected: Set<string>) => {
    setColumnFilters((prev) => ({
      ...prev,
      [field]: selected,
    }));
  };

  const toggleRow = (id: string) => {
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

  // Helper to highlight matching text
  const highlightText = (text: string, searchWord: string) => {
    if (!searchWord.trim()) return text;
    const escaped = searchWord.replace(/[-\/\\^$*+?.()|[\]{}]/g, "\\$&");
    const regex = new RegExp(`(${escaped})`, "gi");
    const parts = text.split(regex);
    return (
      <>
        {parts.map((part, i) =>
          regex.test(part) ? (
            <mark key={i} className="bg-amber-100 text-amber-900 rounded-[2px] px-0.5 font-semibold">
              {part}
            </mark>
          ) : (
            part
          )
        )}
      </>
    );
  };

  // Helper to format absolute local time
  const formatDateTime = (dateString: string) => {
    try {
      return new Date(dateString).toLocaleString("ru-RU", {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
    } catch (e) {
      return dateString;
    }
  };

  const renderSimpleSortHeader = (field: LogField, label: string) => {
    const activeSort = sortConfigs.find((s) => s.field === field);
    return (
      <button
        onClick={() => handleSortChange(field)}
        className="flex items-center gap-1 hover:text-indigo-600 transition-colors focus:outline-none font-bold text-xs uppercase tracking-normal select-none text-slate-500 text-left"
      >
        <span>{label}</span>
        {activeSort ? (
          activeSort.order === "asc" ? (
            <ArrowUp className="h-3.5 w-3.5 text-indigo-650 text-indigo-600 font-bold" />
          ) : (
            <ArrowDown className="h-3.5 w-3.5 text-indigo-655 text-indigo-600 font-bold" />
          )
        ) : (
          <ArrowUpDown className="h-3 w-3 text-slate-400 opacity-40 hover:opacity-100" />
        )}
      </button>
    );
  };

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
          {processedLogs.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full py-16 text-center">
              <div className="h-14 w-14 rounded-full bg-slate-100 flex items-center justify-center text-slate-400 mb-4">
                <Clock className="h-7 w-7" />
              </div>
              <p className="text-slate-600 font-semibold text-sm">Логи не найдены</p>
              <p className="text-xs text-slate-400 mt-1.5 max-w-sm px-4">
                {actionLog.length === 0
                  ? "История событий пуста."
                  : "Нет записей, соответствующих заданным фильтрам и поисковому запросу."}
              </p>
            </div>
          ) : (
            <div className="w-full overflow-x-hidden">
              <table className="w-full border-separate border-spacing-0 text-sm">
                <thead className="[&_th]:sticky [&_th]:top-0 [&_th]:z-20 [&_th]:bg-slate-100 [&_th]:border-b [&_th]:border-slate-200">
                  <tr>
                    <th className="w-[10%] p-3 text-left">
                      <SortableFilterHeader<LogField>
                        field="status"
                        label="Статус"
                        currentSorts={sortConfigs}
                        onSortChange={handleSortChange}
                        values={uniqueValues.status}
                        selectedValues={columnFilters.status}
                        onFilterChange={handleColumnFilterChange}
                        valueLabel={(val) => 
                          val === "success" ? "Успешно" : val === "error" ? "Ошибка" : "Информация"
                        }
                      />
                    </th>
                    <th className="w-[16%] p-3 text-left">
                      {renderSimpleSortHeader("createdAt", "Дата и время")}
                    </th>
                    <th className="w-[13%] p-3 text-left">
                      <SortableFilterHeader<LogField>
                        field="sectionName"
                        label="Участок"
                        currentSorts={sortConfigs}
                        onSortChange={handleSortChange}
                        values={uniqueValues.sectionName}
                        selectedValues={columnFilters.sectionName}
                        onFilterChange={handleColumnFilterChange}
                      />
                    </th>
                    <th className="w-[10%] p-3 text-left">
                      <SortableFilterHeader<LogField>
                        field="taskIds"
                        label="Задание"
                        currentSorts={sortConfigs}
                        onSortChange={handleSortChange}
                        values={uniqueValues.taskIds}
                        selectedValues={columnFilters.taskIds}
                        onFilterChange={handleColumnFilterChange}
                        valueLabel={(val) => `#${val}`}
                      />
                    </th>
                    <th className="w-[13%] p-3 text-left">
                      <SortableFilterHeader<LogField>
                        field="productSku"
                        label="Артикул"
                        currentSorts={sortConfigs}
                        onSortChange={handleSortChange}
                        values={uniqueValues.productSku}
                        selectedValues={columnFilters.productSku}
                        onFilterChange={handleColumnFilterChange}
                      />
                    </th>
                    <th className="w-[16%] p-3 text-left">
                      <SortableFilterHeader<LogField>
                        field="operationName"
                        label="Операция"
                        currentSorts={sortConfigs}
                        onSortChange={handleSortChange}
                        values={uniqueValues.operationName}
                        selectedValues={columnFilters.operationName}
                        onFilterChange={handleColumnFilterChange}
                      />
                    </th>
                    <th className="w-[12%] p-3 text-left">
                      {renderSimpleSortHeader("qtyText", "Количество")}
                    </th>
                    <th className="w-[10%] p-3 text-left text-xs font-bold text-slate-500 uppercase tracking-normal select-none">
                      Подробности
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 bg-white">
                  {processedLogs.map((entry) => {
                    const isSuccess = entry.status === "success";
                    const isError = entry.status === "error";
                    const isInfo = entry.status === "info";
                    const isExpanded = expandedRows.has(entry.id);

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
                            {formatDateTime(entry.createdAt)}
                          </td>

                          {/* Section Name */}
                          <td className="p-3 align-middle truncate">
                            {entry.sectionName ? (
                              <span
                                className="inline-flex items-center rounded-md px-2.5 py-0.8 text-xs font-semibold bg-slate-100 text-slate-700 border border-slate-200/60 max-w-full truncate"
                                title={`${entry.sectionName} (${entry.sectionCode})`}
                              >
                                {highlightText(entry.sectionName, search)}
                              </span>
                            ) : (
                              <span className="text-slate-400 font-medium">—</span>
                            )}
                          </td>

                          {/* Task IDs */}
                          <td className="p-3 align-middle font-mono text-xs font-semibold text-slate-500 truncate">
                            {entry.taskIds && entry.taskIds.length > 0 ? (
                              <div className="flex flex-wrap gap-1">
                                {entry.taskIds.map((id) => (
                                  <span
                                    key={id}
                                    className={`px-1.5 py-0.5 rounded text-[10.5px] border ${
                                      search.trim() && String(id).includes(search.trim())
                                        ? "bg-amber-100 border-amber-300 text-amber-950 font-bold"
                                        : "bg-slate-50 border-slate-200/80 text-slate-650"
                                    }`}
                                  >
                                    #{id}
                                  </span>
                                ))}
                              </div>
                            ) : (
                              <span className="text-slate-400 font-medium">—</span>
                            )}
                          </td>

                          {/* Product SKU */}
                          <td className="p-3 align-middle font-mono text-xs font-semibold text-slate-600 truncate">
                            {entry.productSku ? (
                              <span title={entry.productSku}>
                                {highlightText(entry.productSku, search)}
                              </span>
                            ) : (
                              <span className="text-slate-400 font-medium">—</span>
                            )}
                          </td>

                          {/* Operation Name */}
                          <td className="p-3 align-middle font-medium text-xs text-slate-700 truncate">
                            {entry.operationName ? (
                              <span title={entry.operationName}>
                                {highlightText(entry.operationName, search)}
                              </span>
                            ) : (
                              <span className="text-slate-400 font-medium">—</span>
                            )}
                          </td>

                          {/* Quantity */}
                          <td className="p-3 align-middle font-semibold text-xs text-slate-600 truncate">
                            {entry.qtyText ? (
                              <span title={entry.qtyText}>{entry.qtyText}</span>
                            ) : (
                              <span className="text-slate-400 font-medium">—</span>
                            )}
                          </td>

                          {/* Compact Details Column */}
                          <td className="p-3 align-middle pr-10 relative">
                            <div className="flex items-center justify-between gap-2">
                              <div className="truncate max-w-[200px]">
                                {entry.errorDetails ? (
                                  <span className="text-red-655 text-red-655 text-red-600 font-semibold text-xs truncate block" title={entry.errorDetails}>
                                    ⚠️ {highlightText(entry.errorDetails, search)}
                                  </span>
                                ) : entry.comment ? (
                                  <span className="text-slate-655 text-slate-550 text-slate-500 italic text-xs truncate block" title={entry.comment}>
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
                        </tr>
                        {isExpanded && (
                          <tr className="bg-slate-50/50">
                            <td colSpan={8} className="p-4 border-b border-slate-200">
                              <div className="bg-white rounded-lg border border-slate-200 p-4 shadow-sm space-y-3 text-xs text-slate-700">
                                <div className="flex items-center justify-between border-b border-slate-100 pb-2 mb-1">
                                  <div className="flex items-center gap-2">
                                    <span className="font-bold text-slate-800 text-sm">Детали события: {entry.title}</span>
                                  </div>
                                  <span className="text-slate-400 font-mono text-[10px]">ID: {entry.id}</span>
                                </div>
                                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                  <div className="space-y-1">
                                    <p className="text-slate-400 uppercase font-bold text-[9px] tracking-wider">Полное сообщение</p>
                                    <p className="whitespace-pre-wrap leading-relaxed text-slate-700 font-medium bg-slate-50/50 p-2.5 rounded border border-slate-100">{entry.message}</p>
                                  </div>
                                  <div className="space-y-3 md:border-l md:border-slate-100 md:pl-4">
                                    {entry.comment && (
                                      <div>
                                        <p className="text-slate-400 uppercase font-bold text-[9px] tracking-wider">Комментарий исполнителя</p>
                                        <p className="text-slate-700 font-semibold italic bg-slate-50 p-2.5 rounded border border-slate-100 mt-1">💬 {entry.comment}</p>
                                      </div>
                                    )}
                                    {entry.errorDetails && (
                                      <div>
                                        <p className="text-slate-400 uppercase font-bold text-[9px] tracking-wider">Сведения об ошибке</p>
                                        <p className="text-red-750 text-red-655 text-red-655 text-red-600 font-semibold bg-red-50/40 p-2.5 rounded border border-red-100 mt-1">⚠️ {entry.errorDetails}</p>
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
        <div className="flex items-center justify-end p-4 border-t border-slate-100 bg-slate-50 shrink-0">
          <button
            className="px-5 py-2.5 rounded-lg bg-slate-800 text-white hover:bg-slate-700 text-sm font-semibold transition-colors shadow-sm"
            onClick={onClose}
          >
            Закрыть
          </button>
        </div>
      </div>
    </div>
  );
}
