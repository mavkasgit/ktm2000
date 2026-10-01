import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Loader2 } from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Button,
  Badge,
  toast,
} from "@/shared/ui";
import {
  forceDeleteImportBatch,
  getBatchForceDeletePreview,
  type BatchDeleteConflict,
  type BatchForceDeletePreview,
} from "@/shared/api/productionPlans";
import { formatCompletedOperationsLabel } from "@/shared/api/stock";
import { queryKeys } from "@/shared/api/queryKeys";
import { invalidateAfter } from "@/shared/api/cacheInvalidation";
import { getErrorMessage } from "@/shared/api/client";
import { fmtQtyPrecise } from "@/shared/lib/quantityFormat";

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  planId: number;
  batchId: number;
  filename: string;
  conflict: BatchDeleteConflict;
  onForceDeleted: () => void;
};

type StockEffect = BatchForceDeletePreview["stock_effects"][number];

/**
 * Ключ строки свода «Как изменятся остатки» — зеркало ключа StockBalance
 * (ADR-0055).
 *
 * Пустые состояния оси обязаны различимы: `null` («не зафиксировано») и `[]`
 * («без операций») — разные остатки, но прежний `join(",")` склеивал их в одну
 * строку ключа, а бэкенд в одном ответе отдаёт обе группы. Два одинаковых
 * ключа в списке — предупреждение React и риск «прилипания» строк в диалоге,
 * подтверждающем необратимое удаление. Габарит входит в ключ по той же
 * причине: у одной пары артикул/участок свод различает и его.
 */
export function stockEffectRowKey(effect: StockEffect): string {
  const ops = effect.completed_operations;
  const opsAxis = ops === null ? "<null>" : `<${[...ops].sort().join(",")}>`;
  const dimsAxis =
    effect.dimensions == null ? "<null>" : JSON.stringify(effect.dimensions);
  return `${effect.product_sku}|${effect.location_id}|${dimsAxis}|${opsAxis}`;
}

/**
 * Принудительное удаление импорта «поверх» живых данных.
 *
 * Экран — только последствия: оператор видит, ЧТО снесётся и как изменятся
 * остатки, и принимает решение одной кнопкой. Ни ввода имени файла, ни ввода
 * причины: барьер «введите имя руками» тут не работал — имя и так стоит в
 * заголовке, а причина одинакова для всех случаев («удалено принудительно»).
 * Обе остаются в контракте API и пишутся в БД: `confirmation` — точное имя
 * файла, `reason` — константа ниже (см. MIN_REASON_LENGTH в бэкенде).
 */
const FORCE_DELETE_REASON = "принудительное удаление импорта оператором";

export function BatchForceDeleteDialog({
  open,
  onOpenChange,
  planId,
  batchId,
  filename,
  conflict,
  onForceDeleted,
}: Props) {
  const queryClient = useQueryClient();
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) setError(null);
  }, [open]);

  const { data: preview, isLoading, error: previewError } = useQuery({
    queryKey: queryKeys.plan.forceDeletePreview(planId, batchId),
    queryFn: () => getBatchForceDeletePreview(planId, batchId),
    enabled: open && !!batchId,
  });

  const hardBlockers = preview?.blockers ?? [];
  const canSubmit = !deleting && hardBlockers.length === 0;

  async function handleConfirm() {
    if (!canSubmit) return;
    setDeleting(true);
    setError(null);
    try {
      const result = await forceDeleteImportBatch(planId, batchId, {
        confirmation: filename,
        reason: FORCE_DELETE_REASON,
      });
      void invalidateAfter(queryClient, "importForceDeleted");
      toast({
        title: "Импорт удалён",
        description: `Снесено позиций: ${result.positions}, заданий: ${result.work_tasks}, передач: ${result.transfers}, проводок: ${result.ledger_entries}. Остатки возвращены к состоянию до импорта.`,
        variant: "success",
      });
      onOpenChange(false);
      onForceDeleted();
    } catch (e) {
      const message = getErrorMessage(e);
      setError(message);
      toast({ title: "Ошибка удаления импорта", description: message, variant: "destructive" });
    } finally {
      setDeleting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="w-[calc(100vw-2rem)] max-w-3xl max-h-[85vh] grid-rows-[auto_minmax(0,1fr)_auto]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-destructive" />
            Принудительное удаление импорта
          </DialogTitle>
          <DialogDescription>
            Файл «{filename}» будет снесён вместе с производственными данными. Это
            не отмена — данные исчезнут из плана, участков и склада, а остатки
            вернутся к состоянию до импорта.
          </DialogDescription>
        </DialogHeader>

        <div className="min-h-0 overflow-y-auto space-y-4 text-sm">
          {isLoading && (
            <p className="flex items-center gap-2 text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" /> Считаем последствия…
            </p>
          )}

          {previewError != null && (
            <p className="text-destructive">{getErrorMessage(previewError)}</p>
          )}

          {preview != null && hardBlockers.length > 0 && (
            <div className="rounded-md border border-destructive/40 bg-destructive/5 p-3">
              <h4 className="font-medium mb-1 text-destructive">
                Удаление невозможно даже принудительно
              </h4>
              <p className="text-muted-foreground mb-2">
                Эти данные связаны с чужим импортом — снести их значит испортить чужое.
                Сначала удалите смежный импорт.
              </p>
              <ul className="space-y-1 max-h-40 overflow-y-auto">
                {hardBlockers.map((b, i) => (
                  <li key={`${b.position_id}-${i}`} className="font-mono text-xs text-destructive">
                    {b.reason}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {preview != null && hardBlockers.length === 0 && (
            <>
              <section>
                <h4 className="font-medium mb-2 sticky top-0 bg-background py-1">
                  Что будет снесено
                </h4>
                <dl className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                  <Count label="Позиций плана" value={preview.positions} />
                  <Count label="Линий участка" value={preview.section_plan_lines} />
                  <Count label="Заданий" value={preview.work_tasks} />
                  <Count label="Передач" value={preview.transfers} />
                  <Count label="Брак" value={preview.defects} />
                  <Count label="Проводок склада" value={preview.ledger_entries} />
                </dl>
              </section>

              <section>
                <h4 className="font-medium mb-2">Как изменятся остатки</h4>
                {preview.stock_effects.length === 0 ? (
                  <p className="text-muted-foreground">Проводок по этому импорту нет — склад не меняется.</p>
                ) : (
                  <div className="max-h-48 overflow-y-auto rounded border">
                    <table className="w-full text-xs">
                      <thead className="border-b bg-muted/50 sticky top-0">
                        <tr>
                          <th className="text-left p-2 whitespace-nowrap">Артикул</th>
                          <th className="text-left p-2 whitespace-nowrap">Участок</th>
                          <th className="text-left p-2 whitespace-nowrap">Операции</th>
                          <th className="text-right p-2 whitespace-nowrap">Изменение</th>
                        </tr>
                      </thead>
                      <tbody>
                        {preview.stock_effects.map((e) => (
                          <tr key={stockEffectRowKey(e)} className="border-b">
                            <td className="p-2 whitespace-nowrap">{e.product_sku}</td>
                            <td className="p-2 whitespace-nowrap">{e.location_code}</td>
                            {/* ADR-0055: без этой ячейки две строки одного
                                артикула и участка выглядели бы одинаково —
                                ключ остатка различает их по операциям. Второй
                                аргумент — признак, развитый справочником: подпись
                                обязана совпадать с доской остатков, иначе здесь
                                печатались бы коды (PRESS_WINDOW). */}
                            <td className="p-2 whitespace-nowrap text-muted-foreground">
                              {formatCompletedOperationsLabel(
                                e.completed_operations,
                                e.completed_stages,
                              )}
                            </td>
                            <td
                              className={`p-2 text-right whitespace-nowrap tabular-nums ${
                                e.net_delta.startsWith("-") ? "text-red-600" : "text-green-700"
                              }`}
                            >
                              {signedQty(e.net_delta)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                <p className="text-muted-foreground mt-2">
                  Остатки пересчитаются из проводок: «−» означает, что материала на
                  участке станет меньше, «+» — больше.
                </p>
              </section>

              <section>
                <h4 className="font-medium mb-2">Почему обычное удаление недоступно</h4>
                <ul className="space-y-1 text-muted-foreground max-h-32 overflow-y-auto">
                  {conflict.blockers.slice(0, 50).map((b, i) => (
                    <li key={`${b.position_id}-${i}`} className="text-xs">
                      позиция #{b.position_id} — {blockerText(b.reason)}
                    </li>
                  ))}
                  {conflict.blockers.length > 50 && (
                    <li className="text-xs">…и ещё {conflict.blockers.length - 50}</li>
                  )}
                </ul>
              </section>

              {error != null && <p className="text-destructive">{error}</p>}
            </>
          )}
        </div>

        <DialogFooter className="flex-col sm:flex-col gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={deleting}>
            Отмена
          </Button>
          <Button variant="destructive" onClick={() => void handleConfirm()} disabled={!canSubmit}>
            {deleting ? "Удаление…" : "Удалить принудительно"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Count({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded border px-2 py-1.5">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="text-base font-semibold tabular-nums">{value}</dd>
    </div>
  );
}

/** Смена количества с явным знаком: «−5» читается как уход, «+5» — как приход. */
function signedQty(net: string): string {
  const formatted = fmtQtyPrecise(net);
  return formatted.startsWith("-") ? formatted : `+${formatted}`;
}

function blockerText(reason: string): string {
  if (reason === "released") return "запущена в производство";
  if (reason.startsWith("transfer №")) return `связана с передачей ${reason}`;
  return reason;
}

