/**
 * Подготовка листа к многократной оценке ширин и сама оценка.
 *
 * Оценка вызывается сотни раз (перебор ширин), поэтому ячейки готовятся один
 * раз: натуральная ширина, разбиение на слова и число строк при данной ширине.
 * Высота строки — `max` по колонкам, как в браузере: одна длинная ячейка
 * определяет строку, остальные на неё не влияют.
 */
import {
  CELL_PADDING_PX,
  LINE_HEIGHT_PX,
  MIN_ROW_HEIGHT_PX,
  ROW_PADDING_PX,
} from "./columns.mjs";
import { pillsWidth } from "./text.mjs";

function prepareCell(measurer, column, value) {
  if (column.kind === "pills") {
    const pills = Array.isArray(value) ? value : [];
    return {
      kind: "pills",
      wrap: false,
      clamp: null,
      naturalWidth: pillsWidth(pills, column.font),
      prepared: null,
    };
  }
  const text = value == null ? "" : String(value);
  const prepared = measurer.prepare(text, column.font);
  return {
    kind: column.kind,
    wrap: Boolean(column.wrap),
    clamp: column.clamp ?? null,
    naturalWidth: measurer.naturalWidth(prepared),
    prepared,
  };
}

/**
 * Готовит лист к многократной оценке ширин.
 *
 * `options.singleLineMeasurer` (#483) — измеритель для колонок без переноса.
 * Им считается всё, что по определению занимает одну строку: numeric, mono,
 * control и `truncate`-текст. Их натуральная ширина влияет только на счётчик
 * обрезки (`cost = Σ height + λ × truncated`), а при `λ = 0` — ни на что:
 * переносить там нечего, `lines` всегда 1. Поэтому `pretext` (сегментация +
 * canvas) нужен только `wrap`-колонкам, а остальным достаточно табличных
 * метрик — это та же политика, просто без лишней работы.
 */
export function prepareSheet(sheet, measurer, options = {}) {
  const { singleLineMeasurer = null } = options;
  const columns = sheet.columns;
  const rows = sheet.rows.map((row) => {
    const cells = new Array(columns.length);
    for (let index = 0; index < columns.length; index += 1) {
      const column = columns[index];
      const columnMeasurer =
        singleLineMeasurer && column.wrap !== true ? singleLineMeasurer : measurer;
      cells[index] = prepareCell(columnMeasurer, column, row.values[column.id]);
    }
    return cells;
  });
  // `measurer` — тот, которым готовились `wrap`-ячейки: именно его зовут
  // `measureCell`/`cellThresholds` для переноса.
  return { columns, rows, measurer };
}

/**
 * Число строк и признак обрезки одной ячейки при данной полезной ширине.
 *
 * Единственное место, где описана политика переполнения: этим же правилом
 * пользуется кэш кривых (`lib/curves.mjs`), иначе оптимизатор и `evaluate`
 * разошлись бы в трактовке `clamp`/пилюль/контролов.
 */
export function measureCell(measurer, cell, usable) {
  if (cell.kind === "pills" || !cell.wrap) {
    const truncatable = cell.kind !== "control" && cell.kind !== "numeric";
    return { lines: 1, truncated: truncatable && cell.naturalWidth > usable };
  }
  const raw = measurer.lineCount(cell.prepared, usable);
  const limit = cell.clamp ?? Number.POSITIVE_INFINITY;
  return {
    lines: Math.min(Number.isFinite(raw) ? raw : Number.MAX_SAFE_INTEGER, limit),
    truncated: raw > limit,
  };
}

/**
 * @param {{columns: any[], rows: any[][], measurer: any}} prepared
 * @param {Record<string, number>} widths
 * @param {{lambda?: number, collectRows?: boolean}} options
 */
export function evaluate(prepared, widths, options = {}) {
  const { lambda = 20, collectRows = false } = options;
  const { columns, rows, measurer } = prepared;
  const heights = collectRows ? new Array(rows.length) : null;

  let totalHeight = 0;
  let maxHeight = 0;
  let multiLineRows = 0;
  let rows3Plus = 0;
  let truncatedCells = 0;

  for (let rowIndex = 0; rowIndex < rows.length; rowIndex += 1) {
    const cells = rows[rowIndex];
    let maxLines = 1;
    let truncatedInRow = 0;

    for (let index = 0; index < columns.length; index += 1) {
      const column = columns[index];
      const cell = cells[index];
      const usable = widths[column.id] - CELL_PADDING_PX;
      const measured = measureCell(measurer, cell, usable);
      const lines = measured.lines;
      if (measured.truncated) truncatedInRow += 1;
      if (lines > maxLines) maxLines = lines;
    }

    const height = Math.max(MIN_ROW_HEIGHT_PX, maxLines * LINE_HEIGHT_PX + ROW_PADDING_PX);
    totalHeight += height;
    if (height > maxHeight) maxHeight = height;
    if (maxLines >= 2) multiLineRows += 1;
    if (maxLines >= 3) rows3Plus += 1;
    truncatedCells += truncatedInRow;
    if (heights) heights[rowIndex] = height;
  }

  const count = rows.length || 1;
  let p95Height = 0;
  if (heights) {
    const sorted = [...heights].sort((a, b) => a - b);
    p95Height = sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * 0.95))] ?? 0;
  }

  return {
    totalHeight,
    meanHeight: totalHeight / count,
    p95Height,
    maxHeight,
    multiLineRows,
    multiLineShare: multiLineRows / count,
    rows3Plus,
    rows3PlusShare: rows3Plus / count,
    truncatedCells,
    truncatedShare: truncatedCells / (count * columns.length),
    lambda,
    cost: totalHeight + lambda * truncatedCells,
    heights,
  };
}

/** Прогрев: одна оценка на дефолтных ширинах, чтобы JIT не попал в замер. */
export function evaluateFull(prepared, widths, options = {}) {
  return evaluate(prepared, widths, { ...options, collectRows: true });
}
