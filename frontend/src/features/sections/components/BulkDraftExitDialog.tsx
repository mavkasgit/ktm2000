/**
 * Выход из массового ввода с непустым черновиком (#283).
 *
 * Черновик живёт в состоянии страницы и покидает её вместе с режимом: выход по
 * Escape, тумблер «Групповые операции» и переключение участка теряли бы
 * набранное молча. Правило решения: при непустом черновике выход — через
 * подтверждение; пустой черновик ничего не спрашивает.
 */

import { Button, Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/shared/ui";
import { DIALOG_SIZES } from "@/shared/lib/dialogSizes";
import { cn } from "@/shared/utils/cn";
import { fmtQty } from "@/shared/lib/quantityFormat";

export type BulkDraftExitDialogProps = {
  open: boolean;
  /** Что теряется: сколько заданий и сколько в них введено. */
  summary: { tasks: number; good: number; defect: number };
  onCancel: () => void;
  onConfirm: () => void;
};

export function BulkDraftExitDialog({ open, summary, onCancel, onConfirm }: BulkDraftExitDialogProps) {
  return (
    <Dialog open={open} onOpenChange={(next) => (next ? undefined : onCancel())}>
      <DialogContent className={cn(DIALOG_SIZES.sm.width, DIALOG_SIZES.sm.height)}>
        <DialogHeader>
          <DialogTitle>Сбросить введённое количество?</DialogTitle>
          <DialogDescription>
            В черновике {summary.tasks} заданий: годные {fmtQty(summary.good)}, брак {fmtQty(summary.defect)}.
            Введённое не будет записано.
          </DialogDescription>
        </DialogHeader>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="outline" onClick={onCancel}>
            Остаться
          </Button>
          <Button variant="destructive" onClick={onConfirm}>
            Сбросить
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
