/**
 * Ширины колонок предпросмотра остатков — чистый расчёт (#483, эпик #475).
 *
 * Модель повторяет исследование (`research/column-widths`, спека
 * `docs/specs/preview-column-widths.md`), но только в той части, которая
 * нужна продукту:
 *
 * - **Считаются только переносимые колонки.** «Ошибки» — единственная
 *   колонка, чья ширина меняет высоту строки. «Наименование» обрезается
 *   (`truncate`), «Операции» — пилюли в одну строку, остальные — одна строка
 *   по определению. Их ширины участвуют в бюджете, но `pretext` для них не
 *   вызывается: при `λ = 0` высота от них не зависит.
 * - **Пилюли — не `pretext`.** Ширина ряда пилюль считается по содержимому
 *   (`previewPillWidths.ts`), а нижняя граница «Операций» — квантиль по этим
 *   ширинам: не хуже текущей доли обрезанных строк на этой ширине.
 * - **Бюджет в пикселях, наружу — проценты.** Считаем от `contentWidth`
 *   (95% таблицы: 2 × 2.5% служебных колонок), в `<colgroup>` отдаём проценты,
 *   чтобы ресайз до пересчёта не рвал раскладку.
 * - **Честное переполнение.** Если нижние границы не влезают в бюджет,
 *   раскладка не «подкручивает» `minPx`, а отдаёт `overflow: true` и
 *   минимальную ширину таблицы: появится горизонтальный скролл.
 *
 * Высота строки — `max(минимум строки, lines × lineHeight + padding)`, где
 * `lineHeight` приходит из CSS ячейки (у «Ошибок» это `leading-snug` =
 * 15.125 px). Это второй потребитель модели: `VirtualizedTableBody` получает
 * предсказанную высоту вместо среднего по таблице.
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

export type PreviewColumnPolicy = "fixed" | "truncate" | "pills" | "wrap";

export interface PreviewColumnSpec {
  id: string;
  policy: PreviewColumnPolicy;
  /** Доля таблицы из `remainderPreviewColumns`, проценты. */
  baselineShare: number;
  minPx: number;
  /**
   * Потолок доли содержательной ширины. У «Ошибок» — защита от монополиста;
   * ограничение пилюль (`minPx`/квантиль) важнее и потолком не срезается.
   */
  maxShare?: number;
}

/**
 * Политика и границы по `id` колонки. Доли не дублируются: они берутся из
 * `remainderPreviewColumns`, единственного места, где объявлена раскладка.
 * `minPx` — из спеки §6 (шапка, контрол, пара знаков).
 */
const COLUMN_POLICY: Record<
  string,
  { policy: PreviewColumnPolicy; minPx: number; maxShare?: number }
> = {
  row: { policy: "fixed", minPx: 32 },
  source_code: { policy: "fixed", minPx: 60 },
  sku: { policy: "fixed", minPx: 70 },
  source_name: { policy: "truncate", minPx: 90, maxShare: 0.35 },
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
 * Дефолтный лимит интеграции — «не хуже текущего фикса», а не строгий ≤5%:
 * строгий режим несовместим с выигрышем на 1180 (спека §11).
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
  fonts: { errors: PreviewFont; pill: PreviewFont };
  specs?: readonly PreviewColumnSpec[];
  minRowHeightPx?: number;
  rowPaddingPx?: number;
  cellPaddingPx?: number;
  /** Переопределение лимита пилюль (тесты); по умолчанию — по ширине. */
  pillLimitShare?: number;
}

export interface PreviewWidthResult {
  tableWidthPx: number;
  contentWidthPx: number;
  widthsPx: Record<string, number>;
  /** Проценты для `<colgroup>`: сумма содержательных + 5% служебных = 100. */
  shares: Record<string, string>;
  rowHeights: ReadonlyMap<number, number>;
  errorsWidthPx: number;
  errorsLinesTotal: number;
  overflow: boolean;
  minTableWidthPx: number;
  pillsFloorPx: number;
  pillsTruncatedShare: number;
  pillsLimitShare: number;
}

function round(value: number, digits = 3): number {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

/**
 * Минимальная ширина «Операций», при которой обрезано не больше `limitShare`
 * строк. `pillWidth` — натуральная ширина ряда, поэтому ряд помещается, когда
 * `pillWidth <= width - padding`. Квантиль, а не перебор кандидатов: ширина
 * ряда не зависит от колонки, и множество порогов — сами ширины строк.
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
 * Считает ширины и предсказанные высоты строк.
 *
 * Порядок распределения бюджета:
 * 1. фиксированные колонки — текущая доля таблицы, но не уже `minPx`;
 * 2. «Наименование» — свой минимум (обрезается в одну строку, высоту не
 *    меняет, поэтому не расширяется: освободившиеся пиксели нужны «Ошибкам»);
 * 3. «Операции» — нижняя граница по пилюлям (лимит «не хуже текущего»);
 * 4. «Ошибки» — весь остаток до `maxShare`; модель линии считает она одна.
 */
export function computePreviewColumnWidths(input: PreviewWidthInput): PreviewWidthResult {
  const specs = input.specs ?? PREVIEW_COLUMN_SPECS;
  const cellPadding = input.cellPaddingPx ?? PREVIEW_CELL_PADDING_PX;
  const minRowHeight = input.minRowHeightPx ?? PREVIEW_MIN_ROW_HEIGHT_PX;
  const rowPadding = input.rowPaddingPx ?? PREVIEW_ROW_PADDING_PX;
  const tableWidth = Math.max(PREVIEW_TABLE_MIN_WIDTH_PX, input.containerWidth);
  const contentWidth = tableWidth * PREVIEW_CONTENT_SHARE;
  const limitShare = input.pillLimitShare ?? pillsTruncationLimitAtWidth(tableWidth);

  const widths: Record<string, number> = {};
  let fixedTotal = 0;
  let sourceSpec: PreviewColumnSpec | null = null;
  let pillsSpec: PreviewColumnSpec | null = null;
  let errorsSpec: PreviewColumnSpec | null = null;

  for (const spec of specs) {
    if (spec.policy === "fixed") {
      const width = Math.max(spec.minPx, (spec.baselineShare / 100) * tableWidth);
      widths[spec.id] = width;
      fixedTotal += width;
    } else if (spec.policy === "truncate") {
      sourceSpec = spec;
    } else if (spec.policy === "pills") {
      pillsSpec = spec;
    } else {
      errorsSpec = spec;
    }
  }

  const pillWidths = input.rows.map((row) => row.pillWidth);
  // Пилюли не уже текущей доли: лимит «не хуже текущего фикса» выполняется по
  // построению, а модель ряда только расширяет колонку, если квантиль требует.
  const pillsCurrent = pillsSpec
    ? Math.max(pillsSpec.minPx, (pillsSpec.baselineShare / 100) * tableWidth)
    : 0;
  const pillsFloor = pillsSpec
    ? Math.max(
        pillsFloorWidth(pillWidths, limitShare, pillsSpec.minPx, cellPadding),
        pillsCurrent,
      )
    : 0;
  const sourceMin = sourceSpec?.minPx ?? 0;

  // Ошибки: нижняя граница — самое широкое слово строки (#479/H4): pretext
  // переносит по сегментам, а CSS с `overflow-wrap: normal` слово не рвёт.
  let errorsMaxWordWidth = 0;
  const preparedErrors = new Map<number, unknown>();
  for (const row of input.rows) {
    const prepared = input.measurer.prepare(row.errorsText, input.fonts.errors);
    preparedErrors.set(row.rowKey, prepared);
    errorsMaxWordWidth = Math.max(
      errorsMaxWordWidth,
      input.measurer.maxWordWidth(prepared),
    );
  }
  const errorsFloor = Math.max(
    errorsSpec?.minPx ?? 0,
    errorsMaxWordWidth + cellPadding,
  );
  const errorsMax = errorsSpec?.maxShare
    ? errorsSpec.maxShare * contentWidth
    : Number.POSITIVE_INFINITY;

  const remaining = contentWidth - fixedTotal - sourceMin - pillsFloor;
  let errorsWidth = Math.min(Math.max(remaining, errorsFloor), errorsMax);
  let sourceWidth = sourceMin;
  let pillsWidth = pillsFloor;

  // Остаток после потолка «Ошибок» отдаём «Наименованию» (больше текста без
  // роста высоты), затем «Операциям» (пилюли перестают обрезаться).
  let leftover = contentWidth - fixedTotal - sourceWidth - pillsWidth - errorsWidth;
  if (leftover > 0.5 && sourceSpec) {
    const sourceMax = sourceSpec.maxShare
      ? sourceSpec.maxShare * contentWidth
      : Number.POSITIVE_INFINITY;
    const extra = Math.min(leftover, Math.max(0, sourceMax - sourceWidth));
    sourceWidth += extra;
    leftover -= extra;
  }
  if (leftover > 0.5 && pillsSpec) {
    pillsWidth += leftover;
    leftover = 0;
  }

  if (sourceSpec) widths[sourceSpec.id] = sourceWidth;
  if (pillsSpec) widths[pillsSpec.id] = pillsWidth;
  if (errorsSpec) widths[errorsSpec.id] = errorsWidth;
  errorsWidth = widths[errorsSpec?.id ?? ""] ?? errorsWidth;

  const totalContent = Object.values(widths).reduce((sum, width) => sum + width, 0);
  const overflow = totalContent > contentWidth + 0.5;
  // При переполнении таблица обязана прокручиваться, а не сжимать колонки:
  // `minPx` — жёсткий инвариант, ширина таблицы — нет.
  const minTableWidthPx = overflow
    ? Math.ceil(totalContent / PREVIEW_CONTENT_SHARE)
    : PREVIEW_TABLE_MIN_WIDTH_PX;

  const errorsUsable = Math.max(0, errorsWidth - cellPadding);
  const rowHeights = new Map<number, number>();
  let errorsLinesTotal = 0;
  for (const row of input.rows) {
    const prepared = preparedErrors.get(row.rowKey);
    const lines =
      row.errorsWraps && prepared
        ? Math.max(1, input.measurer.lineCount(prepared, errorsUsable))
        : 1;
    errorsLinesTotal += lines;
    rowHeights.set(
      row.rowKey,
      predictRowHeight(lines, input.fonts.errors.lineHeightPx, minRowHeight, rowPadding),
    );
  }

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
    errorsWidthPx: round(errorsWidth, 2),
    errorsLinesTotal,
    overflow,
    minTableWidthPx,
    pillsFloorPx: round(pillsWidth, 2),
    pillsTruncatedShare: pillsTruncatedShareAt(pillWidths, pillsWidth, cellPadding),
    pillsLimitShare: limitShare,
  };
}
