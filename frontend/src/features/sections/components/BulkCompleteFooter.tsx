/**
 * components/BulkCompleteFooter.tsx — панель подтверждения массового ввода
 * факта на доске участка (#283).
 *
 * Панель массовых операций уходила вместе со своим вводом, а итог «к записи»
 * показывать стало негде: суммы в шапке группы занял инпут группы. Поэтому
 * подтверждение (дата, смена, комментарий, счётчики, стратегия дефицита) живёт
 * в футере — по образцу групповой передачи (`BulkTransferFooter`).
 *
 * Причина недоступности подтверждения читается текстом рядом с кнопкой
 * (ADR-0049): «нет заданий для завершения» и «количество не введено» — разные
 * причины, и раньше вторая молчала. Стратегия дефицита обязательна, когда
 * факт превышает доступный лимит: панель её не отправляла вовсе, и расхождение
 * с диалогом уходит вместе с панелью.
 */

import { useMemo, useState } from "react";
import { AlertTriangle } from "lucide-react";

import type { SectionBoardTask, ShortageStrategy } from "@/shared/api/shopfloor";
import {
  ActionWithReason,
  Button,
  DatePicker,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/shared/ui";
import { cn } from "@/shared/utils/cn";
import { actionReasonText, type ActionReasonCode } from "@/shared/lib/actionReasons";
import { fmtQty } from "@/shared/lib/quantityFormat";
import { taskOperations } from "../lib/taskView";
import {
  draftEntries,
  draftEntryFieldSummary,
  draftEntryTotals,
  type BulkDraft,
  type DraftShortage,
} from "../lib/bulkDraft";
import { groupTasksByBlockReason } from "../lib/taskStatus";

const SHORTAGE_OPTIONS: { value: ShortageStrategy; label: string; hint: string }[] = [
  {
    value: "negative_remainder",
    label: "В scrap (списать в брак)",
    hint: "Излишек записывается дефицитом (списанием). Рекомендуется, если это брак.",
  },
  {
    value: "partial",
    label: "Частичное принятие",
    hint: "Завершается только доступное, излишек остаётся неучтённым.",
  },
  {
    value: "fail",
    label: "Отмена операции",
    hint: "Ничего не сохраняется, приходит ошибка о нехватке материала.",
  },
];

/** Короткое имя задания для счётчиков и списков футера. */
function taskLabel(task: SectionBoardTask): string {
  const operation = task.operation_name || task.operation_code || "Операция";
  return `${task.display_sku || task.product_sku} · ${operation} · №${task.sequence}`;
}

export type BulkCompleteFooterProps = {
  /** Все выделенные задания, включая строки вне текущего фильтра. */
  selectedTasks: SectionBoardTask[];
  /** id строк, видимых на доске сейчас, — по ним считается «вне фильтра». */
  visibleTaskIds: ReadonlySet<number>;
  draft: BulkDraft;
  performedDate: string;
  onPerformedDateChange: (value: string) => void;
  performedShift: "1" | "2";
  onPerformedShiftChange: (shift: "1" | "2") => void;
  comment: string;
  onCommentChange: (value: string) => void;
  shortageStrategy: ShortageStrategy | null;
  onShortageStrategyChange: (strategy: ShortageStrategy) => void;
  shortage: DraftShortage | null;
  submitBlockReason: ActionReasonCode | null;
  pending: boolean;
  onConfirm: () => void;
  onCancel: () => void;
};

export function BulkCompleteFooter({
  selectedTasks,
  visibleTaskIds,
  draft,
  performedDate,
  onPerformedDateChange,
  performedShift,
  onPerformedShiftChange,
  comment,
  onCommentChange,
  shortageStrategy,
  onShortageStrategyChange,
  shortage,
  submitBlockReason,
  pending,
  onConfirm,
  onCancel,
}: BulkCompleteFooterProps) {
  const [showOutside, setShowOutside] = useState(false);

  const { entries, skipped } = useMemo(
    () => draftEntries(selectedTasks, draft),
    [selectedTasks, draft],
  );
  const totals = useMemo(() => draftEntryTotals(entries), [entries]);
  // «+100» — добавка, «400 → 500» — факт станет 500: без этого «просто число»
  // в поле читалось бы как добавка, и оператор не сверил бы запись.
  const goodSummary = useMemo(() => draftEntryFieldSummary(entries, "good"), [entries]);
  const defectSummary = useMemo(() => draftEntryFieldSummary(entries, "defect"), [entries]);
  const outsideFilter = useMemo(
    () => selectedTasks.filter((task) => !visibleTaskIds.has(task.id)),
    [selectedTasks, visibleTaskIds],
  );
  const skippedByReason = useMemo(() => groupTasksByBlockReason(skipped), [skipped]);

  return (
    <div className="fixed inset-x-0 bottom-0 z-40 border-t bg-background/95 backdrop-blur shadow-[0_-4px_24px_rgba(0,0,0,0.08)]">
      <div className="w-full px-6 py-3">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
          <div className="min-w-0 flex-1 space-y-1.5">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
              <span className="font-semibold">Массовое завершение</span>
              <span className="text-muted-foreground">
                Выбрано: {selectedTasks.length} · к записи:{" "}
                <span className="font-medium text-emerald-700">годные {goodSummary}</span>,{" "}
                <span className="font-medium text-red-600">брак {defectSummary}</span>
              </span>
              {outsideFilter.length > 0 && (
                <button
                  type="button"
                  className="rounded border px-1.5 py-0.5 text-xs text-slate-700 hover:bg-muted"
                  onClick={() => setShowOutside((prev) => !prev)}
                >
                  вне текущего фильтра: {outsideFilter.length} {showOutside ? "▾" : "▸"}
                </button>
              )}
            </div>

            {showOutside && outsideFilter.length > 0 && (
              <div className="max-h-24 overflow-y-auto rounded-md border bg-muted/30 p-2 text-xs">
                {outsideFilter.map((task) => (
                  <div key={task.id} className="truncate border-b border-border/50 py-0.5 last:border-0">
                    {taskLabel(task)}
                  </div>
                ))}
              </div>
            )}

            {skipped.length > 0 && (
              <div className="flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 px-2 py-1 text-xs text-amber-800">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                <div>
                  <span className="font-medium">
                    Будет пропущено: {skipped.length} (количество введено, завершить нельзя)
                  </span>
                  {skippedByReason.map(({ reason, tasks }) => (
                    <div key={reason}>
                      {actionReasonText(reason)}: {tasks.map((task) => task.product_sku).join(", ")}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {shortage && (
              <div className="flex flex-wrap items-center gap-2 rounded-md border border-amber-300 bg-amber-50/70 px-2 py-1 text-xs text-amber-800">
                <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                <span>
                  Факт {fmtQty(shortage.fact)} больше доступного лимита {fmtQty(shortage.limit)}:
                  излишек {fmtQty(shortage.excess)} шт.
                </span>
              </div>
            )}

          </div>

          <div className="flex flex-col gap-3 lg:flex-row lg:flex-wrap lg:items-end xl:shrink-0">
            <DatePicker
              value={performedDate}
              onChange={onPerformedDateChange}
              label="Дата"
              disabled={pending}
            />

            <div className="flex flex-col gap-1.5">
              <span className="text-sm font-medium">Смена</span>
              <div className="flex h-10 items-center gap-1 rounded-md bg-muted p-0.5">
                {(["1", "2"] as const).map((shift) => (
                  <button
                    key={shift}
                    type="button"
                    disabled={pending}
                    onClick={() => onPerformedShiftChange(shift)}
                    className={cn(
                      "flex h-8 items-center justify-center rounded px-3 text-sm font-medium transition-all",
                      performedShift === shift
                        ? "bg-background text-foreground shadow-sm"
                        : "text-muted-foreground hover:text-foreground",
                    )}
                  >
                    {shift === "1" ? "1-я" : "2-я"}
                  </button>
                ))}
              </div>
            </div>

            {shortage && (
              <div className="flex min-w-[240px] flex-col gap-1.5">
                <span className="text-sm font-medium">Излишек</span>
                <Select
                  value={shortageStrategy ?? ""}
                  onValueChange={(value) => onShortageStrategyChange(value as ShortageStrategy)}
                  disabled={pending}
                >
                  <SelectTrigger className="h-10">
                    <SelectValue placeholder="Что делать с излишком" />
                  </SelectTrigger>
                  <SelectContent>
                    {SHORTAGE_OPTIONS.map((option) => (
                      <SelectItem key={option.value} value={option.value} title={option.hint}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}

            <div className="flex min-w-[200px] flex-col gap-1.5">
              <span className="text-sm font-medium">Комментарий</span>
              <Input
                value={comment}
                onChange={(event) => onCommentChange(event.target.value)}
                placeholder="Необязательно"
                disabled={pending}
              />
            </div>

            {/* Кнопки — на уровне полей: невидимая подпись занимает ту же
                строку, что «Дата»/«Смена»/«Комментарий», а причина отказа
                уходит вправо от кнопки, а не под неё (иначе блок кнопок выше
                остальных и кнопка висит ниже поля). */}
            <div className="flex flex-col gap-1.5">
              <span aria-hidden className="invisible text-sm font-medium">
                Действие
              </span>
              <div className="flex h-10 items-center gap-2">
                <Button variant="outline" onClick={onCancel} disabled={pending}>
                  Отмена
                </Button>
                <ActionWithReason reason={submitBlockReason} layout="row">
                  <Button onClick={onConfirm} disabled={pending || submitBlockReason !== null}>
                    {pending ? "Запись…" : `Записать (${entries.length})`}
                  </Button>
                </ActionWithReason>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
