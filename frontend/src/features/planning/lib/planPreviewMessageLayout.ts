/**
 * Раскладка пары колонок «Ошибки»/«Предупр.» в превью импорта плана.
 *
 * Колонки условные: строка без сообщений вообще не рисует ячейку, поэтому
 * соседние ячейки добирают освободившиеся слоты через `colSpan`. Пара
 * «Ошибки»+«Предупр.» — две колонки, и сообщение одного типа занимает обе,
 * когда второго нет: иначе текст («Не задано количество на подвес: 2,7 м»)
 * упирается в 150px и переносится на десяток строк.
 *
 * Правило живёт здесь, потому что от него зависят и ячейки строки, и
 * `colSpan` строки с сырыми данными: разъезд в колонках тихо съедает
 * последние ячейки таблицы, и это видно только глазами.
 */

/** Число колонок таблицы превью, включая уголок сброса фильтров. */
export const PLAN_PREVIEW_TOTAL_COLUMNS = 10;

/** Колонки до «Маршрута»: шеврон, ID, Строка, Артикул, Кол-во, Наименование. */
const COLUMNS_BEFORE_MESSAGES = 6;

/** Слоты «Маршрут»+«Ошибки»+«Предупр.»: маршрут всегда один, плюс два под сообщения. */
const MESSAGE_SLOT_COUNT = 3;

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
  const errorsColSpan = hasErrors ? (hasWarnings ? 1 : 2) : 0;
  const warningsColSpan = hasWarnings ? (hasErrors ? 1 : 2) : 0;
  const routeColSpan = MESSAGE_SLOT_COUNT - errorsColSpan - warningsColSpan;

  const rowColSpan =
    COLUMNS_BEFORE_MESSAGES + routeColSpan + errorsColSpan + warningsColSpan + 1;

  return {
    hasErrors,
    hasWarnings,
    errorsColSpan,
    warningsColSpan,
    routeColSpan,
    detailColSpan: rowColSpan,
  };
}
