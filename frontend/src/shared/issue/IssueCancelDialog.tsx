import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, Input } from "@/shared/ui";
import { RadioGroup, RadioGroupItem } from "@/shared/ui/radio-group";
import {
  DIALOG_SIZES,
} from "@/shared/lib/dialogSizes";
import { TABLE_ROW_COMPACT } from "@/shared/lib/dataTableStyles";
import { fmtServerQty } from "@/shared/lib/quantityFormat";
import { getErrorMessage } from "@/shared/api/client";
import { invalidateAfter } from "@/shared/api/cacheInvalidation";
import { queryKeys } from "@/shared/api/queryKeys";
import {
  cancelIssue,
  previewIssueCancellation,
  type IssueCancelMode,
  type IssueCancelScenario,
} from "@/shared/api/transfers";
import { toast } from "@/shared/ui/use-toast";

/**
 * Отмена выдачи: оператор явно выбирает режим (#282, #349).
 *
 * * «Отменить остаток» — возвращаются только передачи, которые получатель
 *   ещё не взял в работу; принятое остаётся как есть.
 * * «Полный откат» — отменяется вся выдача, включая принятую часть:
 *   обратные проводки возвращают материал на склады, остатки сходятся.
 *
 * Режим не выбирается за оператора: последствия для уже принятого материала
 * разные, и предупреждение о количестве принятого показывается до нажатия.
 * Причина отказа — только серверная (`reason` из `cancel-preview` и текст
 * `detail` при 400): своих формулировок здесь нет, оператор должен читать то
 * же, что записано в журнале.
 */
const ROW = { ...TABLE_ROW_COMPACT };

interface IssueCancelDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Номер выдачи; `null` — окно закрыто и превью не запрашивается. */
  issueNo: string | null;
  onCancelled?: () => void;
}

/** Ключ операции живёт один показ окна: повтор запроса не задвоит возврат. */
function newOperationKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `issue-cancel-${crypto.randomUUID()}`;
  }
  return `issue-cancel-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

const MODE_LABELS: Record<IssueCancelMode, string> = {
  remainder: "Отменить остаток",
  full: "Полный откат",
};

export function IssueCancelDialog({ open, onOpenChange, issueNo, onCancelled }: IssueCancelDialogProps) {
  const queryClient = useQueryClient();
  const [commentValue, setCommentValue] = useState("");
  const [mode, setMode] = useState<IssueCancelMode | null>(null);
  const [operationKey, setOperationKey] = useState(newOperationKey);

  // Состояние относится к этой выдаче и этому показу: при закрытии оно не
  // должно переехать на следующую отмену.
  useEffect(() => {
    if (!open) {
      setCommentValue("");
      setMode(null);
      return;
    }
    setOperationKey(newOperationKey());
  }, [open, issueNo]);

  const previewQuery = useQuery({
    queryKey: queryKeys.transfers.issueCancelPreview(issueNo as string),
    queryFn: () => previewIssueCancellation(issueNo as string),
    enabled: open && Boolean(issueNo),
  });

  const cancelMutation = useMutation({
    mutationFn: (args: { mode: IssueCancelMode; comment: string | null; operationKey: string }) =>
      cancelIssue(issueNo as string, {
        mode: args.mode,
        comment: args.comment ?? undefined,
        idempotencyKey: args.operationKey,
      }),
    onSuccess: (data) => {
      void invalidateAfter(queryClient, "actionReversed");
      toast({
        variant: "success",
        title: data.idempotent_replay ? "Выдача уже отменена" : "Выдача отменена",
        description:
          `Режим: ${MODE_LABELS[data.mode]}. Отменено передач: ${data.cancelled_transfers.length}` +
          `, оставлено без изменений: ${data.kept_transfers.length}` +
          `, этапов возвращено в работу: ${data.restored_stages.length}`,
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
  const scenario: IssueCancelScenario | null = preview && mode ? preview[mode] : null;
  const acceptedQuantity = preview ? Number(preview.full.accepted_quantity.replace(",", ".")) : 0;
  // Кнопка дизейблится, только когда причина показана текстом под ней: по
  // ADR-0032 недоступность обязана быть видна без наведения.
  const blockReason = !issueNo
    ? "Нет номера выдачи"
    : loading
      ? "Считаем, что вернёт отмена…"
      : previewQuery.error
        ? getErrorMessage(previewQuery.error)
        : !preview
          ? null
          : !mode
            ? "Выберите режим: отменить остаток или выполнить полный откат"
            : !scenario?.can_cancel
              ? scenario?.reason ?? "Выдачу нельзя отменить в этом режиме"
              : scenario.returns.length === 0
                ? "Все передачи выдачи уже отменены"
                : null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className={DIALOG_SIZES.md.width}
        data-testid="issue-cancel-dialog"
      >
        <DialogHeader>
          <DialogTitle>Отменить выдачу</DialogTitle>
          <DialogDescription>
            Выдача {issueNo ?? "—"}: выберите, что делать с уже принятой частью.
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
            <RadioGroup
              value={mode ?? ""}
              onValueChange={(value) => setMode(value as IssueCancelMode)}
              aria-label="Режим отмены выдачи"
            >
              <div
                className="flex cursor-pointer items-start gap-3 rounded-md border p-3"
                onClick={() => setMode("remainder")}
                data-testid="issue-cancel-mode-remainder"
              >
                <RadioGroupItem value="remainder" className="mt-0.5" aria-label="Отменить остаток" />
                <div className="space-y-1">
                  <div className="font-medium">Отменить остаток</div>
                  <p className="text-xs text-muted-foreground">
                    Вернётся только то, что получатель ещё не взял в работу.
                    Принятое останется как есть.
                  </p>
                  <p className="text-xs" data-testid="issue-cancel-remainder-summary">
                    {preview.remainder.summary}
                  </p>
                  {!preview.remainder.can_cancel && preview.remainder.reason ? (
                    <p className="text-xs text-destructive">{preview.remainder.reason}</p>
                  ) : null}
                </div>
              </div>

              <div
                className="flex cursor-pointer items-start gap-3 rounded-md border p-3"
                onClick={() => setMode("full")}
                data-testid="issue-cancel-mode-full"
              >
                <RadioGroupItem value="full" className="mt-0.5" aria-label="Полный откат" />
                <div className="space-y-1">
                  <div className="font-medium">Полный откат</div>
                  <p className="text-xs text-muted-foreground">
                    Откатится вся выдача, включая принятую часть: остатки
                    складов восстановятся обратными проводками.
                  </p>
                  <p className="text-xs" data-testid="issue-cancel-full-summary">
                    {preview.full.summary}
                  </p>
                  {acceptedQuantity > 0 ? (
                    <p
                      className="rounded-md bg-amber-50 px-2 py-1 text-xs text-amber-800"
                      data-testid="issue-cancel-full-warning"
                    >
                      Уже принято получателем: {fmtServerQty(preview.full.accepted_quantity)} шт.
                      Этот материал вернётся на склады, а участок освободится.
                    </p>
                  ) : null}
                  {!preview.full.can_cancel && preview.full.reason ? (
                    <p className="text-xs text-destructive">{preview.full.reason}</p>
                  ) : null}
                </div>
              </div>
            </RadioGroup>

            {scenario && scenario.returns.length > 0 ? (
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
                  {scenario.returns.map((row) => (
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

            {scenario && scenario.stages.length > 0 ? (
              <div className="text-xs text-muted-foreground" data-testid="issue-cancel-stages">
                Снова в работу:{" "}
                {scenario.stages
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
            disabled={Boolean(blockReason) || !mode || cancelMutation.isPending}
            onClick={() => {
              if (!mode) return;
              cancelMutation.mutate({
                mode,
                comment: commentValue.trim() || null,
                operationKey,
              });
            }}
          >
            {cancelMutation.isPending
              ? "Отмена…"
              : mode
                ? MODE_LABELS[mode]
                : "Отменить выдачу"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
