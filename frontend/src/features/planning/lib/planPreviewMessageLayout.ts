/**
 * Раскладка пары колонок «Ошибки»/«Предупр.» в превью импорта плана.
 *
 * Слоты пары считает общий `messagePairLayout` — правило одно на обе
 * таблицы плана, — а здесь к нему добавлен `colSpan` строки с сырыми
 * данными: сумма всех `colSpan` строки обязана равняться числу колонок,
 * иначе развёрнутая строка тихо съедает уголок сброса фильтров.
 */
import { messagePairLayout } from "./messageColumns";

/** Число колонок таблицы превью, включая уголок сброса фильтров. */
export const PLAN_PREVIEW_TOTAL_COLUMNS = 10;

/** Колонки до «Маршрута»: шеврон, ID, Строка, Артикул, Кол-во, Наименование. */
const COLUMNS_BEFORE_MESSAGES = 6;

/** Слоты «Маршрут»+«Ошибки»+«Предупр.»: маршрут всегда один, плюс два под сообщения. */
const SLOTS_AROUND_MESSAGES = 3;

export type PlanPreviewMessageLayout = {
  /** В строке есть хотя бы одна ошибка — ячейка «Ошибки» рисуется. */
  hasErrors: boolean;
  /** В строке есть хотя бы одно предупреждение — ячейка «Предупр.» рисуется. */
  hasWarnings: boolean;
  /** `colSpan` ячейки «Ошибки»; 0 — ячейки нет. */
  errorsColSpan: 0 | 1 | 2;
  /** `colSpan` ячейки «Предупр.»; 0 — ячейки нет. */
  warningsColSpan: 0 | 1 | 2;
  /** `colSpan` ячейки «Маршрут»: без сообщений забирает все три слота. */
  routeColSpan: number;
  /** `colSpan` строки с сырыми данными — всегда на всю ширину таблицы. */
  detailColSpan: number;
};

/**
 * Раскладка для строки с указанным набором сообщений. `detailColSpan` не
 * зависит от сообщений: сумма всех `colSpan` строки всегда равна числу
 * колонок, поэтому и при двух ячейках, и при одной развёрнутая строка
 * закрывает таблицу целиком.
 */
export function planPreviewMessageLayout(
  hasErrors: boolean,
  hasWarnings: boolean,
): PlanPreviewMessageLayout {
  const { errorsColSpan, warningsColSpan, precedingColSpan: routeColSpan } =
    messagePairLayout(hasErrors, hasWarnings);

  return {
    hasErrors,
    hasWarnings,
    errorsColSpan,
    warningsColSpan,
    routeColSpan,
    // Развёрнутая строка закрывает таблицу целиком при любом наборе
    // сообщений: сумма всех colSpan строки не зависит от их числа.
    detailColSpan:
      COLUMNS_BEFORE_MESSAGES + SLOTS_AROUND_MESSAGES + 1,
  };
}
