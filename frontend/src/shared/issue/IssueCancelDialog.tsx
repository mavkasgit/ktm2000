import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, Input } from "@/shared/ui";
import {
  DIALOG_SIZES,
} from "@/shared/lib/dialogSizes";
import { TABLE_ROW_COMPACT } from "@/shared/lib/dataTableStyles";
import { fmtServerQty } from "@/shared/lib/quantityFormat";
import { getErrorMessage } from "@/shared/api/client";
import { invalidateAfter } from "@/shared/api/cacheInvalidation";
import { queryKeys } from "@/shared/api/queryKeys";
import { cancelIssue, previewIssueCancellation } from "@/shared/api/transfers";
import { toast } from "@/shared/ui/use-toast";

/**
 * Отмена выдачи целиком (#282, п.8).
 *
 * Окно живёт в `shared`, а не в фиче: entry point у него два — журнал передач
 * (`features/transfers`) и журнал отмен (`features/reversal`), а соседние
 * фичи по границам FSD друг друга не видят.
 *
 * Причина отказа — только серверная: `reason` из `cancel-preview` и текст
 * `detail` при 400. Своих формулировок здесь нет, потому что оператор должен
 * читать то же, что записано в журнале.
 */
const ROW = { ...TABLE_ROW_COMPACT };

interface IssueCancelDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Номер выдачи; `null` — окно закрыто и превью не запрашивается. */
  issueNo: string | null;
  onCancelled?: () => void;
}

export function IssueCancelDialog({ open, onOpenChange, issueNo, onCancelled }: IssueCancelDialogProps) {
  const queryClient = useQueryClient();
  const [commentValue, setCommentValue] = useState("");

  // Комментарий относится к этой выдаче и к этому просмотру: при закрытии он
  // не должен переехать на следующую отмену.
  useEffect(() => {
    if (!open) setCommentValue("");
  }, [open]);

  const previewQuery = useQuery({
    queryKey: queryKeys.transfers.issueCancelPreview(issueNo as string),
    queryFn: () => previewIssueCancellation(issueNo as string),
    enabled: open && Boolean(issueNo),
  });

  const cancelMutation = useMutation({
    mutationFn: (comment: string | null) => cancelIssue(issueNo as string, comment ?? undefined),
    onSuccess: (data) => {
      void invalidateAfter(queryClient, "actionReversed");
      toast({
        variant: "success",
        title: "Выдача отменена",
        description: `Отменено передач: ${data.cancelled_transfers.length}, этапов возвращено в работу: ${data.restored_stages.length}`,
      });
      onOpenChange(false);
      onCancelled?.();
    },
    onError: (err) => {
      // Блокировка — HTTP 400 с русским текстом: показываем его как есть.
      toast({ variant: "destructive", title: "Отмена невозможна", description: getErrorMessage(err) });
    },
  });

  const preview = previewQuery.data ?? null;
  const loading = previewQuery.isPending && open && Boolean(issueNo);
  // Кнопка дизейблится, только когда причина показана текстом под ней: по
  // ADR-0032 недоступность обязана быть видна без наведения.
  const blockReason = !issueNo
    ? "Нет номера выдачи"
    : loading
      ? "Считаем, что вернёт отмена…"
      : previewQuery.error
        ? getErrorMessage(previewQuery.error)
        : preview && !preview.can_cancel
          ? preview.reason ?? "Выдачу нельзя отменить целиком"
          : preview && preview.returns.length === 0
            ? "Все передачи выдачи уже отменены"
            : null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className={DIALOG_SIZES.md.width}
        data-testid="issue-cancel-dialog"
      >
        <DialogHeader>
          <DialogTitle>Отменить выдачу целиком</DialogTitle>
          <DialogDescription>
            Выдача {issueNo ?? "—"}: откатываются все её передачи и только те
            пропущенные этапы, которые поставила эта выдача.
          </DialogDescription>
        </DialogHeader>

        {loading ? (
          <p className="flex items-center gap-2 py-4 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Предпросмотр отмены…
          </p>
        ) : previewQuery.error && !preview ? (
          <p className="py-4 text-sm text-destructive" data-testid="issue-cancel-error">
            {getErrorMessage(previewQuery.error)}
          </p>
        ) : preview ? (
          <div className="space-y-3 text-sm">
            {/* Готовая строка от сервера: «вернём 40 на „Хранилище Б“, …». */}
            <p className="font-medium" data-testid="issue-cancel-summary">
              {preview.summary}
            </p>

            {preview.returns.length > 0 ? (
              <table className="w-full text-xs">
                <caption className="text-left text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Вернётся на склады
                </caption>
                <thead>
                  <tr className="border-b text-left text-muted-foreground">
                    <th className={ROW.headerCell}>Передача</th>
                    <th className={ROW.headerCell}>Куда</th>
                    <th className={`${ROW.headerCell} text-right`}>Количество</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.returns.map((row) => (
                    <tr
                      key={row.transfer_id}
                      className="border-b border-border/50 last:border-0"
                      data-testid={`issue-cancel-return-${row.transfer_no}`}
                    >
                      <td className={`${ROW.cell} font-mono`}>{row.transfer_no}</td>
                      <td className={ROW.cell}>{row.location_name}</td>
                      <td className={`${ROW.cell} text-right font-mono tabular-nums`}>
                        {fmtServerQty(row.quantity)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : null}

            {preview.stages.length > 0 ? (
              <div className="text-xs text-muted-foreground" data-testid="issue-cancel-stages">
                Снова в работу:{" "}
                {preview.stages
                  .map((stage) => `${stage.sequence} · ${stage.stage_name ?? "этап"}`)
                  .join("; ")}
              </div>
            ) : null}
          </div>
        ) : null}

        <Input
          className="mt-3"
          placeholder="Комментарий (необязательно)"
          data-testid="issue-cancel-comment"
          value={commentValue}
          onChange={(event) => setCommentValue(event.target.value)}
        />

        <DialogFooter className="gap-2">
          {/* Причина — текстом, а не `title`: её видно без наведения. */}
          {blockReason ? (
            <p
              className="mr-auto max-w-[60%] text-[11px] leading-tight text-destructive"
              data-testid="issue-cancel-reason"
            >
              {blockReason}
            </p>
          ) : null}
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Закрыть
          </Button>
          <Button
            variant="destructive"
            data-testid="issue-cancel-confirm"
            disabled={Boolean(blockReason) || cancelMutation.isPending}
            onClick={() => cancelMutation.mutate(commentValue.trim() || null)}
          >
            {cancelMutation.isPending ? "Отмена…" : "Отменить выдачу целиком"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
