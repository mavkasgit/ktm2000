import { useState, useCallback, useEffect, useMemo, useRef } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Send,
  Inbox,
  RefreshCw,
  AlertCircle,
  ChevronRight,
  ChevronDown,
  Search,
} from "lucide-react";

import {
  ActionWithReason,
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
  DataTableColumnHeader,
  TableCornerResetCell,
  TableCornerResetHeader,
  DATA_TABLE_STYLES,
  VirtualizedTableBody,
  TablePaginationFooter,
} from "@/shared/ui";
import { useFilterableTable } from "@/shared/hooks/useFilterableTable";
import { usePaginatedTableQuery } from "@/shared/hooks/usePaginatedTableQuery";

import { getSpgList } from "@/shared/api/spg";
import {
  cancelTransfer,
  correctTransfer,
  createTransfer,
  finalReleaseTask,
  listReadyToTransfer,
  listTransferHistory,
  type ReadyToTransferListParams,
  type IncomingTransfer,
  type ReadyToTransferTask,
  type TransferHistoryListParams,
  type ReadyToTransferResponse,
  type TransferHistoryResponse,
} from "@/shared/api/transfers";
import { getErrorMessage } from "@/shared/api/client";
import { invalidateAfter } from "@/shared/api/cacheInvalidation";
import { queryKeys } from "@/shared/api/queryKeys";
import { formatDimensionsFilterValue, formatDimensionsLabel } from "@/shared/api/stock";
import { buildColumnApiParams } from "@/shared/lib/columnSpecs";
import { isFirstRowsLoad, keepPreviousDataForScope } from "@/shared/lib/tableQueryPlaceholder";
import { historyColumns, readyColumns } from "../lib/transferColumns";
import { TABLE_ROW_COMPACT } from "@/shared/lib/dataTableStyles";
import { cn } from "@/shared/utils/cn";
import {
  useBulkSelection,
  BulkResultsDialog,
  type BulkActionResultItem,
  type BulkActionSummary,
  type BulkRunnerProgress,
} from "@/shared/bulk";
import {
  BulkTransferFooter,
  type BulkTransferSubmitData,
} from "../components/BulkTransferFooter";
import {
  dimensionsKey,
  groupReadyTransfers,
  isFinalReadyRow,
  type ReadyTransferGroup,
} from "../lib/groupReadyTransfers";
import { makeIdempotencyKey, runTransferBatch } from "../lib/runTransferBatch";
import { useFlushableDebouncedValue } from "@/shared/lib/useDebouncedValue";
import {
  buildHistorySortParam,
  buildReadySortParam,
  type HistorySortField,
  type ReadySortField,
} from "../lib/transferSortParams";
import { fmtQty } from "@/shared/lib/quantityFormat";
import { actionReasonText, type ActionReasonCode } from "@/shared/lib/actionReasons";

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
  if (n.includes("exceeds releasable quantity")) {
    return "Количество больше доступного к выпуску.";
  }
  if (n.includes("only for final route stage")) {
    return "Финальный выпуск доступен только на финальном этапе маршрута.";
  }
  return null;
}

type StatusBadgeVariant = "default" | "destructive" | "outline" | "secondary";

/** Строка таблицы «Готово к передаче»: задание либо заголовок группы заданий. */
type ReadyTableRow =
  | { kind: "task"; task: ReadyToTransferTask; groupKey: string | null }
  | { kind: "group"; group: ReadyTransferGroup };

function statusBadgeLabel(status: string): string {
  // Under the explicit-transfer model, transfer_send auto-accepts the
  // transfer inline. By the time the operator sees the history list,
  // every transfer is either "Принята", "Аннулирована" or "Скорректирована"
  // (amended, тикет #124 — живёт новая пара SEND/RECEIVE).
  if (status === "cancelled") return "Аннулирована";
  if (status === "amended") return "Скорректирована";
  return "Принята";
}

function statusBadgeVariant(status: string): StatusBadgeVariant {
  if (status === "cancelled") return "destructive";
  if (status === "amended") return "secondary";
  return "outline";
}

function getReadyCellValue(task: ReadyToTransferTask, field: ReadySortField): string {
  switch (field) {
    case "positionId":
      return String(task.plan_position_id);
    case "sku":
      return task.product_sku ?? "—";
    case "dimensions":
      return formatDimensionsLabel(task.dimensions, task.dimensions_label);
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

function getHistoryStatusLabel(
  transfer: IncomingTransfer,
  sectionIdsInSpg: Set<number>,
): string {
  const isIncoming = sectionIdsInSpg.has(transfer.to_section_id);
  const direction = isIncoming ? "Входящая" : "Исходящая";
  if (transfer.status === "cancelled") return `${direction} / Аннулирована`;
  if (transfer.status === "amended") return `${direction} / Скорректирована`;
  if (transfer.status === "sent") return `${direction} / Отправлена`;
  if (transfer.status === "partially_accepted") return `${direction} / Частично принята`;
  return `${direction} / Принята`;
}


/**
 * Параметры журнала собираются из описания колонок. Раньше здесь стояло
 * четыре строки с именами колонок.
 */
function buildHistoryColumnApiParams(
  columnFilters: Partial<Record<HistorySortField, Set<string>>>,
  columnSearchQueries: Partial<Record<HistorySortField, string>>,
): Record<string, string> {
  return buildColumnApiParams(columnFilters, columnSearchQueries, historyColumns);
}

/**
 * Параметры готовых к передаче собираются из описания колонок. Раньше здесь
 * стояло семь строк с именами колонок, включая ручной вызов точного значения
 * по имени поля «Размер».
 *
 * Возвращается `Record<string, string>`, а не `Pick<ReadyToTransferListParams, …>`:
 * приведение к `Pick` компилируется с любым набором строковых ключей и
 * поэтому ничего не проверяет — именно через него проскочило имя
 * `transferableQty` вместо `transferable_qty`, и фильтр перестал уезжать.
 */
function buildReadyColumnApiParams(
  columnFilters: Partial<Record<ReadySortField, Set<string>>>,
  columnSearchQueries: Partial<Record<ReadySortField, string>>,
): Record<string, string> {
  return buildColumnApiParams(columnFilters, columnSearchQueries, readyColumns);
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
  invalidateTransferCaches: () => void;
}

function ReadyTransferRow({
  task,
  bulkMode,
  isSelected,
  onSelect,
  isSubmitting,
  tryAcquire,
  release,
  invalidateTransferCaches,
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
        dimensions: task.dimensions ?? undefined,
      }),
    onSuccess: () => {
      toast({
        variant: "success",
        title: "Передача создана",
        description: `Позиция #${task.plan_position_id} отправлена`,
      });
      invalidateTransferCaches();
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

  const isFinalRow = isFinalReadyRow(task);
  const releaseMutation = useMutation({
    mutationFn: (idempotencyKey: string) =>
      finalReleaseTask(task.task_id, {
        quantity,
        comment: undefined,
        idempotency_key: idempotencyKey,
        dimensions: task.dimensions ?? undefined,
      }),
    onSuccess: () => {
      toast({
        variant: "success",
        title: "Финальный выпуск",
        description: `Позиция #${task.plan_position_id} выпущена`,
      });
      invalidateTransferCaches();
    },
    onError: (err: unknown) => {
      const message = getErrorMessage(err);
      const hint = conflictHintFromTransferError(message);
      toast({
        variant: "destructive",
        title: "Ошибка выпуска",
        description: hint ?? message,
      });
    },
  });

  const maxQty = parseFloat(task.transferable_quantity);
  const qtyNum = parseFloat(quantity || "0");
  const overLimit = qtyNum > maxQty;
  const isOverPlan = qtyNum > parseFloat(task.planned_quantity);
  /** Количество не введено или обнулено — передавать нечего (#193). */
  const quantityReason: ActionReasonCode | null = qtyNum > 0 ? null : "zero_quantity";

  return (
    <TableRow
      data-row-kind="ready-task"
      // Стабильный идентификатор строки ready-таблицы: единица передачи —
      // пара «задание × размер» (см. `groupReadyTransfers`), поэтому одного
      // `task_id` мало. E2E-хелперы адресуют строку по нему: динамический
      // `rows.first()` уводит клик в соседнюю строку при refetch, а текст
      // строки меняется на «Отправка…» прямо во время ожидания.
      data-row-key={`${task.task_id}:${dimensionsKey(task.dimensions)}`}
      className={bulkMode ? "cursor-pointer hover:bg-muted/50" : undefined}
      onClick={bulkMode ? onSelect : undefined}
    >
      {bulkMode && (
        <TableCell className="${TABLE_ROW_COMPACT.cell} w-[40px]" onClick={(e) => e.stopPropagation()}>
          <Checkbox
            checked={isSelected}
            disabled={isFinalRow}
            onCheckedChange={onSelect}
            title={isFinalRow ? actionReasonText("final_release_not_in_bulk") : undefined}
          />
        </TableCell>
      )}
      <TableCell className="${TABLE_ROW_COMPACT.cell} font-mono text-xs text-muted-foreground">#{task.plan_position_id}</TableCell>
      <TableCell className={TABLE_ROW_COMPACT.cell}>{task.product_sku ?? "—"}</TableCell>
      <TableCell className="${TABLE_ROW_COMPACT.cell} text-xs text-muted-foreground whitespace-nowrap">
        {formatDimensionsLabel(task.dimensions, task.dimensions_label)}
      </TableCell>
      <TableCell className={TABLE_ROW_COMPACT.cell}>
        <div className="text-xs">
          <div className="font-medium">{task.operation_name ?? "—"}</div>
          <div className="text-muted-foreground">#{task.sequence}</div>
        </div>
      </TableCell>
      <TableCell className="${TABLE_ROW_COMPACT.cell} text-right tabular-nums">
        <div className="whitespace-nowrap">
          <span className="font-medium">{fmtQty(task.transferable_quantity)} шт.</span>{" "}
          <span className="text-[11px] text-muted-foreground">
            (план {fmtQty(task.planned_quantity)})
          </span>
          {task.dimensions != null && (
            <span className="ml-1 text-[10px] text-muted-foreground" title="Габарит из плана">
              · {formatDimensionsLabel(task.dimensions, task.dimensions_label)}
            </span>
          )}
        </div>
        {task.completion_comment && (
          <div className="text-[10px] text-muted-foreground mt-0.5 leading-tight" title={task.completion_comment}>
            {task.completion_comment}
          </div>
        )}
      </TableCell>
      <TableCell className="${TABLE_ROW_COMPACT.cell} text-xs">
        {task.has_next_step ? (
          <>
            <div>{task.next_operation_name ?? "—"}</div>
            <div className="text-muted-foreground">
              {task.next_section_code ?? "—"} #{task.next_step_sequence ?? "—"}
            </div>
          </>
        ) : (
          <div>
            <Badge variant="outline">Финальный</Badge>
            {bulkMode && isFinalRow && (
              <div className="mt-0.5 whitespace-nowrap text-[10px] leading-tight text-muted-foreground">
                {actionReasonText("final_release_not_in_bulk")}
              </div>
            )}
          </div>
        )}
      </TableCell>
      {!bulkMode && (
        <TableCell className={TABLE_ROW_COMPACT.cell} onClick={(e) => e.stopPropagation()}>
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
            <ActionWithReason reason={quantityReason}>
              {isFinalRow ? (
                <Button
                  size="sm"
                  className={TABLE_ROW_COMPACT.actionButton}
                  disabled={isSubmitting || releaseMutation.isPending || quantityReason !== null}
                  title={quantityReason ? actionReasonText(quantityReason) : "Финальный выпуск готовой продукции"}
                  onClick={() => {
                    if (submittingRef.current || isSubmitting || releaseMutation.isPending) return;
                    if (!tryAcquire()) return;
                    submittingRef.current = true;
                    const key = makeIdempotencyKey(`final-release-${task.task_id}`);
                    releaseMutation.mutate(key, {
                      onSettled: () => {
                        submittingRef.current = false;
                        release();
                      },
                    });
                  }}
                >
                  {releaseMutation.isPending || isSubmitting ? "Отправка..." : "Отправить"}
                </Button>
              ) : (
                <Button
                  size="sm"
                  className={TABLE_ROW_COMPACT.actionButton}
                  disabled={isSubmitting || mutation.isPending || quantityReason !== null}
                  title={quantityReason ? actionReasonText(quantityReason) : "Передать на следующий этап"}
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
              )}
            </ActionWithReason>
          </div>
        </TableCell>
      )}
      <TableCornerResetCell />
    </TableRow>
  );
}

/**
 * Ряд-заголовок группы ready-строк — строк, неразличимых для передачи: тот же
 * артикул, участок, размер и адресат (см. `groupReadyTransfers`). Группа свёрнута
 * по умолчанию; введённое общее количество распределяется по строкам
 * последовательно (`runTransferBatch`). В чекбокс-режиме группы раскрыты
 * принудительно и групповой кнопки не имеют.
 */
function ReadyTransferGroupRow({
  group,
  bulkMode,
  isCollapsed,
  isSubmitting,
  hasInFlightRow,
  onToggleCollapse,
  onTransferGroup,
}: {
  group: ReadyTransferGroup;
  bulkMode: boolean;
  isCollapsed: boolean;
  isSubmitting: boolean;
  hasInFlightRow: boolean;
  onToggleCollapse: () => void;
  onTransferGroup: (group: ReadyTransferGroup, quantity: string) => void;
}) {
  const [quantity, setQuantity] = useState(() => fmtQty(group.totalTransferable));

  useEffect(() => {
    setQuantity(fmtQty(group.totalTransferable));
  }, [group.totalTransferable]);

  const { common } = group;
  const qtyNum = parseFloat(quantity || "0");
  const overLimit = Math.round(qtyNum * 1000) > Math.round(group.totalTransferable * 1000);
  /**
   * Причина, по которой передача группы не нажимается (#193). Собственная
   * отправка группы (`isSubmitting`) причиной не считается — о ней говорит
   * надпись «Отправка...».
   */
  const groupBlockReason: ActionReasonCode | null = hasInFlightRow
    ? "row_in_flight"
    : qtyNum > 0
      ? null
      : "zero_quantity";

  return (
    <TableRow
      data-row-kind="ready-group"
      className={`border-y border-border/60 bg-muted/50 font-semibold hover:bg-muted ${
        bulkMode ? "" : "cursor-pointer"
      }`}
      onClick={bulkMode ? undefined : onToggleCollapse}
    >
      {bulkMode && <TableCell className="${TABLE_ROW_COMPACT.cell} w-[40px]" />}
      <TableCell className="${TABLE_ROW_COMPACT.cell} text-center">
        <button
          className="p-1 hover:bg-muted rounded transition-colors text-muted-foreground"
          title={bulkMode ? "Группа раскрыта для ручного выбора" : isCollapsed ? "Раскрыть" : "Скрыть"}
          disabled={bulkMode}
          onClick={(e) => {
            e.stopPropagation();
            onToggleCollapse();
          }}
        >
          {isCollapsed ? (
            <ChevronRight className="h-4 w-4 shrink-0" />
          ) : (
            <ChevronDown className="h-4 w-4 shrink-0" />
          )}
        </button>
      </TableCell>
      <TableCell className={TABLE_ROW_COMPACT.cell}>
        <div className="flex items-center gap-2">
          <span>{group.productSku ?? "—"}</span>
          <Badge variant="secondary" className="font-bold">
            &times;{group.rows.length}
          </Badge>
        </div>
      </TableCell>
      <TableCell className="${TABLE_ROW_COMPACT.cell} text-xs text-muted-foreground whitespace-nowrap">
        {common.dimensionsLabel ?? "—"}
      </TableCell>
      <TableCell className={TABLE_ROW_COMPACT.cell}>
        <div className="text-xs">
          <div className="font-medium">{common.operationName ?? "—"}</div>
          <div className="text-muted-foreground">
            {common.sequence == null ? "—" : `#${common.sequence}`}
          </div>
        </div>
      </TableCell>
      <TableCell className="${TABLE_ROW_COMPACT.cell} text-right tabular-nums">
        {/* Как у одиночной строки: в «К передаче» — текст, редактируемое поле —
            в «Действиях». Сумма по группе, распределяется по строкам. */}
        <div className="whitespace-nowrap">
          <span className="font-medium">{fmtQty(group.totalTransferable)} шт.</span>{" "}
          <span className="text-[11px] text-muted-foreground">
            ({group.rows.length} поз.)
          </span>
        </div>
      </TableCell>
      <TableCell className="${TABLE_ROW_COMPACT.cell} text-xs">
        {group.hasNextStep ? (
          <>
            <div>{common.nextOperationName ?? "—"}</div>
            <div className="text-muted-foreground">
              {common.nextSectionCode ?? "—"} #{common.nextStepSequence ?? "—"}
            </div>
          </>
        ) : (
          <Badge variant="outline">Финальный</Badge>
        )}
      </TableCell>
      {!bulkMode && (
        <TableCell className={TABLE_ROW_COMPACT.cell} onClick={(e) => e.stopPropagation()}>
          <div className="flex items-center justify-end gap-2">
            <div className="flex items-center gap-1">
              <Input
                type="number"
                step="1"
                min="0"
                value={quantity}
                disabled={isSubmitting}
                className={`w-20 h-8 text-right px-2 ${
                  overLimit ? "border-amber-400 focus-visible:ring-amber-400" : ""
                }`}
                title={
                  overLimit
                    ? `Больше доступного (${fmtQty(group.totalTransferable)} шт.) — излишек не передастся`
                    : "Общее количество группы: распределится по строкам по порядку"
                }
                onChange={(e) => setQuantity(e.target.value)}
              />
            </div>
            <ActionWithReason reason={groupBlockReason}>
              <Button
                size="sm"
                className={TABLE_ROW_COMPACT.actionButton}
                disabled={isSubmitting || groupBlockReason !== null}
                title={
                  groupBlockReason
                    ? actionReasonText(groupBlockReason)
                    : group.allFinal
                      ? "Финальный выпуск всех заданий группы"
                      : "Передать на следующий этап все задания группы"
                }
                onClick={() => onTransferGroup(group, quantity)}
              >
                {isSubmitting ? "Отправка..." : group.allFinal ? "Отправить" : "Передать"}
              </Button>
            </ActionWithReason>
          </div>
        </TableCell>
      )}
      <TableCornerResetCell />
    </TableRow>
  );
}

const headerCellClass = cn(DATA_TABLE_STYLES.headerRow, DATA_TABLE_STYLES.headerCell, TABLE_ROW_COMPACT.headerCell);

export function TransfersPage() {
  const queryClient = useQueryClient();
  const [spgId, setSpgId] = useState<number | null>(null);
  const [showAllSpgs, setShowAllSpgs] = useState(true);
  const [editTransferRecord, setEditTransferRecord] = useState<IncomingTransfer | null>(null);
  const [historySearch, setHistorySearch] = useState("");
  const { value: debouncedHistorySearch, flush: flushHistorySearch } =
    useFlushableDebouncedValue(historySearch);
  const [readySearch, setReadySearch] = useState("");
  const { value: debouncedReadySearch, flush: flushReadySearch } =
    useFlushableDebouncedValue(readySearch);
  // Журнал передач — боковая панель: не отнимает ширину у «Готово к передаче».
  const [historyOpen, setHistoryOpen] = useState(false);
  const historyScrollRef = useRef<HTMLDivElement>(null);
  const readyScrollRef = useRef<HTMLDivElement>(null);


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
  const [bulkSubmitting, setBulkSubmitting] = useState(false);

  // Группы свёрнуты по умолчанию: в наборе — раскрытые оператором, в рамках сессии.
  const [expandedGroupKeys, setExpandedGroupKeys] = useState<Set<string>>(new Set());
  const [groupSubmittingKey, setGroupSubmittingKey] = useState<string | null>(null);

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

  const {
    bindColumn: bindReadyColumn,
    columnFilters: readyColumnFilters,
    columnSearchQueries: readyColumnSearchQueries,
    debouncedColumnSearchQueries: readyDebouncedColumnSearchQueries,
    sortConfigs: readySortConfigs,
    handleSort: applyReadySort,
    hasActiveFilters: hasReadyFiltersActive,
    resetAll: resetReadyFiltersBase,
  } = useFilterableTable<ReadySortField>({
    extraHasActive: debouncedReadySearch.trim().length > 0,
    onExtraReset: () => setReadySearch(""),
  });

  const readyColumnApiParams = useMemo(
    () => buildReadyColumnApiParams(readyColumnFilters, readyDebouncedColumnSearchQueries),
    [readyColumnFilters, readyDebouncedColumnSearchQueries],
  );

  const readyPagination = usePaginatedTableQuery({
    resetPageDeps: [
      showAllSpgs,
      activeSpgId,
      debouncedReadySearch,
      readyColumnFilters,
      readyDebouncedColumnSearchQueries,
      readySortConfigs,
    ],
  });

  const readyQueryParams = useMemo(
    () => ({
      limit: readyPagination.limit,
      offset: readyPagination.offset,
      search: debouncedReadySearch.trim() || undefined,
      sort: buildReadySortParam(readySortConfigs),
      ...readyColumnApiParams,
    }),
    [
      readyPagination.limit,
      readyPagination.offset,
      debouncedReadySearch,
      readySortConfigs,
      readyColumnApiParams,
    ],
  );

  // Дерево держится на смене страницы, фильтра и сортировки, но НЕ через смену
  // ГХП: он переключается селектом без размонтирования, и placeholder оставил бы
  // строки прежнего ГХП под новым — при том, что подписи участков в них уже
  // пересчитаны по новому (ADR-0044).
  const { data: readyData, isPending: readyPending, refetch: refetchReady } = useQuery({
    queryKey: showAllSpgs
      ? queryKeys.transfers.readyAll(readyQueryParams)
      : queryKeys.transfers.ready(activeSpgId, readyQueryParams),
    queryFn: () =>
      listReadyToTransfer({
        spg_id: showAllSpgs ? undefined : activeSpgId,
        ...readyQueryParams,
      }),
    enabled: showAllSpgs || activeSpgId != null,
    placeholderData: keepPreviousDataForScope<ReadyToTransferResponse>(
      (key) => key[1],
      showAllSpgs ? "all" : activeSpgId,
    ),
  });

  const {
    bindColumn: bindHistoryColumn,
    columnFilters: historyColumnFilters,
    columnSearchQueries: historyColumnSearchQueries,
    debouncedColumnSearchQueries: historyDebouncedColumnSearchQueries,
    sortConfigs: historySortConfigs,
    setSortConfigs: setHistorySortConfigs,
    handleSort: applyHistorySort,
    hasActiveFilters: hasHistoryFiltersActive,
    resetAll: resetHistoryFiltersBase,
  } = useFilterableTable<HistorySortField>({
    extraHasActive: historySearch.trim().length > 0,
    onExtraReset: () => {
      setHistorySearch("");
      setHistorySortConfigs([]);
    },
  });

  const historyColumnApiParams = useMemo(
    () => buildHistoryColumnApiParams(historyColumnFilters, historyDebouncedColumnSearchQueries),
    [historyColumnFilters, historyDebouncedColumnSearchQueries],
  );

  const historyPagination = usePaginatedTableQuery({
    resetPageDeps: [
      showAllSpgs,
      activeSpgId,
      debouncedHistorySearch,
      historyColumnFilters,
      historyDebouncedColumnSearchQueries,
      historySortConfigs,
    ],
  });

  const historyQueryParams = useMemo(
    () => ({
      limit: historyPagination.limit,
      offset: historyPagination.offset,
      search: debouncedHistorySearch.trim() || undefined,
      sort: buildHistorySortParam(historySortConfigs),
      ...historyColumnApiParams,
    }),
    [
      historyPagination.limit,
      historyPagination.offset,
      debouncedHistorySearch,
      historySortConfigs,
      historyColumnApiParams,
    ],
  );

  const { data: historyData, isPending: historyPending, refetch: refetchHistory } = useQuery({
    queryKey: showAllSpgs
      ? queryKeys.transfers.historyAll(historyQueryParams)
      : queryKeys.transfers.history(activeSpgId, historyQueryParams),
    queryFn: () =>
      listTransferHistory({
        spg_id: showAllSpgs ? undefined : activeSpgId,
        ...historyQueryParams,
      }),
    enabled: showAllSpgs || activeSpgId != null,
    placeholderData: keepPreviousDataForScope<TransferHistoryResponse>(
      (key) => key[1],
      showAllSpgs ? "all" : activeSpgId,
    ),
  });

  const readyItems = readyData?.items ?? [];
  const readyTotal = readyData?.total ?? 0;

  const readyGroupItems = useMemo(() => groupReadyTransfers(readyItems), [readyItems]);

  // Свёрнутая группа и сортировка по колонке несовместимы: в шапке группы
  // печатается общий этап и СУММА «К передаче», а порядок групп — порядок
  // первого появления строки. Пока колонка не выбрана, дефолтный порядок
  // сервера (этап маршрута) группировке не противоречит, и группы остаются
  // свёрнутыми. Как только оператор выбрал колонку, рисуем строки заданий
  // как есть: тогда порядок строк совпадает с тем, что напечатано в ячейке.
  const readySortingActive = readySortConfigs.length > 0;

  // Строки таблицы «Готово к передаче» = свёрнутые группы (только заголовки) +
  // дети раскрытых + одиночные строки. В чекбокс-режиме группы раскрыты
  // принудительно: там оператор выбирает строки точечно, а групповую отправку
  // делает футер.
  const readyTableRows = useMemo<ReadyTableRow[]>(() => {
    if (readySortingActive) {
      // Порядок пришёл с сервера и уже отсортирован по выбранной колонке —
      // рендерим строки заданий как есть, без перегруппировки.
      return readyItems.map((task) => ({ kind: "task" as const, task, groupKey: null }));
    }
    const rows: ReadyTableRow[] = [];
    for (const item of readyGroupItems) {
      if (item.kind === "single") {
        rows.push({ kind: "task", task: item.row, groupKey: null });
        continue;
      }
      rows.push({ kind: "group", group: item });
      if (bulkMode || expandedGroupKeys.has(item.key)) {
        for (const task of item.rows) rows.push({ kind: "task", task, groupKey: item.key });
      }
    }
    return rows;
  }, [bulkMode, readyGroupItems, readyItems, expandedGroupKeys, readySortingActive]);

  const historyItems = historyData?.transfers ?? [];
  const historyTotal = historyData?.total ?? 0;
  const {
    page: historyPage,
    setPage: setHistoryPage,
    limit: historyLimit,
    setLimit: setHistoryLimit,
    resetPage: resetHistoryPage,
    getTotalPages: computeHistoryTotalPages,
    getRangeLabel: historyRangeLabel,
  } = historyPagination;
  const historyTotalPages = computeHistoryTotalPages(historyTotal);

  const {
    page: readyPage,
    setPage: setReadyPage,
    limit: readyLimit,
    setLimit: setReadyLimit,
    resetPage: resetReadyPage,
    getTotalPages: computeReadyTotalPages,
    getRangeLabel: readyRangeLabel,
  } = readyPagination;
  const readyTotalPages = computeReadyTotalPages(readyTotal);

  // Цикл клика общий (нет → убыв. → возр. → снять): третье состояние
  // возвращает свёрнутые группы, а выбранные приоритеты уходят на сервер
  // все сразу одной строкой `sort`.
  const handleReadySort = useCallback(
    (field: ReadySortField) => {
      applyReadySort(field);
      readyPagination.resetPage();
    },
    [applyReadySort, readyPagination],
  );

  const resetReadyFilters = useCallback(() => {
    resetReadyFiltersBase();
  }, [resetReadyFiltersBase]);

  const handleHistorySort = useCallback(
    (field: HistorySortField) => {
      applyHistorySort(field);
      resetHistoryPage();
    },
    [applyHistorySort, resetHistoryPage],
  );

  const resetHistoryFilters = useCallback(() => {
    resetHistoryFiltersBase();
  }, [resetHistoryFiltersBase]);

  const readyUniqueValues = useMemo(
    () => ({
      positionId: [...new Set(readyItems.map((t) => String(t.plan_position_id)))].sort(
        (a, b) => Number(a) - Number(b),
      ),
      sku: [...new Set(readyItems.map((t) => t.product_sku ?? "—"))].sort(),
      dimensions: [...new Set(readyItems.map((t) => JSON.stringify(t.dimensions ?? null)))].sort(
        (a, b) => formatDimensionsFilterValue(a).localeCompare(formatDimensionsFilterValue(b), "ru"),
      ),
      stage: [...new Set(readyItems.map((t) => t.operation_name ?? "—"))].sort(),
      transferableQty: [...new Set(readyItems.map((t) => fmtQty(t.transferable_quantity)))].sort(
        (a, b) => parseFloat(a) - parseFloat(b),
      ),
      next: [...new Set(readyItems.map((t) => getReadyCellValue(t, "next")))].sort(),
    }),
    [readyItems],
  );

  const historySectionIds = useMemo(() => {
    if (showAllSpgs) return allSectionIds;
    return new Set(spgs?.find((s) => s.id === activeSpgId)?.sections.map((sec) => sec.section_id) ?? []);
  }, [showAllSpgs, allSectionIds, spgs, activeSpgId]);

  const getHistoryCell = useCallback(
    (transfer: IncomingTransfer, field: HistorySortField) =>
      getHistoryCellValue(transfer, field, historySectionIds),
    [historySectionIds],
  );

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

  function handleRefresh() {
    void refetchReady();
    void refetchHistory();
  }

  // Передача меняет остатки, доску участков и журнал передач — задеты все
  // домены, к которым она прикасается, поэтому сброс берём из реестра.
  const invalidateTransferCaches = useCallback(() => {
    void invalidateAfter(queryClient, "transferChanged");
  }, [queryClient]);

  const cancelMutation = useMutation({
    mutationFn: (transferId: number) => cancelTransfer(transferId),
    onSuccess: () => {
      toast({
        variant: "success",
        title: "Передача отменена",
        description: "Передача успешно аннулирована",
      });
      invalidateTransferCaches();
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

  const selectedReadyTasks = useMemo(
    // Финальные строки (тикет #96) исключаются из групповой передачи:
    // для них действие — «Отправить» (final release), не createTransfer.
    () => readyItems.filter((t) => !isFinalReadyRow(t) && bulkSelection.isSelected(t.task_id)),
    [readyItems, bulkSelection],
  );

  const toggleGroupCollapse = useCallback((key: string) => {
    setExpandedGroupKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  async function handleGroupTransfer(group: ReadyTransferGroup, quantity: string) {
    if (groupSubmittingKey != null) return;
    setGroupSubmittingKey(group.key);

    // Диалог подтверждения не нужен: введённое количество распределяется по
    // строкам последовательно, габариты берутся из строк как есть.
    const { results, summary, undistributed } = await runTransferBatch({
      rows: group.rows,
      idempotencyPrefix: "transfer-send-group",
      totalQuantity: parseFloat(quantity || "0"),
    });

    setGroupSubmittingKey(null);
    setBulkResults(results);
    setBulkSummary(summary);

    invalidateTransferCaches();

    const description = [`Отправлено ${summary.success} из ${summary.total} позиций`];
    if (undistributed > 0) {
      description.push(`не передано ${fmtQty(undistributed)} шт. — ждёт завершения`);
    }

    toast({
      title: summary.failed > 0 ? "Частичный успех" : "Передача выполнена",
      description: description.join("; "),
      variant: summary.failed > 0 ? "destructive" : "success",
    });

    if (summary.failed > 0 || summary.skipped > 0) {
      setBulkResultsOpen(true);
    }
  }

  const handleBulkTransferSubmit = useCallback(async (data: BulkTransferSubmitData) => {
    const selectedTasks = readyItems.filter(t => !isFinalReadyRow(t) && bulkSelection.isSelected(t.task_id));
    if (selectedTasks.length === 0) return;

    setBulkSubmitting(true);
    setBulkProgress({ total: selectedTasks.length, completed: 0, running: true });

    const { results, summary } = await runTransferBatch({
      rows: selectedTasks,
      idempotencyPrefix: "transfer-send-bulk",
      comment: data.comment.trim() || undefined,
      executorUserId: data.executorUserId,
      performedAt: data.performedAt,
      physicalHandoverAt: data.physicalHandoverAt,
      postFactum: data.postFactum,
      onProgress: setBulkProgress,
    });

    setBulkProgress(null);
    setBulkSubmitting(false);

    setBulkResults(results);
    setBulkSummary(summary);

    invalidateTransferCaches();

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
  }, [readyItems, bulkSelection, invalidateTransferCaches]);

  if (spgs !== undefined && spgs.length === 0) {
    return (
      <div className="text-center">
        <h1 className="text-xl font-semibold mb-2">Передачи между ГХП</h1>
        <p className="text-muted-foreground">В системе нет зарегистрированных групп хранения и производства (ГХП).</p>
      </div>
    );
  }

  return (
    <div className={cn("space-y-6 w-full", bulkMode && "pb-44")}>
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
          <Button
            variant="outline"
            size="sm"
            title="Открыть журнал передач"
            onClick={() => setHistoryOpen(true)}
          >
            <Inbox className="h-4 w-4 mr-1" /> Журнал передач
          </Button>
          <Button variant="outline" size="sm" onClick={handleRefresh}>
            <RefreshCw className="h-4 w-4 mr-1" /> Обновить
          </Button>
        </div>
      </header>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-4 space-y-0 pb-3">
          <CardTitle className="flex items-center gap-2 shrink-0">
            <Send className="h-4 w-4" />
            Готово к передаче
            {readyTotal > 0 && <Badge variant="secondary">{readyTotal}</Badge>}
          </CardTitle>
          <div className="relative w-full max-w-sm">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
            <Input
              type="text"
              placeholder="Поиск по ID, артикулу, этапу…"
              value={readySearch}
              onChange={(e) => setReadySearch(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  flushReadySearch();
                  resetReadyPage();
                }
              }}
              className="pl-9"
            />
          </div>
          {readyTotal > 0 && (
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
          {isFirstRowsLoad(readyPending, readyItems) ? (
            <div className="text-sm text-muted-foreground py-4 text-center">Загрузка…</div>
          ) : readyTotal === 0 && !debouncedReadySearch.trim() && !hasReadyFiltersActive ? (
            <div className="text-sm text-muted-foreground py-6 text-center">
              Нет заданий, готовых к передаче на участках выбранной ГХП. Завершите работу на этапе, чтобы появились задания
              с доступным к передаче количеством.
            </div>
          ) : (
            <>
            <div
              ref={readyScrollRef}
              className={DATA_TABLE_STYLES.container}
              style={{ maxHeight: "70vh", overflow: "auto" }}
            >
            <table className="w-full caption-bottom text-sm">
              <TableHeader>
                <TableRow>
                  {bulkMode && (
                    <TableHead className={`${headerCellClass} w-[40px]`}>
                      <Checkbox
                        checked={bulkSelection.isAllSelected(
                          readyItems.filter((t) => !isFinalReadyRow(t)).map((t) => t.task_id),
                        )}
                        onCheckedChange={(checked) => {
                          if (checked) {
                            bulkSelection.selectAll(
                              readyItems.filter((t) => !isFinalReadyRow(t)).map((t) => t.task_id),
                            );
                          } else {
                            bulkSelection.clear();
                          }
                        }}
                      />
                    </TableHead>
                  )}
                  {readyColumns.map((column) => (
                    <TableHead
                      key={column.id}
                      className={`${headerCellClass} p-0${column.id === "transferableQty" ? " text-right" : ""}`}
                    >
                      <DataTableColumnHeader
                        column={column}
                        bindColumn={bindReadyColumn}
                        values={readyUniqueValues[column.filterField] ?? []}
                        currentSorts={readySortConfigs}
                        onSortChange={handleReadySort}
                      />
                    </TableHead>
                  ))}
                  {!bulkMode && (
                    <TableHead className={headerCellClass}>
                      Действия
                    </TableHead>
                  )}
                  <TableCornerResetHeader
                    hasActiveFilters={hasReadyFiltersActive}
                    onReset={resetReadyFilters}
                    dataTableHeader
                  />
                </TableRow>
              </TableHeader>
              {readyItems.length === 0 ? (
                <TableBody>
                  <TableRow>
                    <TableCell
                      colSpan={bulkMode ? 8 : 8}
                      className="${TABLE_ROW_COMPACT.cell} py-6 text-center text-sm text-muted-foreground"
                    >
                      Нет заданий, соответствующих фильтру
                    </TableCell>
                  </TableRow>
                </TableBody>
              ) : (
                <VirtualizedTableBody
                  rows={readyTableRows}
                  rowHeight={TABLE_ROW_COMPACT.rowHeightPx}
                  colSpan={bulkMode ? 8 : 8}
                  scrollContainerRef={readyScrollRef}
                  renderRow={(row) =>
                    row.kind === "group" ? (
                      <ReadyTransferGroupRow
                        key={row.group.key}
                        group={row.group}
                        bulkMode={bulkMode}
                        isCollapsed={!bulkMode && !expandedGroupKeys.has(row.group.key)}
                        isSubmitting={groupSubmittingKey === row.group.key}
                        hasInFlightRow={row.group.rows.some((task) =>
                          isTransferInFlight(task.task_id),
                        )}
                        onToggleCollapse={() => toggleGroupCollapse(row.group.key)}
                        onTransferGroup={handleGroupTransfer}
                      />
                    ) : (
                      <ReadyTransferRow
                        key={row.task.task_id}
                        task={row.task}
                        bulkMode={bulkMode}
                        isSelected={bulkSelection.isSelected(row.task.task_id)}
                        onSelect={() => bulkSelection.selectOne(row.task.task_id)}
                        isSubmitting={
                          isTransferInFlight(row.task.task_id) ||
                          (row.groupKey != null && groupSubmittingKey === row.groupKey)
                        }
                        tryAcquire={() => tryAcquireTransferLock(row.task.task_id)}
                        release={() => releaseTransferLock(row.task.task_id)}
                        invalidateTransferCaches={invalidateTransferCaches}
                      />
                    )
                  }
                />
              )}
            </table>
            </div>
            <TablePaginationFooter
              page={readyPage}
              totalPages={readyTotalPages}
              total={readyTotal}
              shownCount={readyItems.length}
              limit={readyLimit}
              onPageChange={setReadyPage}
              onLimitChange={setReadyLimit}
              rangeLabel={readyRangeLabel(readyItems.length, readyTotal)}
            />
            </>
          )}
        </CardContent>
      </Card>

      <Dialog open={historyOpen} onOpenChange={setHistoryOpen}>
        <DialogContent className="!left-auto !right-0 !top-0 !translate-x-0 !translate-y-0 h-screen max-h-screen w-[min(100vw,760px)] max-w-none rounded-none border-l p-0 flex flex-col gap-0">
          <div className="shrink-0 border-b bg-background px-6 py-3 space-y-2">
            <DialogTitle className="flex items-center gap-2 text-lg font-semibold">
              <Inbox className="h-4 w-4" />
              Журнал передач
            </DialogTitle>
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
              <Input
                type="text"
                placeholder="Поиск по ID, артикулу, участкам, № передачи…"
                value={historySearch}
                onChange={(e) => setHistorySearch(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    flushHistorySearch();
                    resetHistoryPage();
                  }
                }}
                className="pl-9"
              />
            </div>
          </div>
          <div className="flex-1 overflow-auto p-4">
            {isFirstRowsLoad(historyPending, historyItems) ? (
              <div className="text-sm text-muted-foreground py-4 text-center">Загрузка…</div>
            ) : historyTotal === 0 && !hasHistoryFiltersActive ? (
              <div className="text-sm text-muted-foreground py-6 text-center">
                Нет записей в журнале передач для выбранной ГХП.
              </div>
            ) : (
              <>
                <div
                  ref={historyScrollRef}
                  className={DATA_TABLE_STYLES.container}
                  style={{ maxHeight: "70vh", overflow: "auto" }}
                >
                  <table className="w-full caption-bottom text-sm">
                    <TableHeader>
                      <TableRow>
                        {historyColumns.map((column) => (
                          <TableHead
                            key={column.id}
                            className={`${headerCellClass} p-0 ${column.headerClassName ?? ""}`}
                          >
                            <DataTableColumnHeader
                              column={column}
                              bindColumn={bindHistoryColumn}
                              values={column.filterField ? historyUniqueValues[column.filterField] : undefined}
                              currentSorts={historySortConfigs}
                              onSortChange={handleHistorySort}
                            />
                          </TableHead>
                        ))}
                        <TableCornerResetHeader
                          hasActiveFilters={hasHistoryFiltersActive}
                          onReset={resetHistoryFilters}
                          dataTableHeader
                        />
                      </TableRow>
                    </TableHeader>
                    {historyItems.length === 0 ? (
                      <TableBody>
                        <TableRow>
                          <TableCell colSpan={9} className="${TABLE_ROW_COMPACT.cell} py-6 text-center text-sm text-muted-foreground">
                            Нет записей, соответствующих фильтру
                          </TableCell>
                        </TableRow>
                      </TableBody>
                    ) : (
                      <VirtualizedTableBody
                        rows={historyItems}
                        rowHeight={TABLE_ROW_COMPACT.rowHeightPx}
                        colSpan={9}
                        scrollContainerRef={historyScrollRef}
                        renderRow={(t) => {
                          const isIncoming = historySectionIds.has(t.to_section_id);
                          const isCancelled = t.status === "cancelled";
                          const statusBadge = (() => {
                            if (isCancelled) return { label: "Аннулирована", variant: "destructive" as const };
                            if (t.status === "amended") return { label: "Скорректирована", variant: "secondary" as const };
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
                              <TableCell className="${TABLE_ROW_COMPACT.cell} font-mono text-xs text-muted-foreground">
                                #{t.plan_position_id}
                              </TableCell>
                              <TableCell className={TABLE_ROW_COMPACT.cell}>
                                <div className="text-xs">
                                  <div className="font-medium">{t.from_section_name}</div>
                                  <div className="text-muted-foreground">{t.from_operation_name}</div>
                                </div>
                              </TableCell>
                              <TableCell className={TABLE_ROW_COMPACT.cell}>
                                <div className="text-xs">
                                  <div className="font-medium">{t.to_section_name}</div>
                                  <div className="text-muted-foreground">{t.to_operation_name}</div>
                                </div>
                              </TableCell>
                              <TableCell className="${TABLE_ROW_COMPACT.cell} text-xs font-medium">{t.product_sku}</TableCell>
                              <TableCell className="${TABLE_ROW_COMPACT.cell} text-xs text-muted-foreground whitespace-nowrap">
                                {formatDimensionsLabel(t.dimensions)}
                              </TableCell>
                              <TableCell className="${TABLE_ROW_COMPACT.cell} text-right tabular-nums font-semibold whitespace-nowrap">
                                {fmtQty(t.sent_quantity)}
                              </TableCell>
                              <TableCell className={TABLE_ROW_COMPACT.cell}>
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
                              <TableCell className="${TABLE_ROW_COMPACT.cell} text-right w-[40px]">
                                <ChevronRight className="h-4 w-4 text-muted-foreground/60 transition-transform group-hover:translate-x-0.5 inline-block" />
                              </TableCell>
                              <TableCornerResetCell />
                            </TableRow>
                          );
                        }}
                      />
                    )}
                  </table>
                </div>
                <TablePaginationFooter
                  page={historyPage}
                  totalPages={historyTotalPages}
                  total={historyTotal}
                  shownCount={historyItems.length}
                  limit={historyLimit}
                  onPageChange={setHistoryPage}
                  onLimitChange={setHistoryLimit}
                  rangeLabel={historyRangeLabel(historyItems.length, historyTotal)}
                />
              </>
            )}
          </div>
        </DialogContent>
      </Dialog>

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
            invalidateTransferCaches();
          }}
          onCancel={() => {
            cancelMutation.mutate(editTransferRecord.transfer_id);
          }}
          isCancelling={cancelMutation.isPending && cancelMutation.variables === editTransferRecord.transfer_id}
        />
      )}

      {bulkMode && (
        <BulkTransferFooter
          selectedTasks={selectedReadyTasks}
          onSubmit={handleBulkTransferSubmit}
          onExit={exitBulkMode}
          onClearSelection={() => bulkSelection.clear()}
          pending={bulkSubmitting}
          progress={bulkProgress}
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


