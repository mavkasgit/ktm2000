import { useMemo, useState, useCallback, useRef, useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getProductionPlanningRowDetail,
  listPlans,
  listProductionPlanningRows,
  manualPassToStage,
  takeToWork,
  cancelPositionExecution,
  cancelPositionsExecutionBatch,
  restorePositionExecution,
  restorePositionsExecutionBatch,
  softDeleteCancelledPosition,
  softDeletePositionsExecutionBatch,
  manualPassPositionsExecutionBatch,
  getPositionHistory,
  type ProductionPlanningRow,
  type StatusHistoryEntry,
  type ProductionPlanningRowDetail,
} from "@/shared/api/productionPlans";
import { listSections } from "@/shared/api/sections";
import { useTableQueryEngine, SortConfig, ColumnSortDef } from "@/shared/hooks/useTableQueryEngine";
import { nextMultiSortConfigs } from "@/shared/lib/multiSort";
import { toast } from "@/shared/ui/use-toast";
import { getErrorMessage } from "@/shared/api/client";
import { queryKeys } from "@/shared/api/queryKeys";
import {
  BulkResultsDialog,
  runBulkAction,
  summarizeBulkResults,
  useBulkHotkeys,
  useBulkSelection,
  type BulkActionDefinition,
  type BulkActionResultItem,
  type BulkActionSummary,
  type BulkRunnerProgress,
} from "@/shared/bulk";
import { ExecutionTable } from "../components/ExecutionTable";
import { ExecutionDialogs } from "../components/ExecutionDialogs";
import { ProductWipStatsDialog } from "../components/ProductWipStatsDialog";
import {
  ExecutionSortField,
  positionStatusLabels,
  fmtQty,
  getLaunchBlockReason,
  getCancelBlockReason,
  getRestoreBlockReason,
  getSoftDeleteBlockReason,
  getManualPassBlockReason,
  getCellValue,
} from "../components/execution-utils";

export function ExecutionPage() {
  const [selectedPositionId, setSelectedPositionId] = useState<number | null>(null);
  const [wipStatsSku, setWipStatsSku] = useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [hideColumnIds, setHideColumnIds] = useState(false);
  const [sortConfigs, setSortConfigs] = useState<SortConfig<ExecutionSortField>[]>([]);
  const [columnFilters, setColumnFilters] = useState<
    Partial<Record<ExecutionSortField, Set<string>>>
  >({});

  const handleColumnFilterChange = useCallback(
    (field: ExecutionSortField, selected: Set<string>) => {
      setColumnFilters((prev) => ({ ...prev, [field]: selected }));
    },
    [],
  );

  const { data: rows, isLoading, error } = useQuery({
    queryKey: queryKeys.execution.rows(),
    queryFn: listProductionPlanningRows,
  });
  const { data: plans } = useQuery({
    queryKey: queryKeys.execution.plans(),
    queryFn: listPlans,
  });
  const { data: sections } = useQuery({
    queryKey: queryKeys.sections.all(),
    queryFn: listSections,
  });

  const { data: detail, isLoading: detailLoading, error: detailError } = useQuery({
    queryKey: queryKeys.execution.rowDetail(selectedPositionId as number),
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

  const invalidateAll = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: queryKeys.execution.rows() });
    queryClient.invalidateQueries({ queryKey: queryKeys.execution.rowDetailAll() });
    queryClient.invalidateQueries({ queryKey: queryKeys.execution.plans() });
    queryClient.invalidateQueries({ queryKey: queryKeys.shopfloor.boardAll() });
    queryClient.invalidateQueries({ queryKey: queryKeys.shopfloor.statsAll() });
    queryClient.invalidateQueries({ queryKey: queryKeys.shopfloor.summary() });
    queryClient.invalidateQueries({ queryKey: queryKeys.shopfloor.incomingTransfersAll() });
    queryClient.invalidateQueries({ queryKey: queryKeys.transfers.readyAll() });
    queryClient.invalidateQueries({ queryKey: queryKeys.transfers.historyAll() });
    queryClient.invalidateQueries({ queryKey: queryKeys.spg.snapshotAll() });
    queryClient.invalidateQueries({ queryKey: queryKeys.spg.remaindersAll() });
    queryClient.invalidateQueries({ queryKey: queryKeys.spg.defectsAll() });
    queryClient.invalidateQueries({ queryKey: queryKeys.plan.allPositions() });
    queryClient.invalidateQueries({ queryKey: queryKeys.plan.previewAll() });
    queryClient.invalidateQueries({ queryKey: queryKeys.sections.all() });
  }, [queryClient]);

  const bulkSelection = useBulkSelection<number>();
  const [selectedBulkActionId, setSelectedBulkActionId] = useState("take-to-work");
  const [bulkProgress, setBulkProgress] = useState<BulkRunnerProgress | null>(null);
  const [bulkResults, setBulkResults] = useState<BulkActionResultItem<number>[]>([]);
  const [bulkSummary, setBulkSummary] = useState<BulkActionSummary | null>(null);
  const [bulkResultsOpen, setBulkResultsOpen] = useState(false);
  const [bulkMode, setBulkMode] = useState(false);
  const [selectionOrder, setSelectionOrder] = useState<number[]>([]);
  const [bulkSoftDeleting, setBulkSoftDeleting] = useState(false);
  const [bulkDeleteConfirmOpen, setBulkDeleteConfirmOpen] = useState(false);
  const [launchDialog, setLaunchDialog] = useState<{ open: boolean; mode: "single" | "bulk"; positionIds: number[] }>({
    open: false,
    mode: "single",
    positionIds: [],
  });
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
  const [manualPassBulkDialog, setManualPassBulkDialog] = useState<{
    open: boolean;
    targetRouteStepId: string;
    comment: string;
    positionIds: number[];
  }>({
    open: false,
    targetRouteStepId: "",
    comment: "",
    positionIds: [],
  });

  const { data: manualPassDetail, isLoading: manualPassDetailLoading } = useQuery<ProductionPlanningRowDetail>({
    queryKey: queryKeys.execution.rowDetail(manualPassDialog.positionId as number),
    queryFn: () => getProductionPlanningRowDetail(manualPassDialog.positionId as number),
    enabled: manualPassDialog.open && manualPassDialog.positionId !== null,
  });

  const takeToWorkMutation = useMutation({
    mutationFn: takeToWork,
    onSuccess: (data) => {
      const results = data.results.map<BulkActionResultItem<number>>((result) => ({
        id: result.position_id,
        status: result.status === "already_started" ? "skipped" : result.status,
        reason: result.reason,
        meta: { tasks_created: result.tasks_created },
      }));
      const summary = summarizeBulkResults(results);
      setBulkResults(results);
      setBulkSummary(summary);
      if (summary.failed > 0 || summary.skipped > 0) setBulkResultsOpen(true);
      const successCount = summary.success;
      const failCount = summary.failed;
      const alreadyCount = summary.skipped;
      if (failCount > 0) {
        toast({ title: "Частичный успех", description: `${successCount} успешно, ${failCount} ошибок, ${alreadyCount} уже запущено`, variant: "destructive" });
      } else {
        toast({ title: "Запуск завершён", description: `${successCount} запущено, ${alreadyCount} уже было запущено`, variant: "success" });
      }
      invalidateAll();
      bulkSelection.clear();
      setSelectionOrder([]);
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
      invalidateAll();
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
      invalidateAll();
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
      invalidateAll();
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
      invalidateAll();
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

  const handleSingleLaunch = useCallback((row: ProductionPlanningRow) => {
    const reason = getLaunchBlockReason(row);
    if (reason) {
      toast({ title: "Невозможно запустить", description: reason, variant: "destructive" });
      return;
    }
    takeToWorkMutation.mutate([row.plan_position_id]);
  }, [takeToWorkMutation]);

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

  const requestBulkManualPass = useCallback(() => {
    if (bulkSelection.selectedCount === 0) return;
    setManualPassBulkDialog({
      open: true,
      targetRouteStepId: "",
      comment: "",
      positionIds: Array.from(bulkSelection.selectedIds),
    });
  }, [bulkSelection.selectedCount, bulkSelection.selectedIds]);

  const confirmBulkManualPass = useCallback(async () => {
    if (!manualPassBulkDialog.targetRouteStepId || manualPassBulkDialog.positionIds.length === 0) return;
    setManualPassBulkDialog((prev) => ({ ...prev, open: false }));
    const selectedPositionsMap = new Map(rows?.map((r) => [r.plan_position_id, r]) ?? []);
    const results: BulkActionResultItem<number>[] = [];
    setBulkProgress({ total: manualPassBulkDialog.positionIds.length, completed: 0, running: true });

    // Pre-filter: only send eligible positions to the bulk endpoint.
    const eligibleIds: number[] = [];
    for (const id of manualPassBulkDialog.positionIds) {
      const row = selectedPositionsMap.get(id);
      if (!row) {
        results.push({ id, status: "failed", reason: "Позиция не найдена" });
      } else if (!row.route_id || !["approved", "released"].includes(row.position_status)) {
        results.push({ id, status: "skipped", reason: "Нужна утвержденная или запущенная строка с маршрутом" });
      } else {
        eligibleIds.push(id);
      }
    }

    if (eligibleIds.length > 0) {
      const completeRoute = manualPassBulkDialog.targetRouteStepId === "complete";
      try {
        const response = await manualPassPositionsExecutionBatch({
          position_ids: eligibleIds,
          target_route_stage_id: completeRoute ? null : Number(manualPassBulkDialog.targetRouteStepId),
          complete_route: completeRoute,
          comment: manualPassBulkDialog.comment.trim() || null,
          idempotency_key: `manual-pass-bulk-${manualPassBulkDialog.targetRouteStepId}-${Date.now()}`,
        });
        for (const result of response.results) {
          results.push({
            id: result.position_id,
            status: result.status,
            reason: result.reason,
            meta: {
              movements_created: result.movements_created,
              transfers_created: result.transfers_created,
              tasks_created: result.tasks_created,
            },
          });
        }
      } catch (e) {
        const reason = getErrorMessage(e);
        for (const id of eligibleIds) {
          results.push({ id, status: "failed", reason });
        }
      }
    }

    setBulkProgress({ total: manualPassBulkDialog.positionIds.length, completed: manualPassBulkDialog.positionIds.length, running: false });
    const summary = summarizeBulkResults(results);
    setBulkResults(results);
    setBulkSummary(summary);
    if (summary.failed > 0) setBulkResultsOpen(true);
    setBulkProgress(null);
    invalidateAll();
    toast({
      title: summary.failed > 0 ? "Частичный успех" : "Массовый сквозной проход",
      description: summary.failed > 0
        ? `${summary.success} успешно, ${summary.failed} ошибок`
        : `${summary.success} успешно, ${summary.skipped} пропущено`,
      variant: summary.failed > 0 ? "destructive" : "success",
    });
    bulkSelection.clear();
    setSelectionOrder([]);
  }, [manualPassBulkDialog.comment, manualPassBulkDialog.positionIds, manualPassBulkDialog.targetRouteStepId, rows, queryClient, bulkSelection]);

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
      const row = rows?.find((r) => r.plan_position_id === deleteDialog.positionId);
      if (row) {
        softDeleteMutation.mutate({ planId: row.production_plan_id, positionId: deleteDialog.positionId, reason: deleteDialog.reason || undefined });
      }
    }
    setDeleteDialog({ open: false, positionId: null, reason: "" });
  }, [deleteDialog.positionId, deleteDialog.reason, rows, softDeleteMutation]);

  const toggleSelect = useCallback((id: number) => {
    setSelectionOrder((prev) => {
      const idx = prev.indexOf(id);
      if (idx === -1) {
        return [id, ...prev];
      }
      return prev.filter((x) => x !== id);
    });
    bulkSelection.selectOne(id);
  }, [bulkSelection]);

  const exitBulkMode = useCallback(() => {
    bulkSelection.clear();
    setSelectionOrder([]);
    setBulkMode(false);
  }, [bulkSelection]);

  useEffect(() => {
    if (!bulkMode) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") exitBulkMode();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [bulkMode, exitBulkMode]);

  const requestBulkSoftDelete = useCallback(() => {
    if (bulkSelection.selectedCount === 0) return;
    setBulkDeleteConfirmOpen(true);
  }, [bulkSelection.selectedCount]);

  const handleBulkSoftDelete = useCallback(async () => {
    setBulkDeleteConfirmOpen(false);
    if (bulkSelection.selectedCount === 0) return;
    const selectedIds = Array.from(bulkSelection.selectedIds);
    const selectedPositionsMap = new Map(rows?.map((r) => [r.plan_position_id, r]) ?? []);

    const results: BulkActionResultItem<number>[] = [];
    setBulkProgress({ total: selectedIds.length, completed: 0, running: true });
    setBulkSoftDeleting(true);

    // Pre-filter: only send cancelled positions to the bulk endpoint.
    // Others are reported as "skipped" without hitting the API.
    const eligibleIds: number[] = [];
    for (const id of selectedIds) {
      const row = selectedPositionsMap.get(id);
      if (!row) {
        results.push({ id, status: "failed", reason: "Позиция не найдена" });
      } else if (row.position_status !== "cancelled") {
        results.push({ id, status: "skipped", reason: `Статус "${positionStatusLabels[row.position_status] || row.position_status}"` });
      } else {
        eligibleIds.push(id);
      }
    }

    if (eligibleIds.length > 0) {
      try {
        const response = await softDeletePositionsExecutionBatch({ position_ids: eligibleIds });
        for (const result of response.results) {
          results.push({
            id: result.position_id,
            status: result.status,
            reason: result.reason,
          });
        }
      } catch (e) {
        const reason = getErrorMessage(e);
        for (const id of eligibleIds) {
          results.push({ id, status: "failed", reason });
        }
      }
    }

    setBulkProgress({ total: selectedIds.length, completed: selectedIds.length, running: false });
    const summary = summarizeBulkResults(results);
    setBulkResults(results);
    setBulkSummary(summary);
    if (summary.failed > 0) setBulkResultsOpen(true);
    setBulkSoftDeleting(false);
    setBulkProgress(null);
    invalidateAll();
    toast({
      title: summary.failed > 0 ? "Частичный успех" : "Массовое удаление",
      description: summary.failed > 0
        ? `${summary.success} успешно, ${summary.failed} ошибок`
        : `${summary.success} успешно, ${summary.skipped} пропущено`,
      variant: summary.failed > 0 ? "destructive" : "success",
    });
    bulkSelection.clear();
    setSelectionOrder([]);
  }, [bulkSelection, rows]);

  const confirmCancel = useCallback(() => {
    if (cancelDialog.positionId) {
      cancelPositionMutation.mutate(cancelDialog.positionId);
    }
    setCancelDialog({ open: false, positionId: null, isReleased: false });
  }, [cancelDialog.positionId, cancelPositionMutation]);

  // Filter states
  const executionActiveFilterSummary = useMemo(() => {
    const labels: string[] = [];
    if (searchQuery.trim()) labels.push("Поиск");
    const columnFilterFields: Partial<Record<ExecutionSortField, string>> = {
      id: "ID", row: "Строка", plan: "План", sku: "SKU", name: "Наименование",
      qty: "Кол-во", route: "Маршрут", status: "Статус", stage: "Этап",
    };
    for (const [field, selected] of Object.entries(columnFilters)) {
      if (selected && selected.size > 0) {
        labels.push(`Колонка: ${columnFilterFields[field as ExecutionSortField] || field}`);
      }
    }
    return { count: labels.length, labels };
  }, [columnFilters, searchQuery]);

  const resetExecutionFilters = useCallback(() => {
    setSearchQuery("");
    setColumnFilters({});
  }, []);

  const executionFilterFields = useMemo(() => [
    {
      kind: "search" as const,
      key: "search",
      value: searchQuery,
      onChange: setSearchQuery,
      placeholder: "Поиск",
      layoutSpan: "min-w-[250px]",
    },
    {
      kind: "bulk" as const,
      key: "bulk-mode",
      enabled: bulkMode,
      onChange: (enabled: boolean) => {
        if (enabled) {
          setBulkMode(true);
        } else {
          exitBulkMode();
        }
      },
    },
    {
      kind: "toggle" as const,
      key: "hide-ids",
      label: "Скрыть ID/Строка/План",
      checked: hideColumnIds,
      onChange: setHideColumnIds,
    },
  ], [hideColumnIds, searchQuery, bulkMode, exitBulkMode]);

  const uniqueValuesByField = useMemo(() => {
    const allRows = rows || [];
    return {
      id: [...new Set(allRows.map((r) => String(r.plan_position_id)))],
      row: [...new Set(allRows.map((r) => String(r.source_row_number ?? "")))],
      plan: [...new Set(allRows.map((r) => `${r.production_plan_id} ${planNameById.get(r.production_plan_id) || ""}`))],
      sku: [...new Set(allRows.map((r) => r.source_sku))],
      name: [...new Set(allRows.map((r) => r.source_name || "").filter(Boolean))],
      qty: [...new Set(allRows.map((r) => fmtQty(r.quantity)))],
      route: [...new Set(allRows.map((r) => r.route_name || "Не назначен"))],
      status: [...new Set(allRows.map((r) => r.is_completed ? "completed" : r.position_status))],
      stage: [...new Set(allRows.map((r) => r.current_stage_section_name || "—"))],
    };
  }, [rows, planNameById]);

  const combinedPredicate = useMemo(() => {
    const activeColumnFilters = Object.entries(columnFilters).filter(
      ([, selected]) => selected && selected.size > 0,
    );
    if (activeColumnFilters.length === 0) return null;

    return (row: ProductionPlanningRow) => {
      for (const [field, selected] of activeColumnFilters) {
        const cellValue = getCellValue(row, field as ExecutionSortField);
        if (!selected.has(cellValue)) return false;
      }
      return true;
    };
  }, [columnFilters]);

  const executionSortDefs: ColumnSortDef<ProductionPlanningRow, ExecutionSortField>[] = useMemo(() => [
    { field: "id", getSortValue: (r) => r.plan_position_id },
    { field: "row", getSortValue: (r) => r.source_row_number ?? 0 },
    { field: "plan", getSortValue: (r) => r.production_plan_id },
    { field: "sku", getSortValue: (r) => r.source_sku },
    { field: "name", getSortValue: (r) => r.source_name || "" },
    { field: "qty", getSortValue: (r) => r.quantity },
    { field: "route", getSortValue: (r) => r.route_name || "" },
    { field: "status", getSortValue: (r) => r.position_status },
    { field: "stage", getSortValue: (r) => r.current_stage_sequence ?? 0 },
  ], []);

  const executionQueryResult = useTableQueryEngine<ProductionPlanningRow, ExecutionSortField>({
    rows: rows || [],
    getId: (r) => r.plan_position_id,
    searchQuery,
    filterPredicate: combinedPredicate,
    sortConfigs,
    sortDefs: executionSortDefs,
  });
  const filteredRows = executionQueryResult.rows;

  const handleSelectAll = useCallback(() => {
    const filteredIds = filteredRows.map((r) => r.plan_position_id);
    bulkSelection.selectAll(filteredIds);
    setSelectionOrder(filteredIds);
  }, [bulkSelection, filteredRows]);

  const handleResetAll = useCallback(() => {
    bulkSelection.clear();
    resetExecutionFilters();
    setSelectionOrder([]);
  }, [bulkSelection, resetExecutionFilters]);

  const rowById = useMemo(() => {
    const map = new Map<number, ProductionPlanningRow>();
    (rows || []).forEach((row) => map.set(row.plan_position_id, row));
    return map;
  }, [rows]);

  const executionBulkActions = useMemo<BulkActionDefinition<number, Map<number, ProductionPlanningRow>>[]>(() => [
    {
      id: "take-to-work",
      label: "Взять в работу",
      primaryLabel: "Взять в работу",
      pendingLabel: "Запуск...",
      isEligible: (id, context) => {
        const row = context.get(id);
        return Boolean(row && !getLaunchBlockReason(row));
      },
      getIneligibleReason: (id, context) => {
        const row = context.get(id);
        return row ? getLaunchBlockReason(row) : "Строка не найдена";
      },
      run: async (ids) => {
        const data = await takeToWork(ids);
        return data.results.map((result) => ({
          id: result.position_id,
          status: result.status === "already_started" ? "skipped" : result.status,
          reason: result.reason,
          meta: { tasks_created: result.tasks_created },
        }));
      },
    },
    {
      id: "cancel",
      label: "Отменить / остановить",
      primaryLabel: "Отменить",
      pendingLabel: "Отмена...",
      isEligible: (id, context) => {
        const row = context.get(id);
        return Boolean(row && !getCancelBlockReason(row));
      },
      getIneligibleReason: (id, context) => {
        const row = context.get(id);
        return row ? getCancelBlockReason(row) : "Строка не найдена";
      },
      run: async (ids) => {
        const data = await cancelPositionsExecutionBatch({ position_ids: ids });
        return data.results.map((result) => ({
          id: result.position_id,
          status: result.status,
          reason: result.reason,
        }));
      },
    },
    {
      id: "restore",
      label: "Восстановить",
      primaryLabel: "Восстановить",
      pendingLabel: "Восстановление...",
      isEligible: (id, context) => {
        const row = context.get(id);
        return Boolean(row && !getRestoreBlockReason(row));
      },
      getIneligibleReason: (id, context) => {
        const row = context.get(id);
        return row ? getRestoreBlockReason(row) : "Строка не найдена";
      },
      run: async (ids) => {
        const data = await restorePositionsExecutionBatch({ position_ids: ids });
        return data.results.map((result) => ({
          id: result.position_id,
          status: result.status,
          reason: result.reason,
        }));
      },
    },
    {
      id: "soft-delete",
      label: "Удалить из списка",
      primaryLabel: "Удалить",
      pendingLabel: "Удаление...",
      isEligible: (id, context) => {
        const row = context.get(id);
        return Boolean(row && !getSoftDeleteBlockReason(row));
      },
      getIneligibleReason: (id, context) => {
        const row = context.get(id);
        return row ? getSoftDeleteBlockReason(row) : "Строка не найдена";
      },
      run: async (ids) => {
        const response = await softDeletePositionsExecutionBatch({ position_ids: ids });
        return response.results.map((result) => ({
          id: result.position_id,
          status: result.status,
          reason: result.reason,
        }));
      },
    },
    {
      id: "manual-pass",
      label: "Сквозной проход",
      primaryLabel: "Сквозной проход",
      pendingLabel: "Сквозной проход...",
      isEligible: (id, context) => {
        const row = context.get(id);
        return Boolean(row && !getManualPassBlockReason(row));
      },
      getIneligibleReason: (id, context) => {
        const row = context.get(id);
        return row ? getManualPassBlockReason(row) : "Строка не найдена";
      },
      run: async () => {
        // This is handled via dialog — runSelectedBulkAction intercepts it
        return [];
      },
    },
  ], []);

  const runBulkActionById = useCallback(async (actionId: string) => {
    const action = executionBulkActions.find((a) => a.id === actionId);
    if (!action) return;
    if (bulkSelection.selectedCount === 0) {
      toast({ title: "Выберите строки", description: "Отметьте строки для массового действия", variant: "destructive" });
      return;
    }
    setBulkProgress({ total: bulkSelection.selectedCount, completed: 0, running: true });
    const results = await runBulkAction(action, bulkSelection.selectedIds, rowById, setBulkProgress);
    const summary = summarizeBulkResults(results);
    setBulkResults(results);
    setBulkSummary(summary);
    if (summary.failed > 0 || summary.skipped > 0) setBulkResultsOpen(true);
    invalidateAll();
    toast({
      title: summary.failed > 0 ? "Частичный успех" : "Массовое действие выполнено",
      description: `${summary.success} успешно, ${summary.skipped} пропущено, ${summary.failed} ошибок`,
      variant: summary.failed > 0 ? "destructive" : "success",
    });
    bulkSelection.clear();
    setSelectionOrder([]);
    setBulkProgress(null);
  }, [bulkSelection, executionBulkActions, queryClient, rowById, invalidateAll]);

  const runSelectedBulkAction = useCallback(async (actionId?: string) => {
    if (bulkSelection.selectedCount === 0) {
      toast({ title: "Выберите строки", description: "Отметьте строки для массового действия", variant: "destructive" });
      return;
    }
    const resolvedActionId = actionId ?? selectedBulkActionId;
    const action = executionBulkActions.find((a) => a.id === resolvedActionId) ?? executionBulkActions[0]!;
    // manual-pass requires a dialog first
    if (resolvedActionId === "manual-pass") {
      setManualPassBulkDialog({
        open: true,
        targetRouteStepId: "",
        comment: "",
        positionIds: Array.from(bulkSelection.selectedIds),
      });
      return;
    }
    setBulkProgress({ total: bulkSelection.selectedCount, completed: 0, running: true });
    const results = await runBulkAction(action, bulkSelection.selectedIds, rowById, setBulkProgress);
    const summary = summarizeBulkResults(results);
    setBulkResults(results);
    setBulkSummary(summary);
    if (summary.failed > 0 || summary.skipped > 0) setBulkResultsOpen(true);
    invalidateAll();
    toast({
      title: summary.failed > 0 ? "Частичный успех" : "Массовое действие выполнено",
      description: `${summary.success} успешно, ${summary.skipped} пропущено, ${summary.failed} ошибок`,
      variant: summary.failed > 0 ? "destructive" : "success",
    });
    bulkSelection.clear();
    setSelectionOrder([]);
    setBulkProgress(null);
  }, [bulkSelection, executionBulkActions, queryClient, rowById, selectedBulkActionId, invalidateAll]);

  const tableScrollRef = useRef<HTMLDivElement>(null);

  const filteredIds = useMemo(() => filteredRows.map((r) => r.plan_position_id), [filteredRows]);

  useBulkHotkeys({
    scopeRef: tableScrollRef,
    filteredIds,
    hasSelection: bulkSelection.selectedCount > 0,
    disabled: isLoading,
    isRunning: Boolean(bulkProgress?.running),
    selectAllFiltered: bulkSelection.selectAllFiltered,
    clear: bulkSelection.clear,
    runPrimary: runSelectedBulkAction,
  });

  const totalRows = rows?.length || 0;
  const releasedRows = rows?.filter((r) => r.is_released && !r.is_completed).length || 0;
  const completedRows = rows?.filter((r) => r.is_completed).length || 0;

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
      <ExecutionTable
        rows={rows || []}
        filteredRows={filteredRows}
        isLoading={isLoading}
        bulkMode={bulkMode}
        totalRows={totalRows}
        releasedRows={releasedRows}
        completedRows={completedRows}
        filterFields={executionFilterFields}
        resetFilters={resetExecutionFilters}
        activeFilterSummary={executionActiveFilterSummary}
        sortConfigs={sortConfigs}
        handleSortChange={handleSortChange}
        getAriaSort={getAriaSort}
        columnFilters={columnFilters}
        onColumnFilterChange={handleColumnFilterChange}
        uniqueValuesByField={uniqueValuesByField}
        hideColumnIds={hideColumnIds}
        bulkSelection={bulkSelection}
        bulkProgress={bulkProgress}
        bulkSummary={bulkSummary}
        selectedBulkActionId={selectedBulkActionId}
        onActionChange={setSelectedBulkActionId}
        executionBulkActions={executionBulkActions}
        onRunSelectedBulkAction={runSelectedBulkAction}
        onEnterBulkMode={() => setBulkMode(true)}
        onExitBulkMode={exitBulkMode}
        sectionMetaById={sectionMetaById}
        rowById={rowById}
        onOpenDetail={openDetail}
        onSingleLaunch={handleSingleLaunch}
        onManualPass={handleManualPass}
        onCancel={handleCancel}
        onRestore={handleRestore}
        onSoftDelete={handleSoftDelete}
        onOpenHistory={openHistory}
        onToggleSelect={toggleSelect}
        onSelectAll={handleSelectAll}
        onResetAll={handleResetAll}
        onRequestBulkSoftDelete={requestBulkSoftDelete}
        onRemoveSelection={(id) => setSelectionOrder((prev) => prev.filter((x) => x !== id))}
        onSkuClick={setWipStatsSku}
        tableScrollRef={tableScrollRef}
      />

      <ExecutionDialogs
        drawerOpen={drawerOpen}
        onDrawerOpenChange={(open) => {
          setDrawerOpen(open);
          if (!open) setSelectedPositionId(null);
        }}
        detail={detail ?? null}
        detailLoading={detailLoading}
        detailError={detailError}
        selectedPositionId={selectedPositionId}
        launchDialog={launchDialog}
        onLaunchDialogChange={setLaunchDialog}
        takeToWorkPending={takeToWorkMutation.isPending}
        onConfirmLaunch={confirmLaunch}
        manualPassDialog={manualPassDialog}
        onManualPassDialogChange={setManualPassDialog}
        manualPassDetail={manualPassDetail}
        manualPassDetailLoading={manualPassDetailLoading}
        manualPassPending={manualPassMutation.isPending}
        onConfirmManualPass={confirmManualPass}
        manualPassBulkDialog={manualPassBulkDialog}
        onManualPassBulkDialogChange={setManualPassBulkDialog}
        bulkManualPassPending={bulkSoftDeleting || Boolean(bulkProgress?.running)}
        onConfirmBulkManualPass={confirmBulkManualPass}
        cancelDialog={cancelDialog}
        onCancelDialogChange={setCancelDialog}
        cancelPending={cancelPositionMutation.isPending}
        onConfirmCancel={confirmCancel}
        restoreDialog={restoreDialog}
        onRestoreDialogChange={setRestoreDialog}
        restorePending={restorePositionMutation.isPending}
        onConfirmRestore={confirmRestore}
        deleteDialog={deleteDialog}
        onDeleteDialogChange={setDeleteDialog}
        softDeletePending={softDeleteMutation.isPending}
        onConfirmSoftDelete={confirmSoftDelete}
        bulkResultsOpen={bulkResultsOpen}
        onBulkResultsChange={setBulkResultsOpen}
        bulkSummary={bulkSummary}
        bulkResults={bulkResults}
        bulkDeleteConfirmOpen={bulkDeleteConfirmOpen}
        onBulkDeleteConfirmChange={setBulkDeleteConfirmOpen}
        bulkSoftDeleting={bulkSoftDeleting}
        bulkSelectedCount={bulkSelection.selectedCount}
        onConfirmBulkSoftDelete={handleBulkSoftDelete}
        historyDialogOpen={historyDialogOpen}
        onHistoryDialogChange={setHistoryDialogOpen}
        historyLoading={historyLoading}
        historyEntries={historyEntries}
      />

      <ProductWipStatsDialog
        sku={wipStatsSku}
        open={wipStatsSku !== null}
        onOpenChange={(open) => {
          if (!open) setWipStatsSku(null);
        }}
      />
    </>
  );
}
