import { useMemo, useState, useCallback, useRef, useEffect } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getProductionPlanningRowDetail,
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
  type ListProductionPlanningRowsParams,
  type ProductionPlanningRow,
  type ProductionPlanningRowDetail,
} from "@/shared/api/productionPlans";
import { RemainderAllocationDialog } from "../components/RemainderAllocationDialog";
import type { SourceAllocation } from "../components/RemainderAllocationDialog";
import { listSections } from "@/shared/api/sections";
import { useFilterableTable } from "@/shared/hooks/useFilterableTable";
import type { SortConfig } from "@/shared/hooks/useTableQueryEngine";
import { usePaginatedTableQuery } from "@/shared/hooks/usePaginatedTableQuery";
import { formatDimensionsFilterValue } from "@/shared/api/stock";


import { toast } from "@/shared/ui/use-toast";
import { buildActiveFilterSummary } from "@/shared/ui/buildActiveFilterSummary";
import { getErrorMessage } from "@/shared/api/client";
import { invalidateAfter } from "@/shared/api/cacheInvalidation";
import { operationalPollingOptions } from "@/shared/api/operationalPolling";
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
  getLaunchBlockReason,
  getCancelBlockReason,
  getRestoreBlockReason,
  getSoftDeleteBlockReason,
  getManualPassBlockReason,
} from "../components/execution-utils";
import { fmtQty } from "@/shared/lib/quantityFormat";
import { buildExecutionSortParam } from "../lib/executionSortMapping";
import { useDebouncedValue } from "@/shared/lib/useDebouncedValue";
import { buildColumnApiParams } from "@/shared/lib/columnSpecs";
import { executionTableColumns } from "../components/execution-table-columns";
import { isFirstRowsLoad } from "@/shared/lib/tableQueryPlaceholder";


/**
 * Порядок строк до первого клика по шапке: сперва утверждённые позиции плана,
 * внутри них — от большего количества к меньшему, дальше то, что уже в работе,
 * и последними отменённые. Второй приоритет сортирует количество внутри каждой
 * группы статусов, а не только внутри утверждённых: иначе работающие позиции
 * оказывались бы в случайном порядке.
 *
 * Статус сервер сравнивает по порядку значений enum `plan_position_status`, а не
 * по строке, поэтому `status:asc` и есть нужная очередь (см.
 * `_sort_columns` в `production_planning_rows.py`).
 */
const EXECUTION_DEFAULT_SORT: SortConfig<ExecutionSortField>[] = [
  { field: "status", order: "asc" },
  { field: "qty", order: "desc" },
];

/**
 * Параметры запроса по отфильтрованным колонкам — из описания колонок, а не
 * перечислением: пока здесь стояло десять вызовов `pickColumnApiValue` по
 * имени колонки, одиннадцатая потребовала бы правки этого кода. Имя параметра
 * запроса и правило «это значение серверу не показывать» объявлены у колонки
 * там, где она описана.
 */
function buildExecutionColumnApiParams(
  columnFilters: Partial<Record<ExecutionSortField, Set<string>>>,
  columnSearchQueries: Partial<Record<ExecutionSortField, string>>,
): Pick<
  ListProductionPlanningRowsParams,
  | "plan_position_id"
  | "source_row_number"
  | "product_sku"
  | "source_name"
  | "quantity"
  | "route_name"
  | "status"
  | "current_stage_section_name"
  | "dimensions"
> {
  return buildColumnApiParams(columnFilters, columnSearchQueries, executionTableColumns);
}

/**
 * Подписи колонок для счётчика активных фильтров — из описания колонки, как
 * на доске задач. Ручной словарь расходился с таблицей: колонки «Размер» в
 * нём не было, и оператор читал «Колонка: dimensions».
 */
const EXECUTION_COLUMN_LABELS: Record<string, string> = Object.fromEntries(
  executionTableColumns.flatMap((column) =>
    column.filterField ? [[column.filterField, column.label] as const] : [],
  ),
);


export function ExecutionPage() {
  const [selectedPositionId, setSelectedPositionId] = useState<number | null>(null);
  const [wipStatsSku, setWipStatsSku] = useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const debouncedSearchQuery = useDebouncedValue(searchQuery);
  const {
    bindColumn,
    columnFilters,
    columnSearchQueries,
    debouncedColumnSearchQueries,
    sortConfigs,
    setSortConfigs,
    handleSort: handleSortChange,
    resetColumnFilters,
    hasActiveFilters: hasTableFiltersActive,
  } = useFilterableTable<ExecutionSortField>({
    defaultSort: EXECUTION_DEFAULT_SORT,
    extraHasActive: searchQuery.trim().length > 0,
  });

  const {
    page,
    setPage,
    limit,
    setLimit,
    offset,
    getTotalPages,
    getRangeLabel,
    resetPage,
  } = usePaginatedTableQuery({
    resetPageDeps: [
      debouncedSearchQuery,
      columnFilters,
      debouncedColumnSearchQueries,
      sortConfigs,
    ],
  });


  const columnApiParams = useMemo(
    () => buildExecutionColumnApiParams(columnFilters, debouncedColumnSearchQueries),
    [columnFilters, debouncedColumnSearchQueries],
  );

  // Вся выбранная сортировка уезжает одной строкой `sort` по приоритетам.
  // Несортируемые сервером колонки в неё не попадают.
  const sortParams = useMemo(
    () => ({ sort: buildExecutionSortParam(sortConfigs) }),
    [sortConfigs],
  );

  const rowsQueryParams = useMemo(
    () => ({
      search: debouncedSearchQuery.trim() || undefined,
      ...sortParams,
      limit,
      offset,
      ...columnApiParams,
    }),
    [debouncedSearchQuery, sortParams, limit, offset, columnApiParams],
  );

  // `placeholderData: keepPreviousData` — обязателен: фильтры, сортировка и
  // страница входят в queryKey, поэтому их смена открывает новую запись кэша.
  // Без placeholder `isLoading` гасит страницу целиком — вместе с открытым
  // поповером и набранным в нём текстом. `isPending` ниже ловит только первую
  // загрузку, когда строк на экране ещё не было ни разу.
  const { data: rowsData, isPending, isFetching, error } = useQuery({
    queryKey: queryKeys.execution.rows(rowsQueryParams),
    queryFn: () => listProductionPlanningRows(rowsQueryParams),
    placeholderData: keepPreviousData,
    // «Чужие действия видны без F5» (#206): строки контроля перечитываются,
    // пока вкладка в фокусе. См. `operationalPolling.ts` и ADR-0041.
    ...operationalPollingOptions,
  });

  const rows = rowsData?.rows ?? [];
  const total = rowsData?.total ?? 0;
  const totalPages = getTotalPages(total);
  const { data: sections } = useQuery({
    queryKey: queryKeys.sections.all(),
    queryFn: listSections,
  });

  const { data: detail, isLoading: detailLoading, error: detailError } = useQuery({
    queryKey: queryKeys.execution.rowDetail(selectedPositionId as number),
    queryFn: () => getProductionPlanningRowDetail(selectedPositionId as number),
    enabled: drawerOpen && selectedPositionId !== null,
  });

  const sectionMetaById = useMemo(() => {
    const map = new Map<number, { icon: string | null; icon_color: string | null }>();
    (sections || []).forEach((s) => map.set(s.id, { icon: s.icon, icon_color: s.icon_color }));
    return map;
  }, [sections]);

  const queryClient = useQueryClient();

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
  const [remainderDialog, setRemainderDialog] = useState<{
    open: boolean;
    positionId: number | null;
    sku: string;
    name: string;
    quantity: number;
  }>({
    open: false,
    positionId: null,
    sku: "",
    name: "",
    quantity: 0,
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
    mutationFn: ({
      positionIds,
      remainderAllocation,
    }: {
      positionIds: number[];
      remainderAllocation?: Array<{ balance_id: number; quantity: number }>;
    }) => takeToWork(positionIds, remainderAllocation),
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
      void invalidateAfter(queryClient, "executionChanged");
      bulkSelection.clear();
      setSelectionOrder([]);
      setRemainderDialog((prev) => ({ ...prev, open: false }));
      setLaunchDialog({ open: false, mode: "single", positionIds: [] });
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
      void invalidateAfter(queryClient, "executionChanged");
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
      void invalidateAfter(queryClient, "executionChanged");
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
      void invalidateAfter(queryClient, "executionChanged");
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
      void invalidateAfter(queryClient, "executionChanged");
    },
    onError: (err) => toast({ title: "Ошибка удаления", description: getErrorMessage(err), variant: "destructive" }),
  });

  const handleSingleLaunch = useCallback((row: ProductionPlanningRow) => {
    const reason = getLaunchBlockReason(row);
    if (reason) {
      toast({ title: "Невозможно запустить", description: reason, variant: "destructive" });
      return;
    }
    setRemainderDialog({
      open: true,
      positionId: row.plan_position_id,
      sku: row.source_sku,
      name: row.source_name || "",
      quantity: row.quantity,
    });
  }, []);

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
    takeToWorkMutation.mutate({ positionIds: launchDialog.positionIds });
    setLaunchDialog({ open: false, mode: "single", positionIds: [] });
  }, [launchDialog.positionIds, takeToWorkMutation]);

  const confirmLaunchWithAutoConsume = useCallback(
    (_autoConsume: boolean, allocation: SourceAllocation[] | null) => {
      if (!remainderDialog.positionId) return;
      takeToWorkMutation.mutate({
        positionIds: [remainderDialog.positionId],
        // Выбранный источник едет в take-to-work и списывается бэкендом
        // (#314). null = оператор снял выбор: запуск без источника.
        remainderAllocation: allocation ?? undefined,
      });
      setRemainderDialog((prev) => ({ ...prev, open: false }));
    },
    [remainderDialog.positionId, takeToWorkMutation],
  );

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
    const selectedPositionsMap = new Map(rows.map((r) => [r.plan_position_id, r]));
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
    void invalidateAfter(queryClient, "executionChanged");
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
      const row = rows.find((r) => r.plan_position_id === deleteDialog.positionId);
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
    const selectedPositionsMap = new Map(rows.map((r) => [r.plan_position_id, r]));

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
    void invalidateAfter(queryClient, "executionChanged");
    toast({
      title: summary.failed > 0 ? "Частичный успех" : "Массовое удаление",
      description: summary.failed > 0
        ? `${summary.success} успешно, ${summary.failed} ошибок`
        : `${summary.success} успешно, ${summary.skipped} пропущено`,
      variant: summary.failed > 0 ? "destructive" : "success",
    });
    bulkSelection.clear();
    setSelectionOrder([]);
  }, [bulkSelection, queryClient, rows]);

  const confirmCancel = useCallback(() => {
    if (cancelDialog.positionId) {
      cancelPositionMutation.mutate(cancelDialog.positionId);
    }
    setCancelDialog({ open: false, positionId: null, isReleased: false });
  }, [cancelDialog.positionId, cancelPositionMutation]);

  // Filter states
  const executionActiveFilterSummary = useMemo(
    () =>
      buildActiveFilterSummary(searchQuery, sortConfigs.length, {
        columnFilters,
        columnSearchQueries,
        columnLabels: EXECUTION_COLUMN_LABELS,
      }),
    [columnFilters, columnSearchQueries, searchQuery, sortConfigs.length],
  );

  const resetExecutionFilters = useCallback(() => {
    setSearchQuery("");
    resetColumnFilters();
    resetPage();
  }, [resetColumnFilters, resetPage]);

  const handleSortWithReset = useCallback(
    (field: ExecutionSortField) => {
      handleSortChange(field);
      resetPage();
    },
    [handleSortChange, resetPage],
  );

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
  ], [searchQuery, bulkMode, exitBulkMode]);

  const uniqueValuesByField = useMemo(() => {
    return {
      id: [...new Set(rows.map((r) => String(r.plan_position_id)))],
      row: [...new Set(rows.map((r) => String(r.source_row_number ?? "")))],
      sku: [...new Set(rows.map((r) => r.source_sku))],
      name: [...new Set(rows.map((r) => r.source_name || "").filter(Boolean))],
      qty: [...new Set(rows.map((r) => fmtQty(r.quantity)))],
      route: [...new Set(rows.map((r) => r.route_name || "Не назначен"))],
      status: [...new Set(rows.map((r) => (r.is_completed ? "completed" : r.position_status)))],
      stage: [...new Set(rows.map((r) => r.current_stage_section_name || "—"))],
      dimensions: [...new Set(rows.map((r) => JSON.stringify(r.dimensions ?? null)))].sort(
        (a, b) => formatDimensionsFilterValue(a).localeCompare(formatDimensionsFilterValue(b), "ru"),
      ),
    };
  }, [rows]);

  const handleSelectAll = useCallback(() => {
    const pageIds = rows.map((r) => r.plan_position_id);
    bulkSelection.selectAll(pageIds);
    setSelectionOrder(pageIds);
  }, [bulkSelection, rows]);

  const handleResetAll = useCallback(() => {
    bulkSelection.clear();
    resetExecutionFilters();
    setSortConfigs([]);
    setSelectionOrder([]);
  }, [bulkSelection, resetExecutionFilters]);

  const rowById = useMemo(() => {
    const map = new Map<number, ProductionPlanningRow>();
    rows.forEach((row) => map.set(row.plan_position_id, row));
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
    void invalidateAfter(queryClient, "executionChanged");
    toast({
      title: summary.failed > 0 ? "Частичный успех" : "Массовое действие выполнено",
      description: `${summary.success} успешно, ${summary.skipped} пропущено, ${summary.failed} ошибок`,
      variant: summary.failed > 0 ? "destructive" : "success",
    });
    bulkSelection.clear();
    setSelectionOrder([]);
    setBulkProgress(null);
  }, [bulkSelection, executionBulkActions, queryClient, rowById]);

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
    void invalidateAfter(queryClient, "executionChanged");
    toast({
      title: summary.failed > 0 ? "Частичный успех" : "Массовое действие выполнено",
      description: `${summary.success} успешно, ${summary.skipped} пропущено, ${summary.failed} ошибок`,
      variant: summary.failed > 0 ? "destructive" : "success",
    });
    bulkSelection.clear();
    setSelectionOrder([]);
    setBulkProgress(null);
  }, [bulkSelection, executionBulkActions, queryClient, rowById, selectedBulkActionId]);

  const tableScrollRef = useRef<HTMLDivElement>(null);

  const filteredIds = useMemo(() => rows.map((r) => r.plan_position_id), [rows]);

  useBulkHotkeys({
    scopeRef: tableScrollRef,
    filteredIds,
    hasSelection: bulkSelection.selectedCount > 0,
    // Блокируются только пока строк на экране нет: массовые действия выводятся
    // из загруженных строк, и на фоновой перезагрузке (страница, сортировка)
    // отключать их незачем — на экране дерево, строки на месте (ADR-0044).
    disabled: rows.length === 0,
    isRunning: Boolean(bulkProgress?.running),
    selectAllFiltered: bulkSelection.selectAllFiltered,
    clear: bulkSelection.clear,
    runPrimary: runSelectedBulkAction,
  });

  const totalRows = total;
  const releasedRows = rows.filter((r) => r.is_released && !r.is_completed).length;
  const completedRows = rows.filter((r) => r.is_completed).length;

  const openDetail = (positionId: number) => {
    setSelectedPositionId(positionId);
    setDrawerOpen(true);
  };

  // Заглушка — только пока строк не было ни разу. Дальше дерево остаётся на
  // месте, а смену параметров показывает `isFetching`: иначе смена страницы
  // или фильтра размонтировала бы таблицу вместе с открытым поповером.
  if (isFirstRowsLoad(isPending, rows)) {
    return <div className="p-6 text-sm text-muted-foreground">Загрузка...</div>;
  }

  if (error) {
    return <div className="p-6 text-sm text-red-600">Ошибка загрузки: {String(error)}</div>;
  }

  return (
    <>
      <ExecutionTable
        rows={rows}
        isLoading={isFetching}
        bulkMode={bulkMode}
        totalRows={totalRows}
        releasedRows={releasedRows}
        completedRows={completedRows}
        filterFields={executionFilterFields}
        activeFilterSummary={executionActiveFilterSummary}
        tableHasActiveFilters={hasTableFiltersActive}
        sortConfigs={sortConfigs}
        handleSortChange={handleSortWithReset}
        page={page}
        totalPages={totalPages}
        total={total}
        limit={limit}
        onPageChange={setPage}
        onLimitChange={setLimit}
        rangeLabel={getRangeLabel(rows.length, total, { onPage: true })}
        bindColumn={bindColumn}
        uniqueValuesByField={uniqueValuesByField}
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
      />

      <RemainderAllocationDialog
        open={remainderDialog.open}
        onOpenChange={(open) => setRemainderDialog((prev) => ({ ...prev, open }))}
        positionId={remainderDialog.positionId}
        positionSku={remainderDialog.sku}
        positionName={remainderDialog.name}
        releaseQuantity={remainderDialog.quantity}
        pending={takeToWorkMutation.isPending}
        onConfirm={confirmLaunchWithAutoConsume}
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
