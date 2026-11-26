/**
 * Рантайм адаптивной политики (#489): продуктовая `computePreviewColumnWidths`
 * считает **обе** раскладки (`H_full` и `H_trunc`), а затем выбирает по θ.
 *
 * Гейт §15 — тот же: медиана расчёта на 300 строках × 11 колонках при CPU
 * throttling 4× ≤ 100 мс. Дополнительно меряется стоимость самой проверки
 * (`H_trunc`: один `lineCount` «Ошибок» на строку) — это и есть цена
 * «считать обе раскладки» против «считать только полный текст».
 *
 * Модуль — **настоящий** продуктовый, собранный Vite'ом в
 * `browser/.product-build` (`node research/column-widths/adaptive.mjs` или
 * `beforeAll` в `adaptive.spec.mjs`). Копии формул нет: иначе замер доказывал
 * бы модель, а не код, который поедет в продукт.
 *
 * Повторы (9) идут без прогрева: продукт считает лист один раз. `pretext`
 * кэширует сегменты, поэтому перед каждым повтором кэш сбрасывается.
 */
import { buildColumns } from "../lib/columns.mjs";
import { generateSheet } from "../lib/generator.mjs";
import { createMeasurer } from "../lib/measurers.mjs";
import { pillsWidth } from "../lib/text.mjs";
import { loadFonts } from "./fonts.mjs";

const SEED = 1;
/** То же число строк, что в гейте #483: 300 — допустимая подвыборка H2. */
const ROWS = 300;
const COLUMN_COUNT = 11;
const REPS = 9;
const PROFILES = ["realistic", "long-tail"];
const WIDTHS = [
  { tableWidth: 1180, pillsMaxTruncatedShare: 0.3279 },
  { tableWidth: 1400, pillsMaxTruncatedShare: 0.1949 },
  { tableWidth: 1500, pillsMaxTruncatedShare: 0.1297 },
  { tableWidth: 1600, pillsMaxTruncatedShare: 0.0564 },
  { tableWidth: 1920, pillsMaxTruncatedShare: 0.0001 },
];
const THRESHOLD_MS = 100;
const THRESHOLD = 0.05;

/** Метрики строки — из CSS предпросмотра (как `previewColumnWidths`). */
const FONTS = {
  name: { family: '"Inter"', sizePx: 11, weight: 400, lineHeightPx: 16.5 },
  errors: { family: '"Inter"', sizePx: 11, weight: 500, lineHeightPx: 15.125 },
  pill: { family: '"Inter"', sizePx: 10, weight: 500, lineHeightPx: 20 },
};

const percentile = (values, p) => {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const position = (sorted.length - 1) * p;
  const lower = Math.floor(position);
  const upper = Math.ceil(position);
  if (lower === upper) return sorted[lower];
  return sorted[lower] + (sorted[upper] - sorted[lower]) * (position - lower);
};

const round = (value, digits = 2) => {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
};

const summarize = (values) => {
  const sorted = [...values].sort((a, b) => a - b);
  return {
    count: values.length,
    min: round(sorted[0]),
    median: round(percentile(values, 0.5)),
    p95: round(percentile(values, 0.95)),
    max: round(sorted[sorted.length - 1]),
  };
};

/** Research-измеритель → `PreviewTextMeasurer` продукта. */
function toProductMeasurer(base) {
  return {
    prepare: (text) => base.prepare(text, "sans"),
    naturalWidth: (prepared) => base.naturalWidth(prepared),
    maxWordWidth: (prepared) => base.maxWordWidth(prepared),
    lineCount: (prepared, usableWidth) => base.lineCount(prepared, usableWidth),
  };
}

/** Строки листа в контракте продукта: тот же текст, что печатает ячейка. */
function buildRows(sheet) {
  return sheet.rows.map((row, index) => ({
    rowKey: index + 1,
    nameText: String(row.values.source_name ?? ""),
    errorsText: String(row.values.errors ?? ""),
    errorsWraps: true,
    pillWidth: pillsWidth(row.values.operations, "sans"),
  }));
}

async function runBenchmark() {
  const status = document.getElementById("status");
  const say = (text) => {
    if (status) status.textContent = text;
  };

  let product;
  try {
    product = await import("./.product-build/previewColumnWidths.mjs");
  } catch (error) {
    window.__bundleError = String(error?.stack ?? error);
    throw error;
  }
  const { computePreviewColumnWidths } = product;

  const fonts = await loadFonts();
  say("Шрифты загружены, создаю измеритель…");
  const base = await createMeasurer("pretext");
  const measurer = toProductMeasurer(base);
  const columns = buildColumns(COLUMN_COUNT);

  const scenarios = [];
  for (const profile of PROFILES) {
    const sheet = generateSheet({ profile, rows: ROWS, columns, seed: SEED });
    const rows = buildRows(sheet);
    for (const width of WIDTHS) {
      scenarios.push({ profile, rows, ...width });
    }
  }

  const allTotal = [];
  const allBaselinePass = [];
  let cold = null;

  const measured = [];
  for (const scenario of scenarios) {
    say(`${scenario.profile} @ ${scenario.tableWidth}: замер…`);
    const reps = [];
    let result = null;

    for (let rep = 0; rep < REPS; rep += 1) {
      base.clearCache?.();
      const t0 = performance.now();
      result = computePreviewColumnWidths({
        containerWidth: scenario.tableWidth,
        rows: scenario.rows,
        measurer,
        fonts: FONTS,
      });
      const totalMs = performance.now() - t0;
      reps.push(totalMs);
      allTotal.push(totalMs);
      if (!cold) {
        cold = {
          profile: scenario.profile,
          tableWidth: scenario.tableWidth,
          totalMs,
        };
      }
    }

    // Цена проверки «H_trunc»: один `lineCount` «Ошибок» на строку на текущей
    // доле колонки (11% — из `remainderPreviewColumns`).
    const baselineErrorsUsable = 0.11 * scenario.tableWidth - 12;
    base.clearCache?.();
    const t1 = performance.now();
    for (const row of scenario.rows) {
      measurer.lineCount(
        measurer.prepare(row.errorsText, FONTS.errors),
        baselineErrorsUsable,
      );
    }
    const baselinePassMs = performance.now() - t1;
    allBaselinePass.push(baselinePassMs);

    measured.push({
      profile: scenario.profile,
      tableWidth: scenario.tableWidth,
      reps: reps.map((value) => round(value)),
      summary: summarize(reps),
      baselinePassMs: round(baselinePassMs),
      result: {
        policy: result.policy,
        fullTextHeightPx: result.fullTextHeightPx,
        baselineHeightPx: result.baselineHeightPx,
        heightDeltaPct: round(
          (result.fullTextHeightPx / result.baselineHeightPx - 1) * 100,
          2,
        ),
        nameWidthPx: result.nameWidthPx,
        errorsWidthPx: result.errorsWidthPx,
        pillsWidthPx: result.pillsFloorPx,
        minTableWidthPx: result.minTableWidthPx,
        overflow: result.overflow,
        ruleSatisfied:
          result.policy ===
          (result.fullTextHeightPx <= result.baselineHeightPx * (1 + THRESHOLD)
            ? "full-text"
            : "baseline"),
      },
    });
  }

  const overall = {
    total: summarize(allTotal),
    baselinePass: summarize(allBaselinePass),
  };
  const pass = overall.total.median <= THRESHOLD_MS;

  const payload = {
    meta: {
      ticket: 489,
      startedAt: new Date().toISOString(),
      seed: SEED,
      rows: ROWS,
      columnCount: COLUMN_COUNT,
      profiles: PROFILES,
      widths: WIDTHS,
      reps: REPS,
      threshold: THRESHOLD,
      productModule: "frontend/src/features/spg/lib/previewColumnWidths.ts",
      fonts,
      cpuThrottling: window.__throttleRate ?? 4,
      devicePixelRatio: window.devicePixelRatio,
      userAgent: navigator.userAgent,
      hardwareConcurrency: navigator.hardwareConcurrency,
    },
    configs: measured,
    overall,
    cold: {
      profile: cold.profile,
      tableWidth: cold.tableWidth,
      totalMs: round(cold.totalMs),
    },
    threshold: {
      ms: THRESHOLD_MS,
      basis: "медиана суммарного времени по всем повторам ≤ 100 мс",
      pass,
      medianTotalMs: overall.total.median,
      p95TotalMs: overall.total.p95,
      coldTotalMs: round(cold.totalMs),
    },
  };

  say(`Готово: медиана ${overall.total.median} мс — ${pass ? "pass" : "fail"}`);
  return payload;
}

let benchmark = null;

window.runAdaptiveBenchmark = () => {
  benchmark ??= runBenchmark();
  return benchmark;
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
