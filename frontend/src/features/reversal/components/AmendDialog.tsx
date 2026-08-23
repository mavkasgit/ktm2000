import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "@/shared/api/queryKeys";
import {
  amendAction,
  parseReversalError,
  previewAmend,
  type JournalAction,
  type PreviewResponse,
} from "@/shared/api/actions";
import { toast } from "@/shared/ui/use-toast";
import { Button, Input } from "@/shared/ui";
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

/** Изменение действия transfer_send (тикет #115 amend, UI #117).
 *  Поля — по _AMEND_FIELDS компенсатора: quantity/from_task_id/to_task_id/dimensions. */
export function AmendDialog({
  action,
  open,
  onOpenChange,
  onAmended,
}: {
  action: Pick<JournalAction, "id" | "action_type" | "status"> | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onAmended?: () => void;
}) {
  const queryClient = useQueryClient();
  const [quantity, setQuantity] = useState("");
  const [fromTaskId, setFromTaskId] = useState("");
  const [toTaskId, setToTaskId] = useState("");
  const [dimensions, setDimensions] = useState("");
  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [refreshNonce, setRefreshNonce] = useState(0);
  useEffect(() => {
    if (!open) {
      setQuantity("");
      setFromTaskId("");
      setToTaskId("");
      setDimensions("");
      setPreview(null);
      setConfirming(false);
    }
  }, [open]);

  if (!action) return null;

  const buildChanges = (): Record<string, unknown> => {
    const changes: Record<string, unknown> = {};
    if (quantity.trim()) changes.quantity = quantity.trim();
    if (fromTaskId.trim()) changes.from_task_id = Number(fromTaskId.trim());
    if (toTaskId.trim()) changes.to_task_id = Number(toTaskId.trim());
    if (dimensions.trim()) {
      try {
        changes.dimensions = JSON.parse(dimensions);
      } catch {
        changes.dimensions = dimensions.trim();
      }
    }
    return changes;
  };

  const handlePreview = async () => {
    setLoading(true);
    try {
      const data = await previewAmend(action.id, buildChanges(), false);
      setPreview(data);
    } catch (err) {
      toast({
        variant: "destructive",
        title: parseReversalError(err).message || "Ошибка предпросмотра",
      });
    } finally {
      setLoading(false);
    }
  };

  const handleConfirm = async () => {
    if (!preview?.plan_token) return;
    setConfirming(true);
    try {
      const result = await amendAction(action.id, {
        plan_token: preview.plan_token,
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.actions.all });
      toast({
        variant: "success",
        title: "Действие изменено",
        description: `Создано новое действие #${result.new_action_id}`,
      });
      onOpenChange(false);
      onAmended?.();
    } catch (err) {
      const info = parseReversalError(err);
      if (classifyReversalConflict(info) === "stale-token") {
        toast({
          variant: "destructive",
          title: STALE_TOKEN_TOAST_TITLE,
        });
        void handlePreview();
      } else {
        toast({ variant: "destructive", title: info.message || "Ошибка изменения" });
      }
    } finally {
      setConfirming(false);
    }
  };

  const blocked =
    !preview || preview.blockers.length > 0 || !preview?.plan_token;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl" data-testid="amend-dialog">
        <DialogHeader>
          <DialogTitle>
            Изменить действие #{action.id} (transfer_send)
          </DialogTitle>
          <DialogDescription>
            Изменение выполняется компенсацией: старое действие отменится,
            создастся новое. Preview-first — сначала предпросмотр.
          </DialogDescription>
        </DialogHeader>

        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1">
            <label htmlFor="amend-quantity" className="text-sm font-medium text-slate-700">Количество</label>
            <Input
              id="amend-quantity"
              data-testid="amend-quantity"
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
              placeholder="напр. 5"
            />
          </div>
          <div className="space-y-1">
            <label htmlFor="amend-dimensions" className="text-sm font-medium text-slate-700">Габариты (JSON)</label>
            <Input
              id="amend-dimensions"
              data-testid="amend-dimensions"
              value={dimensions}
              onChange={(e) => setDimensions(e.target.value)}
              placeholder='{"length_mm": 1200}'
            />
          </div>
          <div className="space-y-1">
            <label htmlFor="amend-from" className="text-sm font-medium text-slate-700">Из задачи (from_task_id)</label>
            <Input
              id="amend-from"
              data-testid="amend-from-task"
              value={fromTaskId}
              onChange={(e) => setFromTaskId(e.target.value)}
              placeholder="ID задачи-источника"
            />
          </div>
          <div className="space-y-1">
            <label htmlFor="amend-to" className="text-sm font-medium text-slate-700">В задачу (to_task_id)</label>
            <Input
              id="amend-to"
              data-testid="amend-to-task"
              value={toTaskId}
              onChange={(e) => setToTaskId(e.target.value)}
              placeholder="ID задачи-приёмника"
            />
          </div>
        </div>

        {preview && (
          <div className="mt-2">
            <PreviewZones
              revert={preview.revert}
              stays={preview.stays}
              blockers={preview.blockers}
            />
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Закрыть
          </Button>
          {!preview ? (
            <Button
              onClick={handlePreview}
              disabled={loading}
              data-testid="amend-preview"
            >
              {loading ? "Загрузка…" : "Предпросмотр"}
            </Button>
          ) : (
            <Button
              data-testid="amend-confirm"
              disabled={blocked || confirming}
              onClick={handleConfirm}
            >
              {confirming ? "Изменение…" : "Изменить"}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
