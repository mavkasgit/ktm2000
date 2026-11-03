import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  previewReverse,
  reverseAction,
  parseReversalError,
  type JournalAction,
  type PreviewResponse,
} from "@/shared/api/actions";
import { invalidateAfter } from "@/shared/api/cacheInvalidation";
import { toast } from "@/shared/ui/use-toast";
import { Button } from "@/shared/ui";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/shared/ui/dialog";
import { fmtServerQty } from "@/shared/lib/quantityFormat";
import { IssueCancelDialog } from "@/shared/issue/IssueCancelDialog";
import { PreviewZones } from "./PreviewZones";
import {
  classifyReversalConflict,
  STALE_TOKEN_TOAST_TITLE,
} from "../lib/reversalConflicts";

export function ReversePreviewDialog({
  action,
  open,
  onOpenChange,
  onReversed,
}: {
  action: JournalAction | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onReversed?: () => void;
}) {
  const [cascade, setCascade] = useState(false);
  // Отмена выдачи целиком (#282) — отдельное окно из `shared`: оно своё
  // предпросмотр-превью и свою блокировку по серверной `reason`.
  const [cancelIssueOpen, setCancelIssueOpen] = useState(false);
  const queryClient = useQueryClient();
  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [reason, setReason] = useState("");
  const [refreshNonce, setRefreshNonce] = useState(0);

  useEffect(() => {
    if (!open || !action) return;
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    previewReverse(action.id, cascade)
      .then((data) => {
        if (!cancelled) setPreview(data);
      })
      .catch((err) => {
        if (!cancelled) setLoadError(parseReversalError(err).message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, action, refreshNonce, cascade]);

  useEffect(() => {
    if (!open) {
      setPreview(null);
      setReason("");
      setConfirming(false);
      setLoadError(null);
      setCascade(false);
      setRefreshNonce(0);
      setCancelIssueOpen(false);
    }
  }, [open]);

  if (!action) return null;

  const handleConfirm = async () => {
    if (!preview?.plan_token) return;
    setConfirming(true);
    try {
      const result = await reverseAction(action.id, {
        plan_token: preview.plan_token,
        reason: reason.trim() || null,
      });
      void invalidateAfter(queryClient, "actionReversed");
      toast({
        variant: "success",
        title: "Действие отменено",
        description: `Отменено действий: ${result.reversed_action_ids.length}, проводок скомпенсировано: ${result.compensated_tx_ids.length}`,
      });
      onOpenChange(false);
      onReversed?.();
    } catch (err) {
      const info = parseReversalError(err);
      const conflict = classifyReversalConflict(info);
      if (conflict === "stale-token") {
        // StalePlanToken: мир изменился — авто-refresh preview (ADR-0019 п.5)
        toast({ variant: "destructive", title: STALE_TOKEN_TOAST_TITLE });
        setRefreshNonce((n) => n + 1);
      } else if (conflict === "dependent-actions") {
        // HasDependentActions: предложить каскад
        toast({
          variant: "destructive",
          title: "Есть зависимые действия",
          description: `Повторите отмену каскадом: ${info.chain!.map((id) => `#${id}`).join(", ")}`,
        });
        setCascade(true);
        setRefreshNonce((n) => n + 1);
      } else {
        toast({ variant: "destructive", title: info.message || "Ошибка отмены" });
      }
    } finally {
      setConfirming(false);
    }
  };

  const blocked = !preview || preview.blockers.length > 0 || !preview?.plan_token;

  return (
    <>
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl" data-testid="reverse-preview-dialog">
        <DialogHeader>
          <DialogTitle>
            Отмена действия #{action.id} ({action.action_type})
          </DialogTitle>
          <DialogDescription>
            Предпросмотр отката. Подтверждение выполняет компенсацию проводок.
          </DialogDescription>
        </DialogHeader>

        {loading ? (
          <p className="py-4 text-sm text-slate-500">Загрузка предпросмотра…</p>
        ) : loadError ? (
          <p className="py-4 text-sm text-red-600">{loadError}</p>
        ) : preview ? (
          <PreviewZones
            revert={preview.revert}
            stays={preview.stays}
            blockers={preview.blockers}
            will_replay={preview.will_replay}
          />
        ) : null}

        {/* #282: строка `transfer_send` в журнале несёт количество, номер
            передачи и номер выдачи. Откат одного действия и отмена всей
            выдачи (N передач с общим `issue_no`) — разные операции, поэтому
            вход в окно отмены выдачи здесь отдельный. */}
        {action.transfer_no || action.issue_no || action.quantity != null ? (
          <div
            className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground"
            data-testid="reverse-issue-details"
          >
            {action.transfer_no ? (
              <span data-testid="reverse-transfer-no">Передача № {action.transfer_no}</span>
            ) : null}
            {action.quantity != null ? (
              <span data-testid="reverse-quantity">{fmtServerQty(action.quantity)} шт.</span>
            ) : null}
            {action.issue_no ? (
              <span data-testid="reverse-issue-no">Выдача {action.issue_no}</span>
            ) : null}
          </div>
        ) : null}
        {action.issue_no ? (
          <div className="mt-2">
            <Button
              variant="outline"
              size="sm"
              data-testid="reverse-open-cancel-issue"
              onClick={() => setCancelIssueOpen(true)}
            >
              Отменить выдачу целиком
            </Button>
          </div>
        ) : null}

      <input
          className="mt-3 w-full rounded border border-slate-200 px-2 py-1.5 text-sm"
          placeholder="Причина отмены (необязательно)"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          data-testid="reverse-reason-input"
        />

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Закрыть
          </Button>
          <Button
            variant="destructive"
            data-testid="reverse-confirm"
            disabled={blocked || confirming || loading}
            onClick={handleConfirm}
          >
            {confirming ? "Отмена…" : "Отменить"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
      {/* Отмена выдачи целиком (#282): своё превью и серверная причина отказа. */}
      <IssueCancelDialog
        open={cancelIssueOpen}
        onOpenChange={setCancelIssueOpen}
        issueNo={action.issue_no ?? null}
        onCancelled={onReversed}
      />
    </>
  );
}
