/**
 * Секция «История импортов» внутри модалки импорта остатков.
 *
 * Стоит здесь по решению заказчика (#232, Q21): историю видно там, где
 * импорт и делают. Цена этого решения — посмотреть прошлый импорт можно
 * только открыв модалку заново; минус зафиксирован в ADR-0052 §Последствия.
 *
 * Три действия различаются по смыслу (ADR-0052 п.5):
 * «посмотреть» — прочитать строки и текущий остаток; «откатить» — вернуть
 * остатки к состоянию до импорта зеркальными компенсациями; «удалить» —
 * убрать запись из списка, не трогая ledger.
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
} from "@/shared/ui";
import { Loader2, RefreshCw, Undo2 } from "lucide-react";
import { getErrorMessage } from "@/shared/api/client";
import { previewReverse } from "@/shared/api/actions";
import { invalidateAfter } from "@/shared/api/cacheInvalidation";
import { queryKeys } from "@/shared/api/queryKeys";
import {
  getStockImportBatch,
  getStockImportBatches,
  getStockImportBatchFileUrl,
  hideStockImportBatch,
  importRollbackBlockerLabel,
  rollbackStockImportBatch,
  type StockImportBatch,
} from "@/shared/api/stockImportHistory";
import { useAuth } from "@/features/auth/hooks/useAuth";
import { POLICIES } from "../../auth/policies";

function fmtDate(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("ru-RU");
}

function statusLabel(batch: StockImportBatch): string {
  if (batch.status === "rolled_back") return "Откатан";
  if (batch.clear_existing) return "Залит (с очисткой склада)";
  return "Залит";
}

export function ImportHistorySection() {
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const canRollback = POLICIES.rollbackImport(user?.role);

  const [detailId, setDetailId] = useState<number | null>(null);
  const [rollbackTarget, setRollbackTarget] = useState<StockImportBatch | null>(null);
  const [hideTarget, setHideTarget] = useState<StockImportBatch | null>(null);

  const { data: batches, isLoading, isFetching, error } = useQuery({
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
    mutationFn: ({ batchId, reason }: { batchId: number; reason: string }) =>
      hideStockImportBatch(batchId, reason),
    onSuccess: async () => {
      await invalidateAfter(queryClient, "stockImportHidden");
    },
  });

  return (
    <section className="mt-3 pt-3 border-t border-border space-y-1.5">
      <div className="flex items-center justify-between">
        <h3 className="text-[11px] font-semibold text-foreground">
          История импортов
        </h3>
        <Button
          variant="ghost"
          size="sm"
          className="h-6 px-1.5 text-[10px]"
          disabled={isFetching}
          onClick={() => {
            void queryClient.invalidateQueries({
              queryKey: queryKeys.stock.importBatches(),
            });
          }}
        >
          <RefreshCw className="h-3 w-3 mr-1" />
          Обновить
        </Button>
      </div>

      {isLoading ? (
        <div className="flex items-center gap-2 py-3 text-[11px] text-muted-foreground">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          Загрузка истории…
        </div>
      ) : error ? (
        <p className="text-[11px] text-destructive">
          Не удалось загрузить историю: {getErrorMessage(error)}
        </p>
      ) : !batches || batches.length === 0 ? (
        <p className="text-[11px] text-muted-foreground py-2">
          Импортов пока не было.
        </p>
      ) : (
        <div className="border border-border rounded-lg overflow-hidden">
          <table className="w-full text-[11px] text-left border-collapse">
            <thead>
              <tr className="bg-muted/50 border-b border-border">
                <th className="px-2 py-1.5 font-semibold text-foreground">
                  Файл
                </th>
                <th className="px-2 py-1.5 font-semibold text-foreground">
                  Склад
                </th>
                <th className="px-2 py-1.5 font-semibold text-foreground">
                  Когда
                </th>
                <th className="px-2 py-1.5 font-semibold text-foreground">
                  Строк
                </th>
                <th className="px-2 py-1.5 font-semibold text-foreground">
                  Состояние
                </th>
                <th className="px-2 py-1.5" />
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
                    <td className="px-2 py-1.5 text-foreground">
                      {batch.filename ?? (
                        <span className="text-muted-foreground">
                          {batch.legacy ? "файл не сохранился" : "из буфера"}
                        </span>
                      )}
                    </td>
                    <td className="px-2 py-1.5 text-muted-foreground">
                      {batch.location_name ?? "—"}
                    </td>
                    <td className="px-2 py-1.5 text-muted-foreground whitespace-nowrap">
                      {fmtDate(batch.created_at)}
                    </td>
                    <td className="px-2 py-1.5 text-muted-foreground tabular-nums whitespace-nowrap">
                      {batch.imported_rows}
                      {batch.skipped_rows > 0 ? ` / ${batch.skipped_rows} проп.` : ""}
                    </td>
                    <td className="px-2 py-1.5 text-muted-foreground whitespace-nowrap">
                      {statusLabel(batch)}
                    </td>
                    <td className="px-2 py-1.5">
                      <div className="flex items-center justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-6 px-1.5 text-[10px]"
                          onClick={() => setDetailId(batch.batch_id)}
                        >
                          Посмотреть
                        </Button>
                        {batch.file_id != null && (
                          <a
                            href={getStockImportBatchFileUrl(batch.batch_id)}
                            className="inline-flex h-6 items-center rounded-md px-1.5 text-[10px] hover:bg-accent"
                          >
                            Скачать
                          </a>
                        )}
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-6 px-1.5 text-[10px]"
                          disabled={!rollbackEnabled}
                          title={blockedLabel ?? undefined}
                          onClick={() => setRollbackTarget(batch)}
                        >
                          <Undo2 className="h-3 w-3 mr-1" />
                          Откатить
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-6 px-1.5 text-[10px] text-destructive"
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
        <p className="text-[10px] text-muted-foreground">
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
        onConfirm={async (reason) => {
          if (!hideTarget) return;
          try {
            await hideMutation.mutateAsync({
              batchId: hideTarget.batch_id,
              reason,
            });
            setHideTarget(null);
          } catch {
            // Ошибка в mutation.error.
          }
        }}
      />
    </section>
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
                Батч откатан {fmtDate(data.batch.rolled_back_at)} — эти строки уже
                не в остатках. «Текущий остаток» показывает, что осталось на
                складе сейчас.
              </p>
            )}
            <div className="max-h-[50vh] overflow-y-auto border border-border rounded-lg">
              <table className="w-full text-[11px] text-left border-collapse">
                <thead>
                  <tr className="bg-muted/50 border-b border-border">
                    <th className="px-2 py-1.5">Строка</th>
                    <th className="px-2 py-1.5">Артикул</th>
                    <th className="px-2 py-1.5">Кол-во</th>
                    <th className="px-2 py-1.5">Размер</th>
                    <th className="px-2 py-1.5">Склад</th>
                    <th className="px-2 py-1.5">Текущий остаток</th>
                    <th className="px-2 py-1.5">Вердикт</th>
                  </tr>
                </thead>
                <tbody>
                  {data.rows.map((row) => (
                    <tr
                      key={row.row_id}
                      className="border-b border-border last:border-0"
                    >
                      <td className="px-2 py-1 text-muted-foreground tabular-nums">
                        {row.source_row_number}
                      </td>
                      <td className="px-2 py-1 text-foreground">
                        {row.product_sku ?? row.sku}
                        {row.matched_sku && row.matched_sku !== row.sku && (
                          <span className="text-[10px] text-muted-foreground">
                            {" "}(из «{row.sku}»)
                          </span>
                        )}
                      </td>
                      <td className="px-2 py-1 text-foreground tabular-nums">
                        {row.quantity ?? "—"}
                      </td>
                      <td className="px-2 py-1 text-muted-foreground">
                        {row.dimensions_label}
                      </td>
                      <td className="px-2 py-1 text-muted-foreground">
                        {row.target_section_name ?? "—"}
                      </td>
                      <td className="px-2 py-1 text-foreground tabular-nums">
                        {row.current_balance ?? "—"}
                      </td>
                      <td
                        className={`px-2 py-1 ${
                          row.status === "invalid"
                            ? "text-destructive"
                            : "text-muted-foreground"
                        }`}
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
            . Запись в истории останется со статусом «Откатан».
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
  onConfirm: (reason: string) => void;
}) {
  const [reason, setReason] = useState("");
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
        <input
          className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs"
          placeholder="Причина (минимум 3 символа)"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
        {error != null && (
          <p className="text-xs text-destructive">
            {getErrorMessage(error)}
          </p>
        )}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={pending}>Отмена</AlertDialogCancel>
          <AlertDialogAction
            disabled={pending || reason.trim().length < 3}
            onClick={(event) => {
              event.preventDefault();
              onConfirm(reason.trim());
            }}
          >
            {pending ? "Удаление…" : "Убрать из списка"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
