import { useMemo, useState } from "react";

import type { AcceptTransferInput, IncomingTransfer } from "@/shared/api/shopfloor";
import {
  Badge,
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  Input,
} from "@/shared/ui";

function fmtQty(value: string): string {
  const n = parseFloat(value);
  if (!Number.isFinite(n)) return "0";
  return Number.isInteger(n) ? String(n) : n.toFixed(3).replace(/\.?0+$/, "");
}

function toNumber(value: string | number): number {
  const n = typeof value === "number" ? value : parseFloat(value);
  return Number.isFinite(n) ? n : 0;
}

type AcceptDialogState = {
  open: boolean;
  mode: "partial" | "reject";
  transfer: IncomingTransfer | null;
  acceptNow: string;
  rejectNow: string;
  reason: string;
  comment: string;
};

type IncomingTransfersPanelProps = {
  transfers: IncomingTransfer[];
  isLoading: boolean;
  isPending: boolean;
  onAccept: (transferId: number, payload: AcceptTransferInput) => void;
};

export function IncomingTransfersPanel({
  transfers,
  isLoading,
  isPending,
  onAccept,
}: IncomingTransfersPanelProps) {
  const [dialog, setDialog] = useState<AcceptDialogState>({
    open: false,
    mode: "partial",
    transfer: null,
    acceptNow: "",
    rejectNow: "",
    reason: "",
    comment: "",
  });
  const [dialogError, setDialogError] = useState<string | null>(null);

  const openPartial = (transfer: IncomingTransfer) => {
    setDialog({
      open: true,
      mode: "partial",
      transfer,
      acceptNow: "",
      rejectNow: "",
      reason: "",
      comment: "",
    });
    setDialogError(null);
  };

  const openReject = (transfer: IncomingTransfer) => {
    setDialog({
      open: true,
      mode: "reject",
      transfer,
      acceptNow: "",
      rejectNow: "",
      reason: "",
      comment: "",
    });
    setDialogError(null);
  };

  const closeDialog = () => {
    setDialog((prev) => ({ ...prev, open: false, transfer: null }));
    setDialogError(null);
  };

  const remaining = useMemo(() => {
    if (!dialog.transfer) return 0;
    return toNumber(dialog.transfer.remaining_quantity);
  }, [dialog.transfer]);

  const submitDialog = () => {
    if (!dialog.transfer) return;
    const sent = toNumber(dialog.transfer.sent_quantity);
    const currentAccepted = toNumber(dialog.transfer.accepted_quantity);
    const currentRejected = toNumber(dialog.transfer.rejected_quantity);

    if (dialog.mode === "reject") {
      if (!dialog.reason.trim()) {
        setDialogError("Укажите причину отклонения остатка.");
        return;
      }
      onAccept(dialog.transfer.transfer_id, {
        accepted_quantity: currentAccepted,
        rejected_quantity: sent - currentAccepted,
        reason: dialog.reason.trim(),
        comment: dialog.comment.trim() || undefined,
      });
      closeDialog();
      return;
    }

    const acceptNow = toNumber(dialog.acceptNow);
    const rejectNow = toNumber(dialog.rejectNow);
    if (acceptNow < 0 || rejectNow < 0) {
      setDialogError("Количество не может быть отрицательным.");
      return;
    }
    if (acceptNow + rejectNow <= 0) {
      setDialogError("Укажите количество к приемке или отклонению.");
      return;
    }
    if (acceptNow + rejectNow > remaining) {
      setDialogError(`Сумма превышает остаток (${fmtQty(String(remaining))}).`);
      return;
    }
    if (rejectNow > 0 && !dialog.reason.trim()) {
      setDialogError("Для отклонения укажите причину.");
      return;
    }

    onAccept(dialog.transfer.transfer_id, {
      accepted_quantity: currentAccepted + acceptNow,
      rejected_quantity: currentRejected + rejectNow,
      reason: dialog.reason.trim() || undefined,
      comment: dialog.comment.trim() || undefined,
    });
    closeDialog();
  };

  return (
    <div className="rounded-lg border p-4 space-y-3">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold">Входящие передачи</h3>
        <Badge variant="secondary">{transfers.length}</Badge>
      </div>

      {isLoading && <div className="text-sm text-muted-foreground">Загрузка входящих передач...</div>}
      {!isLoading && transfers.length === 0 && (
        <div className="rounded-lg border p-3 text-sm text-muted-foreground text-center">Нет входящих передач</div>
      )}

      {!isLoading && transfers.length > 0 && (
        <div className="space-y-2">
          {transfers.map((transfer) => {
            const sent = toNumber(transfer.sent_quantity);
            const accepted = toNumber(transfer.accepted_quantity);
            const rejected = toNumber(transfer.rejected_quantity);
            const left = Math.max(0, sent - accepted - rejected);
            return (
              <div key={transfer.transfer_id} className="rounded-lg border p-3">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <div className="font-medium">{transfer.transfer_no}</div>
                    <div className="text-xs text-muted-foreground">
                      {transfer.from_section_code} · {transfer.from_section_name}
                      {" -> "}
                      {transfer.to_operation_name || "Следующий этап"}
                    </div>
                  </div>
                  <Badge variant={left > 0 ? "destructive" : "secondary"}>
                    Остаток: {fmtQty(String(left))}
                  </Badge>
                </div>
                <div className="mt-2 grid grid-cols-2 gap-2 text-xs">
                  <div>Отправлено: <span className="font-medium">{fmtQty(transfer.sent_quantity)}</span></div>
                  <div>Принято: <span className="font-medium">{fmtQty(transfer.accepted_quantity)}</span></div>
                  <div>Отклонено: <span className="font-medium">{fmtQty(transfer.rejected_quantity)}</span></div>
                  <div>Статус: <span className="font-medium">{transfer.status}</span></div>
                </div>
                <div className="mt-3 flex flex-wrap gap-1">
                  <Button
                    size="sm"
                    onClick={() => onAccept(transfer.transfer_id, { accepted_quantity: transfer.sent_quantity, rejected_quantity: "0" })}
                    disabled={isPending || left <= 0}
                  >
                    Принять полностью
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => openPartial(transfer)} disabled={isPending || left <= 0}>
                    Принять частично
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => openReject(transfer)} disabled={isPending || left <= 0}>
                    Отклонить остаток
                  </Button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      <Dialog open={dialog.open} onOpenChange={(open) => !open && closeDialog()}>
        <DialogContent className="sm:max-w-[520px]">
          <DialogHeader>
            <DialogTitle>{dialog.mode === "partial" ? "Принять частично" : "Отклонить остаток"}</DialogTitle>
            <DialogDescription>
              {dialog.transfer?.transfer_no} · Остаток {fmtQty(String(remaining))}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            {dialog.mode === "partial" && (
              <>
                <div>
                  <label className="text-sm font-medium">Принять сейчас</label>
                  <Input type="number" step="0.001" value={dialog.acceptNow} onChange={(e) => setDialog((prev) => ({ ...prev, acceptNow: e.target.value }))} />
                </div>
                <div>
                  <label className="text-sm font-medium">Отклонить сейчас</label>
                  <Input type="number" step="0.001" value={dialog.rejectNow} onChange={(e) => setDialog((prev) => ({ ...prev, rejectNow: e.target.value }))} />
                </div>
              </>
            )}
            <div>
              <label className="text-sm font-medium">Причина</label>
              <Input value={dialog.reason} onChange={(e) => setDialog((prev) => ({ ...prev, reason: e.target.value }))} placeholder="Обязательно при отклонении" />
            </div>
            <div>
              <label className="text-sm font-medium">Комментарий</label>
              <Input value={dialog.comment} onChange={(e) => setDialog((prev) => ({ ...prev, comment: e.target.value }))} placeholder="Опционально" />
            </div>
            {dialogError && <div className="text-sm text-red-600">{dialogError}</div>}
            <div className="flex justify-end gap-2 pt-1">
              <Button variant="outline" onClick={closeDialog}>Отмена</Button>
              <Button onClick={submitDialog} disabled={isPending}>{isPending ? "Сохранение..." : "Сохранить"}</Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

