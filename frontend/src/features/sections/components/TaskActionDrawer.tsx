import type { Dispatch, SetStateAction } from "react";
import { useEffect } from "react";
import { AlertTriangle } from "lucide-react";
import { cn } from "@/shared/utils/cn";

import type { SectionBoardTask, ShortageStrategy } from "@/shared/api/shopfloor";
import { formatDimensionsLabel } from "@/shared/api/stock";
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
import {
  getReadyStatusLabel,
  isTaskCompletable,
} from "../lib/taskStatus";

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
  // in_work = issued - completed - rejected (cached_in_work_quantity removed; compute inline)
  return Math.max(
    0,
    toNumber(task.cache.issued_quantity) - toNumber(task.cache.completed_quantity) - toNumber(task.cache.rejected_quantity),
  );
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
  shortageStrategy: ShortageStrategy;
  setShortageStrategy: Dispatch<SetStateAction<ShortageStrategy>>;
  autoTransferNext: boolean;
  setAutoTransferNext: Dispatch<SetStateAction<boolean>>;
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
  shortageStrategy,
  setShortageStrategy,
  autoTransferNext,
  setAutoTransferNext,
  pending,
  conflictHint,
  onSubmit,
}: TaskActionDrawerProps) {
  const isGroup = !!tasks && tasks.length > 0;

  // Трансформирующий этап (ADR-0002): факт вводится во входных заготовках,
  // выходы приходуются автоматически пропорционально порции.
  const isTransform =
    !isGroup && !!task?.transforms_dimensions && (task?.outputs?.length ?? 0) > 0;
  const inputQty = isTransform ? toNumber(task?.input_quantity ?? "0") : 0;
  const inputConsumed = isTransform ? toNumber(task?.input_consumed_quantity ?? "0") : 0;
  const inputRejected = isTransform ? toNumber(task?.cache.rejected_quantity ?? "0") : 0;
  const remainingInput = Math.max(0, inputQty - inputConsumed - inputRejected);

  // Авто-передача неприменима к трансформации (выходы разных
  // габаритов) — сбрасываем флаг, чтобы не ушёл в payload.
  useEffect(() => {
    if (isTransform && autoTransferNext) setAutoTransferNext(false);
  }, [isTransform, autoTransferNext, setAutoTransferNext]);

  const maxQty = isTransform
    ? remainingInput
    : isGroup
    ? tasks.reduce(
        (sum, t) =>
          sum +
          Math.max(
            0,
            Math.round(parseFloat(t.cache.issued_quantity) || 0) -
              Math.round(parseFloat(t.cache.completed_quantity) || 0) -
              Math.round(parseFloat(t.cache.rejected_quantity) || 0),
          ),
        0,
      )
    : inWorkQuantity(task);

  const available = isGroup
    ? tasks.reduce((sum, t) => sum + Math.max(0, Math.round(parseFloat(t.cache.available_quantity) || 0)), 0)
    : (task ? Math.round(parseFloat(task.cache.available_quantity) || 0) : 0);

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

  const factTotal = qtyNum + defectNum;
  // Для трансформации лимит — остаток входа, стратегии дефицита неприменимы.
  const hasShortage = !isTransform && factTotal > maxQty + available;

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
                {isTransform ? (
                  <>
                    <div>
                      Вход:{" "}
                      <span className="font-medium">
                        {inputQty} × {formatDimensionsLabel(task?.input_dimensions)}
                      </span>
                    </div>
                    <div>Раскроено: <span className="font-medium">{inputConsumed}</span></div>
                    <div>Брак: <span className="font-medium">{inputRejected}</span></div>
                    <div>Осталось: <span className="font-medium">{remainingInput}</span></div>
                  </>
                ) : (
                  <>
                    <div>В работе: <span className="font-medium">{maxQty}</span></div>
                    <div>Годные: <span className="font-medium">{completedQty}</span></div>
                    <div>Брак: <span className="font-medium">{rejectedQty}</span></div>
                  </>
                )}
              </div>
              {!isGroup && task && task.operation_names && task.operation_names.length > 1 && (
                <div className="mt-2">
                  <Badge variant="secondary">Будет выполнено: {task.operation_names.join(" + ")}</Badge>
                </div>
              )}
            </div>
          )}

          {isTransform && !!task?.outputs_progress?.length && (
            <div className="rounded-lg border p-3 space-y-2">
              <div className="text-sm font-medium">Прогресс по выходам</div>
              {task.outputs_progress.map((row, idx) => {
                const totalQty = parseFloat(row.quantity) || 0;
                const producedQty = parseFloat(row.produced_quantity) || 0;
                const pct = totalQty > 0
                  ? Math.min(100, Math.round((producedQty / totalQty) * 100))
                  : 0;
                return (
                  <div key={row.row_number ?? idx} className="space-y-1">
                    <div className="flex justify-between text-xs">
                      <span>{formatDimensionsLabel(row.dimensions)}</span>
                      <span className="tabular-nums text-muted-foreground">
                        {fmtQty(row.produced_quantity)} / {fmtQty(row.quantity)}
                      </span>
                    </div>
                    <div className="h-1.5 rounded bg-muted overflow-hidden">
                      <div className="h-full bg-primary" style={{ width: `${pct}%` }} />
                    </div>
                  </div>
                );
              })}
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

          {isGroup && tasks && tasks.some((t) => !isTaskCompletable(t)) && (() => {
            const notTransferred = tasks.filter(
              (t) => t.status === "ready" && getReadyStatusLabel(t) === "Не передано",
            );
            const other = tasks.filter(
              (t) => !isTaskCompletable(t) && !(t.status === "ready" && getReadyStatusLabel(t) === "Не передано"),
            );
            const total = notTransferred.length + other.length;
            return (
              <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-800">
                <div className="flex items-start gap-2">
                  <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
                  <div className="flex-1">
                    <div className="font-medium">
                      {total} из {tasks.length} задач будут пропущены
                    </div>
                    {notTransferred.length > 0 && (
                      <div className="mt-1 text-xs">
                        <span className="font-semibold">«Не передано» ({notTransferred.length}):</span>{" "}
                        {Array.from(new Set(notTransferred.map((t) => t.product_sku)))
                          .slice(0, 5)
                          .join(", ")}
                        {notTransferred.length > 5 ? "…" : ""} — сырьё с предыдущего участка ещё не поступило.
                      </div>
                    )}
                    {other.length > 0 && (
                      <div className="mt-1 text-xs">
                        <span className="font-semibold">Прочие ({other.length}):</span>{" "}
                        ожидают сырья или уже завершены.
                      </div>
                    )}
                  </div>
                </div>
              </div>
            );
          })()}

          <div className="flex flex-row flex-wrap items-end gap-3">
            <div className="flex flex-col gap-1.5">
              <label className="text-sm font-medium">
                {isTransform ? "Факт (раскроено заготовок)" : "Факт (годные)"}
              </label>
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
              <label className="text-sm font-medium">
                {isTransform ? "Брак (заготовок)" : "Брак"}
              </label>
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
              {isTransform
                ? `Сумма факта и брака больше остатка входа: ${maxQty}`
                : `Сумма факта и брака больше объема в работе: ${maxQty}`}
            </div>
          )}

          <div className="flex flex-row flex-wrap gap-2">
            {(task || isGroup) && (
              <Button
                type="button"
                variant="outline"
                onClick={() => setActionQty(String(isTransform ? inputQty : plannedQty))}
                className="shrink-0 w-[150px] h-8"
              >
                Плановое ({isTransform ? inputQty : plannedQty})
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

          {hasShortage && (
            <div className="rounded-lg border border-amber-300 bg-amber-50/50 p-4 space-y-3">
              <div className="text-sm font-medium text-amber-800 flex items-center gap-2">
                <AlertTriangle className="h-4 w-4 shrink-0" />
                <span>Превышение доступного материала</span>
              </div>
              <p className="text-xs text-amber-700">
                Фактический объем ({factTotal}) превышает доступный лимит ({maxQty + available}). Выберите действие:
              </p>
              <div className="space-y-1">
                <p className="text-[11px] font-medium text-slate-700">Что делать с излишком ({factTotal - (maxQty + available)} шт.)?</p>
              </div>
              <div className="grid grid-cols-1 gap-2 pt-1">
                <button
                  type="button"
                  onClick={() => setShortageStrategy("negative_remainder")}
                  className={cn(
                    "flex flex-col text-left p-3 rounded-lg border text-xs font-medium transition-all hover:bg-muted/50",
                    shortageStrategy === "negative_remainder"
                      ? "bg-background border-amber-500 shadow-sm ring-1 ring-amber-500"
                      : "bg-background/50 border-slate-200"
                  )}
                >
                  <span className="font-semibold text-slate-800">В scrap (списать в брак)</span>
                  <span className="text-muted-foreground text-[10px] mt-0.5">Завершить операцию, записав излишек (-{factTotal - (maxQty + available)} шт) как дефицит (списание). Рекомендуется, если излишек — брак.</span>
                </button>
                <button
                  type="button"
                  onClick={() => setShortageStrategy("partial")}
                  className={cn(
                    "flex flex-col text-left p-3 rounded-lg border text-xs font-medium transition-all hover:bg-muted/50",
                    shortageStrategy === "partial"
                      ? "bg-background border-amber-500 shadow-sm ring-1 ring-amber-500"
                      : "bg-background/50 border-slate-200"
                  )}
                >
                  <span className="font-semibold text-slate-800">Частичное принятие (только доступное)</span>
                  <span className="text-muted-foreground text-[10px] mt-0.5">Завершить только доступные детали ({maxQty + available} шт). Излишек ({factTotal - (maxQty + available)} шт) останется неучтённым.</span>
                </button>
                <button
                  type="button"
                  onClick={() => setShortageStrategy("fail")}
                  className={cn(
                    "flex flex-col text-left p-3 rounded-lg border text-xs font-medium transition-all hover:bg-muted/50",
                    shortageStrategy === "fail"
                      ? "bg-background border-amber-500 shadow-sm ring-1 ring-amber-500"
                      : "bg-background/50 border-slate-200"
                  )}
                >
                  <span className="font-semibold text-slate-800">Отмена операции</span>
                  <span className="text-muted-foreground text-[10px] mt-0.5">Блокировать операцию и вернуть ошибку о нехватке материалов. Ничего не будет сохранено.</span>
                </button>
              </div>
            </div>
          )}

          <div>
            <label className="text-sm font-medium">Комментарий</label>
            <Input value={actionComment} onChange={(e) => setActionComment(e.target.value)} placeholder="Опционально" />
          </div>

          {!isTransform && (
            <label className="flex items-start gap-2 cursor-pointer select-none rounded-md border border-slate-200 bg-slate-50/50 p-3 hover:bg-slate-50">
              <Checkbox
                checked={autoTransferNext}
                onCheckedChange={(v) => setAutoTransferNext(Boolean(v))}
                className="mt-0.5"
              />
              <div className="flex-1">
                <div className="text-sm font-medium">Сразу отправить на следующий участок</div>
                <div className="text-xs text-muted-foreground mt-0.5">
                  Создаст запись в «Передачах» на нужное количество годных.
                  Снимите, если хотите управлять перемещением вручную.
                </div>
              </div>
            </label>
          )}
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
