import { useState, useMemo, Fragment, useEffect } from "react";
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
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { getAuditLogs, type AuditLogEntry } from "@/shared/api/auditLogs";
import { SectionSelect, DateRangePicker, Combobox } from "@/shared/ui";
import { listSections } from "@/shared/api/sections";

type LogField = "createdAt" | "status" | "sectionName" | "productSku" | "qtyText" | "action" | "entityType";

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

export function AuditLogsPage() {
  // Поиск и базовые фильтры
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | "success" | "error" | "info">("all");
  const [selectedSectionId, setSelectedSectionId] = useState<string>("all");

  // Расширенные фильтры
  const [actionFilter, setActionFilter] = useState<string>("all");
  const [entityTypeFilter, setEntityTypeFilter] = useState<string>("all");
  const [dateFrom, setDateFrom] = useState<string>("");
  const [dateTo, setDateTo] = useState<string>("");

  // Пагинация
  const [page, setPage] = useState(1);
  const limit = 50;
  const offset = (page - 1) * limit;

  // Серверная сортировка
  const [sortBy, setSortBy] = useState<LogField>("createdAt");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("desc");

  // Раскрытие строк
  const [expandedRows, setExpandedRows] = useState<Set<number>>(new Set());

  // Сброс страницы при изменении любого фильтра
  useEffect(() => {
    setPage(1);
  }, [search, statusFilter, selectedSectionId, actionFilter, entityTypeFilter, dateFrom, dateTo]);

  // Запрос справочника участков
  const { data: sections } = useQuery({
    queryKey: ["sections"],
    queryFn: listSections,
  });

  // Запрос логов с бэкенда с максимальным набором фильтров и сортировок
  const { data, isLoading } = useQuery({
    queryKey: [
      "auditLogs",
      selectedSectionId,
      statusFilter,
      search,
      actionFilter,
      entityTypeFilter,
      dateFrom,
      dateTo,
      sortBy,
      sortOrder,
      offset,
    ],
    queryFn: () =>
      getAuditLogs({
        section_id: selectedSectionId === "all" ? undefined : Number(selectedSectionId),
        status: statusFilter === "all" ? undefined : statusFilter,
        search: search.trim() || undefined,
        action: actionFilter === "all" ? undefined : actionFilter,
        entity_type: entityTypeFilter === "all" ? undefined : entityTypeFilter,
        date_from: dateFrom ? `${dateFrom}T00:00:00` : undefined,
        date_to: dateTo ? `${dateTo}T23:59:59` : undefined,
        sort_by: sortBy === "createdAt" ? "created_at" : sortBy === "sectionName" ? "section_name" : sortBy === "productSku" ? "product_sku" : sortBy === "qtyText" ? "qty_text" : sortBy === "entityType" ? "entity_type" : sortBy,
        sort_order: sortOrder,
        limit,
        offset,
      }),
  });

  const parsedLogs = data?.items || [];
  const total = data?.total || 0;
  const totalPages = Math.ceil(total / limit) || 1;
  const counts = data?.counts || { all: 0, success: 0, error: 0, info: 0 };
  const taskStatuses = data?.task_statuses || {};
  const availableSections = sections || [];

  const handleSortChange = (field: LogField) => {
    if (sortBy === field) {
      setSortOrder((o) => (o === "asc" ? "desc" : "asc"));
    } else {
      setSortBy(field);
      setSortOrder("desc");
    }
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

  const renderSortHeader = (field: LogField, label: string) => {
    const isActive = sortBy === field;
    return (
      <button
        onClick={() => handleSortChange(field)}
        className="flex items-center gap-1 hover:text-indigo-600 transition-colors focus:outline-none font-bold text-xs uppercase tracking-normal select-none text-slate-500 text-left"
      >
        <span>{label}</span>
        {isActive ? (
          sortOrder === "asc" ? (
            <ArrowUp className="h-3.5 w-3.5 text-indigo-655 text-indigo-600 font-bold" />
          ) : (
            <ArrowDown className="h-3.5 w-3.5 text-indigo-655 text-indigo-600 font-bold" />
          )
        ) : (
          <ArrowUpDown className="h-3 w-3 text-slate-400 opacity-40 hover:opacity-100" />
        )}
      </button>
    );
  };

  const hasActiveExtraFilters = actionFilter !== "all" || entityTypeFilter !== "all" || dateFrom !== "" || dateTo !== "";

  return (
    <div className="space-y-6">
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
        </div>
      </header>

      <div className="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden flex flex-col">
        {/* Базовая панель фильтров */}
        <div className="p-4 border-b border-slate-200 bg-slate-50/50 space-y-3">
          <div className="flex flex-wrap items-end gap-4">
            {/* Поиск */}
            <div className="space-y-1.5 w-[300px]">
              <label className="block text-xs font-bold text-slate-500 uppercase tracking-wider mb-1">Поиск</label>
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400 pointer-events-none" />
                <input
                  type="text"
                  placeholder="Поиск..."
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="w-full pl-10 pr-9 py-2 text-sm rounded-lg border border-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 bg-white text-slate-800 placeholder-slate-400 transition-all h-9"
                />
                {search && (
                  <button
                    onClick={() => setSearch("")}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 transition-colors"
                  >
                    <X className="h-4 w-4" />
                  </button>
                )}
              </div>
            </div>

            {/* Участок */}
            <div className="space-y-1.5 w-[250px]">
              <label className="block text-xs font-bold text-slate-500 uppercase tracking-wider mb-1">Участок</label>
              <div className="flex items-center bg-white rounded-lg border border-slate-200 h-9">
                <SectionSelect
                  sections={availableSections}
                  value={selectedSectionId === "all" ? null : Number(selectedSectionId)}
                  onValueChange={(val) => setSelectedSectionId(val === null ? "all" : String(val))}
                  emptyLabel="Все участки"
                  placeholder="Все участки"
                  className="h-8 w-full text-sm border-0"
                />
              </div>
            </div>

            {/* Тип действия (action) */}
            <div className="space-y-1.5 w-[250px]">
              <label className="block text-xs font-bold text-slate-500 uppercase tracking-wider mb-1">Тип действия</label>
              <Combobox
                className="flex h-9 w-full items-center justify-between rounded-md border border-input bg-background px-3 py-2 text-sm"
                options={[
                  { label: "Все действия", value: "all" },
                  { label: "Создание (create)", value: "create" },
                  { label: "Обновление (update)", value: "update" },
                  { label: "Удаление (delete)", value: "delete" },
                  { label: "Утверждение (approve)", value: "approve" },
                  { label: "Отмена (cancel)", value: "cancel" },
                  { label: "Восстановление (restore)", value: "restore" },
                  { label: "Импорт (import)", value: "import" },
                  { label: "Отправка (send)", value: "send" },
                  { label: "Приемка (receive)", value: "receive" },
                  { label: "Корректировка (correct)", value: "correct" },
                  { label: "Выпуск (release)", value: "release" },
                ]}
                value={actionFilter}
                onValueChange={setActionFilter}
                placeholder="Выберите действие..."
              />
            </div>

            {/* Тип сущности (entity_type) */}
            <div className="space-y-1.5 w-[250px]">
              <label className="block text-xs font-bold text-slate-500 uppercase tracking-wider mb-1">Тип сущности</label>
              <Combobox
                className="flex h-9 w-full items-center justify-between rounded-md border border-input bg-background px-3 py-2 text-sm"
                options={[
                  { label: "Все сущности", value: "all" },
                  { label: "Номенклатура", value: "product" },
                  { label: "Участок", value: "section" },
                  { label: "Маршрут", value: "route" },
                  { label: "Техкарта", value: "techcard" },
                  { label: "План производства", value: "production_plan" },
                  { label: "Позиция плана", value: "plan_position" },
                  { label: "Сменное задание", value: "work_task" },
                  { label: "Передача", value: "transfer" },
                  { label: "Брак", value: "defect" },
                  { label: "Импорт-пакет", value: "import_batch" },
                  { label: "Пользователь", value: "user" },
                ]}
                value={entityTypeFilter}
                onValueChange={setEntityTypeFilter}
                placeholder="Выберите сущность..."
              />
            </div>

            {/* Диапазон дат с помощью DateRangePicker */}
            <div className="space-y-1.5 w-[280px]">
              <label className="block text-xs font-bold text-slate-500 uppercase tracking-wider mb-1">Диапазон дат</label>
              <DateRangePicker
                from={dateFrom}
                to={dateTo}
                onChange={(range) => {
                  setDateFrom(range.from || "");
                  setDateTo(range.to || "");
                }}
                className="w-full"
                placeholder="Выберите период логов"
                align="start"
              />
            </div>
          </div>

          {/* Переключатели базовых статусов (success/error/info) */}
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

            {hasActiveExtraFilters && (
              <button
                onClick={() => {
                  setActionFilter("all");
                  setEntityTypeFilter("all");
                  setDateFrom("");
                  setDateTo("");
                }}
                className="text-xs text-red-600 hover:text-red-800 font-bold"
              >
                Сбросить фильтры
              </button>
            )}
          </div>
        </div>

        {/* Таблица */}
        <div className="overflow-x-auto">
          {isLoading ? (
            <div className="flex items-center justify-center py-20 text-slate-400 text-sm">
              Загрузка журнала аудита...
            </div>
          ) : parsedLogs.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-center">
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
            <table className="w-full border-separate border-spacing-0 text-sm">
              <thead className="bg-slate-100 border-b border-slate-200">
                <tr>
                  <th className="w-[8%] p-3 text-left">{renderSortHeader("status", "Статус")}</th>
                  <th className="w-[16%] p-3 text-left">{renderSortHeader("createdAt", "Дата и время")}</th>
                  <th className="w-[14%] p-3 text-left">{renderSortHeader("sectionName", "Участок")}</th>
                  <th className="w-[12%] p-3 text-left font-bold text-xs uppercase text-slate-500">Задание</th>
                  <th className="w-[12%] p-3 text-left">{renderSortHeader("productSku", "Артикул")}</th>
                  <th className="w-[14%] p-3 text-left">{renderSortHeader("action", "Действие")}</th>
                  <th className="w-[12%] p-3 text-left">{renderSortHeader("entityType", "Сущность")}</th>
                  <th className="w-[12%] p-3 text-left font-bold text-xs uppercase text-slate-500">Подробности</th>
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
                        className="hover:bg-slate-50/60 transition-colors group relative cursor-pointer font-medium"
                        onClick={() => toggleRow(entry.id)}
                      >
                        {/* Статус */}
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

                        {/* Время */}
                        <td className="p-3 text-xs font-mono font-medium text-slate-650 text-slate-500 align-middle">
                          {formatDateTime(entry.created_at)}
                        </td>

                        {/* Участок */}
                        <td className="p-3 align-middle truncate">
                          {entry.section_name ? (
                            <span
                              className="inline-flex items-center rounded-md px-2.5 py-0.8 text-xs font-semibold bg-slate-100 text-slate-700 border border-slate-200/60 max-w-full truncate"
                              title={`${entry.section_name} (${entry.section_code})`}
                            >
                              {entry.section_name}
                            </span>
                          ) : (
                            <span className="text-slate-400">—</span>
                          )}
                        </td>

                        {/* Задания */}
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
                        <td className="p-3 align-middle font-mono text-xs font-semibold text-slate-600 truncate">
                          {entry.product_sku || <span className="text-slate-400">—</span>}
                        </td>

                        {/* Действие (action) */}
                        <td className="p-3 align-middle text-xs truncate">
                          {entry.action ? (
                            <span className="px-2 py-0.5 font-bold rounded bg-indigo-50 border border-indigo-100 text-indigo-700 text-[10px] uppercase">
                              {entry.action}
                            </span>
                          ) : (
                            <span className="text-slate-400">—</span>
                          )}
                        </td>

                        {/* Сущность (entity_type) */}
                        <td className="p-3 align-middle text-xs truncate text-slate-600">
                          {entry.entity_type ? (
                            <span className="font-semibold" title={`${entry.entity_type} #${entry.entity_id}`}>
                              {entry.entity_type} #{entry.entity_id}
                            </span>
                          ) : (
                            <span className="text-slate-400">—</span>
                          )}
                        </td>

                        {/* Описание / действия */}
                        <td className="p-3 align-middle relative pr-4">
                          <div className="flex items-center justify-between gap-2">
                            <span className="text-slate-500 text-xs truncate max-w-[200px]" title={entry.message}>
                              {entry.title}: {entry.message}
                            </span>
                            <button
                              type="button"
                              className="px-2 py-1 text-xs text-indigo-600 font-bold hover:bg-slate-100 rounded transition-colors shrink-0"
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

                      {/* Детали раскрытой строки */}
                      {isExpanded && (
                        <tr className="bg-slate-50/50">
                          <td colSpan={8} className="p-4 border-b border-slate-200">
                            <div className="bg-white rounded-lg border border-slate-200 p-4 shadow-sm space-y-3 text-xs text-slate-700">
                              <div className="flex items-center justify-between border-b border-slate-100 pb-2 mb-1">
                                <span className="font-bold text-slate-800 text-sm">Детали события: {entry.title}</span>
                                <span className="text-slate-400 font-mono text-[10px]">ID: {entry.id}</span>
                              </div>
                              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                <div className="space-y-3">
                                  <div>
                                    <p className="text-slate-400 uppercase font-bold text-[9px] tracking-wider">Полное сообщение</p>
                                    <p className="whitespace-pre-wrap leading-relaxed text-slate-700 font-medium bg-slate-5/50 bg-slate-50/50 p-2.5 rounded border border-slate-100">{entry.message}</p>
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
                                              <span className="font-semibold text-slate-650 text-slate-600 truncate pr-1" title={key}>{key}</span>
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
                                      <p className="text-slate-400 uppercase font-bold text-[9px] tracking-wider">Действие</p>
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
          )}
        </div>

        {/* Футер пагинации */}
        <div className="flex items-center justify-between p-4 border-t border-slate-200 bg-slate-50">
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
        </div>
      </div>
    </div>
  );
}
