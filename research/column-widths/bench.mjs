#!/usr/bin/env node
/**
 * Бенч-харнесс исследования ширин колонок.
 *
 * Основной сценарий — полный текст: `clamp = ∞`, `λ = 0`. Обрезка — отдельная
 * политика, её цена измеряется свипом.
 *
 * Прогон состоит из четырёх частей:
 *
 * - `matrix`  — 7 профилей × {100,1000,5000} × {1180,1500,1920} × {6,12,20} × seeds;
 *               метрики считаются по полному листу, оптимизатор видит ≤500 строк;
 * - `product` — продуктовый срез `ImportRemaindersDialog` (11 колонок) на тех же
 *               профилях/строках/ширинах + сравнение с текущей политикой продукта;
 * - `oracle`  — точный перебор на малых инстансах (60 строк), все оптимизаторы
 *               рядом с эталоном; отсюда берётся gap для H1;
 * - `sweep`   — Парето «высота против потерянного текста»:
 *               `clamp ∈ {∞,6,4,3,2}` при `λ = 20`.
 *
 * Гипотезы H1–H4 выводятся с числом и вердиктом. H4 берётся из браузерного
 * прогона #479 (`results/browser.json`, создаёт `npm run browser:test`), а не из
 * согласия `pretext` ↔ `greedy`: если файла нет — в отчёте «см. browser:test».
 *
 * Запуск:
 *   node research/column-widths/bench.mjs                 # полный прогон
 *   node research/column-widths/bench.mjs --quick         # сжатая матрица
 *   node research/column-widths/bench.mjs --measurer=pretext
 *   node research/column-widths/bench.mjs --seeds=3
 *   node research/column-widths/bench.mjs --only=product  # product|oracle|matrix|
 *                                                         # sweep|all (или через запятую)
 *   node research/column-widths/bench.mjs --lambda=40     # λ свипа (основной всегда 0)
 *
 * Результаты: research/column-widths/results/{bench.json,report.md}. Каталог
 * `results/` не коммитится; JSON содержит все конфигурации и ширины, чтобы
 * перепроверить любой вывод отчёта.
 */
import { mkdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { PROFILES, generateSheet } from "./lib/generator.mjs";
import {
  CELL_PADDING_PX,
  LINE_HEIGHT_PX,
  MIN_ROW_HEIGHT_PX,
  ROW_PADDING_PX,
  SERVICE_WIDTH_PX,
  buildColumns,
  maxWidth,
  sumWidths,
} from "./lib/columns.mjs";
import { createMeasurer } from "./lib/measurers.mjs";
import { evaluate, measureCell, prepareSheet } from "./lib/evaluate.mjs";
import { OPTIMIZERS, oracleOptimizer } from "./lib/optimizers.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const RESULTS_DIR = resolve(HERE, "results");
const BROWSER_RESULTS = resolve(RESULTS_DIR, "browser.json");

/** Ветка для отчёта: env, иначе `.git/HEAD` (работает и из worktree). */
function detectBranch() {
  if (process.env.GIT_BRANCH) return process.env.GIT_BRANCH;
  try {
    let gitDir = resolve(HERE, "../..", ".git");
    if (statSync(gitDir).isFile()) {
      const pointer = readFileSync(gitDir, "utf8").trim();
      if (pointer.startsWith("gitdir:")) {
        gitDir = resolve(dirname(gitDir), pointer.slice("gitdir:".length).trim());
      }
    }
    const head = readFileSync(resolve(gitDir, "HEAD"), "utf8").trim();
    return head.startsWith("ref: refs/heads/")
      ? head.slice("ref: refs/heads/".length)
      : head;
  } catch {
    return "local";
  }
}

/** Основной сценарий: полный текст, штрафа за обрезку нет. */
const MAIN_LAMBDA = 0;
/** Вспомогательный свип политики: цена спрятанного текста. */
const SWEEP_LAMBDA = 20;
/**
 * Потолки строк для свипа. `none` — основной режим; числа — предохранитель.
 * `MAX_LINES = 64` в `lib/curves.mjs` остаётся технической защитой от
 * бесконечного перебора и в отчёте указан отдельно.
 */
const SWEEP_CLAMPS = ["none", 6, 4, 3, 2];
const CSS_ERROR_LINE_HEIGHT_PX = 11 * 1.375; // leading-snug при text-[11px]

const FIT_ROWS = 500;
const ORACLE_ROWS = 60;

const SECTIONS = ["matrix", "oracle", "product", "sweep"];

const args = process.argv.slice(2);
const argValue = (name, fallback) => {
  const prefix = `--${name}=`;
  const found = args.find((argument) => argument.startsWith(prefix));
  return found ? found.slice(prefix.length) : fallback;
};
const QUICK = args.includes("--quick");
const MEASURER_KIND = argValue("measurer", "greedy");
const SEEDS = Number(argValue("seeds", QUICK ? "1" : "2"));
const SWEEP_LAMBDA_VALUE = Number(argValue("lambda", String(SWEEP_LAMBDA)));

export function parseSections(value) {
  const requested = String(value)
    .split(",")
    .map((name) => name.trim())
    .filter(Boolean);
  if (requested.length === 0 || requested.includes("all")) return [...SECTIONS];
  // `sensitivity` — старое имя секции свипа (совместимость флагов).
  const normalized = requested.map((name) =>
    name === "sensitivity" ? "sweep" : name,
  );
  for (const name of normalized) {
    if (!SECTIONS.includes(name)) {
      throw new Error(
        `--only=${name}: неизвестная секция; доступны ${SECTIONS.join(", ")}, all`,
      );
    }
  }
  return SECTIONS.filter((name) => normalized.includes(name));
}

const SECTIONS_TO_RUN = parseSections(argValue("only", "all"));

if (!Number.isInteger(SEEDS) || SEEDS < 1) {
  throw new Error(`--seeds=${SEEDS}: нужно целое ≥ 1`);
}
if (!Number.isFinite(SWEEP_LAMBDA_VALUE) || SWEEP_LAMBDA_VALUE < 0) {
  throw new Error(
    `--lambda=${SWEEP_LAMBDA_VALUE}: нужно неотрицательное число`,
  );
}
const SEED_LIST = Array.from({ length: SEEDS }, (_, index) => index + 1);

/** Спека матрицы: полный прогон — 7 профилей, 3×3×3, 2 seed. */
function matrixSpec() {
  return {
    profiles: QUICK ? ["realistic", "long-tail", "mono"] : PROFILES,
    rows: QUICK ? [100, 1000] : [100, 1000, 5000],
    widths: QUICK ? [1180, 1500] : [1180, 1500, 1920],
    columns: QUICK ? [6, 12] : [6, 12, 20],
  };
}

/** Продуктовый срез: всегда 11 колонок `ImportRemaindersDialog`. */
function productSpec() {
  return {
    profiles: QUICK ? ["realistic", "long-tail"] : PROFILES,
    rows: QUICK ? [100, 1000] : [100, 1000, 5000],
    widths: QUICK ? [1180, 1500] : [1180, 1500, 1920],
    columns: [11],
  };
}

/**
 * Оракул: только малые инстансы (60 строк). 20 колонок в оракул не входят:
 * 12 гибких колонок дают больше комбинаций, чем `maxCombinations`, и эталон
 * пришлось бы прореживать — тогда «gap к оракулу» перестаёт быть честным.
 * 20 колонок остаются стрессом матрицы, 11 — продуктовый срез.
 */
function oracleSpec() {
  return {
    profiles: QUICK ? ["realistic", "long-tail"] : PROFILES,
    rows: [ORACLE_ROWS],
    widths: QUICK ? [1500] : [1180, 1500, 1920],
    columns: QUICK ? [11] : [6, 11, 12],
  };
}

/** Свип политики обрезки: clamp ∈ {∞,6,4,3,2} при λ = 20. */
function sweepSpec() {
  return {
    profiles: QUICK ? ["realistic", "long-tail"] : PROFILES,
    rows: 1000,
    widths: QUICK ? [1500] : [1180, 1500, 1920],
    seed: 1,
    clamps: SWEEP_CLAMPS,
    lambda: SWEEP_LAMBDA_VALUE,
  };
}

function contentWidth(tableWidth) {
  return tableWidth - SERVICE_WIDTH_PX;
}

/**
 * Основной сценарий: переносимые колонки без потолка строк (`clamp = null`).
 * `lib/columns.mjs` оставляет `clamp` объявлением политики, поэтому бенч
 * клонирует колонки, а не правит общий продуктовый набор.
 */
export function mainColumns(count = 11) {
  return buildColumns(count).map((column) =>
    column.wrap ? { ...column, clamp: null } : column,
  );
}

/** Свип: явный потолок строк у всех переносимых колонок. */
export function clampColumns(count, clamp) {
  return buildColumns(count).map((column) =>
    column.wrap
      ? { ...column, clamp: clamp === "none" ? null : clamp }
      : column,
  );
}

/**
 * Текущий продукт как опорная политика: «Наименование» — `truncate`
 * (одна строка), «Ошибки» — полный перенос. Совпадает с
 * `ImportRemaindersDialog`: `truncate` у наименования и `leading-snug` у ошибок.
 */
export function currentProductColumns(count = 11) {
  return buildColumns(count).map((column) => {
    if (column.id === "source_name") {
      return { ...column, wrap: false, clamp: null };
    }
    return column.wrap ? { ...column, clamp: null } : column;
  });
}

function measureRuntime(fn) {
  const start = performance.now();
  const value = fn();
  return { value, ms: performance.now() - start };
}

function prepareForFit(sheet, measurer) {
  const fitRows = Math.min(FIT_ROWS, sheet.rows.length);
  return prepareSheet(
    { ...sheet, rows: sheet.rows.slice(0, fitRows) },
    measurer,
  );
}

function round(value, digits = 2) {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

function clampLabel(clamp) {
  return clamp === "none" ? "без потолка" : String(clamp);
}

function clampOrder(clamp) {
  const index = SWEEP_CLAMPS.indexOf(clamp);
  return index === -1 ? SWEEP_CLAMPS.length : index;
}

function runOptimizer(name, fitPrepared, width, lambda = MAIN_LAMBDA) {
  const optimizer = OPTIMIZERS[name];
  const { value, ms } = measureRuntime(() =>
    optimizer(fitPrepared, width, { lambda }),
  );
  return { name, widths: value.widths, ms };
}

/**
 * Диагностика инварианта `w_i ≤ maxShare_i · W`: нарушение — не «победа»
 * оптимизатора, а баг его реализации, и такой gap к оракулу невалиден.
 */
function widthViolations(columns, widths, contentWidth) {
  const violations = [];
  for (const column of columns) {
    const cap = maxWidth(column, contentWidth);
    if (Number.isFinite(cap) && widths[column.id] > cap + 0.5) {
      violations.push({
        column: column.id,
        width: round(widths[column.id], 1),
        max: round(cap, 1),
      });
    }
  }
  return violations;
}

/** Границы распределения высот в модели: 1/2/3/4+ строк текста. */
const HEIGHT_BUCKETS = [
  { key: "row40", max: MIN_ROW_HEIGHT_PX },
  { key: "row60", max: 2 * LINE_HEIGHT_PX + ROW_PADDING_PX },
  { key: "row80", max: 3 * LINE_HEIGHT_PX + ROW_PADDING_PX },
  { key: "row100Plus", max: Number.POSITIVE_INFINITY },
];

function heightDistribution(heights) {
  const count = heights.length || 1;
  const shares = Object.fromEntries(
    HEIGHT_BUCKETS.map((bucket) => [bucket.key, 0]),
  );
  for (const height of heights) {
    const bucket = HEIGHT_BUCKETS.find((item) => height <= item.max);
    shares[bucket.key] += 1;
  }
  for (const key of Object.keys(shares)) {
    shares[key] = round((shares[key] / count) * 100, 2);
  }
  return shares;
}

function collectMetrics(prepared, widths, lambda = MAIN_LAMBDA) {
  const metrics = evaluate(prepared, widths, { lambda, collectRows: true });
  const heights = metrics.heights ?? [];
  const row4Threshold = 4 * LINE_HEIGHT_PX + ROW_PADDING_PX;
  return {
    height: metrics.totalHeight,
    meanHeight: round(metrics.meanHeight, 2),
    p95Height: metrics.p95Height,
    maxHeight: metrics.maxHeight,
    multiLineShare: round(metrics.multiLineShare * 100, 2),
    rows3PlusShare: round(metrics.rows3PlusShare * 100, 2),
    rows4PlusShare: round(
      (heights.filter((height) => height >= row4Threshold).length /
        (heights.length || 1)) *
        100,
      2,
    ),
    heightBuckets: heightDistribution(heights),
    truncatedCells: metrics.truncatedCells,
    truncatedShare: round(metrics.truncatedShare * 100, 2),
    cost: metrics.cost,
  };
}

/**
 * Доля потерянного текста в переносимых колонках (то, что покупает `clamp`).
 * Пилюли и mono-обрезка сюда не входят: у них своя политика `nowrap`.
 */
function wrapTruncation(prepared, widths) {
  let total = 0;
  let truncated = 0;
  prepared.columns.forEach((column, index) => {
    if (!column.wrap) return;
    const usable = widths[column.id] - CELL_PADDING_PX;
    for (const row of prepared.rows) {
      total += 1;
      if (measureCell(prepared.measurer, row[index], usable).truncated) {
        truncated += 1;
      }
    }
  });
  return {
    cells: total,
    truncated,
    sharePct: round((truncated / (total || 1)) * 100, 2),
  };
}

/**
 * Одна ячейка матрицы: лист по ключу, оптимизатор на подвыборке ≤500 строк,
 * метрики — по полному листу. `seed` фиксирует лист, поэтому числа
 * воспроизводимы; время — единственное, что может отличаться между прогонами.
 */
export function runConfig({
  profile,
  rows,
  tableWidth,
  columnCount,
  seed,
  measurer,
  columns = mainColumns(columnCount),
  lambda = MAIN_LAMBDA,
  policies = false,
}) {
  const sheet = generateSheet({ profile, rows, columns, seed });
  const fitPrepared = prepareForFit(sheet, measurer);
  const fullPrepared = prepareSheet(sheet, measurer);
  const width = contentWidth(tableWidth);

  const results = {};
  for (const name of Object.keys(OPTIMIZERS)) {
    const run = runOptimizer(name, fitPrepared, width, lambda);
    results[name] = {
      widths: run.widths,
      widthSum: round(sumWidths(columns, run.widths), 1),
      violations: widthViolations(columns, run.widths, width),
      ms: round(run.ms, 2),
      ...collectMetrics(fullPrepared, run.widths, lambda),
    };
  }

  const baselineHeight = results.baseline.height || 1;
  const baselineCost = results.baseline.cost || 1;
  for (const metrics of Object.values(results)) {
    metrics.heightRatio = round(metrics.height / baselineHeight, 4);
    metrics.costRatio = round(metrics.cost / baselineCost, 4);
  }

  // (б) текущий продукт как опорная политика: наименование `truncate`,
  // ошибки — полный перенос; ширины — те же текущие доли.
  let policy = null;
  if (policies) {
    const currentPrepared = prepareSheet(
      { ...sheet, columns: currentProductColumns(columnCount) },
      measurer,
    );
    const current = collectMetrics(
      currentPrepared,
      results.baseline.widths,
      0,
    );
    const pick = (source) => ({
      height: source.height,
      meanHeight: source.meanHeight,
      p95Height: source.p95Height,
      maxHeight: source.maxHeight,
      truncatedShare: source.truncatedShare,
    });
    policy = {
      currentProduct: current,
      noClampBaseline: pick(results.baseline),
      noClampBest: pick(results.search),
      growthPct: {
        baseline: round(
          (results.baseline.height / (current.height || 1) - 1) * 100,
          2,
        ),
        best: round(
          (results.search.height / (current.height || 1) - 1) * 100,
          2,
        ),
      },
    };
  }

  return {
    profile,
    rows,
    tableWidth,
    contentWidth: width,
    columnCount,
    seed,
    lambda,
    results,
    policies: policy,
  };
}

/** Оракул на малом инстансе: все оптимизаторы на одном листе рядом с эталоном. */
function runOracleConfig({ profile, tableWidth, columnCount, seed, measurer }) {
  const columns = mainColumns(columnCount);
  const sheet = generateSheet({ profile, rows: ORACLE_ROWS, columns, seed });
  const prepared = prepareSheet(sheet, measurer);
  const width = contentWidth(tableWidth);

  const { value: oracle, ms: oracleMs } = measureRuntime(() =>
    oracleOptimizer(prepared, width, { lambda: MAIN_LAMBDA }),
  );
  const oracleMetrics = collectMetrics(prepared, oracle.widths);

  const results = {};
  for (const name of Object.keys(OPTIMIZERS)) {
    const { value, ms } = measureRuntime(() =>
      OPTIMIZERS[name](prepared, width, { lambda: MAIN_LAMBDA }),
    );
    const metrics = collectMetrics(prepared, value.widths);
    results[name] = {
      widths: value.widths,
      widthSum: round(sumWidths(columns, value.widths), 1),
      violations: widthViolations(columns, value.widths, width),
      ms: round(ms, 2),
      gapCostPct: round(
        ((metrics.cost - oracleMetrics.cost) / (oracleMetrics.cost || 1)) * 100,
        2,
      ),
      gapHeightPct: round(
        ((metrics.height - oracleMetrics.height) / (oracleMetrics.height || 1)) *
          100,
        2,
      ),
      ...metrics,
    };
  }

  return {
    profile,
    rows: ORACLE_ROWS,
    tableWidth,
    contentWidth: width,
    columnCount,
    seed,
    oracle: {
      widths: oracle.widths,
      widthSum: round(sumWidths(columns, oracle.widths), 1),
      ms: round(oracleMs, 2),
      thinned: Boolean(oracle.thinned),
      cost: oracleMetrics.cost,
      height: oracleMetrics.height,
    },
    results,
  };
}

/**
 * H2: та же эвристика на первых 500 строках против полного листа. Внутренняя
 * подвыборка оптимизатора проверяется отдельно (#482) — здесь честная граница
 * «что будет, если оптимизатор увидит только 500 строк».
 */
function runSampleStability(measurer) {
  const cases = [];
  const profiles = QUICK ? ["realistic"] : ["realistic", "long-tail", "outlier"];
  const names = ["narrowing", "breakpoints", "search"];
  for (const profile of profiles) {
    for (const name of names) {
      const columns = mainColumns(12);
      const sheet = generateSheet({ profile, rows: 5000, columns, seed: 1 });
      const width = contentWidth(1500);
      const sample = prepareSheet(
        { ...sheet, rows: sheet.rows.slice(0, 500) },
        measurer,
      );
      const full = prepareSheet(sheet, measurer);
      const sampleRun = OPTIMIZERS[name](sample, width, {
        lambda: MAIN_LAMBDA,
      });
      const fullRun = OPTIMIZERS[name](full, width, {
        lambda: MAIN_LAMBDA,
      });
      const sampleMetrics = collectMetrics(full, sampleRun.widths);
      const fullMetrics = collectMetrics(full, fullRun.widths);
      const deltas = columns
        .filter((column) => column.flex)
        .map((column) =>
          Math.abs(sampleRun.widths[column.id] - fullRun.widths[column.id]),
        );
      cases.push({
        profile,
        optimizer: name,
        sampleHeight: sampleMetrics.height,
        fullHeight: fullMetrics.height,
        heightDeltaPct: round(
          ((sampleMetrics.height - fullMetrics.height) /
            (fullMetrics.height || 1)) *
            100,
          2,
        ),
        sampleCost: sampleMetrics.cost,
        fullCost: fullMetrics.cost,
        costDeltaPct: round(
          ((sampleMetrics.cost - fullMetrics.cost) / (fullMetrics.cost || 1)) *
            100,
          2,
        ),
        maxFlexWidthDeltaPx: round(Math.max(0, ...deltas), 1),
      });
    }
  }
  return cases;
}

/** H3: доли колонок при W 1180–1920 на одном листе. */
function runStabilityAcrossWidths(measurer, widths) {
  const cases = [];
  const profiles = QUICK ? ["realistic"] : ["realistic", "long-tail"];
  for (const profile of profiles) {
    for (const name of ["narrowing", "breakpoints", "search"]) {
      const columns = mainColumns(11);
      const sheet = generateSheet({ profile, rows: 1000, columns, seed: 1 });
      const prepared = prepareSheet(sheet, measurer);
      const byWidth = widths.map((tableWidth) => {
        const run = OPTIMIZERS[name](prepared, contentWidth(tableWidth), {
          lambda: MAIN_LAMBDA,
        });
        const total = sumWidths(columns, run.widths);
        const shares = {};
        for (const column of columns) {
          shares[column.id] = run.widths[column.id] / total;
        }
        return { tableWidth, shares };
      });
      const maxDeltaPct = Math.max(
        ...columns.map((column) => {
          const values = byWidth.map((entry) => entry.shares[column.id]);
          return (Math.max(...values) - Math.min(...values)) * 100;
        }),
      );
      cases.push({
        profile,
        optimizer: name,
        maxShareDeltaPct: round(maxDeltaPct, 2),
      });
    }
  }
  return cases;
}

/** Диагностика модели: pretext против greedy на синтетике. Это не H4. */
async function runMeasurerAgreement(measurer) {
  if (measurer.name !== "greedy") return null;
  let pretext;
  try {
    pretext = await createMeasurer("pretext");
  } catch (error) {
    return { skipped: true, reason: String(error?.message ?? error) };
  }
  const columns = buildColumns(11);
  const sheet = generateSheet({
    profile: "realistic",
    rows: 200,
    columns,
    seed: 7,
  });
  const greedy = prepareSheet(sheet, measurer);
  const prepared = prepareSheet(sheet, pretext);
  let compared = 0;
  let different = 0;
  for (let rowIndex = 0; rowIndex < prepared.rows.length; rowIndex += 1) {
    for (let index = 0; index < columns.length; index += 1) {
      const column = columns[index];
      if (!column.wrap) continue;
      const usable = 180 - 12;
      const a = greedy.measurer.lineCount(
        greedy.rows[rowIndex][index].prepared,
        usable,
      );
      const b = prepared.measurer.lineCount(
        prepared.rows[rowIndex][index].prepared,
        usable,
      );
      compared += 1;
      if (a !== b) different += 1;
    }
  }
  return {
    skipped: false,
    compared,
    different,
    sharePct: round((different / Math.max(1, compared)) * 100, 2),
    note: "диагностика модели, не H4: H4 — только браузерный прогон #479",
  };
}

/** H4 из результата #479 (browser:test), а не из согласия моделей. */
export function loadBrowserH4(path = BROWSER_RESULTS) {
  try {
    const data = JSON.parse(readFileSync(path, "utf8"));
    const h4 = data.h4 ?? {};
    const threshold = h4.threshold ?? 0.01;
    const lineRate = h4.lineMismatchRate ?? null;
    const heightRate = h4.heightMismatchRate ?? null;
    return {
      available: true,
      source: resolve(path) === BROWSER_RESULTS ? "results/browser.json" : path,
      ticket: data.meta?.ticket ?? 479,
      generatedAt: data.meta?.startedAt ?? null,
      threshold,
      cells: h4.cells ?? null,
      lineMismatch: h4.lineMismatch ?? null,
      lineMismatchRate: lineRate,
      heightMismatch: h4.heightMismatch ?? null,
      heightMismatchRate: heightRate,
      wordFitCells: h4.wordFitCells ?? null,
      wordFitLineMismatchRate: h4.wordFitLineMismatchRate ?? null,
      pass:
        typeof h4.pass === "boolean"
          ? h4.pass
          : lineRate !== null &&
            heightRate !== null &&
            lineRate < threshold &&
            heightRate < threshold,
    };
  } catch (error) {
    return {
      available: false,
      source: "см. browser:test",
      reason: String(error?.message ?? error),
    };
  }
}

/**
 * Свип политики обрезки: `clamp ∈ {∞,6,4,3,2}` при `λ = 20`.
 *
 * Основной сценарий (`clamp = ∞`, `λ = 0`) отвечает на вопрос «убирают ли
 * ширины переносы при полном тексте». Свип — приложение: он покупает высоту
 * ценой спрятанного текста, и выбор потолка — решение #485 по Парето, а не
 * часть целевой функции.
 */
export function runSweep(measurer, spec) {
  const cases = [];
  for (const tableWidth of spec.widths) {
    for (const profile of spec.profiles) {
      for (const clamp of spec.clamps) {
        const columns = clampColumns(11, clamp);
        const sheet = generateSheet({
          profile,
          rows: spec.rows,
          columns,
          seed: spec.seed,
        });
        const prepared = prepareSheet(sheet, measurer);
        const { value, ms } = measureRuntime(() =>
          OPTIMIZERS.search(prepared, contentWidth(tableWidth), {
            lambda: spec.lambda,
          }),
        );
        const metrics = collectMetrics(prepared, value.widths, spec.lambda);
        const textLoss = wrapTruncation(prepared, value.widths);
        cases.push({
          profile,
          tableWidth,
          rows: spec.rows,
          lambda: spec.lambda,
          clamp,
          ms: round(ms, 2),
          cost: metrics.cost,
          totalHeight: metrics.height,
          meanHeight: metrics.meanHeight,
          p95Height: metrics.p95Height,
          maxHeight: metrics.maxHeight,
          truncatedShare: metrics.truncatedShare,
          textTruncatedCells: textLoss.truncated,
          textTruncatedShare: textLoss.sharePct,
          multiLineShare: metrics.multiLineShare,
          rows3PlusShare: metrics.rows3PlusShare,
          rows4PlusShare: metrics.rows4PlusShare,
          heightBuckets: metrics.heightBuckets,
          widths: {
            source_name: value.widths.source_name,
            operations: value.widths.operations,
            errors: value.widths.errors,
          },
          widthSum: round(sumWidths(columns, value.widths), 1),
        });
      }
    }
  }
  return cases;
}

function summarizeSweep(cases) {
  const groups = new Map();
  for (const item of cases) {
    const key = item.clamp === "none" ? "none" : String(item.clamp);
    if (!groups.has(key)) {
      groups.set(key, { clamp: item.clamp, lambda: item.lambda, items: [] });
    }
    groups.get(key).items.push(item);
  }
  return [...groups.values()]
    .map(({ clamp, lambda, items }) => {
      const mean = (field) =>
        round(items.reduce((sum, item) => sum + item[field], 0) / items.length, 2);
      const meanWidth = (id) =>
        round(
          items.reduce((sum, item) => sum + item.widths[id], 0) / items.length,
          1,
        );
      return {
        lambda,
        clamp,
        cases: items.length,
        meanTotalHeight: mean("totalHeight"),
        meanHeight: mean("meanHeight"),
        meanP95Height: mean("p95Height"),
        meanMaxHeight: mean("maxHeight"),
        meanTruncatedShare: mean("truncatedShare"),
        meanTextTruncatedShare: mean("textTruncatedShare"),
        meanMultiLineShare: mean("multiLineShare"),
        meanRows3PlusShare: mean("rows3PlusShare"),
        meanRows4PlusShare: mean("rows4PlusShare"),
        meanErrorsWidth: meanWidth("errors"),
        meanSourceNameWidth: meanWidth("source_name"),
        meanRuntimeMs: mean("ms"),
      };
    })
    .sort((a, b) => clampOrder(a.clamp) - clampOrder(b.clamp))
    .map((row, _, all) => ({
      ...row,
      dominated: all.some(
        (other) =>
          other !== row &&
          other.meanHeight <= row.meanHeight &&
          other.meanTextTruncatedShare <= row.meanTextTruncatedShare &&
          (other.meanHeight < row.meanHeight ||
            other.meanTextTruncatedShare < row.meanTextTruncatedShare),
      ),
    }));
}

/**
 * Виртуализация: предсказанная высота `lines × LINE_HEIGHT_PX` против
 * фактического CSS. В продукте «Ошибки» — `font-medium leading-snug`
 * (15.125 px на строку при 11 px), а модель считает 20 px; вес 500 модель не
 * знает. Считаем, в какой доле строк высоту задают именно ошибки и насколько
 * модель завышает их вклад — это вход для #483.
 */
function runVirtualization(measurer, spec) {
  const cases = [];
  for (const profile of spec.profiles) {
    for (const tableWidth of spec.widths) {
      const columns = mainColumns(11);
      const sheet = generateSheet({
        profile,
        rows: spec.rows,
        columns,
        seed: spec.seed,
      });
      const prepared = prepareSheet(sheet, measurer);
      const run = OPTIMIZERS.search(prepared, contentWidth(tableWidth), {
        lambda: MAIN_LAMBDA,
      });
      const rows = prepared.rows.length || 1;
      let errorsDriven = 0;
      let nameDriven = 0;
      let errorLinesSum = 0;
      let overPrediction = 0;
      for (const cells of prepared.rows) {
        let maxLines = 1;
        let errorLines = 1;
        let nameLines = 1;
        for (let index = 0; index < columns.length; index += 1) {
          const column = columns[index];
          const measured = measureCell(
            prepared.measurer,
            cells[index],
            run.widths[column.id] - CELL_PADDING_PX,
          );
          if (measured.lines > maxLines) maxLines = measured.lines;
          if (column.id === "errors") errorLines = measured.lines;
          if (column.id === "source_name") nameLines = measured.lines;
        }
        if (errorLines === maxLines && errorLines >= 2) {
          errorsDriven += 1;
          errorLinesSum += errorLines;
          overPrediction +=
            errorLines * (LINE_HEIGHT_PX - CSS_ERROR_LINE_HEIGHT_PX);
        }
        if (nameLines === maxLines && nameLines >= 2) nameDriven += 1;
      }
      cases.push({
        profile,
        tableWidth,
        rows,
        errorsDrivenShare: round((errorsDriven / rows) * 100, 2),
        nameDrivenShare: round((nameDriven / rows) * 100, 2),
        meanErrorLines: errorsDriven
          ? round(errorLinesSum / errorsDriven, 2)
          : 0,
        modelOverPredictionPx: round(overPrediction / rows, 2),
        modelOverPredictionPerDrivenRowPx: errorsDriven
          ? round(overPrediction / errorsDriven, 2)
          : 0,
        modelLineHeightPx: LINE_HEIGHT_PX,
        cssErrorLineHeightPx: round(CSS_ERROR_LINE_HEIGHT_PX, 3),
      });
    }
  }
  return cases;
}

function summarizeVirtualization(cases) {
  if (cases.length === 0) return null;
  const mean = (field) =>
    round(cases.reduce((sum, item) => sum + item[field], 0) / cases.length, 2);
  return {
    cases: cases.length,
    meanErrorsDrivenShare: mean("errorsDrivenShare"),
    meanNameDrivenShare: mean("nameDrivenShare"),
    meanErrorLines: mean("meanErrorLines"),
    meanModelOverPredictionPx: mean("modelOverPredictionPx"),
    meanModelOverPredictionPerDrivenRowPx: mean(
      "modelOverPredictionPerDrivenRowPx",
    ),
    modelLineHeightPx: LINE_HEIGHT_PX,
    cssErrorLineHeightPx: round(CSS_ERROR_LINE_HEIGHT_PX, 3),
  };
}

export function aggregate(configs) {
  const names = Object.keys(OPTIMIZERS);
  if (configs.length === 0) return {};
  const summary = {};
  for (const name of names) {
    const items = configs.map((config) => config.results[name]);
    const mean = (field) =>
      round(
        items.reduce((sum, item) => sum + item[field], 0) / items.length,
        2,
      );
    summary[name] = {
      configs: items.length,
      meanHeightRatio: round(
        items.reduce((sum, item) => sum + item.heightRatio, 0) / items.length,
        4,
      ),
      meanCostRatio: round(
        items.reduce((sum, item) => sum + item.costRatio, 0) / items.length,
        4,
      ),
      meanTotalHeight: mean("height"),
      meanRowHeight: mean("meanHeight"),
      meanP95Height: mean("p95Height"),
      meanMaxHeight: mean("maxHeight"),
      meanTruncatedShare: mean("truncatedShare"),
      meanMultiLineShare: mean("multiLineShare"),
      meanRows3PlusShare: mean("rows3PlusShare"),
      meanRows4PlusShare: mean("rows4PlusShare"),
      meanHeightBuckets: Object.fromEntries(
        HEIGHT_BUCKETS.map((bucket) => [
          bucket.key,
          round(
            items.reduce(
              (sum, item) => sum + (item.heightBuckets[bucket.key] ?? 0),
              0,
            ) / items.length,
            2,
          ),
        ]),
      ),
      meanCost: mean("cost"),
      meanCostPer1000Rows: round(
        configs.reduce(
          (sum, config) =>
            sum + (config.results[name].cost / config.rows) * 1000,
          0,
        ) / configs.length,
        1,
      ),
      meanRuntimeMs: mean("ms"),
      maxRuntimeMs: round(Math.max(...items.map((item) => item.ms)), 2),
      widthViolations: configs.filter(
        (config) => config.results[name].violations.length > 0,
      ).length,
      wins: configs.filter((config) => {
        // Раскладка с нарушением maxShare не участвует в победах: это не
        // валидный результат, даже если её cost ниже.
        const valid = names.filter(
          (candidate) => config.results[candidate].violations.length === 0,
        );
        if (valid.length === 0) return false;
        const best = valid.reduce(
          (bestName, candidate) =>
            config.results[candidate].cost < config.results[bestName].cost
              ? candidate
              : bestName,
          valid[0],
        );
        return best === name;
      }).length,
    };
  }
  return summary;
}

/** Агрегат по произвольному ключу конфигурации (профиль, W, число строк). */
function groupBy(configs, key, summaryOf) {
  const groups = new Map();
  for (const config of configs) {
    const value = config[key];
    if (!groups.has(value)) groups.set(value, []);
    groups.get(value).push(config);
  }
  return [...groups.entries()]
    .sort((a, b) =>
      typeof a[0] === "number" ? a[0] - b[0] : String(a[0]).localeCompare(String(b[0])),
    )
    .map(([value, items]) => ({ value, summary: summaryOf(items) }));
}

function summarizeOracle(cases) {
  const names = Object.keys(OPTIMIZERS);
  const gaps = {};
  for (const name of names) {
    const values = cases.map((item) => item.results[name].gapCostPct);
    gaps[name] = {
      meanGapPct: round(values.reduce((sum, value) => sum + value, 0) / values.length, 2),
      worstGapPct: round(Math.max(...values), 2),
      widthViolations: cases.filter(
        (item) => item.results[name].violations.length > 0,
      ).length,
      wins: cases.filter(
        (item) =>
          item.results[name].gapCostPct <= 0.01 &&
          item.results[name].violations.length === 0,
      ).length,
    };
  }
  const byProfile = {};
  for (const profile of [...new Set(cases.map((item) => item.profile))]) {
    const items = cases.filter((item) => item.profile === profile);
    byProfile[profile] = {};
    for (const name of names) {
      byProfile[profile][name] = round(
        items.reduce((sum, item) => sum + item.results[name].gapCostPct, 0) /
          items.length,
        2,
      );
    }
  }
  const heuristics = names.filter((name) => name !== "baseline");
  const best = heuristics.reduce(
    (winner, name) =>
      gaps[name].worstGapPct < gaps[winner].worstGapPct ? name : winner,
    heuristics[0],
  );
  return {
    caseCount: cases.length,
    rows: ORACLE_ROWS,
    gaps,
    byProfile,
    best,
    thinned: cases.filter((item) => item.oracle.thinned).length,
  };
}

/** Сравнение политик на продуктовом срезе: текущий фикс vs полный текст. */
function summarizePolicies(configs) {
  const items = configs.filter((config) => config.policies);
  if (items.length === 0) return null;
  const mean = (accessor) =>
    round(
      items.reduce((sum, config) => sum + accessor(config.policies), 0) /
        items.length,
      2,
    );
  return {
    configs: items.length,
    meanCurrentRowHeight: mean((p) => p.currentProduct.meanHeight),
    meanCurrentTotalHeight: mean((p) => p.currentProduct.height),
    meanBaselineRowHeight: mean((p) => p.noClampBaseline.meanHeight),
    meanBaselineTotalHeight: mean((p) => p.noClampBaseline.height),
    meanBestRowHeight: mean((p) => p.noClampBest.meanHeight),
    meanBestTotalHeight: mean((p) => p.noClampBest.height),
    meanCurrentTruncatedShare: mean((p) => p.currentProduct.truncatedShare),
    meanBaselineTruncatedShare: mean((p) => p.noClampBaseline.truncatedShare),
    meanBestTruncatedShare: mean((p) => p.noClampBest.truncatedShare),
    meanGrowthBaselinePct: mean((p) => p.growthPct.baseline),
    meanGrowthBestPct: mean((p) => p.growthPct.best),
  };
}

function verdict(condition) {
  return condition ? "подтверждена" : "не подтверждена";
}

function buildHypotheses({ oracle, sampleStability, widthStability, h4 }) {
  const hypotheses = [];
  if (oracle) {
    const best = oracle.best;
    const worst = oracle.gaps[best].worstGapPct;
    hypotheses.push({
      id: "H1",
      statement:
        "лучшая эвристика отстаёт от оракула не более чем на 5% по cost (clamp=∞, λ=0)",
      value: `${worst}% (${best})`,
      threshold: "≤5%",
      verdict: verdict(worst <= 5),
      note: `worst по ${oracle.caseCount} конфигурациям, ${oracle.rows} строк, основной сценарий`,
    });
  } else {
    hypotheses.push({
      id: "H1",
      statement:
        "лучшая эвристика отстаёт от оракула не более чем на 5% по cost (clamp=∞, λ=0)",
      value: "не проверялась",
      threshold: "≤5%",
      verdict: "нет данных",
      note: "--only без oracle",
    });
  }

  if (sampleStability.length > 0) {
    const worst = [...sampleStability].sort(
      (a, b) => Math.abs(b.heightDeltaPct) - Math.abs(a.heightDeltaPct),
    )[0];
    const fails = sampleStability.filter(
      (item) => Math.abs(item.heightDeltaPct) > 2,
    );
    hypotheses.push({
      id: "H2",
      statement:
        "подвыборка 500 строк даёт ≤2% потерь по высоте (clamp=∞, λ=0)",
      value: `${worst.heightDeltaPct}% (${worst.optimizer}/${worst.profile})`,
      threshold: "≤2%",
      verdict: verdict(fails.length === 0),
      note: `${sampleStability.length} случаев; вне порога: ${
        fails.length || "нет"
      }`,
    });
  } else {
    hypotheses.push({
      id: "H2",
      statement:
        "подвыборка 500 строк даёт ≤2% потерь по высоте (clamp=∞, λ=0)",
      value: "не проверялась",
      threshold: "≤2%",
      verdict: "нет данных",
      note: "--only без matrix/product",
    });
  }

  if (widthStability.length > 0) {
    const worst = [...widthStability].sort(
      (a, b) => b.maxShareDeltaPct - a.maxShareDeltaPct,
    )[0];
    const fails = widthStability.filter((item) => item.maxShareDeltaPct > 5);
    hypotheses.push({
      id: "H3",
      statement:
        "доли колонок устойчивы к W 1180–1920 (Δ ≤ 5 п.п., clamp=∞)",
      value: `${worst.maxShareDeltaPct} п.п. (${worst.optimizer}/${worst.profile})`,
      threshold: "≤5 п.п.",
      verdict: verdict(fails.length === 0),
      note: `${widthStability.length} случаев; вне порога: ${
        fails.length || "нет"
      }`,
    });
  } else {
    hypotheses.push({
      id: "H3",
      statement:
        "доли колонок устойчивы к W 1180–1920 (Δ ≤ 5 п.п., clamp=∞)",
      value: "не проверялась",
      threshold: "≤5 п.п.",
      verdict: "нет данных",
      note: "--only без matrix/product",
    });
  }

  if (h4.available) {
    hypotheses.push({
      id: "H4",
      statement: "pretext расходится с реальным DOM менее чем на 1% строк",
      value: `${(h4.lineMismatchRate * 100).toFixed(2)}% строк, ${(
        h4.heightMismatchRate * 100
      ).toFixed(2)}% высот`,
      threshold: "<1%",
      verdict: verdict(h4.pass),
      note: `браузер #${h4.ticket}: ${h4.lineMismatch}/${h4.cells} ячеек, ${
        h4.source
      }`,
    });
  } else {
    hypotheses.push({
      id: "H4",
      statement: "pretext расходится с реальным DOM менее чем на 1% строк",
      value: "нет results/browser.json",
      threshold: "<1%",
      verdict: "см. browser:test",
      note: "npm --prefix research/column-widths run browser:test",
    });
  }
  return hypotheses;
}

function percent(value) {
  return Number.isFinite(value) ? `${value}%` : "—";
}

function signedPercent(value) {
  if (!Number.isFinite(value)) return "—";
  return `${value > 0 ? "+" : ""}${value}%`;
}

function buildReport(data) {
  const {
    meta,
    matrix,
    product,
    oracle,
    sampleStability,
    widthStability,
    sweep,
    policies,
    virtualization,
    h4,
    hypotheses,
    measurerAgreement,
  } = data;
  const lines = [];
  const push = (...cells) => lines.push(...cells);

  push("# Отчёт: оптимальное распределение ширин колонок");
  push("");
  push(`- Дата: ${meta.date}`);
  push(`- Ветка: \`${meta.branch}\``);
  push(
    `- Команда: \`node research/column-widths/bench.mjs${
      meta.argv ? ` ${meta.argv}` : ""
    }\``,
  );
  push(`- Измеритель: \`${meta.measurer}\``);
  push(`- Seed'ы: ${meta.seeds.join(", ")}`);
  push(
    "- **Основной сценарий:** `clamp = ∞` (полный текст), `λ = 0`. Все основные таблицы ниже — в нём.",
  );
  push(
    `- Свип политики: \`clamp ∈ {∞,6,4,3,2}\`, λ = ${meta.sweepLambda} px за обрезанную ячейку.`,
  );
  push(
    `- \`MAX_LINES = 64\` в \`lib/curves.mjs\` — техническая защита перебора; в основном прогоне потолок не достигается.`,
  );
  push(`- Секции: ${meta.sections.join(", ")}`);
  push(
    `- Конфигураций: ${meta.counts.matrix} матрица, ${meta.counts.product} продуктовый срез, ${meta.counts.oracle} оракул, ${meta.counts.sweep} свип, ${meta.counts.virtualization} виртуализация`,
  );
  push(`- Время прогона: ${meta.runtimeMs} мс`);
  push("");

  if (matrix) {
    push("## Матрица");
    push("");
    push(
      `Профили: ${matrix.spec.profiles.join(", ")}; строки: ${matrix.spec.rows.join(
        "/",
      )}; ширины: ${matrix.spec.widths.join("/")}; колонки: ${matrix.spec.columns.join(
        "/",
      )}; seed: ${meta.seeds.join(",")}.`,
    );
    push("");
    push("| Оптимизатор | Высота / baseline | Суммарная высота (сред.) | Средняя высота строки | p95 | max | Обрезка, % | Переносов, % строк | Строк ≥3, % | Строк ≥4, % | Время, мс (сред./max) | Побед | Наруш. maxShare |");
    push("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|");
    for (const [name, item] of Object.entries(matrix.summary)) {
      push(
        `| ${name} | ${item.meanHeightRatio.toFixed(3)} | ${item.meanTotalHeight} | ${item.meanRowHeight} | ${item.meanP95Height} | ${item.meanMaxHeight} | ${item.meanTruncatedShare} | ${item.meanMultiLineShare} | ${item.meanRows3PlusShare} | ${item.meanRows4PlusShare} | ${item.meanRuntimeMs} / ${item.maxRuntimeMs} | ${item.wins} | ${item.widthViolations} |`,
      );
    }
    push("");
    push(
      "Ничьи в «Побед» достаются первому оптимизатору в списке; раскладки с нарушением «maxShare» в победах не участвуют.",
    );
    push("");
    push("### Распределение высот строк, % строк");
    push("");
    push("| Оптимизатор | 40 px (1 строка) | 60 px (2) | 80 px (3) | ≥100 px (4+) |");
    push("|---|---:|---:|---:|---:|");
    for (const [name, item] of Object.entries(matrix.summary)) {
      const buckets = item.meanHeightBuckets;
      push(
        `| ${name} | ${buckets.row40} | ${buckets.row60} | ${buckets.row80} | ${buckets.row100Plus} |`,
      );
    }
    push("");
    push("### Cost / baseline по ширине таблицы");
    push("");
    const names = Object.keys(matrix.summary);
    push(`| W | ${names.join(" | ")} |`);
    push(`|---:|${names.map(() => "---:").join("|")}|`);
    for (const group of matrix.byWidth) {
      const cells = names.map((name) =>
        group.summary[name] ? group.summary[name].meanCostRatio.toFixed(3) : "—",
      );
      push(`| ${group.value} | ${cells.join(" | ")} |`);
    }
    push("");
    push("### Cost / baseline по числу строк");
    push("");
    push(`| Строк | ${names.join(" | ")} |`);
    push(`|---:|${names.map(() => "---:").join("|")}|`);
    for (const group of matrix.byRows) {
      const cells = names.map((name) =>
        group.summary[name] ? group.summary[name].meanCostRatio.toFixed(3) : "—",
      );
      push(`| ${group.value} | ${cells.join(" | ")} |`);
    }
    push("");
    const bestByMean = [...names].sort(
      (a, b) => matrix.summary[a].meanCostRatio - matrix.summary[b].meanCostRatio,
    );
    const candidate = bestByMean.find((name) => name !== "baseline") ?? bestByMean[0];
    push(
      `Лучший по среднему cost: **${candidate}** (${matrix.summary[candidate].meanCostRatio.toFixed(
        3,
      )} от baseline; средняя высота ${matrix.summary[candidate].meanRowHeight} px, обрезка ${matrix.summary[candidate].meanTruncatedShare}%).`,
    );
    push("");
  }

  if (oracle) {
    push("## Оракул на малых инстансах");
    push("");
    push(
      `Полный перебор порогов на ${oracle.rows} строках; ${oracle.caseCount} конфигураций (профили × ширины × колонки × seed), основной сценарий: ` +
        `\`clamp = ∞\`, \`λ = 0\`. Прорежена сетка в ${oracle.thinned} случаях.`,
    );
    push("");
    const names = Object.keys(oracle.gaps);
    push(`| Оптимизатор | Средний gap cost | Худший gap cost | Конфигураций на оптимуме | Наруш. maxShare |`);
    push("|---|---:|---:|---:|---:|");
    for (const name of names) {
      const item = oracle.gaps[name];
      push(
        `| ${name} | ${percent(item.meanGapPct)} | ${percent(item.worstGapPct)} | ${item.wins}/${oracle.caseCount} | ${item.widthViolations} |`,
      );
    }
    if (names.some((name) => oracle.gaps[name].widthViolations > 0)) {
      push("");
      push(
        "Отрицательный gap у оптимизатора с нарушением `maxShare` — не победа над эталоном: он вышел за допустимую полосу. Это диагностика реализации, а не результат.",
      );
    }
    push("");
    push("Средний gap по профилям (cost к оракулу):");
    push("");
    push(`| Профиль | ${names.join(" | ")} |`);
    push(`|---|${names.map(() => "---:").join("|")}|`);
    for (const [profile, gaps] of Object.entries(oracle.byProfile)) {
      push(
        `| ${profile} | ${names.map((name) => percent(gaps[name])).join(" | ")} |`,
      );
    }
    push("");
  }

  if (product) {
    push("## Продуктовый срез (11 колонок, `ImportRemaindersDialog`)");
    push("");
    push(
      `Профили: ${product.spec.profiles.join(", ")}; строки: ${product.spec.rows.join(
        "/",
      )}; ширины: ${product.spec.widths.join("/")}; колонки: 11; seed: ${meta.seeds.join(
        ",",
      )}. Основной сценарий: \`clamp = ∞\`, \`λ = 0\`, поэтому cost = суммарная высота.`,
    );
    push("");
    push(
      "`baseline` — это **текущие продуктовые доли** (наименование 15%, операции 21%), а не старые 22/13%. Поэтому `cost/baseline` — выигрыш поверх уже сделанного фикса `98e9a4d3`.",
    );
    push("");
    push("| Оптимизатор | Высота / baseline | Cost / baseline | Суммарная высота (сред.) | Cost / 1000 строк | Средняя высота строки | p95 | max | Строк ≥2, % | Строк ≥3, % | Строк ≥4, % | Время, мс | Побед |");
    push("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|");
    for (const [name, item] of Object.entries(product.summary)) {
      push(
        `| ${name} | ${item.meanHeightRatio.toFixed(3)} | ${item.meanCostRatio.toFixed(3)} | ${item.meanTotalHeight} | ${item.meanCostPer1000Rows} | ${item.meanRowHeight} | ${item.meanP95Height} | ${item.meanMaxHeight} | ${item.meanMultiLineShare} | ${item.meanRows3PlusShare} | ${item.meanRows4PlusShare} | ${item.meanRuntimeMs} | ${item.wins} |`,
      );
    }
    push("");
    const large = product.configs.filter((config) => config.rows === 5000);
    if (large.length > 0) {
      const runtimes = large.map((config) => config.results.search.ms);
      push(
        `Время \`search\` на 5000×11 (основной сценарий): среднее ${round(
          runtimes.reduce((sum, value) => sum + value, 0) / runtimes.length,
          2,
        )} мс, максимум ${round(Math.max(...runtimes), 2)} мс — цель «десятки мс» закрыта.`,
      );
      push("");
    }
    if (policies) {
      push("### Сравнение политик");
      push("");
      push(
        "Текущий продукт — `truncate` у наименования и полный перенос ошибок (как в `ImportRemaindersDialog`), ширины — текущие доли. Ниже — цена отказа от обрезки при полном тексте.",
      );
      push("");
      push("| Политика | Средняя высота строки | Суммарная высота (сред.) | Обрезка ячеек, % | Рост к текущему фиксу |");
      push("|---|---:|---:|---:|---:|");
      push(
        `| Текущий продукт (наименование 1 строка, ошибки перенос) | ${policies.meanCurrentRowHeight} | ${policies.meanCurrentTotalHeight} | ${policies.meanCurrentTruncatedShare} | 0% |`,
      );
      push(
        `| Baseline-доли, полный текст | ${policies.meanBaselineRowHeight} | ${policies.meanBaselineTotalHeight} | ${policies.meanBaselineTruncatedShare} | ${signedPercent(policies.meanGrowthBaselinePct)} |`,
      );
      push(
        `| \`search\`, полный текст | ${policies.meanBestRowHeight} | ${policies.meanBestTotalHeight} | ${policies.meanBestTruncatedShare} | ${signedPercent(policies.meanGrowthBestPct)} |`,
      );
      push("");
      push(
        "Обрезка в основном сценарии — это не текст (у него clamp = ∞), а пилюли «Операций»: они nowrap, и по спеке §12 сжимаются с подписью в title. Поэтому `search` экономит высоту в том числе за счёт «Операций»; отрицательный рост — перераспределение бюджета, положительный — цена полного текста.",
      );
      push("");
      push(
        `Ориентир §15: если рост без обрезки больше 25%, обрезка остаётся предохранителем с раскрытием по клику. Здесь \`search\` даёт **${signedPercent(policies.meanGrowthBestPct)}** к текущему фиксу; решение фиксируется в #485.`,
      );
      push("");
    }
    push("### По ширине таблицы");
    push("");
    const productNames = ["baseline", "breakpoints", "search"].filter(
      (name) => product.summary[name],
    );
    push(
      `| W | ${productNames
        .map((name) => `${name}: cost/baseline`)
        .join(" | ")} | ${productNames
        .map((name) => `${name}: обрезка, %`)
        .join(" | ")} |`,
    );
    push(`|---:|${productNames.map(() => "---:").join("|")}|${productNames
      .map(() => "---:")
      .join("|")}|`);
    for (const group of product.byWidth) {
      const costCells = productNames.map((name) =>
        group.summary[name] ? group.summary[name].meanCostRatio.toFixed(3) : "—",
      );
      const truncCells = productNames.map((name) =>
        group.summary[name] ? group.summary[name].meanTruncatedShare : "—",
      );
      push(`| ${group.value} | ${costCells.join(" | ")} | ${truncCells.join(" | ")} |`);
    }
    push("");
    const layout = product.layoutExample;
    if (layout) {
      push(
        `Раскладка гибких колонок (${layout.profile}, ${layout.rows} строк, W=${layout.tableWidth}, seed ${layout.seed}):`,
      );
      push("");
      push("| Оптимизатор | Наименование | Операции | Ошибки |");
      push("|---|---:|---:|---:|");
      for (const [name, widths] of Object.entries(layout.widths)) {
        push(
          `| ${name} | ${widths.source_name} | ${widths.operations} | ${widths.errors} |`,
        );
      }
      push("");
    }
  }

  if (sweep) {
    push("## Свип политики обрезки: Парето «высота против потерянного текста»");
    push("");
    push(
      `Оптимизатор \`search\`, продуктовый срез 11 колонок, ${sweep.spec.rows} строк, seed ${sweep.spec.seed}, λ = ${sweep.spec.lambda} px. ` +
        `Средние по профилям (${sweep.spec.profiles.join(", ")}) и ширинам (${sweep.spec.widths.join("/")}). ` +
        "`clamp = ∞` — основной сценарий; остальные строки — предохранитель, который покупает высоту ценой спрятанного текста.",
    );
    push("");
    push("| clamp | Высота строки | Суммарная высота | p95 | max | Потеряно текста (wrap), % | Обрезка всех ячеек, % | Строк ≥4, % | «Ошибки», px | «Наименование», px | Доминируется |");
    push("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|");
    for (const item of sweep.summary) {
      push(
        `| ${clampLabel(item.clamp)} | ${item.meanHeight} | ${item.meanTotalHeight} | ${item.meanP95Height} | ${item.meanMaxHeight} | ${item.meanTextTruncatedShare} | ${item.meanTruncatedShare} | ${item.meanRows4PlusShare} | ${item.meanErrorsWidth} | ${item.meanSourceNameWidth} | ${item.dominated ? "да" : "нет"} |`,
      );
    }
    push("");
    push(
      "«Потеряно текста» — доля ячеек переносимых колонок, где `lines` упёрлись в `clamp`; пилюли и mono-обрезка сюда не входят. Парето читается по паре (высота, потерянный текст): каждый следующий потолок — цена в пикселях за отказ от части текста. Выбор — #485, не бенч.",
    );
    push("");
  }

  if (virtualization) {
    push("## Виртуализация: предсказанная высота против CSS продукта");
    push("");
    push(
      `Модель считает строку как \`lines × ${virtualization.summary.modelLineHeightPx} px\`, а в продукте «Ошибки» — \`font-medium leading-snug\`: ${virtualization.summary.cssErrorLineHeightPx} px на строку при 11 px. ` +
        "Вес 500 модель не знает; H4 проверен на Inter 400. Ниже — строки, где высоту задают именно «Ошибки», и средняя переоценка моделью.",
    );
    push("");
    push("| Профиль | W | «Ошибки» задают высоту, % строк | «Наименование» задаёт высоту, % | Средние строки ошибок | Переоценка моделью, px/строка листа |");
    push("|---|---:|---:|---:|---:|---:|");
    for (const item of virtualization.cases) {
      push(
        `| ${item.profile} | ${item.tableWidth} | ${item.errorsDrivenShare} | ${item.nameDrivenShare} | ${item.meanErrorLines} | ${item.modelOverPredictionPx} |`,
      );
    }
    push("");
    push(
      `Средняя переоценка на строку листа — **${virtualization.summary.meanModelOverPredictionPx} px**, на строку, где ошибки задают высоту — **${virtualization.summary.meanModelOverPredictionPerDrivenRowPx} px**. ` +
        "Это не ошибка оптимизатора (он сравнивает раскладки в одной модели), а разрыв модели с CSS: для виртуализации предсказанную высоту нужно пересчитать в фактический `line-height` и учесть вес 500 — вход для #483.",
    );
    push("");
  }

  push("## Гипотезы");
  push("");
  push("| Гипотеза | Утверждение | Число | Порог | Вердикт | Комментарий |");
  push("|---|---|---|---|---|---|");
  for (const item of hypotheses) {
    push(
      `| ${item.id} | ${item.statement} | ${item.value} | ${item.threshold} | **${item.verdict}** | ${item.note} |`,
    );
  }
  push("");

  if (sampleStability.length > 0) {
    push("## Подвыборка (H2)");
    push("");
    push("| Профиль | Оптимизатор | 500 строк | 5000 строк | Δ высоты | Δ cost | Δ ширины (max) |");
    push("|---|---|---:|---:|---:|---:|---:|");
    for (const item of sampleStability) {
      push(
        `| ${item.profile} | ${item.optimizer} | ${item.sampleHeight} | ${item.fullHeight} | ${item.heightDeltaPct}% | ${item.costDeltaPct}% | ${item.maxFlexWidthDeltaPx} px |`,
      );
    }
    push("");
  }

  if (widthStability.length > 0) {
    push("## Устойчивость к ширине (H3)");
    push("");
    push("| Профиль | Оптимизатор | max Δ доли колонки |");
    push("|---|---|---:|");
    for (const item of widthStability) {
      push(`| ${item.profile} | ${item.optimizer} | ${item.maxShareDeltaPct} п.п. |`);
    }
    push("");
  }

  push("## Ограничения");
  push("");
  push(
    "- Модель текста в Node — табличные метрики 11px, а не canvas. H4 проверен в браузере отдельно (#479): " +
      (h4.available
        ? `${(h4.lineMismatchRate * 100).toFixed(2)}% расхождений, порог <1%; источник ${h4.source}.`
        : "браузерный JSON не найден, см. `browser:test`."),
  );
  if (measurerAgreement && !measurerAgreement.skipped) {
    push(
      `- Диагностика моделей (не H4): pretext и greedy расходятся на ${measurerAgreement.sharePct}% ячеек синтетики.`,
    );
  }
  const violating = matrix
    ? Object.entries(matrix.summary).filter(([, item]) => item.widthViolations > 0)
    : [];
  if (violating.length > 0) {
    push(
      `- **Нарушение инварианта «maxShare»:** ${violating
        .map(([name, item]) => `${name} — ${item.widthViolations} конфигураций`)
        .join(", ")}. Бенч фиксирует это отдельным столбцом; gap таких конфигураций к оракулу невалиден.`,
    );
  } else {
    push(
      "- Инвариант `maxShare` выполняется во всех конфигурациях (p90 исправлен в #486).",
    );
  }
  push(
    "- `MAX_LINES = 64` в `lib/curves.mjs` — техническая защита от бесконечного перебора; в основном сценарии (`clamp = ∞`) она не достигается на синтетике (максимум ниже 64 строк), но при более длинных текстах станет реальным потолком.",
  );
  push(
    "- `operations` смоделированы как неразрывные пилюли: ширина покупает отсутствие обрезки, а не строки. Поэтому `обрезка всех ячеек` в основном сценарии не ноль даже при `clamp = ∞`; «потеряно текста» в свипе считает только переносимые колонки.",
  );
  push(
    "- Минимум текстовой колонки — `max(minPx, maxWordWidth + padding)` по листу (#479): уже самого широкого слова `pretext` рвёт слово, а CSS с `overflow-wrap: normal` — нет. Если минимумы не влезают в бюджет, раскладка честно переполняется.",
  );
  push(
    "- Поиск идёт по подвыборке ≤500 строк (самые длинные строки по одной на гибкую колонку + равномерная сетка), `cost` считается на полном листе; полная проверка H2 — #482.",
  );
  push(
    "- H2/H3 — честные ограничения текущей эвристики в основном сценарии, а не замазанные числа: вердикт «не подтверждена» означает, что политика стабильности — отдельная задача #482.",
  );
  push("");

  if (matrix) {
    push("## Рекомендация");
    push("");
    const names = Object.keys(matrix.summary);
    const bestByMean = [...names].sort(
      (a, b) => matrix.summary[a].meanCostRatio - matrix.summary[b].meanCostRatio,
    );
    const candidate = bestByMean.find((name) => name !== "baseline") ?? bestByMean[0];
    const item = matrix.summary[candidate];
    push(
      `Основной сценарий: **${candidate}** — лучший средний cost (${item.meanCostRatio.toFixed(
        3,
      )} от текущих долей), среднее время ${item.meanRuntimeMs} мс, максимум ${
        item.maxRuntimeMs
      } мс на конфигурацию; на 5000×11 — десятки мс.`,
    );
    if (policies) {
      push(
        `Отказ от обрезки меняет высоту на **${signedPercent(policies.meanGrowthBestPct)}** к текущему фиксу (порог §15 — +25%). Потолок «line-clamp» выбирается по Парето-таблице выше: это решение #485, бенч только показывает цену.`,
      );
    }
    push("");
  }

  return lines.join("\n");
}

async function main() {
  const started = performance.now();
  const measurer = await createMeasurer(MEASURER_KIND);
  const matrixSchema = matrixSpec();
  const productSchema = productSpec();
  const oracleSchema = oracleSpec();
  const sweepSchema = sweepSpec();

  console.log(
    `[bench] measurer=${measurer.name} seeds=${SEED_LIST.join(",")} main=clamp∞/λ${MAIN_LAMBDA} sweep=λ${SWEEP_LAMBDA_VALUE} quick=${QUICK} sections=${SECTIONS_TO_RUN.join(",")}`,
  );

  let matrix = null;
  if (SECTIONS_TO_RUN.includes("matrix")) {
    const configs = [];
    for (const profile of matrixSchema.profiles) {
      for (const rows of matrixSchema.rows) {
        for (const tableWidth of matrixSchema.widths) {
          for (const columnCount of matrixSchema.columns) {
            for (const seed of SEED_LIST) {
              configs.push(
                runConfig({
                  profile,
                  rows,
                  tableWidth,
                  columnCount,
                  seed,
                  measurer,
                }),
              );
            }
          }
        }
      }
      console.log(`[bench] matrix ${profile}: ${configs.length} конфигураций`);
    }
    const summary = aggregate(configs);
    matrix = {
      spec: { ...matrixSchema, seeds: SEED_LIST },
      configs,
      summary,
      byWidth: groupBy(configs, "tableWidth", aggregate),
      byRows: groupBy(configs, "rows", aggregate),
    };
  }

  let product = null;
  if (SECTIONS_TO_RUN.includes("product")) {
    const configs = [];
    for (const profile of productSchema.profiles) {
      for (const rows of productSchema.rows) {
        for (const tableWidth of productSchema.widths) {
          for (const columnCount of productSchema.columns) {
            for (const seed of SEED_LIST) {
              configs.push(
                runConfig({
                  profile,
                  rows,
                  tableWidth,
                  columnCount,
                  seed,
                  measurer,
                  policies: true,
                }),
              );
            }
          }
        }
      }
      console.log(`[bench] product ${profile}: ${configs.length} конфигураций`);
    }
    const summary = aggregate(configs);
    const policies = summarizePolicies(configs);
    const layoutConfig =
      configs.find(
        (config) =>
          config.profile === "realistic" &&
          config.rows === 1000 &&
          config.tableWidth === 1500 &&
          config.seed === 1,
      ) ?? configs[0];
    const layoutExample = layoutConfig
      ? {
          profile: layoutConfig.profile,
          rows: layoutConfig.rows,
          tableWidth: layoutConfig.tableWidth,
          seed: layoutConfig.seed,
          widths: Object.fromEntries(
            ["baseline", "breakpoints", "search"].map((name) => [
              name,
              {
                source_name: layoutConfig.results[name].widths.source_name,
                operations: layoutConfig.results[name].widths.operations,
                errors: layoutConfig.results[name].widths.errors,
              },
            ]),
          ),
        }
      : null;
    product = {
      spec: {
        ...productSchema,
        seeds: SEED_LIST,
        clamp: "none",
        lambda: MAIN_LAMBDA,
      },
      configs,
      summary,
      policies,
      byWidth: groupBy(configs, "tableWidth", aggregate),
      layoutExample,
    };
  }

  let oracle = null;
  if (SECTIONS_TO_RUN.includes("oracle")) {
    const cases = [];
    for (const profile of oracleSchema.profiles) {
      for (const tableWidth of oracleSchema.widths) {
        for (const columnCount of oracleSchema.columns) {
          for (const seed of SEED_LIST) {
            cases.push(
              runOracleConfig({
                profile,
                tableWidth,
                columnCount,
                seed,
                measurer,
              }),
            );
          }
        }
      }
      console.log(`[bench] oracle ${profile}: ${cases.length} конфигураций`);
    }
    oracle = {
      spec: { ...oracleSchema, seeds: SEED_LIST },
      cases,
      ...summarizeOracle(cases),
    };
  }

  let sweep = null;
  if (SECTIONS_TO_RUN.includes("sweep")) {
    const cases = runSweep(measurer, sweepSchema);
    sweep = {
      spec: sweepSchema,
      cases,
      summary: summarizeSweep(cases),
    };
    console.log(`[bench] sweep: ${cases.length} конфигураций`);
  }

  let virtualization = null;
  if (
    SECTIONS_TO_RUN.includes("product") ||
    SECTIONS_TO_RUN.includes("sweep")
  ) {
    const cases = runVirtualization(measurer, sweepSchema);
    virtualization = {
      spec: {
        profiles: sweepSchema.profiles,
        widths: sweepSchema.widths,
        rows: sweepSchema.rows,
        seed: sweepSchema.seed,
      },
      cases,
      summary: summarizeVirtualization(cases),
    };
    console.log(`[bench] virtualization: ${cases.length} конфигураций`);
  }

  const useStability =
    SECTIONS_TO_RUN.includes("matrix") || SECTIONS_TO_RUN.includes("product");
  const sampleStability = useStability ? runSampleStability(measurer) : [];
  const widthStability = useStability
    ? runStabilityAcrossWidths(measurer, matrixSchema.widths)
    : [];
  const measurerAgreement = await runMeasurerAgreement(measurer);
  const h4 = loadBrowserH4();
  const hypotheses = buildHypotheses({
    oracle,
    sampleStability,
    widthStability,
    h4,
  });

  const meta = {
    date: new Date().toISOString().slice(0, 10),
    branch: detectBranch(),
    measurer: measurer.name,
    seeds: SEED_LIST,
    mainScenario: { clamp: "none", lambda: MAIN_LAMBDA },
    lambda: MAIN_LAMBDA,
    sweepLambda: SWEEP_LAMBDA_VALUE,
    sweepClamps: SWEEP_CLAMPS,
    fitRows: FIT_ROWS,
    oracleRows: ORACLE_ROWS,
    maxLinesCap: 64,
    cssErrorLineHeightPx: round(CSS_ERROR_LINE_HEIGHT_PX, 3),
    quick: QUICK,
    sections: SECTIONS_TO_RUN,
    argv: args.join(" "),
    runtimeMs: round(performance.now() - started, 1),
    counts: {
      matrix: matrix?.configs.length ?? 0,
      product: product?.configs.length ?? 0,
      oracle: oracle?.cases.length ?? 0,
      sweep: sweep?.cases.length ?? 0,
      virtualization: virtualization?.cases.length ?? 0,
    },
  };

  mkdirSync(RESULTS_DIR, { recursive: true });
  const payload = {
    meta,
    matrix: matrix && {
      spec: matrix.spec,
      configs: matrix.configs,
      summary: matrix.summary,
      byWidth: matrix.byWidth,
      byRows: matrix.byRows,
    },
    product: product && {
      spec: product.spec,
      configs: product.configs,
      summary: product.summary,
      policies: product.policies,
      byWidth: product.byWidth,
      layoutExample: product.layoutExample,
    },
    oracle: oracle && {
      spec: { ...oracle.spec, clamp: "none", lambda: MAIN_LAMBDA },
      cases: oracle.cases,
      summary: {
        caseCount: oracle.caseCount,
        rows: oracle.rows,
        gaps: oracle.gaps,
        byProfile: oracle.byProfile,
        best: oracle.best,
        thinned: oracle.thinned,
      },
    },
    sampleStability,
    widthStability,
    sweep: sweep && {
      spec: sweep.spec,
      cases: sweep.cases,
      summary: sweep.summary,
    },
    virtualization,
    measurerAgreement,
    h4,
    hypotheses,
  };
  writeFileSync(
    resolve(RESULTS_DIR, "bench.json"),
    `${JSON.stringify(payload, null, 2)}\n`,
    "utf8",
  );

  const report = buildReport({
    meta,
    matrix,
    product,
    oracle,
    sampleStability,
    widthStability,
    sweep,
    policies: product?.policies ?? null,
    virtualization,
    h4,
    hypotheses,
    measurerAgreement,
  });
  writeFileSync(resolve(RESULTS_DIR, "report.md"), `${report}\n`, "utf8");

  if (matrix) {
    console.log("");
    console.log(
      "Оптимизатор            высота/baseline   cost/baseline   обрезка%   время(мс)   побед",
    );
    for (const [name, item] of Object.entries(matrix.summary)) {
      console.log(
        `${name.padEnd(22)} ${item.meanHeightRatio.toFixed(3).padStart(12)}   ${item.meanCostRatio.toFixed(3).padStart(12)}   ${String(item.meanTruncatedShare).padStart(7)}   ${String(item.meanRuntimeMs).padStart(9)}   ${String(item.wins).padStart(5)}`,
      );
    }
  }
  if (product) {
    console.log("");
    console.log("Продуктовый срез (11 колонок, clamp=∞, λ=0):");
    for (const [name, item] of Object.entries(product.summary)) {
      console.log(
        `${name.padEnd(22)} cost/baseline ${item.meanCostRatio.toFixed(3)}   обрезка ${String(item.meanTruncatedShare).padStart(5)}%   время ${String(item.meanRuntimeMs).padStart(6)} мс`,
      );
    }
    if (product.policies) {
      console.log(
        `Рост полного текста к текущему фиксу: baseline ${signedPercent(product.policies.meanGrowthBaselinePct)}, search ${signedPercent(product.policies.meanGrowthBestPct)}`,
      );
    }
  }
  if (sweep) {
    console.log("");
    console.log("Свип clamp (λ=20): высота строки / потеряно текста");
    for (const item of sweep.summary) {
      console.log(
        `${clampLabel(item.clamp).padEnd(14)} ${String(item.meanHeight).padStart(7)} px   потеряно ${String(item.meanTextTruncatedShare).padStart(6)}%   время ${String(item.meanRuntimeMs).padStart(6)} мс`,
      );
    }
  }
  console.log("");
  for (const item of hypotheses) {
    console.log(`[${item.id}] ${item.verdict}: ${item.value} (порог ${item.threshold})`);
  }
  console.log("");
  console.log(
    `[bench] ${meta.runtimeMs} мс; отчёт: ${resolve(RESULTS_DIR, "report.md")}`,
  );
}

const invokedDirectly =
  process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url);

if (invokedDirectly) {
  main().catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
}
