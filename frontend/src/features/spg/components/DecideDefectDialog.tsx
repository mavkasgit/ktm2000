import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  Button,
  Input,
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from "@/shared/ui";
import type { DefectOut } from "@/shared/api/defects";
import { defectDecide } from "@/shared/api/defects";
import { queryKeys } from "@/shared/api/queryKeys";

interface DecideDefectDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  defect: DefectOut | null;
  spgId?: number;
  onSaved: () => void;
}

export function DecideDefectDialog({
  open,
  onOpenChange,
  defect,
  spgId,
  onSaved,
}: DecideDefectDialogProps) {
  const queryClient = useQueryClient();
  const [decisionType, setDecisionType] = useState("scrap");
  const [quantity, setQuantity] = useState("");
  const [comment, setComment] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open && defect) {
      setDecisionType("scrap");
      setQuantity(String(defect.total_quantity));
      setComment("");
      setError(null);
    }
  }, [open, defect]);

  const saveMutation = useMutation({
    mutationFn: () =>
      defectDecide(defect!.id, {
        decision_type: decisionType,
        quantity: parseFloat(quantity),
        comment: comment || undefined,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.spg.defects(spgId ?? -1) });
      if (spgId != null) {
        void queryClient.invalidateQueries({ queryKey: queryKeys.spg.snapshot(spgId) });
        void queryClient.invalidateQueries({ queryKey: queryKeys.spg.remainders(spgId) });
      }
      onSaved();
      onOpenChange(false);
    },
    onError: (e: unknown) => {
      const msg = e && typeof e === "object" && "response" in e
        ? (e as { response?: { data?: { detail?: string } } }).response?.data?.detail
        : undefined;
      setError((msg as string | undefined) || "Ошибка при принятии решения");
    },
  });

  const handleSave = () => {
    if (!defect) return;

    const qty = parseFloat(quantity);
    if (isNaN(qty) || qty <= 0) {
      setError("Количество должно быть положительным числом");
      return;
    }

    if (qty > defect.total_quantity) {
      setError(`Количество в решении (${qty}) не может превышать объем дефекта (${defect.total_quantity})`);
      return;
    }
    setError(null);
    saveMutation.mutate();
  };

  if (!defect) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[400px]">
        <DialogHeader>
          <DialogTitle>Принятие решения по браку #{defect.id}</DialogTitle>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <div className="text-sm border-b pb-2">
            <div>
              <span className="font-semibold text-muted-foreground">Продукт:</span>{" "}
              {defect.product_sku} — {defect.product_name}
            </div>
            <div>
              <span className="font-semibold text-muted-foreground">Количество брака:</span>{" "}
              {defect.total_quantity} шт.
            </div>
            {defect.reason && (
              <div>
                <span className="font-semibold text-muted-foreground">Причина:</span> {defect.reason}
              </div>
            )}
          </div>

          {/* Decision Type */}
          <div className="space-y-1">
            <label className="text-sm font-medium">Решение</label>
            <Select
              value={decisionType}
              onValueChange={setDecisionType}
            >
              <SelectTrigger className="w-full h-10 text-sm bg-background">
                <SelectValue placeholder="Выберите решение" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="scrap">Списать брак</SelectItem>
                <SelectItem value="accept_with_deviation">Одобрить брак как годный</SelectItem>
                {defect?.task_id && (
                  <SelectItem value="rework_current">Направить на переделку</SelectItem>
                )}
                <SelectItem value="hold">Временное хранение</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Quantity */}
          <div className="space-y-1">
            <label className="text-sm font-medium">Количество для решения</label>
            <Input
              type="number"
              min="0"
              max={defect.total_quantity}
              step="any"
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
            />
          </div>

          {/* Comment */}
          <div className="space-y-1">
            <label className="text-sm font-medium">Комментарий / Обоснование</label>
            <textarea
              className="w-full min-h-[60px] rounded-md border px-3 py-2 text-sm bg-background resize-none focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder="Введите пояснение к решению..."
            />
          </div>

          {error && <div className="text-sm text-destructive font-medium bg-destructive/10 p-2 rounded">{error}</div>}

          <div className="flex justify-end gap-2 pt-2 border-t">
            <Button variant="outline" onClick={() => onOpenChange(false)}>
              Отмена
            </Button>
            <Button onClick={handleSave} disabled={saveMutation.isPending}>
              {saveMutation.isPending ? "Сохранение..." : "Применить решение"}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
