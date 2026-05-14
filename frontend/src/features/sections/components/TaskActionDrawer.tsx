import type { Dispatch, SetStateAction } from "react";
import { AlertTriangle } from "lucide-react";

import type { SectionBoardTask } from "@/shared/api/shopfloor";
import {
  Badge,
  Button,
  Checkbox,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  Input,
} from "@/shared/ui";

import type { TaskActionDialogType } from "./SectionTasksBoard";

function fmtQty(value: string): string {
  const n = parseFloat(value);
  if (!Number.isFinite(n)) return "0";
  return Number.isInteger(n) ? String(n) : n.toFixed(3).replace(/\.?0+$/, "");
}

function toNumber(value: string): number {
  const n = parseFloat(value);
  return Number.isFinite(n) ? n : 0;
}

function actionTitle(type: TaskActionDialogType): string {
  if (type === "issue") return "Выдать в работу";
  if (type === "send") return "Передать на следующий этап";
  return "Внести факт";
}

function maxQuantity(type: TaskActionDialogType, task: SectionBoardTask | null): number {
  if (!task) return 0;
  if (type === "issue") return toNumber(task.cache.available_quantity);
  if (type === "complete") return toNumber(task.cache.in_work_quantity);
  return Math.max(0, toNumber(task.cache.completed_quantity) - toNumber(task.cache.transferred_quantity));
}

type TaskActionDrawerProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  type: TaskActionDialogType;
  task: SectionBoardTask | null;
  actionQty: string;
  setActionQty: Dispatch<SetStateAction<string>>;
  defectQty: string;
  setDefectQty: Dispatch<SetStateAction<string>>;
  timesMatch: boolean;
  onTimesMatchChange: (checked: boolean) => void;
  performedAt: string;
  onPerformedAtChange: (value: string) => void;
  accountedAt: string;
  setAccountedAt: Dispatch<SetStateAction<string>>;
  actionComment: string;
  setActionComment: Dispatch<SetStateAction<string>>;
  pending: boolean;
  conflictHint: string | null;
  onSubmit: () => void;
};

export function TaskActionDrawer({
  open,
  onOpenChange,
  type,
  task,
  actionQty,
  setActionQty,
  defectQty,
  setDefectQty,
  timesMatch,
  onTimesMatchChange,
  performedAt,
  onPerformedAtChange,
  accountedAt,
  setAccountedAt,
  actionComment,
  setActionComment,
  pending,
  conflictHint,
  onSubmit,
}: TaskActionDrawerProps) {
  const maxQty = maxQuantity(type, task);
  const qtyNum = toNumber(actionQty);
  const outOfRange = qtyNum > 0 && maxQty > 0 && qtyNum > maxQty;

  const presets = [25, 50, 100];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="!left-auto !right-0 !top-0 !translate-x-0 !translate-y-0 h-screen max-h-screen w-[min(100vw,560px)] max-w-none rounded-none border-l p-0 flex flex-col gap-0">
        <div className="p-6 border-b">
          <DialogHeader>
            <DialogTitle>{actionTitle(type)}</DialogTitle>
            <DialogDescription>
              {task?.operation_name || "—"} — Этап #{task?.sequence}
            </DialogDescription>
          </DialogHeader>
        </div>

        <div className="flex-1 overflow-auto p-6 space-y-4">
          {task && (
            <div className="rounded-lg border bg-muted/20 p-3 text-xs">
              <div className="grid grid-cols-2 gap-2">
                <div>Доступно: <span className="font-medium">{fmtQty(task.cache.available_quantity)}</span></div>
                <div>В работе: <span className="font-medium">{fmtQty(task.cache.in_work_quantity)}</span></div>
                <div>Факт: <span className="font-medium">{fmtQty(task.cache.completed_quantity)}</span></div>
                <div>К передаче: <span className="font-medium">{fmtQty(String(maxQuantity("send", task)))}</span></div>
              </div>
              {type === "send" && !task.next_task_id && (
                <div className="mt-2">
                  <Badge variant="destructive">Следующий этап не создан</Badge>
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

          <div>
            <label className="text-sm font-medium">
              {type === "complete" ? "Факт (годные)" : "Количество"}
            </label>
            <Input type="number" step="0.001" value={actionQty} onChange={(e) => setActionQty(e.target.value)} />
            <div className="mt-2 flex flex-wrap gap-1">
              {presets.map((p) => (
                <Button
                  key={p}
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    const val = maxQty > 0 ? ((maxQty * p) / 100).toFixed(3).replace(/\.?0+$/, "") : "0";
                    setActionQty(val);
                  }}
                >
                  {p}%
                </Button>
              ))}
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => setActionQty(maxQty > 0 ? String(maxQty) : "0")}
              >
                Макс
              </Button>
            </div>
            {outOfRange && (
              <div className="mt-1 text-xs text-red-600">
                Количество больше допустимого лимита: {fmtQty(String(maxQty))}
              </div>
            )}
          </div>

          {type === "complete" && (
            <div>
              <label className="text-sm font-medium">Брак</label>
              <Input type="number" step="0.001" value={defectQty} onChange={(e) => setDefectQty(e.target.value)} />
            </div>
          )}

          {type === "send" && (
            <div className="text-xs text-muted-foreground">
              Следующий этап: {task?.next_operation_name || "—"}
            </div>
          )}

          <div>
            <label className="text-sm font-medium">Время сдачи</label>
            <Input type="datetime-local" value={performedAt} onChange={(e) => onPerformedAtChange(e.target.value)} />
          </div>

          <div className="flex items-center gap-2">
            <Checkbox checked={timesMatch} onCheckedChange={(c) => onTimesMatchChange(!!c)} id="times-match-action" />
            <label htmlFor="times-match-action" className="text-sm">Время сдачи = Время учета</label>
          </div>

          <div>
            <label className="text-sm font-medium">Время учета</label>
            <Input type="datetime-local" value={accountedAt} onChange={(e) => setAccountedAt(e.target.value)} disabled={timesMatch} />
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

