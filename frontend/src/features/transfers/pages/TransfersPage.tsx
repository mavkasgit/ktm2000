import { useState, useCallback, useEffect, useMemo, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Send, Inbox, RefreshCw, AlertCircle, ChevronRight } from "lucide-react";

import {
  Badge,
  Button,
  buttonVariants,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  Input,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  toast,
  SpgSelect,
  Checkbox,
  AlertDialog,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogFooter,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogAction,
  AlertDialogCancel,
  SortableFilterHeader,
  TableCornerResetCell,
  TableCornerResetHeader,
} from "@/shared/ui";
import { useFilterableTable } from "@/shared/hooks/useFilterableTable";
import { useTableQueryEngine, type ColumnSortDef } from "@/shared/hooks/useTableQueryEngine";
import { getSpgList } from "@/shared/api/spg";
import {
  cancelTransfer,
  correctTransfer,
  createTransfer,
  listReadyToTransfer,
  listTransferHistory,
  type IncomingTransfer,
  type ReadyToTransferTask,
} from "@/shared/api/transfers";
import { getErrorMessage } from "@/shared/api/client";
import { queryKeys } from "@/shared/api/queryKeys";
import {
  useBulkSelection,
  BulkResultsDialog,
  summarizeBulkResults,
  type BulkActionResultItem,
  type BulkActionSummary,
  type BulkRunnerProgress,
} from "@/shared/bulk";

function fmtQty(value: string | number | null | undefined): string {
  if (value == null) return "0";
  const n = parseFloat(String(value));
  if (!Number.isFinite(n)) return "0";
  return String(Math.round(n));
}

function conflictHintFromTransferError(message: string): string | null {
  const n = message.toLowerCase();
  if (n.includes("превышает доступный к передаче")) {
    return "Количество больше доступного к передаче.";
  }
  if (n.includes("следующим этапом маршрута")) {
    return "Передавать можно только на следующий этап маршрута.";
  }
  if (n.includes("превышает доступный к передаче объём исходной задачи")) {
    return "Скорректированное количество превышает доступный к передаче объём исходной задачи.";
  }
  if (n.includes("нельзя уменьшить передачу")) {
    return "Нельзя уменьшить передачу: целевая задача уже использовала материалы.";
  }
  if (n.includes("уже есть активная передача")) {
    return "По этому заданию передача уже создана — измените количество в журнале.";
  }
  return null;
}

function makeIdempotencyKey(prefix: string): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `${prefix}-${crypto.randomUUID()}`;
  }
  return `${prefix}-${Date.now()}-${Math.floor(Math.random() * 1_000_000)}`;
}

type StatusBadgeVariant = "default" | "destructive" | "outline" | "secondary";

function statusBadgeLabel(status: string): string {
  // Under the explicit-transfer model, transfer_send auto-accepts the
  // transfer inline. By the time the operator sees the history list,
  // every transfer is either "Принята" or "Аннулирована".
  if (status === "cancelled") return "Аннулирована";
  return "Принята";
}

function statusBadgeVariant(status: string): StatusBadgeVariant {
  if (status === "cancelled") return "destructive";
  return "outline";
}

type ReadySortField = "taskId" | "sku" | "stage" | "transferableQty" | "next";

function getReadyCellValue(task: ReadyToTransferTask, field: ReadySortField): string {
  switch (field) {
    case "taskId":
      return String(task.task_id);
    case "sku":
      return task.product_sku ?? "—";
    case "stage":
      return task.operation_name ?? "—";
    case "transferableQty":
      return fmtQty(task.transferable_quantity);
    case "next":
      return task.has_next_step
        ? `${task.next_operation_name ?? "—"} / ${task.next_section_code ?? "—"}`
        : "Финальный";
  }
}

type HistorySortField = "from" | "to" | "sku" | "quantity" | "status";

function getHistoryStatusLabel(
  transfer: IncomingTransfer,
  sectionIdsInSpg: Set<number>,
): string {
  const isIncoming = sectionIdsInSpg.has(transfer.to_section_id);
  const direction = isIncoming ? "Входящая" : "Исходящая";
  if (transfer.status === "cancelled") return `${direction} / Аннулирована`;
  if (transfer.status === "sent") return `${direction} / Отправлена`;
  if (transfer.status === "partially_accepted") return `${direction} / Частично принята`;
  return `${direction} / Принята`;
}

function getHistoryCellValue(
  transfer: IncomingTransfer,
  field: HistorySortField,
  sectionIdsInSpg: Set<number>,
): string {
  switch (field) {
    case "from":
      return `${transfer.from_section_name} / ${transfer.from_operation_name ?? "—"}`;
    case "to":
      return `${transfer.to_section_name} / ${transfer.to_operation_name ?? "—"}`;
    case "sku":
      return transfer.product_sku;
    case "quantity":
      return fmtQty(transfer.sent_quantity);
    case "status":
      return getHistoryStatusLabel(transfer, sectionIdsInSpg);
  }
}

interface ReadyTransferRowProps {
  task: ReadyToTransferTask;
  bulkMode: boolean;
  isSelected: boolean;
  onSelect: () => void;
  isSubmitting: boolean;
  tryAcquire: () => boolean;
  release: () => void;
  invalidateShopfloorCaches: (fromSectionId: number | null, toSectionId: number | null) => void;
  invalidateTransfersCaches: () => void;
}

function ReadyTransferRow({
  task,
  bulkMode,
  isSelected,
  onSelect,
  isSubmitting,
  tryAcquire,
  release,
  invalidateShopfloorCaches,
  invalidateTransfersCaches,
}: ReadyTransferRowProps) {
  const [quantity, setQuantity] = useState(task.transferable_quantity);
  const submittingRef = useRef(false);

  useEffect(() => {
    setQuantity(task.transferable_quantity);
  }, [task.transferable_quantity]);

  const mutation = useMutation({
    mutationFn: (idempotencyKey: string) =>
      createTransfer({
        from_task_id: task.task_id,
        to_task_id: undefined,
        quantity,
        comment: undefined,
        idempotency_key: idempotencyKey,
        allow_over_plan: overLimit || isOverPlan,
      }),
    onSuccess: () => {
      toast({
        variant: "success",
        title: "Передача создана",
        description: `Задание #${task.task_id} отправлено`,
      });
      invalidateShopfloorCaches(task.section_id, task.next_section_id);
      invalidateTransfersCaches();
    },
    onError: (err: unknown) => {
      const message = getErrorMessage(err);
      const hint = conflictHintFromTransferError(message);
      toast({
        variant: "destructive",
        title: "Ошибка передачи",
        description: hint ?? message,
      });
    },
  });

  const maxQty = parseFloat(task.transferable_quantity);
  const qtyNum = parseFloat(quantity || "0");
  const overLimit = qtyNum > maxQty;
  const isOverPlan = qtyNum > parseFloat(task.planned_quantity);

  return (
    <TableRow
      className={bulkMode ? "cursor-pointer hover:bg-muted/50" : undefined}
      onClick={bulkMode ? onSelect : undefined}
    >
      {bulkMode && (
        <TableCell className="w-[40px] p-2" onClick={(e) => e.stopPropagation()}>
          <Checkbox
            checked={isSelected}
            onCheckedChange={onSelect}
          />
        </TableCell>
      )}
      <TableCell className="font-mono text-xs">#{task.task_id}</TableCell>
      <TableCell>{task.product_sku ?? "—"}</TableCell>
      <TableCell>
        <div className="text-xs">
          <div className="font-medium">{task.operation_name ?? "—"}</div>
          <div className="text-muted-foreground">#{task.sequence}</div>
        </div>
      </TableCell>
      <TableCell className="text-right tabular-nums">
        <div className="whitespace-nowrap">
          <span className="font-medium">{fmtQty(task.transferable_quantity)} шт.</span>{" "}
          <span className="text-[11px] text-muted-foreground">
            (план {fmtQty(task.planned_quantity)})
          </span>
        </div>
        {task.completion_comment && (
          <div className="text-[10px] text-muted-foreground mt-0.5 leading-tight" title={task.completion_comment}>
            {task.completion_comment}
          </div>
        )}
      </TableCell>
      <TableCell className="text-xs">
        {task.has_next_step ? (
          <>
            <div>{task.next_operation_name ?? "—"}</div>
            <div className="text-muted-foreground">
              {task.next_section_code ?? "—"} #{task.next_step_sequence ?? "—"}
            </div>
          </>
        ) : (
          <Badge variant="outline">Финальный</Badge>
        )}
      </TableCell>
      {!bulkMode && (
        <TableCell onClick={(e) => e.stopPropagation()}>
          <div className="flex items-center justify-end gap-2">
            <div className="flex items-center gap-1">
              <Input
                type="number"
                step="1"
                min="0"
                value={quantity}
                className={`w-20 h-8 text-right px-2 ${
                  overLimit ? "border-amber-400 focus-visible:ring-amber-400" : ""
                }`}
                title={overLimit ? `Превышает доступное (${fmtQty(task.transferable_quantity)} шт.)` : undefined}
                onChange={(e) => setQuantity(e.target.value)}
              />
              {isOverPlan && (
                <Badge variant="outline" className="border-amber-400 text-amber-700 bg-amber-50 dark:bg-amber-950/20 dark:text-amber-400 text-[10px] px-1.5 py-0 h-5 whitespace-nowrap">
                  +{fmtQty(String(qtyNum - parseFloat(task.planned_quantity)))} сверх плана
                </Badge>
              )}
            </div>
            <Button
              size="sm"
              disabled={!task.has_next_step || isSubmitting || mutation.isPending || qtyNum <= 0}
              onClick={() => {
                if (submittingRef.current || isSubmitting || mutation.isPending) return;
                if (!tryAcquire()) return;
                submittingRef.current = true;
                const key = makeIdempotencyKey(`transfer-send-${task.task_id}`);
                mutation.mutate(key, {
                  onSettled: () => {
                    submittingRef.current = false;
                    release();
                  },
                });
              }}
            >
              {mutation.isPending || isSubmitting ? "Отправка..." : "Передать"}
            </Button>
          </div>
        </TableCell>
      )}
      <TableCornerResetCell />
    </TableRow>
  );
}

export function TransfersPage() {
  const queryClient = useQueryClient();
  const [spgId, setSpgId] = useState<number | null>(null);
  const [showAllSpgs, setShowAllSpgs] = useState(true);
  const [editTransferRecord, setEditTransferRecord] = useState<IncomingTransfer | null>(null);

  const inFlightRef = useRef<Set<number>>(new Set());
  const [inFlightVersion, setInFlightVersion] = useState(0);
  const tryAcquireTransferLock = useCallback((taskId: number): boolean => {
    if (inFlightRef.current.has(taskId)) return false;
    inFlightRef.current.add(taskId);
    setInFlightVersion((v) => v + 1);
    return true;
  }, []);
  const releaseTransferLock = useCallback((taskId: number): void => {
    if (!inFlightRef.current.has(taskId)) return;
    inFlightRef.current.delete(taskId);
    setInFlightVersion((v) => v + 1);
  }, []);
  const isTransferInFlight = useCallback(
    (taskId: number): boolean => inFlightRef.current.has(taskId),
    // inFlightVersion нужен в deps, чтобы после release строка перерендерилась и disabled обновился
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [inFlightVersion],
  );

  // Bulk Operations State
  const [bulkMode, setBulkMode] = useState(false);
  const bulkSelection = useBulkSelection<number>();
  const [bulkProgress, setBulkProgress] = useState<BulkRunnerProgress | null>(null);
  const [bulkResults, setBulkResults] = useState<BulkActionResultItem<number>[]>([]);
  const [bulkSummary, setBulkSummary] = useState<BulkActionSummary | null>(null);
  const [bulkResultsOpen, setBulkResultsOpen] = useState(false);
  const [bulkSendOpen, setBulkSendOpen] = useState(false);
  const [bulkComment, setBulkComment] = useState("");

  const { data: spgs } = useQuery({
    queryKey: queryKeys.spg.list(),
    queryFn: getSpgList,
  });

  const activeSpgId = showAllSpgs ? null : (spgId ?? spgs?.find((s) => s.is_active)?.id ?? null);

  const allSectionIds = useMemo(() => {
    if (!showAllSpgs) return new Set<number>();
    const ids = new Set<number>();
    spgs?.filter((s) => s.is_active).forEach((spg) => {
      spg.sections.forEach((sec) => ids.add(sec.section_id));
    });
    return ids;
  }, [showAllSpgs, spgs]);

  const { data: readyData, isLoading: readyLoading, refetch: refetchReady } = useQuery({
    queryKey: showAllSpgs ? queryKeys.transfers.readyAll() : queryKeys.transfers.ready(activeSpgId),
    queryFn: () => listReadyToTransfer({ spg_id: showAllSpgs ? undefined : activeSpgId }),
    enabled: showAllSpgs || activeSpgId != null,
  });

  const { data: historyData, isLoading: historyLoading, refetch: refetchHistory } = useQuery({
    queryKey: showAllSpgs ? queryKeys.transfers.historyAll() : queryKeys.transfers.history(activeSpgId),
    queryFn: () => listTransferHistory({ spg_id: showAllSpgs ? undefined : activeSpgId }),
    enabled: showAllSpgs || activeSpgId != null,
  });

  const readyItems = readyData?.items ?? [];
  const historyItems = historyData?.transfers ?? [];

  const {
    bindColumn: bindReadyColumn,
    buildFilterPredicate: buildReadyFilterPredicate,
    sortConfigs: readySortConfigs,
    handleSort: handleReadySort,
    hasActiveFilters: hasReadyFiltersActive,
    resetAll: resetReadyFilters,
  } = useFilterableTable<ReadySortField>();

  const {
    bindColumn: bindHistoryColumn,
    buildFilterPredicate: buildHistoryFilterPredicate,
    sortConfigs: historySortConfigs,
    handleSort: handleHistorySort,
    hasActiveFilters: hasHistoryFiltersActive,
    resetAll: resetHistoryFilters,
  } = useFilterableTable<HistorySortField>();

  const readyFilterPredicate = useMemo(
    () => buildReadyFilterPredicate(getReadyCellValue),
    [buildReadyFilterPredicate],
  );

  const readySortDefs = useMemo((): ColumnSortDef<ReadyToTransferTask, ReadySortField>[] => [
    { field: "taskId", getSortValue: (t) => t.task_id },
    { field: "sku", getSortValue: (t) => t.product_sku ?? "" },
    { field: "stage", getSortValue: (t) => t.operation_name ?? "" },
    { field: "transferableQty", getSortValue: (t) => parseFloat(t.transferable_quantity) || 0 },
    { field: "next", getSortValue: (t) => t.next_operation_name ?? "" },
  ], []);

  const readyUniqueValues = useMemo(
    () => ({
      taskId: [...new Set(readyItems.map((t) => String(t.task_id)))].sort((a, b) => Number(a) - Number(b)),
      sku: [...new Set(readyItems.map((t) => t.product_sku ?? "—"))].sort(),
      stage: [...new Set(readyItems.map((t) => t.operation_name ?? "—"))].sort(),
      transferableQty: [...new Set(readyItems.map((t) => fmtQty(t.transferable_quantity)))].sort(
        (a, b) => parseFloat(a) - parseFloat(b),
      ),
      next: [...new Set(readyItems.map((t) => getReadyCellValue(t, "next")))].sort(),
    }),
    [readyItems],
  );

  const { rows: filteredReadyItems } = useTableQueryEngine({
    rows: readyItems,
    getId: (t) => t.task_id,
    searchQuery: "",
    filterPredicate: readyFilterPredicate,
    sortConfigs: readySortConfigs,
    sortDefs: readySortDefs,
  });

  const historySectionIds = useMemo(() => {
    if (showAllSpgs) return allSectionIds;
    return new Set(spgs?.find((s) => s.id === activeSpgId)?.sections.map((sec) => sec.section_id) ?? []);
  }, [showAllSpgs, allSectionIds, spgs, activeSpgId]);

  const getHistoryCell = useCallback(
    (transfer: IncomingTransfer, field: HistorySortField) =>
      getHistoryCellValue(transfer, field, historySectionIds),
    [historySectionIds],
  );

  const historyFilterPredicate = useMemo(
    () => buildHistoryFilterPredicate(getHistoryCell),
    [buildHistoryFilterPredicate, getHistoryCell],
  );

  const historySortDefs = useMemo((): ColumnSortDef<IncomingTransfer, HistorySortField>[] => [
    { field: "from", getSortValue: (t) => t.from_section_name },
    { field: "to", getSortValue: (t) => t.to_section_name },
    { field: "sku", getSortValue: (t) => t.product_sku },
    { field: "quantity", getSortValue: (t) => parseFloat(t.sent_quantity) || 0 },
    { field: "status", getSortValue: (t) => getHistoryStatusLabel(t, historySectionIds) },
  ], [historySectionIds]);

  const historyUniqueValues = useMemo(
    () => ({
      from: [...new Set(historyItems.map((t) => getHistoryCellValue(t, "from", historySectionIds)))].sort(),
      to: [...new Set(historyItems.map((t) => getHistoryCellValue(t, "to", historySectionIds)))].sort(),
      sku: [...new Set(historyItems.map((t) => t.product_sku))].sort(),
      quantity: [...new Set(historyItems.map((t) => fmtQty(t.sent_quantity)))].sort(
        (a, b) => parseFloat(a) - parseFloat(b),
      ),
      status: [...new Set(historyItems.map((t) => getHistoryStatusLabel(t, historySectionIds)))].sort(),
    }),
    [historyItems, historySectionIds],
  );

  const { rows: filteredHistoryItems } = useTableQueryEngine({
    rows: historyItems,
    getId: (t) => t.transfer_id,
    searchQuery: "",
    filterPredicate: historyFilterPredicate,
    sortConfigs: historySortConfigs,
    sortDefs: historySortDefs,
  });

  function handleRefresh() {
    void refetchReady();
    void refetchHistory();
  }

  function invalidateShopfloorCaches(fromSectionId: number | null, toSectionId: number | null) {
    const sectionIds = new Set<number>();
    if (fromSectionId != null) sectionIds.add(fromSectionId);
    if (toSectionId != null && toSectionId !== fromSectionId) sectionIds.add(toSectionId);
    sectionIds.forEach((sid) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.shopfloor.board(sid) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.shopfloor.stats(sid) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.shopfloor.incomingTransfers(sid) });
    });
    void queryClient.invalidateQueries({ queryKey: queryKeys.shopfloor.summary() });
    void queryClient.invalidateQueries({ queryKey: queryKeys.sections.all() });
  }

  function invalidateTransfersCaches() {
    void queryClient.invalidateQueries({ queryKey: queryKeys.transfers.readyAll() });
    void queryClient.invalidateQueries({ queryKey: queryKeys.transfers.historyAll() });
    if (activeSpgId != null) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.transfers.ready(activeSpgId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.transfers.history(activeSpgId) });
    }
  }

  const cancelMutation = useMutation({
    mutationFn: (transferId: number) => cancelTransfer(transferId),
    onSuccess: (_, transferId) => {
      toast({
        variant: "success",
        title: "Передача отменена",
        description: "Передача успешно аннулирована",
      });
      const record = historyItems.find((t) => t.transfer_id === transferId);
      if (record) {
        invalidateShopfloorCaches(record.from_section_id, record.to_section_id);
      }
      invalidateTransfersCaches();
    },
    onError: (err: unknown) => {
      toast({
        variant: "destructive",
        title: "Ошибка отмены",
        description: getErrorMessage(err),
      });
    },
  });

  const exitBulkMode = useCallback(() => {
    bulkSelection.clear();
    setBulkMode(false);
  }, [bulkSelection]);

  const handleBulkTransferSubmit = useCallback(async (comment: string) => {
    const selectedTasks = readyItems.filter(t => bulkSelection.isSelected(t.task_id));
    if (selectedTasks.length === 0) return;

    setBulkSendOpen(false);
    setBulkProgress({ total: selectedTasks.length, completed: 0, running: true });

    const results: BulkActionResultItem<number>[] = [];
    let completedCount = 0;

    const actionResults = [];
    for (const task of selectedTasks) {
      try {
        await createTransfer({
          from_task_id: task.task_id,
          to_task_id: undefined,
          quantity: task.transferable_quantity,
          comment: comment.trim() || undefined,
          idempotency_key: makeIdempotencyKey(`transfer-send-bulk-${task.task_id}`),
        });

        completedCount++;
        setBulkProgress(prev => prev ? { ...prev, completed: completedCount } : null);

        actionResults.push({
          id: task.task_id,
          status: "success" as const,
          label: `Задание #${task.task_id} (${task.product_sku ?? "—"})`,
        });
      } catch (err) {
        completedCount++;
        setBulkProgress(prev => prev ? { ...prev, completed: completedCount } : null);

        actionResults.push({
          id: task.task_id,
          status: "failed" as const,
          reason: getErrorMessage(err),
          label: `Задание #${task.task_id} (${task.product_sku ?? "—"})`,
        });
      }
    }

    results.push(...actionResults);

    setBulkProgress(null);

    const summary = summarizeBulkResults(results);
    setBulkResults(results);
    setBulkSummary(summary);

    const sectionPairs = new Set<string>();
    selectedTasks.forEach(task => {
      sectionPairs.add(`${task.section_id}-${task.next_section_id}`);
    });

    sectionPairs.forEach(pair => {
      const [fromId, toId] = pair.split("-").map(Number);
      invalidateShopfloorCaches(fromId, toId);
    });

    invalidateTransfersCaches();

    toast({
      title: summary.failed > 0 ? "Частичный успех" : "Передача выполнена",
      description: `Успешно отправлено ${summary.success} из ${summary.total} перемещений`,
      variant: summary.failed > 0 ? "destructive" : "success",
    });

    if (summary.failed > 0 || summary.skipped > 0) {
      setBulkResultsOpen(true);
    }

    bulkSelection.clear();
    setBulkMode(false);
  }, [readyItems, bulkSelection, invalidateShopfloorCaches, invalidateTransfersCaches]);

  if (spgs !== undefined && spgs.length === 0) {
    return (
      <div className="p-6 text-center">
        <h1 className="text-xl font-semibold mb-2">Передачи между ГХП</h1>
        <p className="text-muted-foreground">В системе нет зарегистрированных групп хранения и производства (ГХП).</p>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6 max-w-screen-2xl">
      <header className="page-header">
        <div>
          <h1 className="page-title">Передачи между ГХП</h1>
          <p className="page-subtitle">
            Отдельный процесс передачи завершённых заданий на следующую ГХП по маршруту.
            В разделе «Готово к передаче» — задания текущего участка, у которых есть
            фактически выполненное количество, ожидающее отправки.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <SpgSelect
            spgs={spgs ?? []}
            value={showAllSpgs ? null : spgId}
            onValueChange={(val) => {
              setShowAllSpgs(false);
              setSpgId(val);
              setEditTransferRecord(null);
              bulkSelection.clear();
              setBulkMode(false);
            }}
            placeholder="Выберите ГХП"
            emptyLabel="Выберите ГХП"
            allLabel="Все ГХП"
            isAllSelected={showAllSpgs}
            onAllSelect={() => {
              setShowAllSpgs(true);
              setSpgId(null);
              setEditTransferRecord(null);
              bulkSelection.clear();
              setBulkMode(false);
            }}
            className="w-[260px] bg-background h-10 border text-sm"
          />
          <Button variant="outline" size="sm" onClick={handleRefresh}>
            <RefreshCw className="h-4 w-4 mr-1" /> Обновить
          </Button>
        </div>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
            <CardTitle className="flex items-center gap-2">
              <Send className="h-4 w-4" />
              Готово к передаче
              {readyItems.length > 0 && <Badge variant="secondary">{readyItems.length}</Badge>}
            </CardTitle>
            {readyItems.length > 0 && (
              <Button
                variant={bulkMode ? "default" : "outline"}
                size="sm"
                onClick={() => {
                  if (bulkMode) {
                    exitBulkMode();
                  } else {
                    setBulkMode(true);
                  }
                }}
              >
                Групповые операции
              </Button>
            )}
          </CardHeader>
          <CardContent>
            {bulkMode && (
              <div className="mb-4 p-2 bg-muted/40 rounded-lg flex items-center justify-between border border-dashed">
                <span className="text-sm font-medium">Выбрано: {bulkSelection.selectedCount}</span>
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    disabled={bulkSelection.selectedCount === 0}
                    onClick={() => {
                      setBulkSendOpen(true);
                    }}
                  >
                    Передать выбранные
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => bulkSelection.clear()}
                  >
                    Сбросить
                  </Button>
                </div>
              </div>
            )}

            {readyLoading ? (
              <div className="text-sm text-muted-foreground py-4 text-center">Загрузка…</div>
            ) : readyItems.length === 0 ? (
              <div className="text-sm text-muted-foreground py-6 text-center">
                Нет заданий, готовых к передаче на участках выбранной ГХП. Завершите работу на этапе, чтобы появились задания
                с доступным к передаче количеством.
              </div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    {bulkMode && (
                      <TableHead className="w-[40px] p-2">
                        <Checkbox
                          checked={bulkSelection.isAllSelected(filteredReadyItems.map((t) => t.task_id))}
                          onCheckedChange={(checked) => {
                            if (checked) {
                              bulkSelection.selectAll(filteredReadyItems.map((t) => t.task_id));
                            } else {
                              bulkSelection.clear();
                            }
                          }}
                        />
                      </TableHead>
                    )}
                    <TableHead className="p-0">
                      <SortableFilterHeader
                        field="taskId"
                        label="Задание"
                        currentSorts={readySortConfigs}
                        onSortChange={handleReadySort}
                        values={readyUniqueValues.taskId}
                        {...bindReadyColumn("taskId")}
                        valueLabel={(v) => `#${v}`}
                      />
                    </TableHead>
                    <TableHead className="p-0">
                      <SortableFilterHeader
                        field="sku"
                        label="Артикул"
                        currentSorts={readySortConfigs}
                        onSortChange={handleReadySort}
                        values={readyUniqueValues.sku}
                        {...bindReadyColumn("sku")}
                      />
                    </TableHead>
                    <TableHead className="p-0">
                      <SortableFilterHeader
                        field="stage"
                        label="Этап"
                        currentSorts={readySortConfigs}
                        onSortChange={handleReadySort}
                        values={readyUniqueValues.stage}
                        {...bindReadyColumn("stage")}
                      />
                    </TableHead>
                    <TableHead className="p-0 text-right">
                      <SortableFilterHeader
                        field="transferableQty"
                        label="К передаче"
                        currentSorts={readySortConfigs}
                        onSortChange={handleReadySort}
                        values={readyUniqueValues.transferableQty}
                        {...bindReadyColumn("transferableQty")}
                        valueLabel={(v) => `${v} шт.`}
                      />
                    </TableHead>
                    <TableHead className="p-0">
                      <SortableFilterHeader
                        field="next"
                        label="Следующий"
                        currentSorts={readySortConfigs}
                        onSortChange={handleReadySort}
                        values={readyUniqueValues.next}
                        {...bindReadyColumn("next")}
                      />
                    </TableHead>
                    {!bulkMode && (
                      <TableHead className="text-xs font-medium text-muted-foreground">
                        Действия
                      </TableHead>
                    )}
                    <TableCornerResetHeader
                      hasActiveFilters={hasReadyFiltersActive}
                      onReset={resetReadyFilters}
                    />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredReadyItems.length === 0 ? (
                    <TableRow>
                      <TableCell
                        colSpan={bulkMode ? 7 : 7}
                        className="py-6 text-center text-sm text-muted-foreground"
                      >
                        Нет заданий, соответствующих фильтру
                      </TableCell>
                    </TableRow>
                  ) : (
                    filteredReadyItems.map((t) => (
                      <ReadyTransferRow
                        key={t.task_id}
                        task={t}
                        bulkMode={bulkMode}
                        isSelected={bulkSelection.isSelected(t.task_id)}
                        onSelect={() => bulkSelection.selectOne(t.task_id)}
                        isSubmitting={isTransferInFlight(t.task_id)}
                        tryAcquire={() => tryAcquireTransferLock(t.task_id)}
                        release={() => releaseTransferLock(t.task_id)}
                        invalidateShopfloorCaches={invalidateShopfloorCaches}
                        invalidateTransfersCaches={invalidateTransfersCaches}
                      />
                    ))
                  )}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="flex items-center gap-2">
              <Inbox className="h-4 w-4" />
              Журнал передач
              {historyItems.length > 0 && <Badge variant="secondary">{historyItems.length}</Badge>}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {historyLoading ? (
              <div className="text-sm text-muted-foreground py-4 text-center">Загрузка…</div>
            ) : historyItems.length === 0 ? (
              <div className="text-sm text-muted-foreground py-6 text-center">
                Нет записей в журнале передач для выбранной ГХП.
              </div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="p-0">
                      <SortableFilterHeader
                        field="from"
                        label="Отправитель (Откуда)"
                        currentSorts={historySortConfigs}
                        onSortChange={handleHistorySort}
                        values={historyUniqueValues.from}
                        {...bindHistoryColumn("from")}
                      />
                    </TableHead>
                    <TableHead className="p-0">
                      <SortableFilterHeader
                        field="to"
                        label="Получатель (Куда)"
                        currentSorts={historySortConfigs}
                        onSortChange={handleHistorySort}
                        values={historyUniqueValues.to}
                        {...bindHistoryColumn("to")}
                      />
                    </TableHead>
                    <TableHead className="p-0">
                      <SortableFilterHeader
                        field="sku"
                        label="Артикул"
                        currentSorts={historySortConfigs}
                        onSortChange={handleHistorySort}
                        values={historyUniqueValues.sku}
                        {...bindHistoryColumn("sku")}
                      />
                    </TableHead>
                    <TableHead className="p-0 text-right">
                      <SortableFilterHeader
                        field="quantity"
                        label="Кол-во"
                        currentSorts={historySortConfigs}
                        onSortChange={handleHistorySort}
                        values={historyUniqueValues.quantity}
                        {...bindHistoryColumn("quantity")}
                      />
                    </TableHead>
                    <TableHead className="p-0">
                      <SortableFilterHeader
                        field="status"
                        label="Статус"
                        currentSorts={historySortConfigs}
                        onSortChange={handleHistorySort}
                        values={historyUniqueValues.status}
                        {...bindHistoryColumn("status")}
                      />
                    </TableHead>
                    <TableHead className="w-[40px]" />
                    <TableCornerResetHeader
                      hasActiveFilters={hasHistoryFiltersActive}
                      onReset={resetHistoryFilters}
                    />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredHistoryItems.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={7} className="py-6 text-center text-sm text-muted-foreground">
                        Нет записей, соответствующих фильтру
                      </TableCell>
                    </TableRow>
                  ) : (
                  filteredHistoryItems.map((t) => {
                    const isIncoming = historySectionIds.has(t.to_section_id);
                    const isCancelled = t.status === "cancelled";
                    const statusBadge = (() => {
                      if (isCancelled) return { label: "Аннулирована", variant: "destructive" as const };
                      if (t.status === "sent") return { label: "Отправлена", variant: "outline" as const };
                      if (t.status === "partially_accepted")
                        return { label: "Частично принята", variant: "outline" as const };
                      return { label: "Принята", variant: "outline" as const };
                    })();
                    return (
                      <TableRow
                        key={t.transfer_id}
                        className={`group cursor-pointer hover:bg-muted/50 transition-colors ${isCancelled ? "opacity-60" : ""}`}
                        onClick={() => setEditTransferRecord(t)}
                      >
                        <TableCell>
                          <div className="text-xs">
                            <div className="font-medium">{t.from_section_name}</div>
                            <div className="text-muted-foreground">{t.from_operation_name}</div>
                          </div>
                        </TableCell>
                        <TableCell>
                          <div className="text-xs">
                            <div className="font-medium">{t.to_section_name}</div>
                            <div className="text-muted-foreground">{t.to_operation_name}</div>
                          </div>
                        </TableCell>
                        <TableCell className="text-xs font-medium">{t.product_sku}</TableCell>
                        <TableCell className="text-right tabular-nums font-semibold whitespace-nowrap">
                          {fmtQty(t.sent_quantity)}
                        </TableCell>
                        <TableCell>
                          <div className="flex flex-col items-start gap-1">
                            <div className="flex flex-wrap items-center gap-1">
                              <Badge variant={isIncoming ? "default" : "secondary"} className="text-[10px] py-0 px-1.5 h-4">
                                {isIncoming ? "Входящая" : "Исходящая"}
                              </Badge>
                              <Badge variant={statusBadge.variant}>
                                {statusBadge.label}
                              </Badge>
                            </div>
                            {t.is_post_factum && (
                              <Badge
                                variant="secondary"
                                className="bg-amber-100 text-amber-800"
                                title={
                                  t.physical_handover_at
                                    ? `Физически передано: ${new Date(t.physical_handover_at).toLocaleString("ru-RU")}`
                                    : "Постфактум-передача"
                                }
                              >
                                Постфактум
                              </Badge>
                            )}
                          </div>
                        </TableCell>
                        <TableCell className="text-right w-[40px]">
                          <ChevronRight className="h-4 w-4 text-muted-foreground/60 transition-transform group-hover:translate-x-0.5 inline-block" />
                        </TableCell>
                        <TableCornerResetCell />
                      </TableRow>
                    );
                  }))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </div>

      {editTransferRecord && (
        <EditTransferDialog
          transfer={editTransferRecord}
          isIncoming={(() => {
            const activeSpg = spgs?.find((s) => s.id === activeSpgId);
            const sectionIdsInSpg = new Set(activeSpg?.sections.map((sec) => sec.section_id) ?? []);
            return sectionIdsInSpg.has(editTransferRecord.to_section_id);
          })()}
          onClose={() => setEditTransferRecord(null)}
          onSuccess={() => {
            setEditTransferRecord(null);
            invalidateShopfloorCaches(editTransferRecord.from_section_id, editTransferRecord.to_section_id);
            invalidateTransfersCaches();
          }}
          onCancel={() => {
            cancelMutation.mutate(editTransferRecord.transfer_id);
          }}
          isCancelling={cancelMutation.isPending && cancelMutation.variables === editTransferRecord.transfer_id}
        />
      )}

      {bulkSendOpen && (
        <CreateBulkTransferDialog
          selectedTasks={readyItems.filter(t => bulkSelection.isSelected(t.task_id))}
          onClose={() => setBulkSendOpen(false)}
          onSubmit={handleBulkTransferSubmit}
        />
      )}

      <BulkResultsDialog
        open={bulkResultsOpen}
        onOpenChange={setBulkResultsOpen}
        title="Результаты групповой передачи"
        summary={bulkSummary}
        results={bulkResults}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Create transfer dialog
// ---------------------------------------------------------------------------



// ---------------------------------------------------------------------------
// Edit transfer dialog
// ---------------------------------------------------------------------------

function EditTransferDialog({
  transfer,
  isIncoming,
  onClose,
  onSuccess,
  onCancel,
  isCancelling,
}: {
  transfer: IncomingTransfer;
  isIncoming: boolean;
  onClose: () => void;
  onSuccess: () => void;
  onCancel: () => void;
  isCancelling: boolean;
}) {
  const [quantity, setQuantity] = useState(transfer.sent_quantity);
  const [comment, setComment] = useState(transfer.comment || "");
  const [error, setError] = useState<string | null>(null);
  const [showCancelConfirm, setShowCancelConfirm] = useState(false);

  const isCancelled = transfer.status === "cancelled";
  const oldQty = parseFloat(transfer.sent_quantity);
  const qtyNum = parseFloat(quantity || "0");
  const hasChanged = qtyNum !== oldQty || comment !== (transfer.comment || "");

  const mutation = useMutation({
    mutationFn: () =>
      correctTransfer(transfer.transfer_id, {
        quantity,
        comment: comment || undefined,
      }),
    onSuccess: () => {
      toast({
        variant: "success",
        title: "Количество изменено",
        description: `Передача ${transfer.transfer_no} успешно скорректирована`,
      });
      onSuccess();
    },
    onError: (err: unknown) => {
      const message = getErrorMessage(err);
      setError(message);
    },
  });

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>
            {isCancelled ? "Детали передачи" : "Управление передачей"}
          </DialogTitle>
          <DialogDescription>
            {isCancelled
              ? "Просмотр информации об аннулированной передаче."
              : "Корректировка объема деталей или аннулирование передачи."}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div className="rounded-lg border bg-muted/20 p-3 text-xs grid grid-cols-2 gap-2">
            <div>
              Отправитель: <span className="font-medium">{transfer.from_section_name}</span>
            </div>
            <div>
              Получатель: <span className="font-medium">{transfer.to_section_name}</span>
            </div>
            <div className="col-span-2">
              Продукт: <span className="font-medium">{transfer.product_sku}</span>
            </div>
            <div className="col-span-2 flex items-center gap-1.5 mt-1">
              <span>Статус:</span>
              <Badge variant={isIncoming ? "default" : "secondary"} className="text-[10px] py-0 px-1.5 h-4">
                {isIncoming ? "Входящая" : "Исходящая"}
              </Badge>
              <Badge variant={statusBadgeVariant(transfer.status)}>
                {statusBadgeLabel(transfer.status)}
              </Badge>
            </div>
          </div>

          {showCancelConfirm ? (
            <div className="space-y-3 rounded-lg border border-destructive bg-destructive/5 p-3.5 mt-2">
              <div className="flex items-start gap-2 text-destructive">
                <AlertCircle className="h-5 w-5 flex-shrink-0 mt-0.5" />
                <div>
                  <h4 className="font-semibold text-sm">Аннулировать передачу?</h4>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    Это действие вернет остатки деталей в исходное состояние.
                  </p>
                </div>
              </div>
              <div className="flex justify-end gap-2 pt-1 text-xs">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setShowCancelConfirm(false)}
                >
                  Назад
                </Button>
                <Button
                  size="sm"
                  variant="destructive"
                  disabled={isCancelling}
                  onClick={onCancel}
                >
                  {isCancelling ? "Аннулирование..." : "Да, аннулировать"}
                </Button>
              </div>
            </div>
          ) : (
            <>
              <div>
                <label className="text-sm font-medium">Количество</label>
                <Input
                  type="number"
                  step="1"
                  min="1"
                  value={quantity}
                  disabled={isCancelled}
                  onChange={(e) => {
                    setQuantity(e.target.value);
                    setError(null);
                  }}
                />
              </div>

              <div>
                <label className="text-sm font-medium">Комментарий / Причина</label>
                <Input
                  value={comment}
                  disabled={isCancelled}
                  onChange={(e) => setComment(e.target.value)}
                  placeholder={isCancelled ? "" : "Укажите причину корректировки"}
                />
              </div>

              {error && (
                <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-800">
                  {error}
                </div>
              )}

              <div className="flex justify-between items-center pt-2 gap-2">
                <div>
                  {!isCancelled && (
                    <Button
                      variant="destructive"
                      onClick={() => setShowCancelConfirm(true)}
                    >
                      Аннулировать
                    </Button>
                  )}
                </div>
                <div className="flex gap-2">
                  <Button variant="outline" onClick={onClose}>
                    {isCancelled ? "Закрыть" : "Отмена"}
                  </Button>
                  {!isCancelled && (
                    <Button
                      onClick={() => mutation.mutate()}
                      disabled={mutation.isPending || qtyNum <= 0 || !hasChanged}
                    >
                      {mutation.isPending ? "Сохранение..." : "Сохранить"}
                    </Button>
                  )}
                </div>
              </div>
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Create bulk transfer dialog
// ---------------------------------------------------------------------------

function CreateBulkTransferDialog({
  selectedTasks,
  onClose,
  onSubmit,
}: {
  selectedTasks: ReadyToTransferTask[];
  onClose: () => void;
  onSubmit: (comment: string) => void;
}) {
  const [comment, setComment] = useState("");

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Групповая передача на следующий этап</DialogTitle>
          <DialogDescription>
            Будет отправлено {selectedTasks.length} заданий на соответствующие следующие этапы маршрутов.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="max-h-[200px] overflow-y-auto rounded-lg border p-3 bg-muted/20 text-xs space-y-2">
            {selectedTasks.map((task) => (
              <div key={task.task_id} className="flex justify-between border-b pb-1 last:border-b-0 last:pb-0">
                <div>
                  <span className="font-mono font-medium">#{task.task_id}</span> ({task.product_sku})
                  <div className="text-muted-foreground">
                    {task.operation_name} &rarr; {task.next_operation_name}
                  </div>
                </div>
                <div className="text-right font-medium">
                  {fmtQty(task.transferable_quantity)} шт.
                </div>
              </div>
            ))}
          </div>

          <div>
            <label className="text-sm font-medium">Общий комментарий</label>
            <Input
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder="Опционально (применится ко всем передачам)"
            />
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={onClose}>
              Отмена
            </Button>
            <Button
              onClick={() => onSubmit(comment)}
              disabled={selectedTasks.length === 0}
            >
              Отправить все
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
