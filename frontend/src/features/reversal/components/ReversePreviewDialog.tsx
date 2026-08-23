import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  previewReverse,
  reverseAction,
  parseReversalError,
  type JournalAction,
  type PreviewResponse,
} from "@/shared/api/actions";
import { queryKeys } from "@/shared/api/queryKeys";
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
  action: Pick<JournalAction, "id" | "action_type" | "status"> | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onReversed?: () => void;
}) {
  const [cascade, setCascade] = useState(false);
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
      void queryClient.invalidateQueries({ queryKey: queryKeys.actions.all });
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
          />
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
  );
}
