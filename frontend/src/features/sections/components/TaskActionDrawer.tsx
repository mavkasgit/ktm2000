import type { Dispatch, SetStateAction } from "react";
import { AlertTriangle } from "lucide-react";
import { cn } from "@/shared/utils/cn";

import type { SectionBoardTask } from "@/shared/api/shopfloor";
import {
  Badge,
  Button,
  Checkbox,
  DatePicker,
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
  return String(Math.round(n));
}

function toNumber(value: string): number {
  const n = parseFloat(value);
  return Number.isFinite(n) ? Math.round(n) : 0;
}

function normalizeIntegerInput(value: string): string {
  const digits = value.replace(/[^\d]/g, "");
  if (!digits) return "";
  return String(parseInt(digits, 10));
}

function inWorkQuantity(task: SectionBoardTask | null): number {
  if (!task) return 0;
  return toNumber(task.cache.in_work_quantity);
}

type TaskActionDrawerProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  task: SectionBoardTask | null;
  tasks?: SectionBoardTask[] | null;
  actionQty: string;
  setActionQty: Dispatch<SetStateAction<string>>;
  defectQty: string;
  setDefectQty: Dispatch<SetStateAction<string>>;
  performedDate: string;
  setPerformedDate: Dispatch<SetStateAction<string>>;
  performedShift: "1" | "2";
  setPerformedShift: Dispatch<SetStateAction<"1" | "2">>;
  actionComment: string;
  setActionComment: Dispatch<SetStateAction<string>>;
  pending: boolean;
  conflictHint: string | null;
  onSubmit: () => void;
};

export function TaskActionDrawer({
  open,
  onOpenChange,
  task,
  tasks,
  actionQty,
  setActionQty,
  defectQty,
  setDefectQty,
  performedDate,
  setPerformedDate,
  performedShift,
  setPerformedShift,
  actionComment,
  setActionComment,
  pending,
  conflictHint,
  onSubmit,
}: TaskActionDrawerProps) {
  const isGroup = !!tasks && tasks.length > 0;

  const maxQty = isGroup
    ? tasks.reduce((sum, t) => sum + Math.max(0, Math.round(parseFloat(t.cache.in_work_quantity) || 0)), 0)
    : inWorkQuantity(task);

  const plannedQty = isGroup
    ? tasks.reduce((sum, t) => sum + Math.max(0, Math.round(parseFloat(t.planned_quantity) || 0)), 0)
    : (task ? Math.round(parseFloat(task.planned_quantity) || 0) : 0);

  const completedQty = isGroup
    ? tasks.reduce((sum, t) => sum + Math.max(0, Math.round(parseFloat(t.cache.completed_quantity) || 0)), 0)
    : (task ? Math.round(parseFloat(task.cache.completed_quantity) || 0) : 0);

  const rejectedQty = isGroup
    ? tasks.reduce((sum, t) => sum + Math.max(0, Math.round(parseFloat(t.cache.rejected_quantity) || 0)), 0)
    : (task ? Math.round(parseFloat(task.cache.rejected_quantity) || 0) : 0);

  const qtyNum = toNumber(actionQty);
  const defectNum = toNumber(defectQty);
  const outOfRange = qtyNum > 0 && maxQty > 0 && qtyNum + defectNum > maxQty;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="!left-auto !right-0 !top-0 !translate-x-0 !translate-y-0 h-screen max-h-screen w-[min(100vw,560px)] max-w-none rounded-none border-l p-0 flex flex-col gap-0">
        <div className="p-6 border-b">
          <DialogHeader>
            <DialogTitle>{isGroup ? "Завершить группу" : "Внести факт"}</DialogTitle>
            <DialogDescription>
              {isGroup
                ? `${tasks[0]?.product_sku || ""} · ${tasks[0]?.operation_name || "—"} · ${tasks.length} заданий`
                : `${task?.operation_name || "—"} — Этап #${task?.sequence}`
              }
            </DialogDescription>
          </DialogHeader>
        </div>

        <div className="flex-1 overflow-auto p-6 space-y-4">
          {(task || isGroup) && (
            <div className="rounded-lg border bg-muted/20 p-3 text-xs">
              <div className="flex flex-row flex-wrap gap-x-4 gap-y-1">
                <div>В работе: <span className="font-medium">{maxQty}</span></div>
                <div>Годные: <span className="font-medium">{completedQty}</span></div>
                <div>Брак: <span className="font-medium">{rejectedQty}</span></div>
              </div>
              {!isGroup && task && task.operation_names && task.operation_names.length > 1 && (
                <div className="mt-2">
                  <Badge variant="secondary">Будет выполнено: {task.operation_names.join(" + ")}</Badge>
                </div>
              )}
            </div>
          )}

          {conflictHint && (
            <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-800">
              <div className="flex items-start gap-2">
                <AlertTriangle className="h-4 w-4 mt-0.5" />
                <span>{conflictHint}</span>
              </div>
            </div>
          )}

          <div className="flex flex-row flex-wrap items-end gap-3">
            <div className="flex flex-col gap-1.5">
              <label className="text-sm font-medium">Факт (годные)</label>
              <Input
                type="number"
                step="1"
                min="0"
                value={actionQty}
                onChange={(e) => setActionQty(normalizeIntegerInput(e.target.value))}
                className="w-[150px] h-8"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <label className="text-sm font-medium">Брак</label>
              <Input
                type="number"
                step="1"
                min="0"
                value={defectQty}
                onChange={(e) => setDefectQty(normalizeIntegerInput(e.target.value))}
                className="w-[150px] h-8"
              />
            </div>
          </div>
          {outOfRange && (
            <div className="mt-1 text-xs text-red-600">
              Сумма факта и брака больше объема в работе: {maxQty}
            </div>
          )}

          <div className="flex flex-row flex-wrap gap-2">
            {(task || isGroup) && (
              <Button
                type="button"
                variant="outline"
                onClick={() => setActionQty(String(plannedQty))}
                className="shrink-0 w-[150px] h-8"
              >
                Плановое ({plannedQty})
              </Button>
            )}
            <Button
              type="button"
              variant="outline"
              onClick={() => setActionQty(maxQty > 0 ? String(maxQty) : "0")}
              className="shrink-0 w-[150px] h-8"
            >
              Максимальное ({maxQty})
            </Button>
          </div>

          <div className="flex flex-row gap-4 items-end">
            <DatePicker
              value={performedDate}
              onChange={setPerformedDate}
              label="Дата"
            />
            <div className="flex flex-col gap-1.5">
              <span className="text-sm font-medium">Смена</span>
              <div className="flex gap-1 bg-muted p-0.5 rounded-md h-8 items-center">
                <button
                  type="button"
                  onClick={() => setPerformedShift("1")}
                  className={cn(
                    "px-3 h-7 text-sm font-medium rounded transition-all flex items-center justify-center",
                    performedShift === "1"
                      ? "bg-background text-foreground shadow-sm"
                      : "text-muted-foreground hover:text-foreground"
                  )}
                >
                  1-я
                </button>
                <button
                  type="button"
                  onClick={() => setPerformedShift("2")}
                  className={cn(
                    "px-3 h-7 text-sm font-medium rounded transition-all flex items-center justify-center",
                    performedShift === "2"
                      ? "bg-background text-foreground shadow-sm"
                      : "text-muted-foreground hover:text-foreground"
                  )}
                >
                  2-я
                </button>
              </div>
            </div>
          </div>

          <div>
            <label className="text-sm font-medium">Комментарий</label>
            <Input value={actionComment} onChange={(e) => setActionComment(e.target.value)} placeholder="Опционально" />
          </div>
        </div>

        <div className="border-t p-4 flex justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Отмена
          </Button>
          <Button onClick={onSubmit} disabled={pending}>
            {pending ? "Сохранение..." : "Сохранить"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
