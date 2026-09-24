import { useEffect, useState } from "react";

import type { SectionBoardTask } from "@/shared/api/shopfloor";
import {
  Button,
  Checkbox,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
} from "@/shared/ui";

type DailyPlanCreateDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  candidates: SectionBoardTask[];
  isLoadingCandidates: boolean;
  candidatesErrorMessage?: string | null;
  isSaving: boolean;
  errorMessage?: string | null;
  onCreate: (input: { plan_date: string; work_task_ids: number[] }) => void;
};

function localToday(): string {
  const date = new Date();
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

export function DailyPlanCreateDialog({
  open,
  onOpenChange,
  candidates,
  isLoadingCandidates,
  candidatesErrorMessage,
  isSaving,
  errorMessage,
  onCreate,
}: DailyPlanCreateDialogProps) {
  const [planDate, setPlanDate] = useState(localToday);
  const [selectedTaskIds, setSelectedTaskIds] = useState<Set<number>>(new Set());

  useEffect(() => {
    if (!open) return;
    setPlanDate(localToday());
    setSelectedTaskIds(new Set());
  }, [open]);

  const toggleTask = (taskId: number, checked: boolean) => {
    setSelectedTaskIds((current) => {
      const next = new Set(current);
      if (checked) next.add(taskId);
      else next.delete(taskId);
      return next;
    });
  };

  const canCreate =
    planDate.length > 0 &&
    selectedTaskIds.size > 0 &&
    !isSaving &&
    !isLoadingCandidates &&
    !candidatesErrorMessage;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] max-w-2xl overflow-hidden">
        <DialogHeader>
          <DialogTitle>Создать дневной план</DialogTitle>
          <DialogDescription>
            Выберите дату и активные задания участка. Состав плана можно будет изменить отдельно.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 overflow-y-auto">
          <label className="block space-y-1.5 text-sm font-medium">
            Дата плана
            <Input
              type="date"
              value={planDate}
              onChange={(event) => setPlanDate(event.target.value)}
              disabled={isSaving}
            />
          </label>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium">Задания</span>
              <span className="text-xs text-muted-foreground">Выбрано: {selectedTaskIds.size}</span>
            </div>
            <div className="max-h-72 divide-y overflow-y-auto rounded-md border">
              {isLoadingCandidates ? (
                <p className="p-4 text-sm text-muted-foreground">Загрузка заданий…</p>
              ) : candidatesErrorMessage ? (
                <p className="p-4 text-sm text-destructive">{candidatesErrorMessage}</p>
              ) : candidates.length === 0 ? (
                <p className="p-4 text-sm text-muted-foreground">Нет активных заданий для плана.</p>
              ) : (
                candidates.map((task) => (
                  <label key={task.id} className="flex cursor-pointer items-center gap-3 p-3 hover:bg-slate-50">
                    <Checkbox
                      checked={selectedTaskIds.has(task.id)}
                      onCheckedChange={(checked) => toggleTask(task.id, checked === true)}
                      disabled={isSaving}
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block text-sm font-medium">{task.display_sku || task.product_sku}</span>
                      <span className="block text-xs text-muted-foreground">
                        #{task.id} · {task.operation_name || "Без операции"} · {task.status}
                      </span>
                    </span>
                  </label>
                ))
              )}
            </div>
          </div>

          {errorMessage && <p className="text-sm text-destructive">{errorMessage}</p>}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isSaving}>
            Отмена
          </Button>
          <Button
            onClick={() => onCreate({ plan_date: planDate, work_task_ids: [...selectedTaskIds] })}
            disabled={!canCreate}
          >
            {isSaving ? "Создание…" : "Создать план"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
