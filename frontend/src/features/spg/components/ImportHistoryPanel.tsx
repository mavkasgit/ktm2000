/**
 * Список батчей импорта остатков с действиями над ними (ADR-0052, #232).
 *
 * Живёт только на отдельной странице «История импортов» (`/spg/import-history`):
 * в модалке импорта показывают итог текущей заливки, а прошлые батчи — здесь.
 *
 * Три действия различаются по смыслу (ADR-0052 п.5): «посмотреть» — прочитать
 * строки и текущий остаток; «откатить» — вернуть остатки к состоянию до
 * импорта зеркальными компенсациями; «удалить» — убрать запись из списка, не
 * трогая ledger.
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Button,
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DATA_TABLE_STYLES,
  TABLE_ROW_DENSE,
  toast,
} from "@/shared/ui";
import { Loader2, Undo2 } from "lucide-react";
import { getErrorMessage } from "@/shared/api/client";
import { previewReverse } from "@/shared/api/actions";
import { invalidateAfter } from "@/shared/api/cacheInvalidation";
import { queryKeys } from "@/shared/api/queryKeys";
import {
  getStockImportBatch,
  getStockImportBatches,
  downloadStockImportBatchFile,
  hideStockImportBatch,
  importRollbackBlockerLabel,
  rollbackStockImportBatch,
  type StockImportBatch,
} from "@/shared/api/stockImportHistory";
import { saveBlobAsFile } from "@/shared/lib/downloadFile";
import { useAuth } from "@/features/auth/hooks/useAuth";
import { fmtQty } from "@/shared/lib/quantityFormat";
import { formatCompletedOperationsLabel } from "@/shared/api/stock";
import { POLICIES } from "../../auth/policies";
import { cn } from "@/shared/utils/cn";

function fmtDate(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("ru-RU");
}

function statusLabel(batch: StockImportBatch): string {
  if (batch.status === "rolled_back") return "Отменен";
  if (batch.clear_existing) return "Залит (с очисткой склада)";
  return "Залит";
}

/**
 * Причина скрытия пишется в `stock_import_batches.delete_reason`, но поля для
 * неё в UI нет: оператору незачем её набирать, а в БД она нужна — отвечает на
 * вопрос «на каком основании запись спрятана». Кто именно скрыл, хранится рядом
 * в `deleted_by`.
 */
const HIDE_REASON = "Убрано из списка оператором";

/**
 * Размеры таблицы — общие токены проекта, а не свои: тот же набор берут
 * «Журнал действий», «Передачи» и остатки. Своя мелкая копия (11px и
 * `py-1.5`) выглядела на экране мельче соседних страниц и разъезжалась с ними
 * при любой правке плотности там.
 */
const HEADER_CELL = cn(DATA_TABLE_STYLES.headerCell, TABLE_ROW_DENSE.headerCell);
const CELL = cn(TABLE_ROW_DENSE.cell, "align-middle");
const ROW_ACTION = TABLE_ROW_DENSE.actionButton;

export function ImportHistoryPanel() {
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const canRollback = POLICIES.rollbackImport(user?.role);

  const [detailId, setDetailId] = useState<number | null>(null);
  const [rollbackTarget, setRollbackTarget] = useState<StockImportBatch | null>(null);
  const [hideTarget, setHideTarget] = useState<StockImportBatch | null>(null);

  const { data: batches, isLoading, error } = useQuery({
    queryKey: queryKeys.stock.importBatches(),
    queryFn: () => getStockImportBatches(),
  });

  const rollbackMutation = useMutation({
    mutationFn: ({ batchId, planToken }: { batchId: number; planToken: string }) =>
      rollbackStockImportBatch(batchId, planToken),
    onSuccess: async () => {
      await invalidateAfter(queryClient, "stockImportRolledBack");
    },
  });

  const hideMutation = useMutation({
    mutationFn: ({ batchId }: { batchId: number }) =>
      hideStockImportBatch(batchId, HIDE_REASON),
    onSuccess: async () => {
      await invalidateAfter(queryClient, "stockImportHidden");
    },
  });

  const downloadMutation = useMutation({
    mutationFn: async (batch: StockImportBatch) => {
      const blob = await downloadStockImportBatchFile(batch.batch_id);
      saveBlobAsFile(blob, batch.filename ?? "импорт-остатков.xlsx");
    },
    onError: (err: unknown) => {
      toast({
        title: `Не удалось скачать файл: ${getErrorMessage(err)}`,
        variant: "destructive",
      });
    },
  });

  return (
    <div className="space-y-1.5">
      {isLoading ? (
        <div className="flex items-center gap-2 py-3 text-sm text-muted-foreground">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          Загрузка истории…
        </div>
      ) : error ? (
        <p className="text-sm text-destructive">
          Не удалось загрузить историю: {getErrorMessage(error)}
        </p>
      ) : !batches || batches.length === 0 ? (
        <p className="text-sm text-muted-foreground py-2">
          Импортов пока не было.
        </p>
      ) : (
        <div className={DATA_TABLE_STYLES.container}>
          <table className="w-full caption-bottom text-sm">
            <thead>
              <tr className={DATA_TABLE_STYLES.headerRow}>
                <th className={HEADER_CELL}>Файл</th>
                <th className={HEADER_CELL}>Склад</th>
                <th className={HEADER_CELL}>Когда</th>
                <th className={HEADER_CELL}>Строки</th>
                <th className={HEADER_CELL}>Состояние</th>
                <th className={HEADER_CELL} />
              </tr>
            </thead>
            <tbody>
              {batches.map((batch) => {
                const blockedLabel = importRollbackBlockerLabel(
                  batch.rollback_blocked_reason,
                );
                const rollbackEnabled = canRollback && batch.can_rollback;
                return (
                  <tr key={batch.batch_id} className="border-b border-border last:border-0">
                    <td className={cn(CELL, "font-medium")}>
                      {batch.filename ?? (
                        <span className="text-muted-foreground font-normal">
                          {batch.legacy ? "файл не сохранился" : "из буфера"}
                        </span>
                      )}
                    </td>
                    <td className={CELL}>{batch.location_name ?? "—"}</td>
                    <td className={cn(CELL, "text-muted-foreground whitespace-nowrap")}>
                      {fmtDate(batch.created_at)}
                    </td>
                    <td className={cn(CELL, "tabular-nums whitespace-nowrap")}>
                      {batch.imported_rows}
                      {batch.skipped_rows > 0 ? ` / ${batch.skipped_rows} проп.` : ""}
                    </td>
                    <td className={cn(CELL, "whitespace-nowrap")}>{statusLabel(batch)}</td>
                    <td className={CELL}>
                      <div className="flex items-center justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          className={ROW_ACTION}
                          onClick={() => setDetailId(batch.batch_id)}
                        >
                          Посмотреть
                        </Button>
                        {batch.file_id != null && (
                          <Button
                            variant="ghost"
                            size="sm"
                            className={ROW_ACTION}
                            disabled={
                              downloadMutation.isPending &&
                              downloadMutation.variables?.batch_id === batch.batch_id
                            }
                            onClick={() => downloadMutation.mutate(batch)}
                          >
                            Скачать
                          </Button>
                        )}
                        <Button
                          variant="ghost"
                          size="sm"
                          className={ROW_ACTION}
                          disabled={!rollbackEnabled}
                          title={blockedLabel ?? undefined}
                          onClick={() => setRollbackTarget(batch)}
                        >
                          <Undo2 className="h-3.5 w-3.5 mr-1" />
                          Откатить
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          className={cn(ROW_ACTION, "text-destructive")}
                          disabled={!canRollback}
                          onClick={() => setHideTarget(batch)}
                        >
                          Удалить
                        </Button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}


      {blockedLabelHint(batches) && (
        <p className="text-xs text-muted-foreground">
          {blockedLabelHint(batches)}
        </p>
      )}

      <ImportBatchDetailDialog
        batchId={detailId}
        onOpenChange={(next) => { if (!next) setDetailId(null); }}
      />

      <RollbackConfirmDialog
        batch={rollbackTarget}
        pending={rollbackMutation.isPending}
        error={rollbackMutation.error}
        onCancel={() => setRollbackTarget(null)}
        onConfirm={async () => {
          if (!rollbackTarget) return;
          try {
            await rollbackMutation.mutateAsync({
              batchId: rollbackTarget.batch_id,
              planToken: await mintPlanToken(rollbackTarget.action_id),
            });
            setRollbackTarget(null);
          } catch {
            // Ошибка уже в mutation.error — диалог остаётся открытым.
          }
        }}
      />

      <HideConfirmDialog
        batch={hideTarget}
        pending={hideMutation.isPending}
        error={hideMutation.error}
        onCancel={() => setHideTarget(null)}
        onConfirm={async () => {
          if (!hideTarget) return;
          try {
            await hideMutation.mutateAsync({
              batchId: hideTarget.batch_id,
            });
            setHideTarget(null);
          } catch {
            // Ошибка уже в mutation.error.
          }
        }}
      />
    </div>
  );
}

/** Подсказка под таблицей: почему часть батчей нельзя откатить. */
function blockedLabelHint(batches: StockImportBatch[] | undefined): string | null {
  if (!batches) return null;
  const notLast = batches.some(
    (b) => b.rollback_blocked_reason === "batch_not_last_for_location",
  );
  return notLast
    ? "Откатить можно только последний импорт по каждому складу — так остаток не вернётся к состоянию, которого на складе не было."
    : null;
}

/**
 * Токен предпросмотра для отката.
 *
 * Откат идёт через общий механизм Reversal, поэтому токен берётся оттуда же:
 * сервер проверяет его подпись и отпечаток мира, а не наш флаг. Отдельный
 * эндпоинт предпросмотра у батча не нужен — он и есть предпросмотр узла.
 */
async function mintPlanToken(actionId: number): Promise<string> {
  const preview = await previewReverse(actionId, false);
  if (preview.plan_token == null) {
    throw new Error(
      preview.blockers[0]?.detail ?? "Откат недоступен: есть блокировки",
    );
  }
  return preview.plan_token;
}

function ImportBatchDetailDialog({
  batchId,
  onOpenChange,
}: {
  batchId: number | null;
  onOpenChange: (open: boolean) => void;
}) {
  const { data, isLoading, error } = useQuery({
    queryKey: queryKeys.stock.importBatch(batchId),
    queryFn: () => getStockImportBatch(batchId as number),
    enabled: batchId != null,
  });

  return (
    <Dialog open={batchId != null} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl">
        <DialogHeader>
          <DialogTitle className="text-base">
            {data ? `Импорт: ${data.batch.filename ?? "без файла"}` : "Импорт"}
          </DialogTitle>
        </DialogHeader>

        {isLoading ? (
          <div className="flex items-center gap-2 py-6 text-xs text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            Загрузка строк…
          </div>
        ) : error ? (
          <p className="text-xs text-destructive">
            {getErrorMessage(error)}
          </p>
        ) : data ? (
          <div className="space-y-2">
            {data.batch.status === "rolled_back" && (
              <p className="text-[11px] text-amber-600 dark:text-amber-500">
                Импорт отменен {fmtDate(data.batch.rolled_back_at)} — эти строки уже
                не в остатках. «Текущий остаток» показывает, что осталось на
                складе сейчас.
              </p>
            )}
            {/* Ось ключа остатка (ADR-0055): без «Операций» две строки одного
                артикула, склада и размера с разными остатками читаются как
                дубль. Пустые состояния различимы: `null` — «не зафиксировано»,
                `[]` — «без операций». */}
            <div className="max-h-[50vh] overflow-y-auto border border-border rounded-lg">
              <table className="w-full caption-bottom text-sm">
                <thead>
                  <tr className={DATA_TABLE_STYLES.headerRow}>
                    <th className={HEADER_CELL}>Строка</th>
                    <th className={HEADER_CELL}>Артикул</th>
                    <th className={HEADER_CELL}>Кол-во</th>
                    <th className={HEADER_CELL}>Размер</th>
                    <th className={HEADER_CELL}>Склад</th>
                    <th className={HEADER_CELL}>Операции</th>
                    <th className={HEADER_CELL}>Текущий остаток</th>
                    <th className={HEADER_CELL}>Вердикт</th>
                  </tr>
                </thead>
                <tbody>
                  {data.rows.map((row) => (
                    <tr
                      key={row.row_id}
                      className="border-b border-border last:border-0"
                    >
                      <td className={cn(CELL, "text-muted-foreground tabular-nums")}>
                        {row.source_row_number}
                      </td>
                      <td className={cn(CELL, "font-medium")}>
                        {row.product_sku ?? row.sku}
                        {row.matched_sku && row.matched_sku !== row.sku && (
                          <span className="text-xs font-normal text-muted-foreground">
                            {" "}(из «{row.sku}»)
                          </span>
                        )}
                      </td>
                      <td className={cn(CELL, "tabular-nums")}>{fmtQty(row.quantity)}</td>
                      <td className={CELL}>{row.dimensions_label}</td>
                      <td className={CELL}>{row.target_section_name ?? "—"}</td>
                      <td className={cn(CELL, "text-muted-foreground")}>
                        {formatCompletedOperationsLabel(row.completed_operations)}
                      </td>
                      <td className={cn(CELL, "tabular-nums font-medium")}>
                        {fmtQty(row.current_balance)}
                      </td>
                      <td
                        className={cn(
                          CELL,
                          row.status === "invalid"
                            ? "text-destructive"
                            : "text-muted-foreground",
                        )}
                      >
                        {row.status === "invalid"
                          ? row.errors[0] ?? "не загружена"
                          : "загружена"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

function RollbackConfirmDialog({
  batch,
  pending,
  error,
  onCancel,
  onConfirm,
}: {
  batch: StockImportBatch | null;
  pending: boolean;
  error: unknown;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <AlertDialog open={batch != null} onOpenChange={(o) => { if (!o) onCancel(); }}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Откатить импорт остатков?</AlertDialogTitle>
          <AlertDialogDescription>
            Остатки вернутся к состоянию до этого импорта: зеркальными
            проводками будет снят приход этого батча
            {batch?.clear_existing
              ? " и возвращён материал, погашенный при очистке склада"
              : ""}
            . Запись в истории останется со статусом «Отменен».
          </AlertDialogDescription>
        </AlertDialogHeader>
        {error != null && (
          <p className="text-xs text-destructive">
            {getErrorMessage(error)}
          </p>
        )}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={pending}>Отмена</AlertDialogCancel>
          <AlertDialogAction
            disabled={pending}
            onClick={(event) => {
              event.preventDefault();
              onConfirm();
            }}
          >
            {pending ? "Откат…" : "Откатить"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

function HideConfirmDialog({
  batch,
  pending,
  error,
  onCancel,
  onConfirm,
}: {
  batch: StockImportBatch | null;
  pending: boolean;
  error: unknown;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <AlertDialog open={batch != null} onOpenChange={(o) => { if (!o) onCancel(); }}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Убрать импорт из списка?</AlertDialogTitle>
          <AlertDialogDescription>
            Это только скрывает запись из истории. Остатки и проводки не
            меняются, откат по-прежнему возможен через журнал действий. Для
            возврата остатков используйте «Откатить».
          </AlertDialogDescription>
        </AlertDialogHeader>
        {error != null && (
          <p className="text-xs text-destructive">
            {getErrorMessage(error)}
          </p>
        )}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={pending}>Отмена</AlertDialogCancel>
          <AlertDialogAction
            disabled={pending}
            onClick={(event) => {
              event.preventDefault();
              onConfirm();
            }}
          >
            {pending ? "Удаление…" : "Убрать из списка"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}