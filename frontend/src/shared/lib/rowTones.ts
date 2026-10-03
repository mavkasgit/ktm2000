/**
 * Тональная раскладка строки data-таблицы: фон, полоса у левого края, цвет
 * текста, карточка узкого экрана и рельс шапки блока — один словарь на все
 * таблицы, которые красят строку состоянием.
 *
 * Размеры, выделение и подложка блока живут в `dataTableStyles.ts` /
 * `tableRowStyles.ts`; здесь только цвет по состоянию. До выноса словарь знала
 * одна доска участков (`features/sections/components/TaskView.tsx`), поэтому
 * строки «Передач» и «Остатков» оставались плоскими при том же 32px и том же
 * шаред-наборе размеров.
 *
 * Тон — не «цвет статуса»: каждая таблица берёт из набора те части, которые
 * несёт её состояние (доска — заливку, полосу и текст; «Передачи» — заливку и
 * полосу; «Остатки» — заливку), и ни одна не переопределяет словарь у себя.
 *
 * `!` на ховере — не косметика: `hover:bg-muted/50` из shadcn-`TableRow`
 * объявлен в собранном CSS позже, чем `hover:bg-blue-50/50`, и без `!`
 * тональный ховер проигрывает базовому на любой таблице, собранной из
 * shadcn-примитивов (`TableRow`), — на сыром `<tr>` доски порядок ничего не
 * решает, поэтому там `!` безвреден.
 */
import { TABLE_ROW_STYLES } from "./tableRowStyles";

export type RowTone = "waiting" | "activeRunning" | "active" | "ok" | "completed" | "scrap" | "plain";

/**
 * `ok` — «сработало успешно» тем же зелёным, что `completed`, но без
 * `line-through` и приглушения: у `completed` зачёркивание значит «дело закрыто
 * и неактуально» (передача, завершённое задание), а в журнале действий успешная
 * запись — живое подтверждение, к которому возвращаются.
 */

/** Заливка строки вне блока: базовый фон плюс ховер того же тона. */
export const ROW_TONE_WASH: Record<RowTone, string> = {
  waiting: "bg-background hover:!bg-slate-50",
  activeRunning: "bg-amber-50/30 hover:!bg-amber-50/70",
  active: "bg-blue-50/20 hover:!bg-blue-50/50",
  ok: "bg-emerald-50/20 hover:!bg-emerald-50/40",
  completed: "bg-emerald-50/10 hover:!bg-emerald-50/30",
  scrap: "bg-red-50/30 hover:!bg-red-50/60",
  plain: "",
};

/** Полоса 4px у левого края первой ячейки. У «обычного» тона — прозрачная. */
export const ROW_TONE_STRIPE: Record<RowTone, string> = {
  waiting: "border-l-4 border-l-yellow-400",
  activeRunning: "border-l-4 border-l-amber-400",
  active: "border-l-4 border-l-blue-400",
  ok: "border-l-4 border-l-emerald-400",
  completed: "border-l-4 border-l-emerald-300",
  scrap: "border-l-4 border-l-red-400",
  plain: "border-l-4 border-l-transparent",
};

/** Цвет текста строки. У «обычного» тона — наследуемый. */
export const ROW_TONE_TEXT: Record<RowTone, string> = {
  waiting: "text-slate-800 dark:text-slate-200",
  activeRunning: "text-slate-900 dark:text-slate-100 font-medium",
  active: "text-slate-900 dark:text-slate-100",
  ok: "text-slate-900 dark:text-slate-100",
  completed:
    "text-emerald-700/80 dark:text-emerald-300/70 line-through decoration-slate-300 opacity-60",
  scrap: "text-red-700 dark:text-red-300",
  plain: "",
};

/** Карточка узкого экрана: тот же тон, что и у строки. */
export const ROW_TONE_CARD: Record<RowTone, string> = {
  waiting: "border border-slate-200 bg-background text-slate-800 rounded-lg border-l-4 border-l-yellow-400",
  activeRunning: "border border-amber-200 bg-amber-50/30 text-slate-900 rounded-lg border-l-4 border-l-amber-400",
  active: "border border-blue-200 bg-blue-50/20 text-slate-900 rounded-lg border-l-4 border-l-blue-400",
  ok: "border border-emerald-200 bg-emerald-50/20 text-slate-900 rounded-lg border-l-4 border-l-emerald-400",
  completed:
    "border border-emerald-100 bg-emerald-50/10 text-slate-400 opacity-60 rounded-lg border-l-4 border-l-emerald-300 line-through decoration-slate-300",
  scrap: "border border-red-200 bg-red-50/30 text-red-700 rounded-lg border-l-4 border-l-red-400",
  plain: "border border-slate-200 rounded-lg bg-card text-card-foreground",
};

/**
 * Рельс шапки блока — тот же левый край 4px, что у строк блока: шапка и её
 * строки читаются одним куском. Цвет — тон блока, а не первой его строки.
 */
export const ROW_TONE_GROUP_RAIL: Record<RowTone, string> = {
  waiting: "border-l-4 border-l-yellow-400",
  activeRunning: "border-l-4 border-l-amber-400",
  active: "border-l-4 border-l-blue-400",
  ok: "border-l-4 border-l-emerald-400",
  completed: "border-l-4 border-l-emerald-300",
  scrap: "border-l-4 border-l-red-400",
  plain: "border-l-4 border-l-slate-300 dark:border-l-slate-600",
};

/**
 * Заливка строки вне блока: тон, а у «обычного» — ховер обычной строки
 * (`TABLE_ROW_STYLES.defaultRow`). У «обычного» тона своей заливки нет, и без
 * подстановки строка теряла бы ховер вовсе.
 */
export function rowToneFill(tone: RowTone): string {
  return ROW_TONE_WASH[tone] || TABLE_ROW_STYLES.defaultRow;
}
