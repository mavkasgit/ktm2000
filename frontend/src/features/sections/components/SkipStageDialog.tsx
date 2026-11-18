/**
 * components/SkipStageDialog.tsx
 * ==============================
 * Ручной пропуск этапа (#348): этап закрывается знаком «Пропущено», причина
 * обязательна.
 *
 * Пропуск — не выполнение и не отмена: факта по этапу не было, проводок ledger
 * не создаётся, а в карточке позиции остаётся причина. Поэтому пустое поле не
 * отправляется: «почему работы не было» — часть факта, а не украшение.
 *
 * Список готовых причин (из тикета #348) — кнопки-заготовки, а не выбор без
 * права правки: любую можно переписать своим текстом. Право на действие
 * проверяет сервер; кнопка на доске показывается только ролям из
 * `POLICIES.skipStage`.
 */

import { useEffect, useState } from "react";
import type { SectionBoardTask } from "@/shared/api/shopfloor";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/shared/ui";

/** Готовые причины из #348: чаще всего этап пропускают именно поэтому. */
const SKIP_REASON_PRESETS = [
  "Материал подан в готовом виде",
  "Работу сделал другой участок",
  "Переделка не нужна",
  "Убрали из маршрута",
] as const;

type SkipStageDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  task: SectionBoardTask | null;
  pending: boolean;
  onSubmit: (reason: string) => void;
};

export function SkipStageDialog({
  open,
  onOpenChange,
  task,
  pending,
  onSubmit,
}: SkipStageDialogProps) {
  const [reason, setReason] = useState("");

  // Причина одного этапа не должна достаться другому: поле очищается при
  // закрытии и при смене задания.
  useEffect(() => {
    if (!open) setReason("");
  }, [open, task?.id]);

  const trimmedReason = reason.trim();
  const canSubmit = trimmedReason.length > 0 && !pending;

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!pending) onOpenChange(next);
      }}
    >
      <DialogContent className="w-[min(100vw-2rem,520px)]">
        <DialogHeader>
          <DialogTitle>Пропустить этап</DialogTitle>
          <DialogDescription>
            {task
              ? `${task.operation_name || "Операция"} — Этап #${task.sequence}. ` +
                "Этап закроется без работы: фактов и движений склада не будет."
              : ""}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-2">
          <label htmlFor="skip-stage-reason" className="text-sm font-medium">
            Причина пропуска
          </label>
          <div className="flex flex-wrap gap-1.5">
            {SKIP_REASON_PRESETS.map((preset) => (
              <Button
                key={preset}
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setReason(preset)}
              >
                {preset}
              </Button>
            ))}
          </div>
          <textarea
            id="skip-stage-reason"
            aria-label="Причина пропуска"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            rows={3}
            placeholder="Например: материал подан в готовом виде"
            aria-invalid={trimmedReason.length === 0}
            className="w-full rounded-md border bg-background px-2 py-1 text-sm"
          />
          {trimmedReason.length === 0 && (
            <p className="text-xs text-muted-foreground">
              Без причины пропуск не сохраняется.
            </p>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={pending}>
            Отмена
          </Button>
          <Button onClick={() => onSubmit(trimmedReason)} disabled={!canSubmit} aria-label="Пропустить">
            {pending ? "Сохранение..." : "Пропустить"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
