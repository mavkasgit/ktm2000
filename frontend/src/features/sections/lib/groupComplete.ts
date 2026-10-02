/**
 * groupComplete.ts — «Завершить группу» из шапки блока: цели диалога → пачка
 * записей.
 *
 * Диалог группы принимает «Факт/Брак» за всю группу — те же два режима, что и
 * поле группы на доске (`+100` — добавить, `500` — факт станет 500). Раскладка
 * цели по строкам — общий домен черновика (`applyGroupField`), а здесь тот же
 * перевод собран в одну чистую функцию: страница не собирает пачку руками, и
 * раскладка не расходится с полем группы.
 *
 * Задания, которые завершить нельзя, в пачку не попадают вовсе: их список
 * возвращается отдельно — диалог перечисляет их до подтверждения.
 */
import type { SectionBoardTask } from "@/shared/api/shopfloor";

import { applyGroupField, draftEntries, type DraftEntry } from "./bulkDraft";
import { getCompletionBlockReason } from "./taskStatus";

export type GroupCompletePlan = {
  /** Записи по строкам: количество уже порция, а не набранная цель. */
  entries: DraftEntry[];
  /** Задания, которым нечего записывать: причина у каждого своя. */
  skipped: SectionBoardTask[];
};

export function planGroupComplete(
  tasks: SectionBoardTask[],
  goodTarget: string,
  defectTarget: string,
): GroupCompletePlan {
  const completable = tasks.filter((task) => getCompletionBlockReason(task) === null);
  const skipped = tasks.filter((task) => getCompletionBlockReason(task) !== null);
  if (completable.length === 0) return { entries: [], skipped };

  // «Годные» раскладываются с чистого черновика, «Брак» — поверх них: поля
  // строк независимы, и порядок раскладок на итог не влияет, но так читается
  // одна причина на каждую строку.
  const draft = applyGroupField(
    applyGroupField({}, completable, "good", goodTarget),
    completable,
    "defect",
    defectTarget,
  );
  const { entries } = draftEntries(completable, draft);
  const written = new Set(entries.map((entry) => entry.taskId));

  // Строка, которой ничего не досталось (цель ниже записанного), тоже
  // пропущена: в пачку она не уедет, и оператор увидит её в списке.
  return {
    entries,
    skipped: [...skipped, ...completable.filter((task) => !written.has(task.id))],
  };
}
