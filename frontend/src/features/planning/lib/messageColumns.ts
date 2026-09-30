/**
 * Пара колонок «Ошибки»/«Предупр.» — общий хвост таблиц плана.
 *
 * Пара — две колонки, а сообщение бывает одно: тогда оно занимает обе,
 * иначе текст («Не задано количество на подвесе») упирается в 180px и
 * обрезается на полуслове. Нет сообщений вовсе — пара не рисуется, и её
 * слоты забирает колонка перед ней (в обеих таблицах это «Маршрут»):
 * иначе последующие ячейки, «Действия» и уголок сброса, уезжают влево.
 *
 * Правило живёт здесь, потому что от него зависят и ячейки строки, и
 * `colSpan` развёрнутой строки с сырыми данными: разъезд в колонках тихо
 * съедает последние ячейки таблицы, и это видно только глазами.
 */

/**
 * Слоты «колонка перед парой» + «Ошибки» + «Предупр.». Колонка перед парой
 * всегда своя, а два слота пары делятся между ячейками сообщений.
 */
const SLOTS_AROUND_MESSAGES = 3;

export type MessagePairLayout = {
  /** `colSpan` ячейки «Ошибки»; 0 — ячейки нет. */
  errorsColSpan: 0 | 1 | 2;
  /** `colSpan` ячейки «Предупр.»; 0 — ячейки нет. */
  warningsColSpan: 0 | 1 | 2;
  /** `colSpan` колонки перед парой: без сообщений забирает все три слота. */
  precedingColSpan: number;
};

/**
 * Раскладка пары для строки. `errorsShown`/`warningsShown` — рисуется ли
 * ячейка (у «Ошибки» это ещё и перекрытая валидация и дубликат строки
 * Excel: они печатаются в её ячейке).
 */
export function messagePairLayout(
  errorsShown: boolean,
  warningsShown: boolean,
): MessagePairLayout {
  const errorsColSpan = errorsShown ? (warningsShown ? 1 : 2) : 0;
  const warningsColSpan = warningsShown ? (errorsShown ? 1 : 2) : 0;
  return {
    errorsColSpan,
    warningsColSpan,
    precedingColSpan: SLOTS_AROUND_MESSAGES - errorsColSpan - warningsColSpan,
  };
}
