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
  FiltersPanel,
  PrintButton,
  buildActiveFilterSummary,
  type FiltersPanelField,
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
import { operationalPollingOptions } from "@/shared/api/operationalPolling";
import { queryKeys } from "@/shared/api/queryKeys";
import { formatDimensionsFilterValue, formatDimensionsLabel } from "@/shared/api/stock";
import { buildColumnApiParams } from "@/shared/lib/columnSpecs";
import { getAriaSort } from "@/shared/lib/multiSort";
import { isFirstRowsLoad, keepPreviousDataForScope } from "@/shared/lib/tableQueryPlaceholder";
import { getReadyCellValue, historyColumns, readyColumns } from "../lib/transferColumns";
import { TABLE_ROW_COMPACT, TABLE_ROW_DENSE } from "@/shared/lib/dataTableStyles";
import { TABLE_ROW_STYLES } from "@/shared/lib/tableRowStyles";
import {
  ROW_TONE_STRIPE,
  rowToneFill,
  type RowTone,
} from "@/shared/lib/rowTones";
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
import { ReadyTransferPrintDialog } from "../components/ReadyTransferPrintDialog";
import {
  dimensionsKey,
  groupReadyTransfers,
  isFinalReadyRow,
  nextStepLabel,
  readyRowIdentity,
  type ReadyTransferGroup,
} from "../lib/groupReadyTransfers";
import {
  enteredTransferQuantity,
  makeIdempotencyKey,
  planTransferQuantities,
  runTransferBatch,
} from "../lib/runTransferBatch";
import { useFlushableDebouncedValue } from "@/shared/lib/useDebouncedValue";
import { isAnyDialogOpen } from "@/shared/lib/dialogOpen";
import {
  buildHistorySortParam,
  buildReadySortParam,
  type HistorySortField,
  type ReadySortField,
} from "../lib/transferSortParams";
import { fmtQty } from "@/shared/lib/quantityFormat";
import { actionReasonText, type ActionReasonCode } from "@/shared/lib/actionReasons";

/**
 * Плотность строки «Передачи» — общий уточнённый набор 32px (ADR-0033), тот
 * же, что у доски участков и «Остатков». Раньше здесь был свой набор на 37px:
 * строки расходились на пять пикселей, а `rowHeightPx` оставался общим (40) —
 * виртуализация считала по одной высоте, а строки были другими.
 *
 * Поле количества повторяет высоту действия: иначе строка растёт от него.
 * `rowHeightPx` общий с доской: высота строки закреплена прямо на `<tr>`,
 * поэтому `border-b` от `TableRow` больше не добавляет к строке пиксель, и
 * все три таблицы дают ровно 32px. Константа обязана совпадать с измеренной
 * высотой — по ней виртуализация ставит полосу обрыва (ADR-0030).
 */
const TRANSFERS_ROW = {
  ...TABLE_ROW_DENSE,
  // Отступ по вертикали — 2px, а не 4px: у этой таблицы `border-collapse`, и
  // её `border-b` добавил бы к строке ещё пиксель сверх общих 32. Высота держит
  // закреплённый ниже `rowHeightPx`, поэтому 24px действия укладываются с запасом.
  cell: "px-2 py-0.5",
  quantityInput: "h-6",
  rowHeightPx: TABLE_ROW_DENSE.rowHeightPx,
} as const;

/**
 * Подсказка у погашенной кнопки строки в массовом режиме. Кнопка остаётся на
 * месте (колонка «Действия» не меняет ширину и страница не прыгает), но
 * действие одно — футер: по строке передача не отправляется.
 */
const BULK_ROW_ACTION_TITLE = "В массовом режиме отправляет «Передать все» в футере";
/**
 * Подсказка у погашенной кнопки финальной строки: её-то футер не отправляет —
 * финальный выпуск в массовую передачу не берётся, и выпускать его надо вне
 * режима. Врать «отправит футер» здесь нельзя.
 */
const BULK_FINAL_ACTION_TITLE = "Финальный выпуск в массовую передачу не берётся: выйдите из режима";

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
  | {
      kind: "task";
      task: ReadyToTransferTask;
      groupKey: string | null;
      /** Строка закрывает блок группы — на ней 3px-граница. */
      isLastInGroup: boolean;
    }
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

/**
 * Тон строки журнала — из общего словаря (`shared/lib/rowTones`), как у
 * «Готово к передаче»: принятая передача — тон `completed` (закрытое дело),
 * отправленная и частично принятая — `activeRunning` (ещё в пути),
 * скорректированная — `active` (живая правка), аннулированная — `plain` (её и
 * так гасит `opacity`).
 *
 * Текст строки тоном не перекрашивается: в словаре `completed` несёт
 * зачёркивание и приглушение — это состояние *задания* на доске, а не
 * состояние *передачи* в журнале.
 */
function historyRowTone(status: string): RowTone {
  if (status === "cancelled") return "plain";
  if (status === "amended") return "active";
  if (status === "sent" || status === "partially_accepted") return "activeRunning";
  return "completed";
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
  /** Строка раскрытой группы: носит подложку блока и рельс (ADR-0065). */
  isInGroup: boolean;
  /** Строка закрывает блок группы — на ней 3px-граница. */
  isLastInGroup: boolean;
  /**
   * Количество строки приходит сверху (массовый режим): строки
   * виртуализированы, и локальное состояние строки терялось бы при прокрутке.
   * Не задано — строка держит количество сама (обычный режим).
   */
  controlledQuantity?: string;
  onQuantityChange?: (value: string) => void;
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
  isInGroup,
  isLastInGroup,
  controlledQuantity,
  onQuantityChange,
  tryAcquire,
  release,
  invalidateTransferCaches,
}: ReadyTransferRowProps) {
  const [ownQuantity, setOwnQuantity] = useState(task.transferable_quantity);
  const quantity = controlledQuantity ?? ownQuantity;
  const setQuantity = onQuantityChange ?? setOwnQuantity;
  const submittingRef = useRef(false);

  useEffect(() => {
    setOwnQuantity(task.transferable_quantity);
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
  // Рёбра блока — на ячейках, а не на `<tr>`: одно правило с доской и
  // остатками (ADR-0065). Внутренний разделитель тише обычного, конец блока —
  // 3px-граница между группами.
  const cellClass = cn(
    TRANSFERS_ROW.cell,
    isInGroup &&
      (isLastInGroup ? TABLE_ROW_STYLES.groupBlockBoundary : TABLE_ROW_STYLES.groupChildSeparator),
  );
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
      data-row-key={readyRowIdentity(task)}
      // Высота строки закреплена: без неё строка равна сумме контента и
      // `border-b` от `TableRow`, то есть 33px вместо общих 32. Ячейки не
      // сжимаются — 24px действия плюс 4px отступа укладываются с запасом.
      style={{ height: TRANSFERS_ROW.rowHeightPx }}
      // Раскрытая строка группы носит общую подложку блока (ADR-0065):
      // строки одного артикула читаются одним куском, а не списком.
      className={cn(
        isSelected
          ? TABLE_ROW_STYLES.selectedRow
          : isInGroup
            ? TABLE_ROW_STYLES.groupBlock
            : TABLE_ROW_STYLES.defaultRow,
        bulkMode && "cursor-pointer",
      )}
      onClick={bulkMode ? onSelect : undefined}
    >
      <TableCell className={cn(cellClass, TABLE_ROW_STYLES.blockRail, "font-mono text-xs text-muted-foreground")}>#{task.plan_position_id}</TableCell>
      <TableCell className={cellClass}>{task.product_sku ?? "—"}</TableCell>
      <TableCell className={`${cellClass} text-xs text-muted-foreground whitespace-nowrap`}>
        {formatDimensionsLabel(task.dimensions, task.dimensions_label)}
      </TableCell>
      <TableCell className={`${cellClass} text-xs whitespace-nowrap`}>
        {task.operation_name ?? "—"}
      </TableCell>
      <TableCell className={`${cellClass} text-right tabular-nums`}>
        <div className="whitespace-nowrap">
          <span className="font-medium">{fmtQty(task.transferable_quantity)} шт.</span>
          {task.dimensions != null && (
            <span className="ml-1 text-[10px] text-muted-foreground" title="Габарит из плана">
              · {formatDimensionsLabel(task.dimensions, task.dimensions_label)}
            </span>
          )}
        </div>
      </TableCell>
      <TableCell
        className={`${cellClass} text-xs whitespace-nowrap`}
        title={task.has_next_step ? nextStepLabel(task.next_operation_name, task.next_section_name) : undefined}
      >
        {task.has_next_step ? (
          nextStepLabel(task.next_operation_name, task.next_section_name)
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
      <TableCell className={cellClass} onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-end gap-2">
          {/* Количество и кнопка живут в строке всегда — в массовом режиме
              кнопка видна, но погашена: отправляет один футер. Прятать её
              нельзя — колонка «Действия» меняла ширину, и доска прыгала при
              входе в режим и выходе из него. Финальный выпуск в массовую
              передачу не берётся: строка не выбирается, и количество ей не
              нужно. */}
          {(!bulkMode || !isFinalRow) && (
            <div className="flex items-center gap-1">
              {/* План — у поля ввода, а не в «К передаче»: подпись «(план N)»
                  рядом с числом съедала ширину, и колонка количеств не
                  выстраивалась. Формат «передано/план»: у нетронутой строки
                  читается «0/3000», как её и просили. */}
              <span
                className="text-[11px] text-muted-foreground tabular-nums whitespace-nowrap"
                title="Уже передано / план задания"
              >
                {fmtQty(task.already_transferred_quantity)}/{fmtQty(task.planned_quantity)}
              </span>
              <Input
                type="number"
                step="1"
                min="0"
                value={quantity}
                className={`w-20 ${TRANSFERS_ROW.quantityInput} text-right px-2 ${
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
          )}
          <ActionWithReason reason={bulkMode ? null : quantityReason}>
            {isFinalRow ? (
              <Button
                size="sm"
                className={TRANSFERS_ROW.actionButton}
                disabled={bulkMode || isSubmitting || releaseMutation.isPending || quantityReason !== null}
                title={
                  bulkMode
                    ? isFinalRow
                      ? BULK_FINAL_ACTION_TITLE
                      : BULK_ROW_ACTION_TITLE
                    : quantityReason
                      ? actionReasonText(quantityReason)
                      : "Финальный выпуск готовой продукции"
                }
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
                  className={TRANSFERS_ROW.actionButton}
                  disabled={bulkMode || isSubmitting || mutation.isPending || quantityReason !== null}
                  title={
                    bulkMode
                      ? BULK_ROW_ACTION_TITLE
                      : quantityReason
                        ? actionReasonText(quantityReason)
                        : "Передать на следующий этап"
                  }
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
      <TableCornerResetCell className={TABLE_ROW_STYLES.groupHeaderCell} />
    </TableRow>
  );
}

/**
 * Ряд-заголовок группы ready-строк — строк, неразличимых для передачи: тот же
 * артикул, участок, размер, адресат и операция (см. `groupReadyTransfers`).
 * Группа свёрнута по умолчанию; введённое общее количество распределяется по
 * строкам последовательно (`runTransferBatch`).
 *
 * В массовом режиме группы раскрыты принудительно, у шапки есть поле общего
 * количества (раскладывается по строкам — как «Годные» в шапке группы на доске
 * участка) и выбор: клик по шапке берёт группу целиком, а подложка шапки
 * окрашивается вместе со строками.
 */
function ReadyTransferGroupRow({
  group,
  bulkMode,
  isCollapsed,
  isSubmitting,
  hasInFlightRow,
  isAllSelected,
  isPartiallySelected,
  controlledQuantity,
  onQuantityChange,
  onSelectGroup,
  onToggleCollapse,
  onTransferGroup,
}: {
  group: ReadyTransferGroup;
  bulkMode: boolean;
  isCollapsed: boolean;
  isSubmitting: boolean;
  hasInFlightRow: boolean;
  /** Все строки группы выделены — шапка носит подложку выбора, как её строки. */
  isAllSelected: boolean;
  /** Часть строк выделена: клик по шапке снимает выбор со всей группы. */
  isPartiallySelected: boolean;
  /** Общее количество группы в массовом режиме: ввод раскладывается по строкам. */
  controlledQuantity?: string;
  onQuantityChange?: (value: string) => void;
  onSelectGroup: () => void;
  onToggleCollapse: () => void;
  onTransferGroup: (group: ReadyTransferGroup, quantity: string) => void;
}) {
  const [ownQuantity, setOwnQuantity] = useState(() => fmtQty(group.totalTransferable));
  const quantity = controlledQuantity ?? ownQuantity;
  const setQuantity = onQuantityChange ?? setOwnQuantity;

  useEffect(() => {
    setOwnQuantity(fmtQty(group.totalTransferable));
  }, [group.totalTransferable]);

  // Ячейка шапки блока: рёбра на ячейках, а не на `<tr>` — одно правило
  // с доской участка и остатками (ADR-0065).
  const groupHeaderCellClass = cn(TRANSFERS_ROW.cell, TABLE_ROW_STYLES.groupHeaderCell);

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
      style={{ height: TRANSFERS_ROW.rowHeightPx }}
      tabIndex={bulkMode ? 0 : undefined}
      aria-selected={bulkMode ? isAllSelected : undefined}
      className={cn(
        "font-semibold",
        bulkMode ? "" : "cursor-pointer",
        // Выделенная группа носит подложку выбора — как её строки: иначе
        // «выбрано» видно на детях, а шапка выглядит невыбранной.
        bulkMode && isAllSelected
          ? TABLE_ROW_STYLES.selectedGroupHeader
          : TABLE_ROW_STYLES.defaultGroupHeader,
      )}
      onClick={bulkMode ? onSelectGroup : onToggleCollapse}
      onKeyDown={(event) => {
        if (!bulkMode) return;
        if (event.target !== event.currentTarget) return;
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        onSelectGroup();
      }}
    >
      <TableCell className={cn(groupHeaderCellClass, TABLE_ROW_STYLES.blockRail, "text-center")}>
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
      <TableCell className={groupHeaderCellClass}>
        <div className="flex items-center gap-2">
          <span>{group.productSku ?? "—"}</span>
          <Badge variant="secondary" className="font-bold">
            &times;{group.rows.length}
          </Badge>
        </div>
      </TableCell>
      <TableCell className={cn(groupHeaderCellClass, "text-xs text-muted-foreground whitespace-nowrap")}>
        {common.dimensionsLabel ?? "—"}
      </TableCell>
      <TableCell className={cn(groupHeaderCellClass, "text-xs whitespace-nowrap")}>
        {common.operationName ?? "—"}
      </TableCell>
      <TableCell className={cn(groupHeaderCellClass, "text-right tabular-nums")}>
        {/* Как у одиночной строки: в «К передаче» — текст, редактируемое поле —
            в «Действиях». Сумма по группе, распределяется по строкам. */}
        <div className="whitespace-nowrap">
          <span className="font-medium">{fmtQty(group.totalTransferable)} шт.</span>{" "}
          <span className="text-[11px] text-muted-foreground">
            ({group.rows.length} поз.)
          </span>
        </div>
      </TableCell>
      <TableCell
        className={cn(groupHeaderCellClass, "text-xs whitespace-nowrap")}
        title={group.hasNextStep ? nextStepLabel(common.nextOperationName, common.nextSectionName) : undefined}
      >
        {group.hasNextStep ? (
          nextStepLabel(common.nextOperationName, common.nextSectionName)
        ) : (
          <Badge variant="outline">Финальный</Badge>
        )}
      </TableCell>
      {/* Ячейка «Действия» есть всегда. В массовом режиме это поле общего
          количества группы (без кнопки: отправляет футер), в обычном — поле и
          кнопка передачи группы. */}
      <TableCell className={groupHeaderCellClass} onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-end gap-2">
          <div className="flex items-center gap-1">
            {/* Как у строки: «передано/план» перед полем, только суммами по
                группе — шапка несёт общее, а не план одной строки. */}
            <span
              className="text-[11px] text-muted-foreground tabular-nums whitespace-nowrap"
              title="Уже передано / план по строкам группы"
            >
              {fmtQty(group.totalAlreadyTransferred)}/{fmtQty(group.totalPlanned)}
            </span>
            <Input
              type="number"
              step="1"
              min="0"
              value={quantity}
              disabled={isSubmitting}
              className={`w-20 ${TRANSFERS_ROW.quantityInput} text-right px-2 ${
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
          <ActionWithReason reason={bulkMode ? null : groupBlockReason}>
            <Button
              size="sm"
              className={TRANSFERS_ROW.actionButton}
              disabled={bulkMode || isSubmitting || groupBlockReason !== null}
              title={
                bulkMode
                  ? group.allFinal
                    ? BULK_FINAL_ACTION_TITLE
                    : BULK_ROW_ACTION_TITLE
                  : groupBlockReason
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
      <TableCornerResetCell />
    </TableRow>
  );
}

const groupHeaderCellClass = cn(DATA_TABLE_STYLES.headerRow, DATA_TABLE_STYLES.headerCell, TABLE_ROW_COMPACT.headerCell);

export function TransfersPage() {
  const queryClient = useQueryClient();
  const [spgId, setSpgId] = useState<number | null>(null);
  const [showAllSpgs, setShowAllSpgs] = useState(true);
  const [editTransferRecord, setEditTransferRecord] = useState<IncomingTransfer | null>(null);
  const [historySearch, setHistorySearch] = useState("");
  const { value: debouncedHistorySearch, flush: flushHistorySearch } =
    useFlushableDebouncedValue(historySearch);
  const [readySearch, setReadySearch] = useState("");
  const { value: debouncedReadySearch } = useFlushableDebouncedValue(readySearch);
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

  // Молчаливого фолбэка на первую активную ГХП нет: под плейсхолдером
  // «Выберите ГХП» уезжали данные чужого выбора. Пустой выбор так и остаётся
  // пустым — запросы по нему не идут (ADR-0060 п.3).
  const activeSpgId = showAllSpgs ? null : spgId;

  // Признак «запрос жив»: либо «Все ГХП», либо выбрана конкретная ГХП. Пока
  // выбора нет, оба запроса выключены (`enabled`), а `isPending` у выключенного
  // запроса не разрешается — гейт загрузки висел бы вечно. Это состояние экран
  // показывает текстом, а не спиннером.
  const spgScopeSelected = showAllSpgs || activeSpgId != null;

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
    enabled: spgScopeSelected,
    // «Готово к передаче» — очередь действий участка: передача, отправленная
    // соседом, должна появиться без F5 (#206, ADR-0041). Журнал передач не
    // опрашивается: это история, а не очередь к действию.
    ...operationalPollingOptions,
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
    // Журнал ленивый (#290): пока панель закрыта, журнал не читаем —
    // первый fetch случается при открытии окна (спиннер — isFirstRowsLoad).
    enabled: spgScopeSelected && historyOpen,
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
      return readyItems.map((task) => ({
        kind: "task" as const,
        task,
        groupKey: null,
        isLastInGroup: false,
      }));
    }
    const rows: ReadyTableRow[] = [];
    for (const item of readyGroupItems) {
      if (item.kind === "single") {
        rows.push({ kind: "task", task: item.row, groupKey: null, isLastInGroup: false });
        continue;
      }
      rows.push({ kind: "group", group: item });
      if (bulkMode || expandedGroupKeys.has(item.key)) {
        item.rows.forEach((task, index) => {
          rows.push({
            kind: "task",
            task,
            groupKey: item.key,
            isLastInGroup: index === item.rows.length - 1,
          });
        });
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

  const [readyPrintOpen, setReadyPrintOpen] = useState(false);
  /**
   * Количества строк массового режима, ключ — `readyRowIdentity`. Живут на
   * странице, а не в строке: строки виртуализированы, и набранное число
   * пропадало бы при прокрутке. Строка без записи идёт своим `transferable`.
   */
  const [bulkQuantities, setBulkQuantities] = useState<Record<string, string>>({});
  /**
   * Набранное в шапке группы (ключ — ключ группы). Хранится отдельно от строк,
   * потому что поле шапки показывает НАБРАННОЕ, а строки — уже разложенное по
   * ним; без этого ввод обрывался бы на первой же цифре, когда раскладка
   * упирается в доступное.
   */
  const [bulkGroupQuantities, setBulkGroupQuantities] = useState<Record<string, string>>({});

  const setRowBulkQuantity = useCallback(
    (groupKey: string | null, identity: string, value: string) => {
      setBulkQuantities((prev) => ({ ...prev, [identity]: value }));
      // Правка строки снимает набранное в шапке: поле группы выводится из строк,
      // и оставленный текст показывал бы не то, что уедет.
      if (!groupKey) return;
      setBulkGroupQuantities((prev) => {
        if (!(groupKey in prev)) return prev;
        const next = { ...prev };
        delete next[groupKey];
        return next;
      });
    },
    [],
  );

  /** Ввод в шапке группы: раскладывается по её строкам тем же правилом, что отправка. */
  const setGroupBulkQuantity = useCallback(
    (group: ReadyTransferGroup, value: string) => {
      setBulkGroupQuantities((prev) => ({ ...prev, [group.key]: value }));
      setBulkQuantities((prev) => {
        const next = { ...prev };
        if (value.trim() === "") {
          // Очистка снимает раскладку: строки возвращаются к своему доступному.
          for (const row of group.rows) delete next[readyRowIdentity(row)];
          return next;
        }
        const { quantities } = planTransferQuantities(group.rows, parseFloat(value) || 0);
        group.rows.forEach((row, index) => {
          next[readyRowIdentity(row)] = quantities[index];
        });
        return next;
      });
      // Набранное в шапке — это и выбор группы: иначе число набрано, а строки
      // в пачку не попали.
      for (const row of group.rows) {
        if (!isFinalReadyRow(row)) bulkSelection.selectOne(row.task_id, true);
      }
    },
    [bulkSelection],
  );

  /** Клик по шапке группы: выделить её строки целиком или снять выбор со всех. */
  const toggleGroupSelection = useCallback(
    (taskIds: number[]) => {
      const allSelected = bulkSelection.isAllSelected(taskIds);
      const someSelected = bulkSelection.isIndeterminate(taskIds);
      const next = !(allSelected || someSelected);
      for (const id of taskIds) bulkSelection.selectOne(id, next);
    },
    [bulkSelection],
  );

  /** Значение поля группы: набранное в шапке, иначе — сумма количеств её строк. */
  const groupBulkQuantity = useCallback(
    (group: ReadyTransferGroup): string => {
      const typed = bulkGroupQuantities[group.key];
      if (typed !== undefined) return typed;
      return String(
        group.rows.reduce(
          (sum, row) =>
            sum + (parseFloat(bulkQuantities[readyRowIdentity(row)] ?? row.transferable_quantity) || 0),
          0,
        ),
      );
    },
    [bulkGroupQuantities, bulkQuantities],
  );

  /** Строки, которые оператор может отправить: финальный выпуск — не передача. */
  const readySelectableIds = useMemo(
    () => readyItems.filter((task) => !isFinalReadyRow(task)).map((task) => task.task_id),
    [readyItems],
  );

  const readyActiveFilterSummary = useMemo(
    () =>
      buildActiveFilterSummary(readySearch, readySortConfigs.length, {
        columnFilters: readyColumnFilters,
        columnSearchQueries: readyDebouncedColumnSearchQueries,
        columnLabels: Object.fromEntries(
          readyColumns.filter((column) => column.filterField).map((column) => [column.filterField, column.label]),
        ),
      }),
    [readySearch, readySortConfigs.length, readyColumnFilters, readyDebouncedColumnSearchQueries],
  );

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
    // Журнал ленивый (#290): выключен, пока панель закрыта, и refetch
    // выключенного запроса в TanStack форсировал бы fetch — обновляем только
    // открытое окно. При закрытой панели свежесть вернёт invalidateAfter при
    // следующем открытии.
    if (historyOpen) {
      void refetchHistory();
    }
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
    // Набранные количества уходят вместе с режимом: в следующий заход строка
    // снова показывает своё доступное.
    setBulkQuantities({});
    setBulkGroupQuantities({});
    setBulkMode(false);
  }, [bulkSelection]);

  /**
   * Escape выходит из массового режима — то же, что кнопка «Выйти» в футере
   * (и то же правило, что на доске участка). Окно поверх режима клавишу не
   * отдаёт: пока открыт диалог, страница её не трогает, иначе второе нажатие
   * выбрасывало бы из режима вместе с окном. Идущая отправка тоже держит режим:
   * прогресс виден только в футере.
   */
  useEffect(() => {
    if (!bulkMode) return;
    const handler = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      // Слушатель в фазе перехвата: окно Radix обрабатывает ту же клавишу
      // раньше (его слушатель на `document` срабатывает до `window`), и к
      // моменту обычной фазы окно уже закрыто — проверка «открыто ли окно»
      // видела бы закрытое. В перехвате состояние ещё честное.
      if (isAnyDialogOpen()) return;
      if (bulkSubmitting || bulkProgress?.running) return;
      event.preventDefault();
      exitBulkMode();
    };
    window.addEventListener("keydown", handler, true);
    return () => window.removeEventListener("keydown", handler, true);
  }, [bulkMode, bulkSubmitting, bulkProgress?.running, exitBulkMode]);

  // Тот же ряд, что на доске участка: поиск → печать → массовые операции
  // («Групповые операции» + «Выделить все»). Массовые операции живут здесь, а
  // не в шапке таблицы: это управление выборкой, а не её данные. Доска
  // (`SectionTasksBoard`) показывает тот же ряд в том же порядке.
  const readyToolbarFields = useMemo((): FiltersPanelField[] => {
    return [
      {
        kind: "search",
        key: "search",
        value: readySearch,
        onChange: setReadySearch,
        placeholder: "Поиск по ID, артикулу, этапу…",
        layoutSpan: "min-w-[250px]",
      },
      {
        kind: "custom",
        key: "print",
        node: (
          <PrintButton
            label="Печать списка"
            disabled={readyTotal === 0}
            onClick={() => setReadyPrintOpen(true)}
          />
        ),
        layoutSpan: "flex-shrink-0",
      },
      {
        kind: "bulk",
        key: "bulk-mode",
        enabled: bulkMode,
        onChange: (enabled: boolean) => (enabled ? setBulkMode(true) : exitBulkMode()),
      },
    ];
  }, [readySearch, readyTotal, bulkMode, exitBulkMode]);

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
    // Нулевые строки (хвост раскладки группы) не отправляются вовсе: правило
    // то же, что в футере, — `enteredTransferQuantity`.
    const rowsToSend = selectedTasks.filter(
      (task) => (parseFloat(enteredTransferQuantity(task, bulkQuantities)) || 0) > 0,
    );
    if (rowsToSend.length === 0) return;

    setBulkSubmitting(true);
    setBulkProgress({ total: rowsToSend.length, completed: 0, running: true });

    const { results, summary } = await runTransferBatch({
      rows: rowsToSend,
      idempotencyPrefix: "transfer-send-bulk",
      // Количество каждой строки — то, что набрано в её поле, а не своё
      // `transferable`: в массовом режиме строки редактируются.
      quantities: bulkQuantities,
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
    setBulkQuantities({});
    setBulkGroupQuantities({});
    setBulkMode(false);
  }, [readyItems, bulkSelection, bulkQuantities, invalidateTransferCaches]);

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
              exitBulkMode();
            }}
            placeholder="Выберите ГХП"
            emptyLabel="Выберите ГХП"
            allLabel="Все ГХП"
            isAllSelected={showAllSpgs}
            onAllSelect={() => {
              setShowAllSpgs(true);
              setSpgId(null);
              setEditTransferRecord(null);
              exitBulkMode();
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
        <CardHeader className="space-y-3 pb-3">
          <CardTitle className="flex items-center gap-2">
            <Send className="h-4 w-4" />
            Готово к передаче
            {readyTotal > 0 && <Badge variant="secondary">{readyTotal}</Badge>}
          </CardTitle>
          <FiltersPanel
            compact
            fields={readyToolbarFields}
            activeSummary={readyActiveFilterSummary}
            onSelectAll={() => {
              setBulkMode(true);
              bulkSelection.selectAll(readySelectableIds);
            }}
            totalRowCount={readySelectableIds.length}
          />
        </CardHeader>
        <CardContent>
          {!spgScopeSelected ? (
            <div className="text-sm text-muted-foreground py-6 text-center">
              Выберите ГХП, чтобы увидеть задания, готовые к передаче.
            </div>
          ) : isFirstRowsLoad(readyPending, readyItems) ? (
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
                  {readyColumns.map((column) => (
                    <TableHead
                      key={column.id}
                      className={`${groupHeaderCellClass} p-0${column.id === "transferableQty" ? " text-right" : ""}`}
                      aria-sort={column.sortField ? getAriaSort(readySortConfigs, column.sortField) : undefined}
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
                  <TableHead className={groupHeaderCellClass}>
                    Действия
                  </TableHead>
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
                      colSpan={8}
                      className={`${TRANSFERS_ROW.cell} py-6 text-center text-sm text-muted-foreground`}
                    >
                      Нет заданий, соответствующих фильтру
                    </TableCell>
                  </TableRow>
                </TableBody>
              ) : (
                <VirtualizedTableBody
                  rows={readyTableRows}
                  rowHeight={TRANSFERS_ROW.rowHeightPx}
                  colSpan={8}
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
                        isAllSelected={bulkSelection.isAllSelected(
                          row.group.rows.filter((task) => !isFinalReadyRow(task)).map((task) => task.task_id),
                        )}
                        isPartiallySelected={bulkSelection.isIndeterminate(
                          row.group.rows.filter((task) => !isFinalReadyRow(task)).map((task) => task.task_id),
                        )}
                        controlledQuantity={bulkMode ? groupBulkQuantity(row.group) : undefined}
                        onQuantityChange={
                          bulkMode
                            ? (value: string) => setGroupBulkQuantity(row.group, value)
                            : undefined
                        }
                        onSelectGroup={() =>
                          toggleGroupSelection(
                            row.group.rows.filter((task) => !isFinalReadyRow(task)).map((task) => task.task_id),
                          )
                        }
                      />
                    ) : (
                      <ReadyTransferRow
                        // Ключ строки — пара «задание × размер», а НЕ task_id:
                        // трансформирующая задача (#91) отдаёт по строке на
                        // каждый выход спецификации, и у всех выходов task_id
                        // ОДИН. При `key={task_id}` четыре строки делили ключ,
                        // React переиспользовал узлы и в DOM оказывалось 8
                        // `<tr>` — по две копии первых выходов, при 5
                        // фактических строках от сервера. Оператор видел
                        // дубли, а тесты падали в strict mode.
                        // Тот же идентификатор, что и у `data-row-key` строки.
                        key={readyRowIdentity(row.task)}
                        task={row.task}
                        bulkMode={bulkMode}
                        isSelected={bulkSelection.isSelected(row.task.task_id)}
                        controlledQuantity={
                          bulkMode ? bulkQuantities[readyRowIdentity(row.task)] : undefined
                        }
                        onQuantityChange={
                          bulkMode
                            ? (value: string) =>
                                setRowBulkQuantity(
                                  row.groupKey,
                                  readyRowIdentity(row.task),
                                  value,
                                )
                            : undefined
                        }
                        onSelect={() => {
                          // Финальный выпуск в массовую передачу не берётся:
                          // чекбокс строки был выключен на нём, и клик по строке
                          // обязан вести себя так же.
                          if (!isFinalReadyRow(row.task)) bulkSelection.selectOne(row.task.task_id);
                        }}
                        isInGroup={row.groupKey != null}
                        isLastInGroup={row.isLastInGroup}
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
            {!spgScopeSelected ? (
              <div className="text-sm text-muted-foreground py-6 text-center">
                Выберите ГХП, чтобы увидеть журнал передач.
              </div>
            ) : isFirstRowsLoad(historyPending, historyItems) ? (
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
                            className={`${groupHeaderCellClass} p-0 ${column.headerClassName ?? ""}`}
                            aria-sort={column.sortField ? getAriaSort(historySortConfigs, column.sortField) : undefined}
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
                          <TableCell colSpan={9} className={`${TRANSFERS_ROW.cell} py-6 text-center text-sm text-muted-foreground`}>
                            Нет записей, соответствующих фильтру
                          </TableCell>
                        </TableRow>
                      </TableBody>
                    ) : (
                      <VirtualizedTableBody
                        rows={historyItems}
                        rowHeight={TRANSFERS_ROW.rowHeightPx}
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
                              className={`group cursor-pointer transition-colors ${rowToneFill(historyRowTone(t.status))} ${isCancelled ? "opacity-60" : ""}`}
                              onClick={() => setEditTransferRecord(t)}
                            >
                              <TableCell className={`${TRANSFERS_ROW.cell} ${ROW_TONE_STRIPE[historyRowTone(t.status)]} font-mono text-xs text-muted-foreground`}>
                                #{t.plan_position_id}
                              </TableCell>
                              <TableCell className={TRANSFERS_ROW.cell}>
                                <div className="text-xs">
                                  <div className="font-medium">{t.from_section_name}</div>
                                  <div className="text-muted-foreground">{t.from_operation_name}</div>
                                </div>
                              </TableCell>
                              <TableCell className={TRANSFERS_ROW.cell}>
                                <div className="text-xs">
                                  <div className="font-medium">{t.to_section_name}</div>
                                  <div className="text-muted-foreground">{t.to_operation_name}</div>
                                </div>
                              </TableCell>
                              <TableCell className={`${TRANSFERS_ROW.cell} text-xs font-medium`}>{t.product_sku}</TableCell>
                              <TableCell className={`${TRANSFERS_ROW.cell} text-xs text-muted-foreground whitespace-nowrap`}>
                                {formatDimensionsLabel(t.dimensions)}
                              </TableCell>
                              <TableCell className={`${TRANSFERS_ROW.cell} text-right tabular-nums font-semibold whitespace-nowrap`}>
                                {fmtQty(t.sent_quantity)}
                              </TableCell>
                              <TableCell className={TRANSFERS_ROW.cell}>
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
                              <TableCell className={`${TRANSFERS_ROW.cell} text-right w-[40px]`}>
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
          quantities={bulkQuantities}
          onSubmit={handleBulkTransferSubmit}
          onCancel={exitBulkMode}
          pending={bulkSubmitting}
          progress={bulkProgress}
        />
      )}

      <ReadyTransferPrintDialog
        open={readyPrintOpen}
        onOpenChange={setReadyPrintOpen}
        rows={readyItems}
        scopeLabel={
          showAllSpgs
            ? "Все ГХП"
            : (spgs?.find((spg) => spg.id === spgId)?.name ?? "Выбранная ГХП")
        }
      />

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


