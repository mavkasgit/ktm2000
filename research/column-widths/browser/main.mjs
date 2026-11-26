/**
 * Браузерная валидация измерителя (H4, тикет #479).
 *
 * Страница не рисует продуктовый экран: она собирает ровно тот контракт,
 * который моделирует `pretext` — `table-fixed` + `<colgroup>`, `11px "Inter"` /
 * `11px "JetBrains Mono"`, `line-height: 20px` (`LINE_HEIGHT_PX`),
 * `overflow-wrap: normal`. Для каждого профиля генератора и нескольких ширин
 * колонки одна и та же строка одновременно:
 *
 * 1. уходит в `measurer.prepare()` + `measurer.lineCount(prepared, width)` —
 *    предсказание модели;
 * 2. рендерится в ячейку таблицы — фактическое число строк и высота.
 *
 * Результат — `window.runBrowserValidation()`; Playwright-спека зовёт его и
 * пишет сырой JSON в `research/column-widths/results/browser.json`.
 */
import { PROFILES, generateSheet } from "../lib/generator.mjs";
import {
  CELL_PADDING_PX,
  LINE_HEIGHT_PX,
  buildColumns,
} from "../lib/columns.mjs";
import { FONT_PX, createMeasurer } from "../lib/measurers.mjs";

/** Один seed на все профили: прогон воспроизводим. */
const SEED = 1;
const ROWS = 100;
const COLUMNS = buildColumns(11);

/** Колонки, для которых модель реально считает перенос (`wrap: true`). */
const TEXT_COLUMNS = COLUMNS.filter((column) => column.wrap === true);
/** Mono-колонки: в продукте обрезаются в одну строку, здесь — диагностика. */
const MONO_COLUMNS = COLUMNS.filter((column) => column.kind === "mono");

/**
 * Ширины — это ширина **контента** ячейки (без `CELL_PADDING_PX`).
 * 60 — заведомо уже минимальной ширины колонки: диагностика `overflow-wrap`,
 * в оптимизаторе такая ширина невозможна (`minPx` текстовых колонок = 90).
 */
const TEXT_WIDTHS = [60, 90, 120, 150, 180, 220, 280];
const MONO_WIDTHS = [60, 90, 120, 150, 220];

const H4_THRESHOLD = 0.01;
const MAX_PRODUCT_MISMATCH_SAMPLES = 200;
const MAX_OTHER_MISMATCH_SAMPLES = 40;

const FONT_SAMPLE = "АБВГДабвгдЁё 0123456789 .,—№ %";

function emptyStats() {
  return {
    cells: 0,
    nonEmpty: 0,
    empty: 0,
    lineMismatch: 0,
    heightMismatch: 0,
    wordFit: 0,
    wordFitLineMismatch: 0,
    belowWordWidth: 0,
    belowWordWidthLineMismatch: 0,
    widthMismatch: 0,
    maxLineDelta: 0,
    maxAbsHeightDelta: 0,
  };
}

function addRecord(target, record) {
  target.cells += 1;
  if (record.isEmpty) {
    target.empty += 1;
  } else {
    target.nonEmpty += 1;
    if (!record.lineMatch) {
      target.lineMismatch += 1;
      target.maxLineDelta = Math.max(
        target.maxLineDelta,
        Math.abs(record.predictedLines - record.domLines),
      );
    }
    if (!record.heightMatch) {
      target.heightMismatch += 1;
      target.maxAbsHeightDelta = Math.max(
        target.maxAbsHeightDelta,
        Math.abs(record.predictedHeight - record.contentHeight),
      );
    }
    if (record.wordFits) {
      target.wordFit += 1;
      if (!record.lineMatch) target.wordFitLineMismatch += 1;
    } else {
      target.belowWordWidth += 1;
      if (!record.lineMatch) target.belowWordWidthLineMismatch += 1;
    }
    if (!record.widthOk) target.widthMismatch += 1;
  }
}

function rate(numerator, denominator) {
  return denominator > 0 ? numerator / denominator : 0;
}

function summarize(stats) {
  return {
    ...stats,
    lineMismatchRate: rate(stats.lineMismatch, stats.nonEmpty),
    heightMismatchRate: rate(stats.heightMismatch, stats.nonEmpty),
    wordFitMismatchRate: rate(stats.wordFitLineMismatch, stats.wordFit),
    belowWordWidthMismatchRate: rate(
      stats.belowWordWidthLineMismatch,
      stats.belowWordWidth,
    ),
  };
}

async function loadFonts() {
  const [inter, mono] = await Promise.all([
    document.fonts.load(`400 ${FONT_PX}px "Inter"`, FONT_SAMPLE),
    document.fonts.load(`400 ${FONT_PX}px "JetBrains Mono"`, FONT_SAMPLE),
  ]);
  await document.fonts.ready;

  const describe = (family, faces) => ({
    family,
    faces: faces.length,
    loaded: faces.length > 0 && faces.every((face) => face.status === "loaded"),
    check: document.fonts.check(`400 ${FONT_PX}px "${family}"`, FONT_SAMPLE),
  });

  const fonts = {
    sans: describe("Inter", inter),
    mono: describe("JetBrains Mono", mono),
  };
  if (!fonts.sans.loaded || !fonts.mono.loaded) {
    throw new Error(
      `webfont не загрузился: ${JSON.stringify(fonts)} — измерять fallback бессмысленно`,
    );
  }
  return fonts;
}

function renderTable(column, width, values) {
  const table = document.createElement("table");
  table.className = "preview-table";
  table.style.width = `${width + CELL_PADDING_PX}px`;

  const colgroup = document.createElement("colgroup");
  const col = document.createElement("col");
  col.style.width = `${width + CELL_PADDING_PX}px`;
  colgroup.appendChild(col);
  table.appendChild(colgroup);

  const tbody = document.createElement("tbody");
  for (const value of values) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    if (column.font === "mono") td.className = "mono";
    const span = document.createElement("span");
    span.textContent = value ?? "";
    td.appendChild(span);
    tr.appendChild(td);
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  return table;
}

/** Число визуальных строк по фрагментам Range: у каждой строки свой `top`. */
function domLineCount(span) {
  if (!span.firstChild) return 0;
  const range = document.createRange();
  range.selectNodeContents(span);
  const tops = new Set();
  for (const rect of range.getClientRects()) {
    if (rect.width <= 0.01 || rect.height <= 0.01) continue;
    tops.add(Math.round(rect.top));
  }
  return tops.size;
}

function contentWidthOf(td) {
  const style = getComputedStyle(td);
  return (
    td.getBoundingClientRect().width -
    parseFloat(style.paddingLeft) -
    parseFloat(style.paddingRight) -
    parseFloat(style.borderLeftWidth) -
    parseFloat(style.borderRightWidth)
  );
}

function contentHeightOf(td) {
  const style = getComputedStyle(td);
  return (
    td.getBoundingClientRect().height -
    parseFloat(style.paddingTop) -
    parseFloat(style.paddingBottom) -
    parseFloat(style.borderTopWidth) -
    parseFloat(style.borderBottomWidth)
  );
}

/**
 * Меряет одну таблицу: каждая строка — одна ячейка, поэтому высота строки
 * таблицы равна высоте этой ячейки и ничем не разбавлена.
 */
function measureTable({ table, values, column, width, measurer, profile }) {
  document.body.appendChild(table);
  // Принудительный layout до `getClientRects()`.
  void table.offsetHeight;

  const records = [];
  const rows = table.tBodies[0].rows;
  for (let index = 0; index < rows.length; index += 1) {
    const text = values[index] ?? "";
    const td = rows[index].cells[0];
    const span = td.firstElementChild;

    const prepared = measurer.prepare(text, column.font);
    const predictedLines = measurer.lineCount(prepared, width);
    const maxWordWidth = measurer.maxWordWidth(prepared);
    const naturalWidth = measurer.naturalWidth(prepared);

    const isEmpty = text.length === 0;
    const domLines = isEmpty ? 0 : domLineCount(span);
    const contentWidth = contentWidthOf(td);
    const contentHeight = isEmpty ? 0 : contentHeightOf(td);
    const predictedHeight = predictedLines * LINE_HEIGHT_PX;

    records.push({
      profile,
      column: column.id,
      font: column.font,
      width,
      index,
      text,
      isEmpty,
      predictedLines,
      domLines,
      predictedHeight,
      contentHeight,
      contentWidth,
      naturalWidth,
      maxWordWidth,
      wordFits: width + 0.01 >= maxWordWidth,
      widthOk: Math.abs(contentWidth - width) <= 0.51,
      lineMatch: isEmpty || predictedLines === domLines,
      heightMatch:
        isEmpty || Math.abs(predictedHeight - contentHeight) <= 0.51,
    });
  }

  table.remove();
  return records;
}

function pushSample(samples, record) {
  if (record.isEmpty || (record.lineMatch && record.heightMatch)) return;
  samples.push({
    profile: record.profile,
    column: record.column,
    width: record.width,
    index: record.index,
    text: record.text,
    predictedLines: record.predictedLines,
    domLines: record.domLines,
    predictedHeight: record.predictedHeight,
    contentHeight: record.contentHeight,
    maxWordWidth: record.maxWordWidth,
    wordFits: record.wordFits,
  });
}

async function runValidation() {
  const startedAt = new Date().toISOString();
  const root = document.getElementById("root");
  const status = document.getElementById("status");
  if (root && status) root.replaceChildren(status);

  const fonts = await loadFonts();
  if (status) status.textContent = "Шрифты загружены, измеряю…";

  const measurer = await createMeasurer("pretext");

  const product = emptyStats();
  const narrow = emptyStats();
  const monoDiagnostic = emptyStats();
  const byProfile = {};
  const byColumn = {};
  const byWidth = {};
  const mismatches = { product: [], narrow: [], mono: [] };

  const bucket = (map, key) => {
    map[key] ??= emptyStats();
    return map[key];
  };
  const columnBucket = (id) => {
    byColumn[id] ??= {
      product: emptyStats(),
      narrow: emptyStats(),
      mono: emptyStats(),
    };
    return byColumn[id];
  };

  for (const profile of PROFILES) {
    byProfile[profile] = {
      product: emptyStats(),
      narrow: emptyStats(),
      mono: emptyStats(),
    };
    const sheet = generateSheet({
      profile,
      rows: ROWS,
      columns: COLUMNS,
      seed: SEED,
    });

    for (const column of TEXT_COLUMNS) {
      const values = sheet.rows.map((row) => row.values[column.id] ?? "");
      for (const width of TEXT_WIDTHS) {
        const table = renderTable(column, width, values);
        const records = measureTable({
          table,
          values,
          column,
          width,
          measurer,
          profile,
        });
        const isProductWidth = width >= column.minPx;
        for (const record of records) {
          const target = isProductWidth ? product : narrow;
          addRecord(target, record);
          addRecord(isProductWidth ? byProfile[profile].product : byProfile[profile].narrow, record);
          addRecord(
            columnBucket(column.id)[isProductWidth ? "product" : "narrow"],
            record,
          );
          addRecord(bucket(byWidth, String(width)), record);
          pushSample(
            isProductWidth ? mismatches.product : mismatches.narrow,
            record,
          );
        }
      }
    }

    for (const column of MONO_COLUMNS) {
      const values = sheet.rows.map((row) => row.values[column.id] ?? "");
      for (const width of MONO_WIDTHS) {
        const table = renderTable(column, width, values);
        const records = measureTable({
          table,
          values,
          column,
          width,
          measurer,
          profile,
        });
        for (const record of records) {
          addRecord(monoDiagnostic, record);
          addRecord(byProfile[profile].mono, record);
          addRecord(columnBucket(column.id).mono, record);
          pushSample(mismatches.mono, record);
        }
      }
    }

    if (status) {
      status.textContent = `Профиль ${profile}: готово`;
    }
  }

  const productSummary = summarize(product);
  const h4 = {
    threshold: H4_THRESHOLD,
    cells: productSummary.nonEmpty,
    lineMismatch: productSummary.lineMismatch,
    lineMismatchRate: productSummary.lineMismatchRate,
    heightMismatch: productSummary.heightMismatch,
    heightMismatchRate: productSummary.heightMismatchRate,
    wordFitCells: productSummary.wordFit,
    wordFitLineMismatch: productSummary.wordFitLineMismatch,
    wordFitLineMismatchRate: productSummary.wordFitMismatchRate,
    belowWordWidthCells: productSummary.belowWordWidth,
    belowWordWidthLineMismatch: productSummary.belowWordWidthLineMismatch,
    belowWordWidthLineMismatchRate:
      productSummary.belowWordWidthMismatchRate,
    pass:
      productSummary.lineMismatchRate < H4_THRESHOLD &&
      productSummary.heightMismatchRate < H4_THRESHOLD,
  };

  const result = {
    meta: {
      ticket: 479,
      epic: 475,
      hypothesis: "H4: pretext расходится с DOM менее чем на 1% строк",
      startedAt,
      seed: SEED,
      rowsPerProfile: ROWS,
      profiles: PROFILES,
      textColumns: TEXT_COLUMNS.map((column) => column.id),
      monoColumns: MONO_COLUMNS.map((column) => column.id),
      textWidths: TEXT_WIDTHS,
      monoWidths: MONO_WIDTHS,
      fontPx: FONT_PX,
      lineHeightPx: LINE_HEIGHT_PX,
      cellPaddingPx: CELL_PADDING_PX,
      overflowWrap: "normal",
      whiteSpace: "normal",
      fonts,
      environment: {
        userAgent: navigator.userAgent,
        devicePixelRatio: window.devicePixelRatio,
        viewport: { width: window.innerWidth, height: window.innerHeight },
      },
    },
    h4,
    product: productSummary,
    narrowDiagnostic: summarize(narrow),
    monoDiagnostic: summarize(monoDiagnostic),
    byProfile: Object.fromEntries(
      Object.entries(byProfile).map(([profile, stats]) => [
        profile,
        {
          product: summarize(stats.product),
          narrow: summarize(stats.narrow),
          mono: summarize(stats.mono),
        },
      ]),
    ),
    byColumn: Object.fromEntries(
      Object.entries(byColumn).map(([column, stats]) => [
        column,
        {
          product: summarize(stats.product),
          narrow: summarize(stats.narrow),
          mono: summarize(stats.mono),
        },
      ]),
    ),
    byWidth: Object.fromEntries(
      Object.entries(byWidth).map(([width, stats]) => [
        width,
        summarize(stats),
      ]),
    ),
    mismatches: {
      product: mismatches.product.slice(0, MAX_PRODUCT_MISMATCH_SAMPLES),
      narrow: mismatches.narrow.slice(0, MAX_OTHER_MISMATCH_SAMPLES),
      mono: mismatches.mono.slice(0, MAX_OTHER_MISMATCH_SAMPLES),
    },
  };

  if (status) {
    status.textContent = `H4: ${(h4.lineMismatchRate * 100).toFixed(2)}% (${h4.pass ? "pass" : "fail"})`;
  }
  return result;
}

let validation = null;

/**
 * Идемпотентный вход для Playwright: считает один раз, повторный вызов отдаёт
 * тот же результат (страница не должна зависеть от порядка вызовов).
 */
window.runBrowserValidation = () => {
  validation ??= runValidation();
  return validation;
};

window.__ready = false;
loadFonts()
  .then(() => {
    const status = document.getElementById("status");
    if (status) status.textContent = "Готово к измерению";
    window.__ready = true;
  })
  .catch((error) => {
    const status = document.getElementById("status");
    if (status) status.textContent = `Ошибка загрузки шрифтов: ${error.message}`;
    window.__fontError = String(error?.stack ?? error);
  });
