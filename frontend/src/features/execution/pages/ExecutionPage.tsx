import { useMemo, useState, useCallback, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getProductionPlanningRowDetail,
  listPlans,
  listProductionPlanningRows,
  manualPassToStage,
  takeToWork,
  cancelPositionExecution,
  restorePositionExecution,
  softDeleteCancelledPosition,
  getPositionHistory,
  type ProductionPlanningRow,
  type TakeToWorkResult,
  type StatusHistoryEntry,
  type ProductionPlanningRowDetail,
} from "@/shared/api/productionPlans";
import { listSections } from "@/shared/api/sections";
import { Badge, Button, Checkbox, Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, Input, Select, SelectContent, SelectItem, SelectTrigger, SelectValue, AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogTitle, AlertDialogDescription, AlertDialogFooter, AlertDialogAction, AlertDialogCancel, renderIcon, FiltersPanel, VirtualizedTableBody, SortableHeader, type FiltersPanelField } from "@/shared/ui";
import { useTableQueryEngine, SortConfig, ColumnSortDef } from "@/shared/hooks/useTableQueryEngine";
import { nextMultiSortConfigs } from "@/shared/lib/multiSort";
import { toast } from "@/shared/ui/use-toast";
import { getErrorMessage } from "@/shared/api/client";
import { RowDetailsSidePanel, adaptExecutionDetail } from "@/features/planning/components/row-details";
import { StepIndicator } from "../components/StepIndicator";

const positionStatusLabels: Record<string, string> = {
  draft: "Черновик",
  invalid: "Ошибка",
  valid: "Валиден",
  approved: "Утвержден",
  released: "Запущен",
  cancelled: "Отменен",
  completed: "Завершён",
};

const positionStatusColor: Record<string, string> = {
  draft: "bg-gray-100 text-gray-700",
  invalid: "bg-red-100 text-red-700",
  valid: "bg-green-100 text-green-700",
  approved: "bg-blue-100 text-blue-700",
  released: "bg-emerald-100 text-emerald-700",
  cancelled: "bg-red-100 text-red-700",
  completed: "bg-violet-100 text-violet-700",
};

function formatRouteAssignedAt(value: string | null | undefined): string {
  if (!value) return "дата неизвестна";
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return "дата неизвестна";
  return dt.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

type RouteMetaLike = Pick<
  ProductionPlanningRow,
  "route_source" | "route_origin" | "route_match_quality" | "route_assigned_at"
>;

function routeMetaLabel(route: RouteMetaLike): string {
  const assignedAt = formatRouteAssignedAt(route.route_assigned_at);
  if (route.route_origin === "manual_confirmed" || route.route_source === "manual") {
    return `вручную • ${assignedAt}`;
  }
  if (route.route_origin === "auto" || route.route_source === "auto") {
    const quality = route.route_match_quality === "exact" ? "полное" : "скорректирован";
    return `автомаппинг (${quality}) • ${assignedAt}`;
  }
  if (route.route_origin === "legacy" || route.route_source === "legacy") {
    return "legacy • дата неизвестна";
  }
  if (route.route_source === "missing") {
    return "не найден";
  }
  return "—";
}

function fmtQty(value: number): string {
  if (Number.isInteger(value)) {
    return String(value);
  }
  return value.toFixed(3).replace(/\.?0+$/, "");
}

function planPreviewUrl(planId: number): string {
  return `/plans/${planId}/preview`;
}

function calcExecutionPercent(fact: number, plan: number): number {
  if (!Number.isFinite(plan) || plan <= 0) {
    return 0;
  }
  return (fact / plan) * 100;
}

function StatusBadge({ status, isCompleted }: { status: string; isCompleted?: boolean }) {
  const displayStatus = isCompleted ? "completed" : status;
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full ${positionStatusColor[displayStatus] || "bg-gray-100 text-gray-700"}`}>
      {positionStatusLabels[displayStatus] || displayStatus}
    </span>
  );
}

function RowRouteCell({ row }: { row: ProductionPlanningRow }) {
  if (row.route_name) {
    const meta = routeMetaLabel(row);
    return (
      <span className="text-xs text-blue-700">
        {row.route_name}
        <span className="text-muted-foreground"> ({meta})</span>
      </span>
    );
  }
  return <span className="text-xs text-red-600">{row.route_error || "Не назначен"}</span>;
}

type ExecutionSortField = "id" | "row" | "plan" | "sku" | "name" | "qty" | "route" | "status"

export function ExecutionPage() {
  const [selectedPositionId, setSelectedPositionId] = useState<number | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [skuFilter, setSkuFilter] = useState("");
  const [rowFilter, setRowFilter] = useState("");
  const [planFilter, setPlanFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [sortConfigs, setSortConfigs] = useState<SortConfig<ExecutionSortField>>([]);

  const { data: rows, isLoading, error } = useQuery({
    queryKey: ["production-planning-rows"],
    queryFn: listProductionPlanningRows,
  });
  const { data: plans } = useQuery({
    queryKey: ["plans"],
    queryFn: listPlans,
  });
  const { data: sections } = useQuery({
    queryKey: ["sections"],
    queryFn: listSections,
  });

  const { data: detail, isLoading: detailLoading, error: detailError } = useQuery({
    queryKey: ["production-planning-row-detail", selectedPositionId],
    queryFn: () => getProductionPlanningRowDetail(selectedPositionId as number),
    enabled: drawerOpen && selectedPositionId !== null,
  });

  const planNameById = useMemo(() => {
    const map = new Map<number, string>();
    (plans || []).forEach((p) => map.set(p.id, p.plan_no));
    return map;
  }, [plans]);
  const sectionMetaById = useMemo(() => {
    const map = new Map<number, { icon: string | null; icon_color: string | null }>();
    (sections || []).forEach((s) => map.set(s.id, { icon: s.icon, icon_color: s.icon_color }));
    return map;
  }, [sections]);

  const queryClient = useQueryClient();
  const [selectedRows, setSelectedRows] = useState<Set<number>>(new Set());
  const [launchDialog, setLaunchDialog] = useState<{ open: boolean; mode: "single" | "bulk"; positionIds: number[] }>({
    open: false,
    mode: "single",
    positionIds: [],
  });
  const [launchResults, setLaunchResults] = useState<TakeToWorkResult[]>([]);
  const [resultsDialogOpen, setResultsDialogOpen] = useState(false);
  const [manualPassDialog, setManualPassDialog] = useState<{
    open: boolean;
    positionId: number | null;
    targetRouteStepId: string;
    comment: string;
  }>({
    open: false,
    positionId: null,
    targetRouteStepId: "",
    comment: "",
  });

  const { data: manualPassDetail, isLoading: manualPassDetailLoading } = useQuery<ProductionPlanningRowDetail>({
    queryKey: ["production-planning-row-detail", manualPassDialog.positionId],
    queryFn: () => getProductionPlanningRowDetail(manualPassDialog.positionId as number),
    enabled: manualPassDialog.open && manualPassDialog.positionId !== null,
  });

  const takeToWorkMutation = useMutation({
    mutationFn: takeToWork,
    onSuccess: (data) => {
      setLaunchResults(data.results);
      setResultsDialogOpen(true);
      const successCount = data.results.filter((r) => r.status === "success").length;
      const failCount = data.results.filter((r) => r.status === "failed").length;
      const alreadyCount = data.results.filter((r) => r.status === "already_started").length;
      if (failCount > 0) {
        toast({ title: "Частичный успех", description: `${successCount} успешно, ${failCount} ошибок, ${alreadyCount} уже запущено`, variant: "destructive" });
      } else {
        toast({ title: "Запуск завершён", description: `${successCount} запущено, ${alreadyCount} уже было запущено`, variant: "success" });
      }
      queryClient.invalidateQueries({ queryKey: ["production-planning-rows"] });
      setSelectedRows(new Set());
    },
    onError: (err) => toast({ title: "Ошибка запуска", description: getErrorMessage(err), variant: "destructive" }),
  });

  const manualPassMutation = useMutation({
    mutationFn: ({
      positionId,
      targetRouteStepId,
      comment,
    }: {
      positionId: number;
      targetRouteStepId: string;
      comment?: string;
    }) => {
      const completeRoute = targetRouteStepId === "complete";
      return manualPassToStage(positionId, {
        target_route_step_id: completeRoute ? undefined : Number(targetRouteStepId),
        complete_route: completeRoute,
        comment,
        idempotency_key: `manual-pass-${positionId}-${targetRouteStepId}-${Date.now()}`,
      });
    },
    onSuccess: (data) => {
      toast({
        title: data.complete_route
          ? (data.position_completed ? "Задача полностью завершена" : "Сквозной проход выполнен (частично)")
          : "Сквозной проход выполнен",
        description: `Пропущено этапов: ${data.skipped_stages}. Создано фактов: ${data.movements_created}.`,
        variant: data.complete_route && !data.position_completed ? "destructive" : "success",
      });
      queryClient.invalidateQueries({ queryKey: ["production-planning-rows"] });
      queryClient.invalidateQueries({ queryKey: ["production-planning-row-detail", data.position_id] });
      setManualPassDialog({ open: false, positionId: null, targetRouteStepId: "", comment: "" });
    },
    onError: (err) => toast({ title: "Ошибка сквозного прохода", description: getErrorMessage(err), variant: "destructive" }),
  });

  const [cancelDialog, setCancelDialog] = useState<{ open: boolean; positionId: number | null; isReleased: boolean }>({
    open: false,
    positionId: null,
    isReleased: false,
  });

  const cancelPositionMutation = useMutation({
    mutationFn: cancelPositionExecution,
    onSuccess: () => {
      toast({ title: "Позиция отменена", variant: "success" });
      queryClient.invalidateQueries({ queryKey: ["production-planning-rows"] });
    },
    onError: (err) => toast({ title: "Ошибка отмены", description: getErrorMessage(err), variant: "destructive" }),
  });

  const [restoreDialog, setRestoreDialog] = useState<{ open: boolean; positionId: number | null; reason: string }>({
    open: false,
    positionId: null,
    reason: "",
  });

  const restorePositionMutation = useMutation({
    mutationFn: ({ positionId, reason }: { positionId: number; reason?: string }) => restorePositionExecution(positionId, reason),
    onSuccess: () => {
      toast({ title: "Позиция восстановлена", variant: "success" });
      queryClient.invalidateQueries({ queryKey: ["production-planning-rows"] });
    },
    onError: (err) => toast({ title: "Ошибка восстановления", description: getErrorMessage(err), variant: "destructive" }),
  });

  const [deleteDialog, setDeleteDialog] = useState<{ open: boolean; positionId: number | null; reason: string }>({
    open: false,
    positionId: null,
    reason: "",
  });

  const softDeleteMutation = useMutation({
    mutationFn: ({ planId, positionId, reason }: { planId: number; positionId: number; reason?: string }) =>
      softDeleteCancelledPosition(planId, positionId, reason),
    onSuccess: () => {
      toast({ title: "Позиция удалена из списка", variant: "success" });
      queryClient.invalidateQueries({ queryKey: ["production-planning-rows"] });
    },
    onError: (err) => toast({ title: "Ошибка удаления", description: getErrorMessage(err), variant: "destructive" }),
  });

  const [historyEntries, setHistoryEntries] = useState<StatusHistoryEntry[]>([]);
  const [historyDialogOpen, setHistoryDialogOpen] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);

  const openHistory = useCallback(async (row: ProductionPlanningRow) => {
    setHistoryLoading(true);
    setHistoryEntries([]);
    setHistoryDialogOpen(true);
    try {
      const entries = await getPositionHistory(row.production_plan_id, row.plan_position_id);
      setHistoryEntries(entries);
    } catch (e) {
      toast({ title: "Ошибка загрузки истории", description: getErrorMessage(e), variant: "destructive" });
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  const isRowLaunched = useCallback((row: ProductionPlanningRow) => {
    return row.has_tasks || row.is_released;
  }, []);

  const getLaunchBlockReason = useCallback((row: ProductionPlanningRow) => {
    if (row.is_completed) return "Уже завершено";
    if (row.has_tasks || row.is_released) return "Уже запущено";
    if (row.position_status !== "approved") return `Статус "${positionStatusLabels[row.position_status] || row.position_status}"`;
    if (!row.route_id) return row.route_error || "Нет маршрута";
    return null;
  }, []);

  const handleSingleLaunch = useCallback((row: ProductionPlanningRow) => {
    const reason = getLaunchBlockReason(row);
    if (reason) {
      toast({ title: "Невозможно запустить", description: reason, variant: "destructive" });
      return;
    }
    setLaunchDialog({ open: true, mode: "single", positionIds: [row.plan_position_id] });
  }, [getLaunchBlockReason]);

  const handleManualPass = useCallback((row: ProductionPlanningRow) => {
    if (!row.route_id || !["approved", "released"].includes(row.position_status)) {
      toast({ title: "Невозможно выполнить сквозной проход", description: "Нужна утвержденная или запущенная строка с маршрутом", variant: "destructive" });
      return;
    }
    setManualPassDialog({
      open: true,
      positionId: row.plan_position_id,
      targetRouteStepId: "",
      comment: "",
    });
  }, []);

  const handleBulkLaunch = useCallback(() => {
    const ids = Array.from(selectedRows);
    if (ids.length === 0) {
      toast({ title: "Выберите строки", description: "Отметьте строки для запуска", variant: "destructive" });
      return;
    }
    setLaunchDialog({ open: true, mode: "bulk", positionIds: ids });
  }, [selectedRows]);

  const toggleRowSelection = useCallback((positionId: number, checked: boolean) => {
    setSelectedRows((prev) => {
      const next = new Set(prev);
      if (checked) next.add(positionId);
      else next.delete(positionId);
      return next;
    });
  }, []);

  const confirmLaunch = useCallback(() => {
    takeToWorkMutation.mutate(launchDialog.positionIds);
    setLaunchDialog({ open: false, mode: "single", positionIds: [] });
  }, [launchDialog.positionIds, takeToWorkMutation]);

  const confirmManualPass = useCallback(() => {
    if (!manualPassDialog.positionId || !manualPassDialog.targetRouteStepId) return;
    manualPassMutation.mutate({
      positionId: manualPassDialog.positionId,
      targetRouteStepId: manualPassDialog.targetRouteStepId,
      comment: manualPassDialog.comment.trim() || undefined,
    });
  }, [manualPassDialog.comment, manualPassDialog.positionId, manualPassDialog.targetRouteStepId, manualPassMutation]);

  const handleCancel = useCallback((row: ProductionPlanningRow) => {
    setCancelDialog({ open: true, positionId: row.plan_position_id, isReleased: row.is_released });
  }, []);

  const handleRestore = useCallback((row: ProductionPlanningRow) => {
    setRestoreDialog({ open: true, positionId: row.plan_position_id, reason: "" });
  }, []);

  const handleSoftDelete = useCallback((row: ProductionPlanningRow) => {
    setDeleteDialog({ open: true, positionId: row.plan_position_id, reason: "" });
  }, []);

  const confirmRestore = useCallback(() => {
    if (restoreDialog.positionId) {
      restorePositionMutation.mutate({ positionId: restoreDialog.positionId, reason: restoreDialog.reason || undefined });
    }
    setRestoreDialog({ open: false, positionId: null, reason: "" });
  }, [restoreDialog.positionId, restoreDialog.reason, restorePositionMutation]);

  const confirmSoftDelete = useCallback(() => {
    if (deleteDialog.positionId) {
      // We need planId - get it from the row data
      const row = rows?.find((r) => r.plan_position_id === deleteDialog.positionId);
      if (row) {
        softDeleteMutation.mutate({ planId: row.production_plan_id, positionId: deleteDialog.positionId, reason: deleteDialog.reason || undefined });
      }
    }
    setDeleteDialog({ open: false, positionId: null, reason: "" });
  }, [deleteDialog.positionId, deleteDialog.reason, rows, softDeleteMutation]);

  const confirmCancel = useCallback(() => {
    if (cancelDialog.positionId) {
      cancelPositionMutation.mutate(cancelDialog.positionId);
    }
    setCancelDialog({ open: false, positionId: null, isReleased: false });
  }, [cancelDialog.positionId, cancelPositionMutation]);

  const executionActiveFilterSummary = useMemo(() => {
    const labels: string[] = [];
    if (skuFilter.trim()) labels.push("SKU/наименование");
    if (rowFilter.trim()) labels.push("Номер строки");
    if (planFilter.trim()) labels.push("План");
    if (statusFilter !== "all") labels.push("Статус");
    return { count: labels.length, labels };
  }, [planFilter, rowFilter, skuFilter, statusFilter]);
  const resetExecutionFilters = useCallback(() => {
    setSkuFilter("");
    setRowFilter("");
    setPlanFilter("");
    setStatusFilter("all");
  }, []);
  const executionFilterFields = useMemo<FiltersPanelField[]>(
    () => [
      {
        kind: "search",
        key: "sku",
        value: skuFilter,
        onChange: setSkuFilter,
        placeholder: "Поиск по SKU / наименованию",
      },
      {
        kind: "search",
        key: "row",
        value: rowFilter,
        onChange: setRowFilter,
        placeholder: "Фильтр по номеру строки",
      },
      {
        kind: "search",
        key: "plan",
        value: planFilter,
        onChange: setPlanFilter,
        placeholder: "Фильтр по плану (ID или PLAN-...)",
      },
      {
        kind: "select",
        key: "status",
        value: statusFilter,
        onChange: setStatusFilter,
        placeholder: "Статус",
        options: [
          { value: "all", label: "Все статусы" },
          { value: "approved", label: "Утвержден" },
          { value: "released", label: "В работе" },
          { value: "completed", label: "Завершён" },
          { value: "cancelled", label: "Отменен" },
        ],
      },
    ],
    [planFilter, rowFilter, skuFilter, statusFilter],
  );

  // Build filter predicate from execution filters
  const executionFilterPredicate = useMemo(() => {
    if (
      statusFilter === "all" &&
      !skuFilter.trim() &&
      !rowFilter.trim() &&
      !planFilter.trim()
    ) {
      return null;
    }

    return (row: ProductionPlanningRow) => {
      if (statusFilter === "completed" && !row.is_completed) return false;
      if (statusFilter !== "all" && statusFilter !== "completed" && row.position_status !== statusFilter) return false;
      if (skuFilter.trim()) {
        const skuTerm = skuFilter.trim().toLowerCase();
        if (!row.source_sku.toLowerCase().includes(skuTerm) && !(row.source_name || "").toLowerCase().includes(skuTerm)) {
          return false;
        }
      }
      if (rowFilter.trim()) {
        const rowTerm = rowFilter.trim();
        if (!String(row.source_row_number ?? "").includes(rowTerm)) return false;
      }
      if (planFilter.trim()) {
        const planTerm = planFilter.trim().toLowerCase();
        const planText = `${row.production_plan_id} ${planNameById.get(row.production_plan_id) || ""}`.toLowerCase();
        if (!planText.includes(planTerm)) return false;
      }
      return true;
    };
  }, [statusFilter, skuFilter, rowFilter, planFilter, planNameById]);

  // Sort definitions for ExecutionPage columns
  const executionSortDefs: ColumnSortDef<ProductionPlanningRow, ExecutionSortField>[] = useMemo(() => [
    { field: "id", getSortValue: (r) => r.plan_position_id },
    { field: "row", getSortValue: (r) => r.source_row_number ?? 0 },
    { field: "plan", getSortValue: (r) => r.production_plan_id },
    { field: "sku", getSortValue: (r) => r.source_sku },
    { field: "name", getSortValue: (r) => r.source_name || "" },
    { field: "qty", getSortValue: (r) => r.quantity },
    { field: "route", getSortValue: (r) => r.route_name || "" },
    { field: "status", getSortValue: (r) => r.position_status },
  ], []);

  const executionQueryResult = useTableQueryEngine<ProductionPlanningRow, ExecutionSortField>({
    rows: rows || [],
    getId: (r) => r.plan_position_id,
    searchQuery: "",
    filterPredicate: executionFilterPredicate,
    sortConfigs,
    sortDefs: executionSortDefs,
  });
  const filteredRows = executionQueryResult.rows;

  const tableScrollRef = useRef<HTMLDivElement>(null);

  const totalRows = rows?.length || 0;
  const releasedRows = rows?.filter((r) => r.is_released && !r.is_completed).length || 0;
  const rowsWithTasks = rows?.filter((r) => r.has_tasks).length || 0;
  const completedRows = rows?.filter((r) => r.is_completed).length || 0;

  // Sort toggle handler: click cycles none -> asc -> desc -> removed
  const handleSortChange = (field: ExecutionSortField) => {
    setSortConfigs((prev) => nextMultiSortConfigs(prev, field));
  };

  const getAriaSort = (field: ExecutionSortField): "none" | "ascending" | "descending" => {
    const active = sortConfigs.find((s) => s.field === field);
    if (!active) return "none";
    return active.order === "asc" ? "ascending" : "descending";
  };

  const openDetail = (positionId: number) => {
    setSelectedPositionId(positionId);
    setDrawerOpen(true);
  };

  if (isLoading) {
    return <div className="p-6 text-sm text-muted-foreground">Загрузка...</div>;
  }

  if (error) {
    return <div className="p-6 text-sm text-red-600">Ошибка загрузки: {String(error)}</div>;
  }

  return (
    <>
      <header className="page-header">
        <div>
          <h1 className="page-title">Контроль выполнения</h1>
          <div className="flex gap-3 text-sm">
            <span className="px-3 py-1 rounded-full bg-muted">Строк всего: {totalRows}</span>
            <span className="px-3 py-1 rounded-full bg-emerald-100 text-emerald-700">В работе: {releasedRows}</span>
            <span className="px-3 py-1 rounded-full bg-violet-100 text-violet-700">Завершено: {completedRows}</span>
          </div>
        </div>
        {selectedRows.size > 0 && (
          <Button onClick={handleBulkLaunch} variant="default">
            <span className="ml-1">Взять выбранные в работу ({selectedRows.size})</span>
          </Button>
        )}
      </header>

      <section className="space-y-3">
        <FiltersPanel
          fields={executionFilterFields}
          onReset={resetExecutionFilters}
          hasActiveFilters={executionActiveFilterSummary.count > 0}
          activeSummary={executionActiveFilterSummary}
        />

        <div ref={tableScrollRef} className="rounded-lg border overflow-auto max-h-[70vh]">
          <table className="w-full border-separate border-spacing-0">
            <thead className="[&_th]:sticky [&_th]:top-0 [&_th]:z-20 [&_th]:bg-background [&_th]:border-b">
              <tr>
                <th className="text-left p-2 w-20" aria-sort={getAriaSort("id")}>
                  <SortableHeader field="id" currentSorts={sortConfigs} onSortChange={handleSortChange}>ID</SortableHeader>
                </th>
                <th className="text-left p-2 w-8"></th>
                <th className="text-left p-2" aria-sort={getAriaSort("row")}>
                  <SortableHeader field="row" currentSorts={sortConfigs} onSortChange={handleSortChange}>Строка</SortableHeader>
                </th>
                <th className="text-left p-2" aria-sort={getAriaSort("plan")}>
                  <SortableHeader field="plan" currentSorts={sortConfigs} onSortChange={handleSortChange}>План</SortableHeader>
                </th>
                <th className="text-left p-2" aria-sort={getAriaSort("sku")}>
                  <SortableHeader field="sku" currentSorts={sortConfigs} onSortChange={handleSortChange}>SKU</SortableHeader>
                </th>
                <th className="text-left p-2" aria-sort={getAriaSort("name")}>
                  <SortableHeader field="name" currentSorts={sortConfigs} onSortChange={handleSortChange}>Наименование</SortableHeader>
                </th>
                <th className="text-left p-2" aria-sort={getAriaSort("qty")}>
                  <SortableHeader field="qty" currentSorts={sortConfigs} onSortChange={handleSortChange}>Кол-во</SortableHeader>
                </th>
                <th className="text-left p-2">Маршрут</th>
                <th className="text-left p-2" aria-sort={getAriaSort("status")}>
                  <SortableHeader field="status" currentSorts={sortConfigs} onSortChange={handleSortChange}>Статус</SortableHeader>
                </th>
                <th className="text-left p-2">Задачи</th>
                <th className="text-left p-2">Действия</th>
              </tr>
            </thead>
            <VirtualizedTableBody
              rows={filteredRows}
              rowHeight={48}
              colSpan={11}
              scrollContainerRef={tableScrollRef}
              renderRow={(row) => {
                const canLaunch = row.position_status === "approved" && !row.has_tasks && !row.is_released && !!row.route_id;
                const canManualPass = !!row.route_id && ["approved", "released"].includes(row.position_status) && !row.is_completed;
                const blockReason = getLaunchBlockReason(row);
                return (
                <tr
                  key={row.plan_position_id}
                  className="border-b hover:bg-accent hover:ring-1 hover:ring-ring/20 cursor-pointer transition-colors"
                  onClick={() => openDetail(row.plan_position_id)}
                >
                  <td className="p-2 font-mono text-xs text-muted-foreground">#{row.plan_position_id}</td>
                  <td className="p-2" onClick={(e) => e.stopPropagation()}>
                    {canLaunch && (
                      <Checkbox
                        checked={selectedRows.has(row.plan_position_id)}
                        onCheckedChange={(checked) => toggleRowSelection(row.plan_position_id, !!checked)}
                      />
                    )}
                  </td>
                  <td className="p-2">#{row.source_row_number ?? "—"}</td>
                  <td className="p-2">
                    {(() => {
                      const planName = planNameById.get(row.production_plan_id) || "—";
                      return (
                        <>
                          <div className="text-xs text-muted-foreground">{row.production_plan_id}</div>
                          {planName !== "—" ? (
                            <a
                              href={planPreviewUrl(row.production_plan_id)}
                              target="_blank"
                              rel="noreferrer"
                              title={planName}
                              className="text-blue-700 hover:underline inline-block max-w-[240px] truncate align-bottom"
                              onClick={(e) => e.stopPropagation()}
                            >
                              План
                            </a>
                          ) : (
                            <div>—</div>
                          )}
                        </>
                      );
                    })()}
                  </td>
                  <td className="p-2 font-mono">{row.source_sku}</td>
                  <td className="p-2">{row.source_name || "—"}</td>
                  <td className="p-2">{fmtQty(row.quantity)}</td>
                  <td className="p-2">
                    <RowRouteCell row={row} />
                  </td>
                  <td className="p-2">
                    <StatusBadge status={row.position_status} isCompleted={row.is_completed} />
                  </td>
                  <td className="p-2">
                    {row.route_steps && row.route_steps.length > 0 ? (
                      <StepIndicator
                        steps={row.route_steps}
                        currentStageSequence={row.current_stage_sequence}
                        currentStageTaskStatus={row.current_stage_task_status}
                        sectionMetaById={sectionMetaById}
                      />
                    ) : row.has_tasks ? (
                      <Badge variant="secondary">Задачи созданы</Badge>
                    ) : (
                      <Badge variant="secondary">Нет</Badge>
                    )}
                  </td>
                  <td className="p-2" onClick={(e) => e.stopPropagation()}>
                    <div className="flex gap-1">
                      {canLaunch ? (
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => handleSingleLaunch(row)}
                        >
                          Взять в работу
                        </Button>
                      ) : (
                        <span
                          className="text-xs text-muted-foreground"
                          title={blockReason || ""}
                        >
                          {blockReason || "—"}
                        </span>
                      )}
                      {canManualPass && (
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => handleManualPass(row)}
                        >
                          Сквозной проход
                        </Button>
                      )}
                      {row.position_status === "approved" && (
                        <Button
                          size="sm"
                          variant="ghost"
                          className="text-red-600 hover:text-red-700"
                          onClick={() => handleCancel(row)}
                        >
                          Отменить
                        </Button>
                      )}
                      {row.position_status === "released" && (
                        <Button
                          size="sm"
                          variant="ghost"
                          className="text-red-600 hover:text-red-700"
                          onClick={() => handleCancel(row)}
                        >
                          Остановить
                        </Button>
                      )}
                      {row.position_status === "cancelled" && (
                        <>
                          <Button
                            size="sm"
                            variant="ghost"
                            className="text-green-600 hover:text-green-700"
                            onClick={() => handleRestore(row)}
                          >
                            Восстановить
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            className="text-red-600 hover:text-red-700"
                            onClick={() => handleSoftDelete(row)}
                          >
                            Удалить из списка
                          </Button>
                        </>
                      )}
                      <Button
                        size="sm"
                        variant="ghost"
                        className="text-gray-500 hover:text-gray-700"
                        onClick={() => openHistory(row)}
                      >
                        История
                      </Button>
                    </div>
                  </td>
                </tr>
                );
              }}
            />
          </table>
          {filteredRows.length === 0 && <p className="p-4 text-sm text-muted-foreground text-center">Нет строк по выбранному фильтру</p>}
        </div>
      </section>

      <RowDetailsSidePanel
        open={drawerOpen}
        onOpenChange={(open) => {
          setDrawerOpen(open);
          if (!open) {
            setSelectedPositionId(null);
          }
        }}
        data={detail ? adaptExecutionDetail(detail) : null}
        loading={detailLoading}
        error={detailError ? String(detailError) : null}
      />

      <Dialog
        open={launchDialog.open}
        onOpenChange={(open) => {
          if (!open) setLaunchDialog({ open: false, mode: "single", positionIds: [] });
        }}
      >
        <DialogContent className="sm:max-w-[480px]">
          <DialogHeader>
            <DialogTitle>Взять в работу</DialogTitle>
            <DialogDescription>
              {launchDialog.mode === "single"
                ? "Будут созданы задачи по всем этапам маршрута для выбранной строки."
                : `Будут созданы задачи по всем этапам маршрута для ${launchDialog.positionIds.length} выбранных строк.`}
            </DialogDescription>
          </DialogHeader>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => setLaunchDialog({ open: false, mode: "single", positionIds: [] })}>
              Отмена
            </Button>
            <Button onClick={confirmLaunch} disabled={takeToWorkMutation.isPending}>
              {takeToWorkMutation.isPending ? "Запуск..." : "Запустить"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog
        open={manualPassDialog.open}
        onOpenChange={(open) => {
          if (!open) setManualPassDialog({ open: false, positionId: null, targetRouteStepId: "", comment: "" });
        }}
      >
        <DialogContent className="sm:max-w-[560px]">
          <DialogHeader>
            <DialogTitle>Сквозной проход</DialogTitle>
            <DialogDescription>
              Система создаст задачи маршрута при необходимости и оформит предыдущие этапы как ручной пропуск. Выбранный этап останется готовым к работе.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            {manualPassDetailLoading ? (
              <p className="text-sm text-muted-foreground">Загрузка маршрута...</p>
            ) : (
              <>
                <div className="space-y-1.5">
                  <div className="text-sm font-medium">Остановиться на этапе</div>
                  <Select
                    value={manualPassDialog.targetRouteStepId}
                    onValueChange={(value) => setManualPassDialog((prev) => ({ ...prev, targetRouteStepId: value }))}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="Выберите этап маршрута" />
                    </SelectTrigger>
                    <SelectContent>
                      {(manualPassDetail?.stages || []).map((stage) => (
                        <SelectItem key={stage.route_step_id} value={String(stage.route_step_id)}>
                          #{stage.sequence} · {stage.section_name} · {stage.operation_name || "Операция"}
                        </SelectItem>
                      ))}
                      {(manualPassDetail?.stages?.length || 0) > 0 && (
                        <SelectItem value="complete">
                          Полное завершение задачи
                        </SelectItem>
                      )}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <div className="text-sm font-medium">Комментарий</div>
                  <Input
                    placeholder="Необязательно"
                    value={manualPassDialog.comment}
                    onChange={(e) => setManualPassDialog((prev) => ({ ...prev, comment: e.target.value }))}
                  />
                </div>
                {manualPassDialog.targetRouteStepId && manualPassDetail && (
                  <div className="rounded border bg-muted/40 p-3 text-sm text-muted-foreground">
                    {manualPassDialog.targetRouteStepId === "complete"
                      ? "Будут вручную закрыты все этапы маршрута. Все созданные факты получат текущее время выполнения и учёта."
                      : "Будут вручную закрыты этапы до выбранного. Все созданные факты получат текущее время выполнения и учёта."}
                  </div>
                )}
              </>
            )}
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => setManualPassDialog({ open: false, positionId: null, targetRouteStepId: "", comment: "" })}>
              Отмена
            </Button>
            <Button
              onClick={confirmManualPass}
              disabled={manualPassMutation.isPending || manualPassDetailLoading || !manualPassDialog.targetRouteStepId}
            >
              {manualPassMutation.isPending ? "Выполнение..." : "Выполнить"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <AlertDialog
        open={cancelDialog.open}
        onOpenChange={(open) => {
          if (!open) setCancelDialog({ open: false, positionId: null, isReleased: false });
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{cancelDialog.isReleased ? "Остановить выполнение?" : "Отменить позицию?"}</AlertDialogTitle>
            <AlertDialogDescription>
              {cancelDialog.isReleased
                ? "Позиция уже запущена. Остановка выполнения переведёт её в статус «Отменен»."
                : "Отмена переведёт позицию в статус «Отменен»."}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Отмена</AlertDialogCancel>
            <AlertDialogAction className="bg-destructive text-destructive-foreground hover:bg-destructive/90" onClick={confirmCancel} disabled={cancelPositionMutation.isPending}>
              {cancelPositionMutation.isPending ? "Отмена..." : cancelDialog.isReleased ? "Остановить" : "Отменить"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog
        open={restoreDialog.open}
        onOpenChange={(open) => {
          if (!open) setRestoreDialog({ open: false, positionId: null, reason: "" });
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Восстановить позицию?</AlertDialogTitle>
            <AlertDialogDescription>
              Позиция будет восстановлена в предыдущий статус. Это действие нельзя отменить.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="py-2">
            <Input
              placeholder="Причина (необязательно)"
              value={restoreDialog.reason}
              onChange={(e) => setRestoreDialog((prev) => ({ ...prev, reason: e.target.value }))}
            />
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel>Отмена</AlertDialogCancel>
            <AlertDialogAction onClick={confirmRestore} disabled={restorePositionMutation.isPending}>
              {restorePositionMutation.isPending ? "Восстановление..." : "Восстановить"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog
        open={deleteDialog.open}
        onOpenChange={(open) => {
          if (!open) setDeleteDialog({ open: false, positionId: null, reason: "" });
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Удалить из списка?</AlertDialogTitle>
            <AlertDialogDescription>
              Позиция будет скрыта из всех рабочих списков. История изменений сохранится.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="py-2">
            <Input
              placeholder="Причина (необязательно)"
              value={deleteDialog.reason}
              onChange={(e) => setDeleteDialog((prev) => ({ ...prev, reason: e.target.value }))}
            />
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel>Отмена</AlertDialogCancel>
            <AlertDialogAction className="bg-destructive text-destructive-foreground hover:bg-destructive/90" onClick={confirmSoftDelete} disabled={softDeleteMutation.isPending}>
              {softDeleteMutation.isPending ? "Удаление..." : "Удалить из списка"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <Dialog
        open={resultsDialogOpen}
        onOpenChange={(open) => {
          if (!open) setResultsDialogOpen(false);
        }}
      >
        <DialogContent className="sm:max-w-[560px]">
          <DialogHeader>
            <DialogTitle>Результат запуска</DialogTitle>
            <DialogDescription>
              {launchResults.filter((r) => r.status === "success").length} успешно,{" "}
              {launchResults.filter((r) => r.status === "already_started").length} уже запущено,{" "}
              {launchResults.filter((r) => r.status === "failed").length} ошибок
            </DialogDescription>
          </DialogHeader>
          <div className="max-h-[320px] overflow-auto space-y-2">
            {launchResults.map((result) => (
              <div key={result.position_id} className="rounded border p-2 text-sm">
                <div className="flex items-center justify-between">
                  <span className="font-medium">Позиция #{result.position_id}</span>
                  <Badge
                    variant={result.status === "success" ? "default" : result.status === "already_started" ? "secondary" : "destructive"}
                  >
                    {result.status === "success" ? "Успешно" : result.status === "already_started" ? "Уже запущено" : "Ошибка"}
                  </Badge>
                </div>
                {result.reason && <div className="text-xs text-muted-foreground mt-1">{result.reason}</div>}
                {result.tasks_created != null && (
                  <div className="text-xs text-muted-foreground mt-1">Задач создано: {result.tasks_created}</div>
                )}
              </div>
            ))}
          </div>
          <div className="flex justify-end pt-2">
            <Button onClick={() => setResultsDialogOpen(false)}>Закрыть</Button>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog
        open={historyDialogOpen}
        onOpenChange={(open) => {
          if (!open) setHistoryDialogOpen(false);
        }}
      >
        <DialogContent className="sm:max-w-[560px]">
          <DialogHeader>
            <DialogTitle>История статусов</DialogTitle>
            <DialogDescription>Хронология изменений статуса позиции</DialogDescription>
          </DialogHeader>
          {historyLoading ? (
            <p className="text-sm text-muted-foreground py-4">Загрузка истории...</p>
          ) : historyEntries.length === 0 ? (
            <p className="text-sm text-muted-foreground py-4">История изменений отсутствует</p>
          ) : (
            <div className="max-h-[400px] overflow-auto space-y-2">
              {historyEntries.map((entry) => (
                <div key={entry.id} className="rounded border p-3 text-sm">
                  <div className="flex items-center justify-between">
                    <span className="font-medium">
                      {positionStatusLabels[entry.from_status] || entry.from_status} → {positionStatusLabels[entry.to_status] || entry.to_status}
                    </span>
                    <Badge variant="secondary">{new Date(entry.changed_at).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" })}</Badge>
                  </div>
                  {entry.reason && <div className="text-xs text-muted-foreground mt-1">{entry.reason}</div>}
                </div>
              ))}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
