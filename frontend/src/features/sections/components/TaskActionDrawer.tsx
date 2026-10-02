import { useState, type Dispatch, type SetStateAction } from "react";
import { AlertTriangle } from "lucide-react";
import { cn } from "@/shared/utils/cn";
import { parseNumericInput } from "@/shared/lib/parseNumericInput";
import { normalizeQuantityInput, parseQuantityInput, type QuantityInputIssue } from "@/shared/lib/quantityInput";
import { resolveFactQuantity } from "../lib/factQuantity";
import { actionReasonText } from "@/shared/lib/actionReasons";
import { groupTasksByBlockReason, isTaskCompletable } from "../lib/taskStatus";

import type { SectionBoardTask, ShortageStrategy } from "@/shared/api/shopfloor";
import { formatDimensionsLabel } from "@/shared/api/stock";
import {
  Badge,
  Button,
  DatePicker,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  Input,
} from "@/shared/ui";
import { fmtQty } from "@/shared/lib/quantityFormat";

function toNumber(value: string): number {
  const n = parseNumericInput(value);
  return n == null ? 0 : Math.round(n);
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
  /**
   * Задания группы: диалог отвечает за группу целиком — ввод «Факт/Брак» здесь
   * цель группы, а раскладывает её по строкам страница (`applyGroupField`).
   * Пусто — диалог одиночного завершения.
   */
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
  pending,
  conflictHint,
  onSubmit,
}: TaskActionDrawerProps) {
  // Причина отклонённого ввода под полем (ADR-0032). Недопустимый символ не
  // подставляется в значение: поле остаётся с тем, что было, и показывает
  // причину, пока значение снова не станет допустимым.
  const [issue, setIssue] = useState<QuantityInputIssue | null>(null);

  const handleQtyChange = (value: string, setValue: Dispatch<SetStateAction<string>>) => {
    const result = normalizeQuantityInput(value);
    setIssue(result.issue);
    if (!result.issue) setValue(result.value);
  };
  // Групповой режим: «Завершить группу» из шапки блока. Числа диалога —
  // суммы по строкам группы, а раскладка набранного по строкам — дело страницы
  // (там же живёт домен черновика, `applyGroupField`).
  const groupTasks = tasks ?? [];
  const isGroup = groupTasks.length > 0;

  // Трансформирующий этап (ADR-0002): факт вводится во входных заготовках,
  // выходы приходуются автоматически пропорционально порции. У группы строк с
  // разными входами такого перевода нет — она завершается как обычная.
  const isTransform =
    !isGroup && !!task?.transforms_dimensions && (task?.outputs?.length ?? 0) > 0;
  const inputQty = isTransform ? toNumber(task?.input_quantity ?? "0") : 0;
  const inputConsumed = isTransform ? toNumber(task?.input_consumed_quantity ?? "0") : 0;
  const inputRejected = isTransform ? toNumber(task?.cache.rejected_quantity ?? "0") : 0;
  const remainingInput = Math.max(0, inputQty - inputConsumed - inputRejected);

  const sumOverGroup = (pick: (groupTask: SectionBoardTask) => string | number | null | undefined) =>
    Math.round(groupTasks.reduce((sum, groupTask) => sum + toNumber(String(pick(groupTask) ?? 0)), 0));

  const maxQty = isTransform
    ? remainingInput
    : isGroup
      ? groupTasks.reduce((sum, groupTask) => sum + inWorkQuantity(groupTask), 0)
      : inWorkQuantity(task);

  const available = isGroup
    ? sumOverGroup((groupTask) => groupTask.cache.available_quantity)
    : task
      ? Math.round(parseFloat(task.cache.available_quantity) || 0)
      : 0;

  const plannedQty = isGroup
    ? sumOverGroup((groupTask) => groupTask.planned_quantity)
    : task
      ? Math.round(parseFloat(task.planned_quantity) || 0)
      : 0;

  const completedQty = isGroup
    ? sumOverGroup((groupTask) => groupTask.cache.completed_quantity)
    : task
      ? Math.round(parseFloat(task.cache.completed_quantity) || 0)
      : 0;

  const rejectedQty = isGroup
    ? sumOverGroup((groupTask) => groupTask.cache.rejected_quantity)
    : task
      ? Math.round(parseFloat(task.cache.rejected_quantity) || 0)
      : 0;

  // Записанный факт колонки: у раскроя «годные» — это раскроенные заготовки
  // входа (ADR-0002), у остальных — записанные годные.
  const recordedGood = isTransform ? inputConsumed : completedQty;
  const recordedDefect = rejectedQty;

  // Ввод в двух режимах: «+100» — добавить, «500» — факт станет 500. Дальше
  // всюду порция, а не набранное число: на сервер уходит порция, и лимиты
  // считаются по ней.
  const goodResolution = resolveFactQuantity(actionQty, recordedGood);
  const defectResolution = resolveFactQuantity(defectQty, recordedDefect);
  const goodIssue =
    goodResolution.kind === "invalid" ? actionReasonText(goodResolution.reason) : null;
  const defectIssue =
    defectResolution.kind === "invalid" ? actionReasonText(defectResolution.reason) : null;
  const qtyNum = goodResolution.kind === "write" ? goodResolution.quantity : 0;
  const defectNum = defectResolution.kind === "write" ? defectResolution.quantity : 0;
  const outOfRange = qtyNum + defectNum > 0 && maxQty > 0 && qtyNum + defectNum > maxQty;

  const factTotal = qtyNum + defectNum;
  // Для трансформации лимит — остаток входа, стратегии дефицита неприменимы.
  const hasShortage = !isTransform && factTotal > maxQty + available;

  // Кнопки заполняют поле в том режиме, в котором оно набрано: «+N» — добавить,
  // «N» — факт станет N. Иначе «Плановое» в режиме добавки записало бы план как
  // добавку и удвоило факт.
  const plannedTarget = isTransform ? inputQty : plannedQty;
  const addMode = parseQuantityInput(actionQty).mode === "add";
  const plannedFill = addMode
    ? `+${Math.max(0, plannedTarget - recordedGood)}`
    : String(plannedTarget);
  const maxFill = addMode ? `+${maxQty}` : String(recordedGood + maxQty);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="!left-auto !right-0 !top-0 !translate-x-0 !translate-y-0 h-screen max-h-screen w-[min(100vw,560px)] max-w-none rounded-none border-l p-0 flex flex-col gap-0">
        <div className="p-6 border-b">
          <DialogHeader>
            <DialogTitle>{isGroup ? "Завершить группу" : "Внести факт"}</DialogTitle>
            <DialogDescription>
              {isGroup
                ? `${groupTasks[0]?.product_sku || ""} · ${groupTasks[0]?.operation_name || "—"} · ${groupTasks.length} заданий`
                : `${task?.operation_name || "—"} — Этап #${task?.sequence}`}
            </DialogDescription>
          </DialogHeader>
        </div>

        <div className="flex-1 overflow-auto p-6 space-y-4">
          {isGroup && (
            <div className="rounded-lg border bg-muted/20 p-3 text-xs">
              <div className="flex flex-row flex-wrap gap-x-4 gap-y-1">
                <div>Заданий: <span className="font-medium">{groupTasks.length}</span></div>
                <div>В работе: <span className="font-medium">{maxQty}</span></div>
                <div>Годные: <span className="font-medium">{completedQty}</span></div>
                <div>Брак: <span className="font-medium">{rejectedQty}</span></div>
                <div>План: <span className="font-medium">{plannedQty}</span></div>
              </div>
            </div>
          )}

          {task && (
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
              {task && task.operation_names && task.operation_names.length > 1 && (
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

          {isGroup && groupTasks.some((groupTask) => !isTaskCompletable(groupTask)) && (() => {
            const byReason = groupTasksByBlockReason(groupTasks);
            const total = byReason.reduce((sum, entry) => sum + entry.tasks.length, 0);
            return (
              <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-800">
                <div className="flex items-start gap-2">
                  <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
                  <div className="flex-1">
                    <div className="font-medium">
                      {total} из {groupTasks.length} задач будут пропущены
                    </div>
                    {byReason.map(({ reason, tasks: grouped }) => (
                      <div className="mt-1 text-xs" key={reason}>
                        <span className="font-semibold">
                          {actionReasonText(reason)} ({grouped.length}):
                        </span>{" "}
                        {Array.from(new Set(grouped.map((groupTask) => groupTask.product_sku)))
                          .slice(0, 5)
                          .join(", ")}
                        {grouped.length > 5 ? "…" : ""}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            );
          })()}

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
              <label className="text-sm font-medium">
                {isTransform ? "Факт (раскроено заготовок)" : "Факт (годные)"}
              </label>
              <Input
                type="text"
                inputMode="numeric"
                value={actionQty}
                onChange={(e) => handleQtyChange(e.target.value, setActionQty)}
                onBlur={() => setIssue(null)}
                aria-invalid={issue !== null || goodIssue !== null}
                title={goodIssue ?? undefined}
                className="w-[150px] h-8"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <label className="text-sm font-medium">
                {isTransform ? "Брак (заготовок)" : "Брак"}
              </label>
              <Input
                type="text"
                inputMode="numeric"
                value={defectQty}
                onChange={(e) => handleQtyChange(e.target.value, setDefectQty)}
                onBlur={() => setIssue(null)}
                aria-invalid={issue !== null || defectIssue !== null}
                title={defectIssue ?? undefined}
                className="w-[150px] h-8"
              />
            </div>
          </div>
          {(issue?.text || goodIssue || defectIssue) && (
            <div className="mt-1 text-xs text-red-600" role="status">
              {issue?.text ?? goodIssue ?? defectIssue}
            </div>
          )}
          {outOfRange && (
            <div className="mt-1 text-xs text-red-600">
              {isTransform
                ? `Сумма факта и брака больше остатка входа: ${maxQty}`
                : `Сумма факта и брака больше объема в работе: ${maxQty}`}
            </div>
          )}

          <div className="flex flex-row flex-wrap gap-2">
            {task && (
              <Button
                type="button"
                variant="outline"
                onClick={() => setActionQty(plannedFill)}
                className="shrink-0 w-[150px] h-8"
              >
                Плановое ({plannedFill})
              </Button>
            )}
            <Button
              type="button"
              variant="outline"
              onClick={() => setActionQty(maxQty > 0 ? maxFill : "0")}
              className="shrink-0 w-[150px] h-8"
            >
              Максимальное ({maxQty > 0 ? maxFill : "0"})
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
