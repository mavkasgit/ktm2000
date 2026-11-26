/**
 * Ширины колонок предпросмотра остатков — чистый расчёт (#483, эпик #475).
 *
 * Сценарий — **основной из спеки (§4): полный текст в обеих текстовых
 * колонках**, `clamp = ∞`. «Наименование» и «Ошибки» переносятся, ширина
 * каждой участвует в высоте строки. Пилюли «Операций» — одна строка, их ширина
 * бесплатна по высоте и ограничена снизу долей обрезанных рядов.
 *
 * Что считается:
 *
 * - **`pretext` — только текстовые колонки** (2 × строки). Однострочные
 *   (numeric, mono, control) остаются на текущей доле: их `lines` всегда 1,
 *   а при `λ = 0` обрезка в высоту не входит.
 * - **Ширины двух текстовых колонок** — 1D-перебор порогов числа строк.
 *   Для каждой колонки и строки подвыборки считаются пороги `(lines → 1)`
 *   бинарным поиском (как `cellThresholds` в research `curves`); кандидаты —
 *   сами пороги, а бюджет между колонками делится один к одному (`errors`
 *   получает остаток). `source_name` шире — `errors` уже, и наоборот;
 *   минимизируется сумма высот строк, а не «ноль обрезки».
 * - **Высота строки** — максимум по колонкам со своими `line-height` из CSS
 *   (`errors` 15.125 px, наименование 16.5 px), плюс `py` и бордер, не ниже
 *   29 px. Это второй потребитель модели: `VirtualizedTableBody` получает
 *   предсказанную высоту каждой строки.
 * - **Подвыборка ≤300 строк** (H2: 200/500/1000 дали 0.21/0.26/0.21% потерь):
 *   ширины подбираются на стратифицированной выборке, высоты — по всем
 *   строкам. Это же число строк в гейте §15.
 * - **Пилюли**: нижняя граница — квантиль натуральных ширин рядов по лимиту
 *   «не хуже текущего фикса» на этой ширине и не уже текущей доли 21%.
 * - **Честное переполнение**: если минимумы текстовых колонок не влезают в
 *   бюджет, `minPx` не подкручивается — таблица получает `min-width` и
 *   горизонтальный скролл.
 *
 * Потеря текста в этом сценарии — **ноль**: у обеих текстовых колонок нет
 * `clamp`/`truncate`, а ширина каждой не меньше `maxWordWidth + padding`
 * (#479/H4), поэтому ни одно слово не обрезается и не вылезает за строку.
 */
import { remainderPreviewColumns } from "./remainderPreviewColumns";
import type {
  PreviewFont,
  PreviewRowMeasurement,
  PreviewTextMeasurer,
} from "./previewTextMeasurer";

/** `min-w-[1180px]` у таблицы предпросмотра. */
export const PREVIEW_TABLE_MIN_WIDTH_PX = 1180;
/** Служебные колонки: шеврон и сброс по 2.5%. */
export const PREVIEW_SERVICE_SHARE = 0.05;
/** Доля таблицы под содержательные колонки. */
export const PREVIEW_CONTENT_SHARE = 1 - PREVIEW_SERVICE_SHARE;
/** `px-1.5` с двух сторон ячейки. */
export const PREVIEW_CELL_PADDING_PX = 12;
/**
 * Строка таблицы: `py-0.5` (2+2) + control `h-6` (24) + 1 px бордер.
 * Проверено DOM-стендом `browser/product.spec.mjs` (#483).
 */
export const PREVIEW_MIN_ROW_HEIGHT_PX = 29;
/** `py-0.5` (2+2) + 1 px `border-b`. */
export const PREVIEW_ROW_PADDING_PX = 5;
/** Потолок строк при поиске порогов (как `MAX_LINES` в research curves). */
const MAX_LINES = 64;
/** Подвыборка для подбора ширин (H2, гейт §15). */
export const PREVIEW_FIT_ROWS = 300;
/** Потолок кандидатов после прореживания. */
const MAX_CANDIDATES = 32;

export type PreviewColumnPolicy = "fixed" | "wrap" | "pills";

export interface PreviewColumnSpec {
  id: string;
  policy: PreviewColumnPolicy;
  /** Доля таблицы из `remainderPreviewColumns`, проценты. */
  baselineShare: number;
  minPx: number;
  /** Потолок доли содержательной ширины; у текстовых — защита от монополиста. */
  maxShare?: number;
}

/**
 * Политика и границы по `id` колонки. Доли не дублируются: они берутся из
 * `remainderPreviewColumns`, единственного места, где объявлена раскладка.
 * `minPx` — из спеки §6.
 */
const COLUMN_POLICY: Record<
  string,
  { policy: PreviewColumnPolicy; minPx: number; maxShare?: number }
> = {
  row: { policy: "fixed", minPx: 32 },
  source_code: { policy: "fixed", minPx: 60 },
  sku: { policy: "fixed", minPx: 70 },
  source_name: { policy: "wrap", minPx: 90, maxShare: 0.35 },
  quantity: { policy: "fixed", minPx: 55 },
  meters: { policy: "fixed", minPx: 55 },
  length: { policy: "fixed", minPx: 45 },
  operations: { policy: "pills", minPx: 90 },
  quality: { policy: "fixed", minPx: 90 },
  section: { policy: "fixed", minPx: 100 },
  errors: { policy: "wrap", minPx: 90, maxShare: 0.3 },
};

export const PREVIEW_COLUMN_SPECS: readonly PreviewColumnSpec[] =
  remainderPreviewColumns.map((column) => {
    const policy = COLUMN_POLICY[column.id];
    if (!policy) {
      throw new Error(
        `previewColumnWidths: у колонки «${column.id}» нет политики ширины — добавьте её в COLUMN_POLICY`,
      );
    }
    return {
      id: column.id,
      baselineShare: Number.parseFloat(column.width),
      ...policy,
    };
  });

/**
 * Текущая доля строк с обрезанными пилюлями на ширине таблицы (#487/#488).
 * Лимит интеграции — «не хуже текущего фикса», а не строгий ≤5%.
 */
const PILL_TRUNCATION_LIMIT: ReadonlyArray<readonly [number, number]> = [
  [1180, 0.3279],
  [1400, 0.1949],
  [1500, 0.1297],
  [1600, 0.0564],
  [1920, 0.0001],
];

export function pillsTruncationLimitAtWidth(tableWidth: number): number {
  const points = PILL_TRUNCATION_LIMIT;
  if (tableWidth <= points[0][0]) return points[0][1];
  const last = points[points.length - 1];
  if (tableWidth >= last[0]) return last[1];
  for (let index = 1; index < points.length; index += 1) {
    const [rightWidth, rightShare] = points[index];
    const [leftWidth, leftShare] = points[index - 1];
    if (tableWidth <= rightWidth) {
      const ratio = (tableWidth - leftWidth) / (rightWidth - leftWidth);
      return leftShare + (rightShare - leftShare) * ratio;
    }
  }
  return last[1];
}

export interface PreviewWidthInput {
  /** Ширина контейнера таблицы (CSS px). */
  containerWidth: number;
  rows: readonly PreviewRowMeasurement[];
  measurer: PreviewTextMeasurer;
  fonts: { name: PreviewFont; errors: PreviewFont; pill: PreviewFont };
  specs?: readonly PreviewColumnSpec[];
  minRowHeightPx?: number;
  rowPaddingPx?: number;
  cellPaddingPx?: number;
  /** Переопределение лимита пилюль (тесты); по умолчанию — по ширине. */
  pillLimitShare?: number;
  /** Потолок подвыборки (тесты); по умолчанию `PREVIEW_FIT_ROWS`. */
  fitRows?: number;
}

export interface PreviewWidthResult {
  tableWidthPx: number;
  contentWidthPx: number;
  widthsPx: Record<string, number>;
  /** Проценты для `<colgroup>`: сумма содержательных + 5% служебных = 100. */
  shares: Record<string, string>;
  rowHeights: ReadonlyMap<number, number>;
  nameWidthPx: number;
  errorsWidthPx: number;
  /** Всегда 0: у текстовых колонок нет `clamp`/`truncate` — текст не теряется. */
  textTruncatedCells: number;
  /** Ячейки, где слово шире колонки (инвариант #479/H4); должно быть 0. */
  wordOverflowCells: number;
  /** Строк в подвыборке, на которой выбраны ширины. */
  fitRows: number;
  /** Суммарная предсказанная высота листа (для сравнения раскладок). */
  totalHeightPx: number;
  overflow: boolean;
  minTableWidthPx: number;
  pillsFloorPx: number;
  pillsTruncatedShare: number;
  pillsLimitShare: number;
}

interface FitRow {
  row: PreviewRowMeasurement;
  namePrepared: unknown;
  errorsPrepared: unknown;
  nameNatural: number;
  errorsNatural: number;
  nameThresholds: number[];
  errorsThresholds: number[];
}

function round(value: number, digits = 3): number {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

/**
 * Минимальная ширина «Операций», при которой обрезано не больше `limitShare`
 * строк. Ряд помещается, когда `pillWidth <= width - padding`, поэтому
 * граница — квантиль натуральных ширин, а не перебор сетки.
 */
export function pillsFloorWidth(
  pillWidths: readonly number[],
  limitShare: number,
  minPx: number,
  cellPaddingPx: number = PREVIEW_CELL_PADDING_PX,
): number {
  if (pillWidths.length === 0) return minPx;
  const sorted = [...pillWidths].sort((a, b) => a - b);
  const allowed = Math.floor(limitShare * sorted.length + 1e-9);
  const index = Math.max(0, sorted.length - 1 - allowed);
  return Math.max(minPx, sorted[index] + cellPaddingPx);
}

/** Доля строк, чей ряд пилюль не помещается в ширину колонки. */
export function pillsTruncatedShareAt(
  pillWidths: readonly number[],
  widthPx: number,
  cellPaddingPx: number = PREVIEW_CELL_PADDING_PX,
): number {
  if (pillWidths.length === 0) return 0;
  const usable = widthPx - cellPaddingPx;
  let truncated = 0;
  for (const width of pillWidths) if (width > usable) truncated += 1;
  return truncated / pillWidths.length;
}

export function predictRowHeight(
  lines: number,
  lineHeightPx: number,
  minRowHeightPx: number = PREVIEW_MIN_ROW_HEIGHT_PX,
  rowPaddingPx: number = PREVIEW_ROW_PADDING_PX,
): number {
  return Math.max(minRowHeightPx, lines * lineHeightPx + rowPaddingPx);
}

/**
 * Пороги «число строк упало до k»: ширины контента, при которых `lineCount`
 * становится ≤ k. `lines(u) = 1 + #{t : t > u}` — та же запись, что в
 * research `curves`, поэтому стоимость ширины считается без вызова измерителя.
 */
export function lineThresholds(
  measurer: PreviewTextMeasurer,
  prepared: unknown,
  minUsableWidth: number,
  maxLines: number = MAX_LINES,
): number[] {
  const natural = measurer.naturalWidth(prepared);
  if (!(natural > minUsableWidth)) return [];
  const cap = Math.min(maxLines, MAX_LINES);
  const thresholds: number[] = [];
  for (let target = 2; target <= cap; target += 1) {
    if (measurer.lineCount(prepared, minUsableWidth) <= target) break;
    let low = minUsableWidth;
    let high = natural;
    while (high - low > 1) {
      const middle = (low + high) >> 1;
      if (measurer.lineCount(prepared, middle) <= target) high = middle;
      else low = middle;
    }
    thresholds.push(high);
  }
  return thresholds;
}

function linesAt(thresholds: readonly number[], usableWidth: number): number {
  let above = 0;
  for (let index = thresholds.length - 1; index >= 0; index -= 1) {
    if (thresholds[index] > usableWidth) above += 1;
    else break;
  }
  return 1 + above;
}

/**
 * Детерминированная стратифицированная подвыборка: самые «тяжёлые» строки
 * (обе колонки) попадают в неё гарантированно, остаток — равномерно. Копия
 * `selectSampleRows` из research curves, адаптированная к двум колонкам.
 */
export function selectFitRows<T>(
  rows: readonly T[],
  limit: number,
  score: (row: T) => number,
): T[] {
  if (rows.length <= limit) return [...rows];
  const order = rows
    .map((row, index) => ({ row, index, value: score(row) }))
    .sort((a, b) => b.value - a.value || a.index - b.index);
  const longCount = Math.min(rows.length, Math.max(4, Math.ceil(limit * 0.2)));
  const chosen = order.slice(0, longCount);
  const rest = order.slice(longCount);
  const need = limit - longCount;
  for (let index = 0; index < need; index += 1) {
    const pick = Math.min(
      rest.length - 1,
      Math.round((index * (rest.length - 1)) / Math.max(1, need - 1)),
    );
    chosen.push(rest[pick]);
  }
  return chosen
    .sort((a, b) => a.index - b.index)
    .map((entry) => entry.row);
}

function thinCandidates(candidates: number[], limit: number): number[] {
  if (candidates.length <= limit) return candidates;
  const result = [];
  for (let index = 0; index < limit; index += 1) {
    result.push(candidates[Math.round((index * (candidates.length - 1)) / (limit - 1))]);
  }
  return [...new Set(result)];
}

/**
 * Считает ширины и предсказанные высоты строк.
 *
 * Бюджет содержательных колонок `C`: фиксированные берут текущую долю (не уже
 * `minPx`), «Операции» — нижнюю границу по пилюлям, остаток `R` делят
 * «Наименование» и «Ошибки». Перебор по ширине наименования: `errors`
 * получает `R - name` (до `maxShare`), поэтому одна переменная, а не две.
 */
export function computePreviewColumnWidths(input: PreviewWidthInput): PreviewWidthResult {
  const specs = input.specs ?? PREVIEW_COLUMN_SPECS;
  const cellPadding = input.cellPaddingPx ?? PREVIEW_CELL_PADDING_PX;
  const minRowHeight = input.minRowHeightPx ?? PREVIEW_MIN_ROW_HEIGHT_PX;
  const rowPadding = input.rowPaddingPx ?? PREVIEW_ROW_PADDING_PX;
  const fitRows = input.fitRows ?? PREVIEW_FIT_ROWS;
  const tableWidth = Math.max(PREVIEW_TABLE_MIN_WIDTH_PX, input.containerWidth);
  const contentWidth = tableWidth * PREVIEW_CONTENT_SHARE;
  const limitShare = input.pillLimitShare ?? pillsTruncationLimitAtWidth(tableWidth);

  const widths: Record<string, number> = {};
  let fixedTotal = 0;
  let nameSpec: PreviewColumnSpec | null = null;
  let pillsSpec: PreviewColumnSpec | null = null;
  let errorsSpec: PreviewColumnSpec | null = null;

  for (const spec of specs) {
    if (spec.policy === "fixed") {
      const width = Math.max(spec.minPx, (spec.baselineShare / 100) * tableWidth);
      widths[spec.id] = width;
      fixedTotal += width;
    } else if (spec.policy === "pills") {
      pillsSpec = spec;
    } else if (spec.id === "source_name") {
      nameSpec = spec;
    } else {
      errorsSpec = spec;
    }
  }
  if (!nameSpec || !errorsSpec) {
    throw new Error("previewColumnWidths: нужны переносимые source_name и errors");
  }

  const pillWidths = input.rows.map((row) => row.pillWidth);
  // Пилюли не уже текущей доли: лимит «не хуже текущего» — по построению.
  const pillsCurrent = pillsSpec
    ? Math.max(pillsSpec.minPx, (pillsSpec.baselineShare / 100) * tableWidth)
    : 0;
  const pillsWidth = pillsSpec
    ? Math.max(
        pillsFloorWidth(pillWidths, limitShare, pillsSpec.minPx, cellPadding),
        pillsCurrent,
      )
    : 0;
  if (pillsSpec) widths[pillsSpec.id] = pillsWidth;

  const preparedRows = input.rows.map((row) => {
    const namePrepared = input.measurer.prepare(row.nameText, input.fonts.name);
    const errorsPrepared = input.measurer.prepare(row.errorsText, input.fonts.errors);
    return {
      row,
      namePrepared,
      errorsPrepared,
      nameNatural: input.measurer.naturalWidth(namePrepared),
      errorsNatural: input.measurer.naturalWidth(errorsPrepared),
    };
  });

  let nameMaxWord = 0;
  let errorsMaxWord = 0;
  for (const prepared of preparedRows) {
    nameMaxWord = Math.max(nameMaxWord, input.measurer.maxWordWidth(prepared.namePrepared));
    errorsMaxWord = Math.max(
      errorsMaxWord,
      input.measurer.maxWordWidth(prepared.errorsPrepared),
    );
  }
  // Инвариант H4: колонка не уже самого широкого слова строки (#479).
  const nameMin = Math.max(nameSpec.minPx, Math.ceil(nameMaxWord) + cellPadding);
  const errorsMin = Math.max(errorsSpec.minPx, Math.ceil(errorsMaxWord) + cellPadding);
  const nameMax = nameSpec.maxShare
    ? nameSpec.maxShare * contentWidth
    : Number.POSITIVE_INFINITY;
  const errorsMax = errorsSpec.maxShare
    ? errorsSpec.maxShare * contentWidth
    : Number.POSITIVE_INFINITY;

  const budget = contentWidth - fixedTotal - pillsWidth;
  const overflow = budget + 0.5 < nameMin + errorsMin;
  const nameCeiling = Math.max(
    nameMin,
    Math.min(nameMax, budget - errorsMin),
  );
  const errorsFloor = errorsMin;

  const sampled = selectFitRows(
    preparedRows,
    Math.min(fitRows, preparedRows.length),
    (prepared) =>
      Math.log1p(prepared.nameNatural) + Math.log1p(prepared.errorsNatural),
  );

  const fitRowsData: FitRow[] = sampled.map((prepared) => ({
    row: prepared.row,
    namePrepared: prepared.namePrepared,
    errorsPrepared: prepared.errorsPrepared,
    nameNatural: prepared.nameNatural,
    errorsNatural: prepared.errorsNatural,
    nameThresholds: lineThresholds(
      input.measurer,
      prepared.namePrepared,
      Math.max(1, nameMin - cellPadding),
    ),
    errorsThresholds: lineThresholds(
      input.measurer,
      prepared.errorsPrepared,
      Math.max(1, errorsFloor - cellPadding),
    ),
  }));

  const candidates = new Set<number>([nameMin, nameCeiling]);
  if (budget - errorsMax > nameMin) candidates.add(budget - errorsMax);
  for (const fit of fitRowsData) {
    for (const threshold of fit.nameThresholds) {
      const width = Math.ceil(threshold) + cellPadding;
      if (width >= nameMin && width <= nameCeiling) candidates.add(width);
    }
  }
  const orderedCandidates = thinCandidates(
    [...candidates].filter((width) => width >= nameMin).sort((a, b) => a - b),
    MAX_CANDIDATES,
  );

  const rowHeightFor = (nameWidth: number, errorsWidth: number, fit: FitRow): number => {
    const nameLines = linesAt(fit.nameThresholds, nameWidth - cellPadding);
    const errorsLines = fit.row.errorsWraps
      ? linesAt(fit.errorsThresholds, errorsWidth - cellPadding)
      : 1;
    return Math.max(
      minRowHeight,
      Math.max(
        nameLines * input.fonts.name.lineHeightPx,
        errorsLines * input.fonts.errors.lineHeightPx,
      ) + rowPadding,
    );
  };

  let best = { nameWidth: nameMin, errorsWidth: errorsMin, cost: Number.POSITIVE_INFINITY };
  for (const nameWidth of orderedCandidates) {
    const errorsWidth = Math.min(Math.max(budget - nameWidth, errorsFloor), errorsMax);
    if (errorsWidth < errorsFloor - 1e-6) continue;
    let cost = 0;
    for (const fit of fitRowsData) cost += rowHeightFor(nameWidth, errorsWidth, fit);
    // При равной высоте предпочитаем более широкое наименование: видно больше
    // текста, а «Ошибки» уже не растут за счёт этого (бюджет один).
    if (cost < best.cost - 1e-6 || (Math.abs(cost - best.cost) <= 1e-6 && nameWidth > best.nameWidth)) {
      best = { nameWidth, errorsWidth, cost };
    }
  }

  widths[nameSpec.id] = best.nameWidth;
  widths[errorsSpec.id] = best.errorsWidth;

  const errorsUsable = best.errorsWidth - cellPadding;
  const nameUsable = best.nameWidth - cellPadding;
  const rowHeights = new Map<number, number>();
  let totalHeight = 0;
  let wordOverflowCells = 0;
  for (const prepared of preparedRows) {
    const { row } = prepared;
    // Текст не теряется: у обеих колонок нет `clamp`/`truncate`. Слово шире
    // колонки — отдельный инвариант (#479/H4): его держит `maxWordWidth` в
    // нижней границе, здесь он только проверяется.
    if (input.measurer.maxWordWidth(prepared.namePrepared) > nameUsable + 0.5) {
      wordOverflowCells += 1;
    }
    if (
      row.errorsWraps &&
      input.measurer.maxWordWidth(prepared.errorsPrepared) > errorsUsable + 0.5
    ) {
      wordOverflowCells += 1;
    }
    const nameLines = row.nameText
      ? Math.max(1, input.measurer.lineCount(prepared.namePrepared, nameUsable))
      : 1;
    const errorsLines =
      row.errorsWraps && row.errorsText
        ? Math.max(1, input.measurer.lineCount(prepared.errorsPrepared, errorsUsable))
        : 1;
    const height = Math.max(
      minRowHeight,
      Math.max(
        nameLines * input.fonts.name.lineHeightPx,
        errorsLines * input.fonts.errors.lineHeightPx,
      ) + rowPadding,
    );
    rowHeights.set(row.rowKey, height);
    totalHeight += height;
  }

  const totalContent = Object.values(widths).reduce((sum, width) => sum + width, 0);
  const minTableWidthPx =
    totalContent > contentWidth + 0.5
      ? Math.ceil(totalContent / PREVIEW_CONTENT_SHARE)
      : PREVIEW_TABLE_MIN_WIDTH_PX;

  const shares: Record<string, string> = {};
  for (const [id, width] of Object.entries(widths)) {
    shares[id] = `${round((width / tableWidth) * 100, 3)}%`;
  }

  return {
    tableWidthPx: tableWidth,
    contentWidthPx: contentWidth,
    widthsPx: Object.fromEntries(
      Object.entries(widths).map(([id, width]) => [id, round(width, 2)]),
    ),
    shares,
    rowHeights,
    nameWidthPx: round(best.nameWidth, 2),
    errorsWidthPx: round(best.errorsWidth, 2),
    textTruncatedCells: 0,
    wordOverflowCells,
    fitRows: fitRowsData.length,
    totalHeightPx: round(totalHeight, 2),
    overflow,
    minTableWidthPx,
    pillsFloorPx: round(pillsWidth, 2),
    pillsTruncatedShare: pillsTruncatedShareAt(pillWidths, pillsWidth, cellPadding),
    pillsLimitShare: limitShare,
  };
}
