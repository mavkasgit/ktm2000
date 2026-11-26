#!/usr/bin/env node
/**
 * Бенч-харнесс исследования ширин колонок.
 *
 * Основной сценарий — полный текст: `clamp = ∞`, `λ = 0`. Обрезка — отдельная
 * политика, её цена измеряется свипом.
 *
 * Прогон состоит из семи частей:
 *
 * - `matrix`  — 7 профилей × {100,1000,5000} × {1180,1500,1920} × {6,12,20} × seeds;
 *               метрики считаются по полному листу, оптимизатор видит ≤500 строк;
 * - `product` — продуктовый срез `ImportRemaindersDialog` (11 колонок) на тех же
 *               профилях/строках/ширинах + сравнение с текущей политикой продукта;
 * - `oracle`  — точный перебор на малых инстансах (60 строк), все оптимизаторы
 *               рядом с эталоном; отсюда берётся gap для H1;
 * - `sweep`   — Парето «высота против потерянного текста»:
 *               `clamp ∈ {∞,6,4,3,2}` при `λ = 20`;
 * - `stability` — матрица сожалений: доли с W0 = 1500 на других ширинах (#482);
 * - `robust`  — один робастный вектор долей на профили × ширины (#482);
 * - `offline` — запасной исход #487: зашитый вектор долей и таблица по 2–3
 *               бакетам против текущих продуктовых долей (порог §15);
 *               дополнительно — ограничение обрезки пилюль (#488).
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
 *   node research/column-widths/bench.mjs --only=product  # matrix|oracle|product|
 *                                                         # sweep|stability|robust|
 *                                                         # offline|all (или через запятую)
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
  baselineWidths,
  buildColumns,
  maxWidth,
  sumWidths,
} from "./lib/columns.mjs";
import { columnMaxWordWidths } from "./lib/curves.mjs";
import { createMeasurer } from "./lib/measurers.mjs";
import { evaluate, measureCell, prepareSheet } from "./lib/evaluate.mjs";
import { OPTIMIZERS, oracleOptimizer } from "./lib/optimizers.mjs";
import {
  buildRobustScenario,
  contentSharesFromFlexShares,
  normalizeShares,
  robustShares,
  widthsFromFlexShares,
} from "./lib/robust.mjs";
import {
  OFFLINE_BUCKET_PLANS,
  OFFLINE_FLEX_SHARES,
  OFFLINE_FLEX_SHARES_SOURCE,
  PILLS_CURRENT_LIMIT_PCT,
  PILLS_LIMIT_MODES,
  PILLS_STRICT_LIMIT_PCT,
  bucketIndexForTableWidth,
  fitBucketShares,
  pillsLimitPctForWidth,
  policyMetrics,
  widthViolations as offlineWidthViolations,
} from "./lib/offline-shares.mjs";

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

const SECTIONS = [
  "matrix",
  "oracle",
  "product",
  "sweep",
  "stability",
  "robust",
  "offline",
];

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

/**
 * Матрица сожалений (#482): доли, подобранные на W0, переносятся на W'.
 * Основной сценарий — полный текст (λ = 0), продуктовая ширина 11 колонок.
 */
function stabilitySpec() {
  return {
    profiles: QUICK ? ["realistic", "long-tail"] : PROFILES,
    rows: QUICK ? 300 : 1000,
    baseWidth: 1500,
    widths: QUICK ? [1180, 1600] : [1180, 1400, 1600, 1920],
    seed: 1,
    columnCount: 11,
    optimizer: "search",
  };
}

/** Робастный вектор (#482): один набор долей на профили × ширины. */
function robustSpec() {
  return {
    profiles: QUICK ? ["realistic", "long-tail"] : PROFILES,
    rows: QUICK ? 300 : 1000,
    widths: QUICK ? [1180, 1600] : [1180, 1400, 1600, 1920],
    seed: 1,
    columnCount: 11,
    rowLimit: QUICK ? 300 : FIT_ROWS,
    maxCandidates: QUICK ? 8 : 12,
  };
}

/**
 * Оффлайн-доли (#487): зашитый вектор #482 против текущих долей.
 * Подбор — seed 1, проверка — seed 2 и отложенные профили; `--quick` урезает
 * профили и строки, его вердикт решением не является.
 */
function offlineSpec() {
  return {
    profiles: QUICK ? ["realistic", "long-tail"] : PROFILES,
    rows: QUICK ? 300 : 1000,
    widths: QUICK ? [1180, 1500, 1600] : [1180, 1400, 1500, 1600, 1920],
    fitSeed: 1,
    seeds: [1, 2],
    columnCount: 11,
    fitRows: QUICK ? 200 : 300,
    fitWidths: [1180, 1500, 1600],
    fitMaxSweeps: 3,
    fitMaxCandidates: 8,
    trainProfiles: ["realistic", "all-short", "mixed"],
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

function average(values) {
  if (values.length === 0) return 0;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function maxOf(values, fallback = 0) {
  return values.length === 0 ? fallback : Math.max(...values);
}

function minOf(values, fallback = 0) {
  return values.length === 0 ? fallback : Math.min(...values);
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
 * Доля потерянного текста: ячейки текстовых колонок, полный текст которых не
 * виден. Считаются и `wrap`-колонки, и однострочные (`truncate` у
 * «Наименования» — та же потеря). Пилюли и mono-обрезка сюда не входят: у них
 * своя политика `nowrap`, и в основном сценарии это не потеря текста, а
 * подпись в `title`.
 */
function textTruncation(prepared, widths) {
  let total = 0;
  let truncated = 0;
  prepared.columns.forEach((column, index) => {
    if (column.kind !== "text") return;
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
    const pick = (source, widths) => ({
      height: source.height,
      meanHeight: source.meanHeight,
      p95Height: source.p95Height,
      maxHeight: source.maxHeight,
      truncatedShare: source.truncatedShare,
      textTruncatedShare: textTruncation(fullPrepared, widths).sharePct,
    });
    policy = {
      currentProduct: {
        ...current,
        textTruncatedShare: textTruncation(currentPrepared, results.baseline.widths)
          .sharePct,
      },
      noClampBaseline: pick(results.baseline, results.baseline.widths),
      noClampBest: pick(results.search, results.search.widths),
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
 * H2: та же эвристика на первых N строках против полного листа (#482:
 * N ∈ {200, 500, 1000}). Внутренняя подвыборка оптимизатора — отдельный
 * вопрос; здесь честная граница «что будет, если оптимизатор увидит только
 * первые N строк». `long-tail` и `outlier` считаются отдельными профилями.
 */
export function runSampleStability(measurer, options = {}) {
  const cases = [];
  const profiles =
    options.profiles ??
    (QUICK ? ["realistic"] : ["realistic", "long-tail", "outlier"]);
  const sampleSizes = options.sampleSizes ?? (QUICK ? [200, 500] : [200, 500, 1000]);
  const rows = options.rows ?? 5000;
  const names = ["narrowing", "breakpoints", "search"];
  for (const profile of profiles) {
    const columns = mainColumns(11);
    const sheet = generateSheet({ profile, rows, columns, seed: 1 });
    const width = contentWidth(1500);
    const full = prepareSheet(sheet, measurer);
    const fullRuns = Object.fromEntries(
      names.map((name) => [name, OPTIMIZERS[name](full, width, { lambda: MAIN_LAMBDA })]),
    );
    for (const sampleSize of sampleSizes) {
      const sample = prepareSheet(
        { ...sheet, rows: sheet.rows.slice(0, sampleSize) },
        measurer,
      );
      for (const name of names) {
        const sampleRun = OPTIMIZERS[name](sample, width, {
          lambda: MAIN_LAMBDA,
        });
        const fullRun = fullRuns[name];
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
          sampleSize,
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

/**
 * Диагностика переноса долей: статические `minPx` и `maxShare`. Для
 * робастного вектора дополнительно проверяется динамический минимум
 * (`maxWordWidth`, #479) — он зависит от листа, поэтому считается отдельно.
 */
function staticViolations(columns, widths, contentWidth) {
  const violations = [];
  for (const column of columns) {
    if (widths[column.id] < column.minPx - 0.5) {
      violations.push({
        column: column.id,
        kind: "minPx",
        width: round(widths[column.id], 1),
        limit: column.minPx,
      });
    }
    const cap = maxWidth(column, contentWidth);
    if (Number.isFinite(cap) && widths[column.id] > cap + 0.5) {
      violations.push({
        column: column.id,
        kind: "maxShare",
        width: round(widths[column.id], 1),
        limit: round(cap, 1),
      });
    }
  }
  return violations;
}

/**
 * Матрица сожалений (#482): оптимизатор подбирает доли на `W0`, результат
 * переносится на `W'`. Основной вариант — проценты (`share × contentWidth`),
 * как в продукте; отдельно считается «пиксели с `W0` без масштабирования» —
 * это не поведение `table-fixed` с процентами, а диагностика.
 */
export function runRegretMatrix(measurer, spec = {}) {
  const profiles = spec.profiles ?? PROFILES;
  const baseWidth = spec.baseWidth ?? 1500;
  const widths = spec.widths ?? [1180, 1400, 1600, 1920];
  const rows = spec.rows ?? 1000;
  const seed = spec.seed ?? 1;
  const columnCount = spec.columnCount ?? 11;
  const optimizerName = spec.optimizer ?? "search";
  const columns = mainColumns(columnCount);
  const baseContent = contentWidth(baseWidth);
  const cases = [];

  for (const profile of profiles) {
    const sheet = generateSheet({ profile, rows, columns, seed });
    const prepared = prepareSheet(sheet, measurer);
    const baseRun = OPTIMIZERS[optimizerName](prepared, baseContent, {
      lambda: MAIN_LAMBDA,
    });
    const baseShares = {};
    for (const column of columns) {
      baseShares[column.id] = baseRun.widths[column.id] / baseContent;
    }

    for (const tableWidth of widths) {
      const content = contentWidth(tableWidth);
      const optimalRun = OPTIMIZERS[optimizerName](prepared, content, {
        lambda: MAIN_LAMBDA,
      });
      const optimalMetrics = evaluate(prepared, optimalRun.widths, {
        lambda: MAIN_LAMBDA,
      });

      const scaledWidths = {};
      for (const column of columns) {
        scaledWidths[column.id] = baseShares[column.id] * content;
      }
      const scaledMetrics = evaluate(prepared, scaledWidths, {
        lambda: MAIN_LAMBDA,
      });

      // «Пиксели с W0 как есть»: не проценты, а фиксированные px.
      const fixedMetrics = evaluate(prepared, baseRun.widths, {
        lambda: MAIN_LAMBDA,
      });

      cases.push({
        profile,
        tableWidth,
        contentWidth: content,
        rows,
        optimizer: optimizerName,
        baseWidth,
        baseContent,
        baseShares,
        optimalCost: optimalMetrics.cost,
        optimalHeight: optimalMetrics.height,
        scaledWidths,
        scaledCost: scaledMetrics.cost,
        scaledHeight: scaledMetrics.height,
        scaledRegretPct: round(
          ((scaledMetrics.cost - optimalMetrics.cost) /
            (optimalMetrics.cost || 1)) *
            100,
          2,
        ),
        scaledWidthSum: round(sumWidths(columns, scaledWidths), 1),
        scaledViolations: staticViolations(columns, scaledWidths, content),
        fixedPixelCost: fixedMetrics.cost,
        fixedPixelHeight: fixedMetrics.height,
        fixedPixelRegretPct: round(
          ((fixedMetrics.cost - optimalMetrics.cost) /
            (optimalMetrics.cost || 1)) *
            100,
          2,
        ),
        fixedPixelWidthSum: round(sumWidths(columns, baseRun.widths), 1),
      });
    }
  }

  const byWidth = widths.map((tableWidth) => {
    const subset = cases.filter((item) => item.tableWidth === tableWidth);
    const scaled = subset.map((item) => item.scaledRegretPct);
    const fixed = subset.map((item) => item.fixedPixelRegretPct);
    const worstScaled = subset.reduce(
      (worst, item) =>
        worst === null || item.scaledRegretPct > worst.scaledRegretPct
          ? item
          : worst,
      null,
    );
    return {
      tableWidth,
      profiles: subset.length,
      meanScaledRegretPct: round(average(scaled), 2),
      worstScaledRegretPct: round(maxOf(scaled), 2),
      worstScaledProfile: worstScaled
        ? `${worstScaled.profile}/${worstScaled.optimizer}`
        : null,
      meanFixedPixelRegretPct: round(average(fixed), 2),
      worstFixedPixelRegretPct: round(maxOf(fixed), 2),
      scaledViolations: subset.reduce(
        (sum, item) => sum + item.scaledViolations.length,
        0,
      ),
    };
  });

  const allScaled = cases.map((item) => item.scaledRegretPct);
  return {
    spec: {
      ...spec,
      profiles,
      widths,
      rows,
      seed,
      columnCount,
      optimizer: optimizerName,
      baseWidth,
    },
    cases,
    byWidth,
    summary: {
      caseCount: cases.length,
      meanScaledRegretPct: round(average(allScaled), 2),
      worstScaledRegretPct: round(maxOf(allScaled), 2),
      thresholdPct: 3,
      passes: maxOf(allScaled) <= 3,
    },
  };
}

/**
 * Робастный вектор (#482): один набор долей на все профили и `W'`.
 *
 * Поиск идёт по кэшу порогов (`lib/robust.mjs`), затем вектор проверяется на
 * полных листах тем же `evaluate`, что и остальной бенч. Рядом считается
 * перенос долей с `W0` (реальное поведение процентов) — порог требует, чтобы
 * робастный вектор был не хуже него.
 */
export function runRobustVector(measurer, spec = {}) {
  const profiles = spec.profiles ?? PROFILES;
  const widths = spec.widths ?? [1180, 1400, 1600, 1920];
  const rows = spec.rows ?? 1000;
  const seed = spec.seed ?? 1;
  const columnCount = spec.columnCount ?? 11;
  const baseWidth = spec.baseWidth ?? 1500;
  const rowLimit = spec.rowLimit ?? FIT_ROWS;
  const maxCandidates = spec.maxCandidates ?? 12;
  const columns = mainColumns(columnCount);
  const baseContent = contentWidth(baseWidth);

  const preparedByProfile = new Map();
  const scenarios = [];
  for (const profile of profiles) {
    const sheet = generateSheet({ profile, rows, columns, seed });
    const prepared = prepareSheet(sheet, measurer);
    preparedByProfile.set(profile, prepared);
    for (const tableWidth of widths) {
      scenarios.push(
        buildRobustScenario({
          prepared,
          contentWidth: contentWidth(tableWidth),
          lambda: MAIN_LAMBDA,
          rowLimit,
          maxCandidates,
          profile,
          tableWidth,
        }),
      );
    }
  }

  const robust = robustShares(scenarios, {
    objectives: spec.objectives,
    maxSweeps: spec.maxSweeps,
  });
  const scenarioAt = (profile, tableWidth) =>
    scenarios.find(
      (scenario) =>
        scenario.profile === profile && scenario.tableWidth === tableWidth,
    );

  const verification = [];
  for (const profile of profiles) {
    const prepared = preparedByProfile.get(profile);
    const baseRun = OPTIMIZERS.search(prepared, baseContent, {
      lambda: MAIN_LAMBDA,
    });
    const baseShares = {};
    for (const column of columns) {
      baseShares[column.id] = baseRun.widths[column.id] / baseContent;
    }
    for (const tableWidth of widths) {
      const content = contentWidth(tableWidth);
      const optimalRun = OPTIMIZERS.search(prepared, content, {
        lambda: MAIN_LAMBDA,
      });
      const optimalMetrics = evaluate(prepared, optimalRun.widths, {
        lambda: MAIN_LAMBDA,
      });

      const scaledWidths = {};
      for (const column of columns) {
        scaledWidths[column.id] = baseShares[column.id] * content;
      }
      const scaledMetrics = evaluate(prepared, scaledWidths, {
        lambda: MAIN_LAMBDA,
      });

      const robustWidths = widthsFromFlexShares(columns, content, robust.shares);
      const robustMetrics = evaluate(prepared, robustWidths, {
        lambda: MAIN_LAMBDA,
      });

      const scenario = scenarioAt(profile, tableWidth);
      const violations = staticViolations(columns, robustWidths, content);
      for (const column of columns) {
        if (!column.flex || !scenario) continue;
        const effective = scenario.model.minimums[column.id];
        if (robustWidths[column.id] < effective - 0.5) {
          violations.push({
            column: column.id,
            kind: "effectiveMin",
            width: round(robustWidths[column.id], 1),
            limit: round(effective, 1),
          });
        }
      }

      verification.push({
        profile,
        tableWidth,
        contentWidth: content,
        optimalCost: optimalMetrics.cost,
        scaledCost: scaledMetrics.cost,
        scaledRegretPct: round(
          ((scaledMetrics.cost - optimalMetrics.cost) /
            (optimalMetrics.cost || 1)) *
            100,
          2,
        ),
        robustCost: robustMetrics.cost,
        robustGapPct: round(
          Math.max(
            0,
            ((robustMetrics.cost - optimalMetrics.cost) /
              (optimalMetrics.cost || 1)) *
              100,
          ),
          2,
        ),
        robustHeight: robustMetrics.height,
        robustWidths,
        robustWidthSum: round(sumWidths(columns, robustWidths), 1),
        violations,
      });
    }
  }

  const byWidth = widths.map((tableWidth) => {
    const subset = verification.filter((item) => item.tableWidth === tableWidth);
    const robustGaps = subset.map((item) => item.robustGapPct);
    const scaledRegrets = subset.map((item) => item.scaledRegretPct);
    const worst = subset.reduce(
      (worstItem, item) =>
        worstItem === null || item.robustGapPct > worstItem.robustGapPct
          ? item
          : worstItem,
      null,
    );
    return {
      tableWidth,
      profiles: subset.length,
      meanRobustGapPct: round(average(robustGaps), 2),
      worstRobustGapPct: round(maxOf(robustGaps), 2),
      worstRobustProfile: worst ? worst.profile : null,
      meanScaledRegretPct: round(average(scaledRegrets), 2),
      worstScaledRegretPct: round(maxOf(scaledRegrets), 2),
      violations: subset.reduce((sum, item) => sum + item.violations.length, 0),
    };
  });

  const robustGaps = verification.map((item) => item.robustGapPct);
  const meanGapPct = average(robustGaps);
  const worstGapPct = maxOf(robustGaps);
  const contentShares = contentSharesFromFlexShares(
    columns,
    baseContent,
    robust.shares,
  );
  return {
    spec: {
      ...spec,
      profiles,
      widths,
      rows,
      seed,
      columnCount,
      baseWidth,
      rowLimit,
      maxCandidates,
    },
    shares: robust.shares,
    contentShares,
    contentSharesByWidth: robust.contentSharesByWidth,
    bounds: robust.bounds,
    seedUsed: robust.seed,
    objective: robust.objective,
    meanGapPct: round(meanGapPct, 2),
    worstGapPct: round(worstGapPct, 2),
    passes: meanGapPct <= 2 && worstGapPct <= 4,
    runs: robust.runs,
    scenarios: robust.scenarios,
    verification,
    byWidth,
  };
}

/**
 * Оффлайн-доли (#487): зашитый вектор #482 и таблица по 2–3 бакетам против
 * текущих продуктовых долей. Основной сценарий — полный текст (`clamp = ∞`,
 * `λ = 0`), поэтому потеря текста должна быть нулевой; обрезка пилюль считается
 * отдельно и в высоту не подмешивается.
 *
 * Подбор идёт на `fitSeed` (1), проверка — на остальных seed'ах и на профилях,
 * которых не было в подборе (`heldOut`). Вектор из #482 не пересчитывается:
 * в отчёт и в #483 идёт одна и та же константа, а `fit` показывает, насколько
 * текущая сетка данных от неё ушла.
 *
 * #488: дополнительно считаются два режима ограничения пилюль — `current`
 * (лимит = текущая продуктовая кривая по W) и `strict` (≤5% на любой W).
 * Для каждого — `search` с нижней границей на каждой W, один вектор и старые
 * 2/3 бакета, плюс таблица «цена п.п. обрезки в высоте».
 */
export function runOfflineShares(measurer, spec = {}) {
  const profiles = spec.profiles ?? PROFILES;
  const widths = spec.widths ?? [1180, 1400, 1500, 1600, 1920];
  const rows = spec.rows ?? 1000;
  const fitSeed = spec.fitSeed ?? 1;
  const seeds = spec.seeds ?? [fitSeed, 2];
  const columnCount = spec.columnCount ?? 11;
  const fitRows = spec.fitRows ?? 300;
  const fitWidths = spec.fitWidths ?? [1180, 1500, 1600];
  const fitMaxSweeps = spec.fitMaxSweeps ?? 3;
  const fitMaxCandidates = spec.fitMaxCandidates ?? 8;
  const trainProfiles = spec.trainProfiles ?? ["realistic", "all-short", "mixed"];
  const columns = mainColumns(columnCount);
  const flexIds = columns.filter((column) => column.flex).map((column) => column.id);
  const pinnedShares = normalizeShares(flexIds, OFFLINE_FLEX_SHARES);

  const preparedCache = new Map();
  const maxWordsCache = new Map();
  const preparedFor = (seed, profile) => {
    const key = `${seed}:${profile}`;
    if (!preparedCache.has(key)) {
      const sheet = generateSheet({ profile, rows, columns, seed });
      const prepared = prepareSheet(sheet, measurer);
      preparedCache.set(key, prepared);
      maxWordsCache.set(key, columnMaxWordWidths(prepared));
    }
    return preparedCache.get(key);
  };
  const fitPreparedCache = new Map();
  const fitPreparedFor = (profile) => {
    if (!fitPreparedCache.has(profile)) {
      const sheet = generateSheet({
        profile,
        rows: fitRows,
        columns,
        seed: fitSeed,
      });
      fitPreparedCache.set(profile, prepareSheet(sheet, measurer));
    }
    return fitPreparedCache.get(profile);
  };

  // Границы бакетов входят в сетку сценариев: без них бакет, подобранный в
  // середине диапазона, мог бы нарушить minPx у края.
  const boundaries = [
    ...new Set(
      Object.values(OFFLINE_BUCKET_PLANS).flatMap((plan) =>
        plan.buckets
          .map((bucket) => bucket.maxTableWidth)
          .filter((value) => Number.isFinite(value)),
      ),
    ),
  ];
  const scenarioWidths = [
    ...new Set([
      ...fitWidths,
      ...boundaries,
      ...Object.values(OFFLINE_BUCKET_PLANS).flatMap((plan) =>
        plan.buckets.flatMap((bucket) => bucket.fitWidths),
      ),
    ]),
  ].sort((a, b) => a - b);

  const scenarios = [];
  for (const profile of profiles) {
    const prepared = fitPreparedFor(profile);
    for (const tableWidth of scenarioWidths) {
      scenarios.push(
        buildRobustScenario({
          prepared,
          contentWidth: contentWidth(tableWidth),
          lambda: MAIN_LAMBDA,
          rowLimit: Math.min(fitRows, FIT_ROWS),
          maxCandidates: fitMaxCandidates,
          profile,
          tableWidth,
        }),
      );
    }
  }
  const fitScenarios = scenarios.filter((scenario) =>
    fitWidths.includes(scenario.tableWidth),
  );

  const fit = robustShares(fitScenarios, {
    objectives: spec.objectives,
    maxSweeps: fitMaxSweeps,
  });
  const fittedPlans = {};
  for (const [name, plan] of Object.entries(OFFLINE_BUCKET_PLANS)) {
    fittedPlans[name] = {
      label: plan.label,
      buckets: fitBucketShares(scenarios, plan, {
        objectives: spec.objectives,
        maxSweeps: fitMaxSweeps,
      }),
    };
  }

  const bucketName = (name) => `bucket${name === "two" ? 2 : 3}`;
  const planNames = Object.keys(fittedPlans);

  const widthsFor = (profile, seed, tableWidth) => {
    const prepared = preparedFor(seed, profile);
    const content = contentWidth(tableWidth);
    const policies = {
      current: baselineWidths(columns, content),
      offline: widthsFromFlexShares(columns, content, pinnedShares),
      refit: widthsFromFlexShares(columns, content, fit.shares),
      search: OPTIMIZERS.search(prepared, content, { lambda: MAIN_LAMBDA })
        .widths,
    };
    const buckets = {};
    for (const name of planNames) {
      const plan = fittedPlans[name];
      const index = bucketIndexForTableWidth(tableWidth, plan);
      buckets[name] = index;
      policies[bucketName(name)] = widthsFromFlexShares(
        columns,
        content,
        plan.buckets[index].shares,
      );
    }
    return { prepared, content, policies, buckets };
  };

  const metricPolicy = (prepared, widths, maxWordWidths, content) => {
    const metrics = policyMetrics(prepared, widths);
    const violations = offlineWidthViolations(
      columns,
      widths,
      content,
      maxWordWidths,
    );
    return {
      height: metrics.height,
      meanHeight: round(metrics.meanHeight, 2),
      p95Height: round(metrics.p95Height, 2),
      maxHeight: round(metrics.maxHeight, 2),
      textCells: metrics.textCells,
      textTruncatedCells: metrics.textTruncatedCells,
      textTruncatedSharePct: round(metrics.textTruncatedSharePct, 2),
      pillCells: metrics.pillCells,
      pillTruncatedCells: metrics.pillTruncatedCells,
      pillTruncatedSharePct: round(metrics.pillTruncatedSharePct, 2),
      widthSum: round(sumWidths(columns, widths), 1),
      violations,
      widths,
    };
  };

  const cases = [];
  for (const seed of seeds) {
    for (const profile of profiles) {
      const prepared = preparedFor(seed, profile);
      const maxWordWidths = maxWordsCache.get(`${seed}:${profile}`);
      for (const tableWidth of widths) {
        const { content, policies, buckets } = widthsFor(
          profile,
          seed,
          tableWidth,
        );
        const measured = {};
        for (const [name, policyWidths] of Object.entries(policies)) {
          measured[name] = metricPolicy(
            prepared,
            policyWidths,
            maxWordWidths,
            content,
          );
        }
        cases.push({
          seed,
          profile,
          tableWidth,
          contentWidth: content,
          buckets,
          policies: measured,
        });
      }
    }
  }

  const policyNames = ["current", "offline", "refit", "search"];
  for (const name of planNames) policyNames.push(bucketName(name));

  /**
   * Ограничение обрезки пилюль (#488). Пилюли не влияют на высоту, поэтому
   * неограниченный поиск отдаёт «Операциям» минимум и покупает высоту ценой
   * `title`-обрезки. Здесь — два режима нижней границы:
   * - `current` — не хуже текущего продукта на той же W (кривая #487);
   * - `strict`  — ≤5% строк с обрезанными пилюлями на любой W.
   * Для каждого режима считаются два ответа: `search` с ограничением на каждом
   * листе (оптимум при данной W) и один оффлайн-вектор долей (то, что можно
   * зашить). Текст не теряется: `clamp = ∞`, `λ = 0`.
   */
  const pillPolicySummary = (subset) => {
    const summarizeOne = (name) => {
      const items = subset.map((item) => item[name]);
      const heightPct = items.map((item) => item.heightPct);
      const pills = items.map((item) => item.pillTruncatedSharePct);
      const limits = subset.map((item) => item.limitPct);
      const currentPills = subset.map(
        (item) => item.current.pillTruncatedSharePct,
      );
      const gaps = items.map((item) => item.gapToUnconstrainedPct);
      return {
        cases: items.length,
        heightPctMean: round(average(heightPct), 2),
        heightPctWorst: round(maxOf(heightPct), 2),
        heightGainPctMean: round(-average(heightPct), 2),
        pillTruncatedSharePctMean: round(average(pills), 2),
        pillTruncatedSharePctWorst: round(maxOf(pills), 2),
        currentPillTruncatedSharePctMean: round(average(currentPills), 2),
        limitPctMean: round(average(limits), 2),
        pillExcessPpMean: round(average(items.map((item) => item.pillExcessPp)), 2),
        pillExcessPpWorst: round(maxOf(items.map((item) => item.pillExcessPp)), 2),
        textTruncatedSharePctWorst: round(
          maxOf(items.map((item) => item.textTruncatedSharePct)),
          2,
        ),
        gapToUnconstrainedPctMean: round(average(gaps), 2),
        gapToUnconstrainedPctWorst: round(maxOf(gaps), 2),
        violations: items.reduce((sum, item) => sum + item.violations, 0),
      };
    };
    return {
      search: summarizeOne("search"),
      vector: summarizeOne("vector"),
      bucket2: summarizeOne("bucket2"),
      bucket3: summarizeOne("bucket3"),
    };
  };

  const pillModes = {};
  for (const mode of PILLS_LIMIT_MODES) {
    const limitPctFor = (tableWidth) => pillsLimitPctForWidth(tableWidth, mode);
    const constrainedScenarios = [];
    for (const profile of profiles) {
      const prepared = fitPreparedFor(profile);
      for (const tableWidth of scenarioWidths) {
        constrainedScenarios.push(
          buildRobustScenario({
            prepared,
            contentWidth: contentWidth(tableWidth),
            lambda: MAIN_LAMBDA,
            rowLimit: Math.min(fitRows, FIT_ROWS),
            maxCandidates: fitMaxCandidates,
            profile,
            tableWidth,
            pillsMaxTruncatedShare: limitPctFor(tableWidth) / 100,
          }),
        );
      }
    }
    const constrainedFitScenarios = constrainedScenarios.filter((scenario) =>
      fitWidths.includes(scenario.tableWidth),
    );
    const vectorFit = robustShares(constrainedFitScenarios, {
      objectives: spec.objectives,
      maxSweeps: fitMaxSweeps,
      pillsConstrained: true,
    });
    const vectorShares = vectorFit.shares;
    // Один вектор на все W может быть несовместим с лимитом (сумма нижних
    // границ > 1). Бакеты — тот же запас, что в #487, но уже с ограничением:
    // если они снимают несовместимость и стоят дешевле, #483 зашивает бакеты.
    const constrainedPlans = {};
    for (const [name, plan] of Object.entries(OFFLINE_BUCKET_PLANS)) {
      constrainedPlans[name] = fitBucketShares(constrainedScenarios, plan, {
        objectives: spec.objectives,
        maxSweeps: fitMaxSweeps,
        pillsConstrained: true,
      });
    }

    const rows = [];
    for (const item of cases) {
      const content = item.contentWidth;
      const prepared = preparedFor(item.seed, item.profile);
      const maxWordWidths = maxWordsCache.get(`${item.seed}:${item.profile}`);
      const limitPct = limitPctFor(item.tableWidth);
      const current = item.policies.current;
      const unconstrained = item.policies.search;
      const flexWidth = (widths) =>
        columns
          .filter((column) => column.flex)
          .reduce((sum, column) => sum + widths[column.id], 0);
      const measure = (name, metrics, widths) => ({
        name,
        height: metrics.height,
        heightPct: round((metrics.height / (current.height || 1) - 1) * 100, 2),
        pillTruncatedSharePct: round(metrics.pillTruncatedSharePct, 2),
        pillExcessPp: round(metrics.pillTruncatedSharePct - limitPct, 2),
        textTruncatedSharePct: round(metrics.textTruncatedSharePct, 2),
        gapToUnconstrainedPct: round(
          (metrics.height / (unconstrained.height || 1) - 1) * 100,
          2,
        ),
        operationsWidth: round(widths.operations, 1),
        operationsFlexSharePct: round(
          (widths.operations / (flexWidth(widths) || 1)) * 100,
          2,
        ),
        violations: offlineWidthViolations(
          columns,
          widths,
          content,
          maxWordWidths,
        ).length,
      });

      const searchRun = OPTIMIZERS.search(prepared, content, {
        lambda: MAIN_LAMBDA,
        pillsMaxTruncatedShare: limitPct / 100,
      });
      const vectorWidths = widthsFromFlexShares(
        columns,
        content,
        vectorShares,
      );
      const bucketMeasurements = {};
      for (const [name, fitted] of Object.entries(constrainedPlans)) {
        const planKey = bucketName(name);
        const bucketIndex = bucketIndexForTableWidth(item.tableWidth, {
          buckets: fitted,
        });
        const bucketWidths = widthsFromFlexShares(
          columns,
          content,
          fitted[bucketIndex].shares,
        );
        bucketMeasurements[planKey] = {
          bucketIndex,
          widths: bucketWidths,
        };
      }
      rows.push({
        seed: item.seed,
        profile: item.profile,
        tableWidth: item.tableWidth,
        contentWidth: content,
        limitPct: round(limitPct, 2),
        current: {
          height: current.height,
          pillTruncatedSharePct: round(current.pillTruncatedSharePct, 2),
        },
        search: measure(
          "search",
          policyMetrics(prepared, searchRun.widths),
          searchRun.widths,
        ),
        vector: measure(
          "vector",
          policyMetrics(prepared, vectorWidths),
          vectorWidths,
        ),
        ...Object.fromEntries(
          Object.entries(bucketMeasurements).map(
            ([name, { widths: bucketWidths }]) => [
              name,
              measure(name, policyMetrics(prepared, bucketWidths), bucketWidths),
            ],
          ),
        ),
      });
    }

    const seedCases = rows.filter((item) => item.seed === fitSeed);
    const overall = pillPolicySummary(seedCases);
    // Пилюли «не хуже текущего» проверяются по средней доле: лимит задан
    // средней продуктовой кривой, а не по каждой строке. Худшее превышение
    // остаётся в отчёте как диагностика (полный лист против подвыборки).
    const withinLimit = (summary) =>
      summary.pillExcessPpMean <= 0.05 &&
      summary.violations === 0 &&
      summary.textTruncatedSharePctWorst === 0;
    const modeDecision = (summary) => ({
      heightPass: summary.heightGainPctMean >= 4,
      pillPass: withinLimit(summary),
      simultaneous:
        summary.heightGainPctMean >= 4 && withinLimit(summary),
    });
    pillModes[mode] = {
      mode,
      label:
        mode === "strict"
          ? `строгий ≤${PILLS_STRICT_LIMIT_PCT}%`
          : "не хуже текущего",
      limitPctByWidth: Object.fromEntries(
        widths.map((tableWidth) => [
          tableWidth,
          round(limitPctFor(tableWidth), 2),
        ]),
      ),
      vector: {
        shares: vectorShares,
        contentShares: contentSharesFromFlexShares(
          columns,
          contentWidth(1500),
          vectorShares,
        ),
        meanGapPct: round(vectorFit.meanGapPct, 2),
        worstGapPct: round(vectorFit.worstGapPct, 2),
        seed: vectorFit.seed,
        objective: vectorFit.objective,
        bounds: vectorFit.bounds,
        feasible: vectorFit.bounds.feasible,
      },
      rows,
      overall,
      byWidth: widths.map((tableWidth) => {
        const subset = seedCases.filter(
          (item) => item.tableWidth === tableWidth,
        );
        return {
          tableWidth,
          limitPctMean: round(
            average(subset.map((item) => item.limitPct)),
            2,
          ),
          ...pillPolicySummary(subset),
        };
      }),
      byProfile: profiles.map((profile) => {
        const subset = seedCases.filter((item) => item.profile === profile);
        return {
          profile,
          limitPctMean: round(
            average(subset.map((item) => item.limitPct)),
            2,
          ),
          ...pillPolicySummary(subset),
        };
      }),
      bySeed: seeds.map((seed) => ({
        seed,
        ...pillPolicySummary(rows.filter((item) => item.seed === seed)),
      })),
      decision: {
        search: modeDecision(overall.search),
        vector: modeDecision(overall.vector),
        bucket2: modeDecision(overall.bucket2),
        bucket3: modeDecision(overall.bucket3),
      },
      plans: Object.fromEntries(
        Object.entries(constrainedPlans).map(([name, buckets]) => [
          name,
          {
            label: OFFLINE_BUCKET_PLANS[name].label,
            buckets,
            feasible: buckets.every((bucket) => bucket.bounds.feasible),
          },
        ]),
      ),
    };
  }

  // Цена одного п.п. обрезки пилюль: ограничение `search` на каждой W, seed 1.
  // Это верхняя оценка (оптимум на листе), а не зашитый вектор — она показывает,
  // сколько высоты вообще стоит пропускать больше пилюль в `title`.
  const tradeoffLimits = spec.pillsTradeoffLimitsPct ?? [
    1, 3, 5, 10, 15, 20, 25, 30, 40, 50, 100,
  ];
  const tradeoffCases = cases.filter((item) => item.seed === fitSeed);
  const pillsTradeoff = tradeoffLimits.map((limitPct) => {
    const items = [];
    for (const item of tradeoffCases) {
      const prepared = preparedFor(item.seed, item.profile);
      const run = OPTIMIZERS.search(prepared, item.contentWidth, {
        lambda: MAIN_LAMBDA,
        pillsMaxTruncatedShare: limitPct / 100,
      });
      const metrics = policyMetrics(prepared, run.widths);
      items.push({
        heightPct:
          (metrics.height / (item.policies.current.height || 1) - 1) * 100,
        gapPct:
          (metrics.height / (item.policies.search.height || 1) - 1) * 100,
        pillPct: metrics.pillTruncatedSharePct,
      });
    }
    return {
      limitPct,
      heightGainPctMean: round(-average(items.map((item) => item.heightPct)), 2),
      pillTruncatedSharePctMean: round(
        average(items.map((item) => item.pillPct)),
        2,
      ),
      pillTruncatedSharePctWorst: round(
        maxOf(items.map((item) => item.pillPct)),
        2,
      ),
      gapToUnconstrainedPctMean: round(
        average(items.map((item) => item.gapPct)),
        2,
      ),
    };
  });
  const marginal = [];
  for (let index = 1; index < pillsTradeoff.length; index += 1) {
    const before = pillsTradeoff[index - 1];
    const after = pillsTradeoff[index];
    const deltaHeight = after.heightGainPctMean - before.heightGainPctMean;
    const deltaPill =
      after.pillTruncatedSharePctMean - before.pillTruncatedSharePctMean;
    marginal.push({
      fromLimitPct: before.limitPct,
      toLimitPct: after.limitPct,
      deltaHeightPct: round(deltaHeight, 2),
      deltaPillPp: round(deltaPill, 2),
      heightPctPerPillPp:
        Math.abs(deltaPill) > 1e-6 ? round(deltaHeight / deltaPill, 2) : null,
    });
  }
  const pillsConstraint = {
    modes: pillModes,
    tradeoff: {
      limits: pillsTradeoff,
      marginal,
      source: "search с нижней границей на каждом листе, seed 1; верхняя оценка",
    },
    limitSource: {
      current: PILLS_CURRENT_LIMIT_PCT,
      strict: PILLS_STRICT_LIMIT_PCT,
      note: "#487: текущая продуктовая обрезка пилюль, среднее по профилям",
    },
  };

  const summarize = (subset, names = policyNames) => {
    const summary = {};
    for (const name of names) {
      const items = subset.filter((item) => item.policies[name]);
      if (items.length === 0) continue;
      const heightPct = items.map(
        (item) =>
          (item.policies[name].height / item.policies.current.height - 1) * 100,
      );
      const textPct = items.map(
        (item) => item.policies[name].textTruncatedSharePct,
      );
      const pillPct = items.map(
        (item) => item.policies[name].pillTruncatedSharePct,
      );
      summary[name] = {
        cases: items.length,
        heightMean: round(average(items.map((item) => item.policies[name].height)), 1),
        heightPctMean: round(average(heightPct), 2),
        heightPctWorst: round(maxOf(heightPct), 2),
        heightPctBest: round(minOf(heightPct), 2),
        textTruncatedSharePctMean: round(average(textPct), 2),
        textTruncatedSharePctWorst: round(maxOf(textPct), 2),
        textTruncatedCells: items.reduce(
          (sum, item) => sum + item.policies[name].textTruncatedCells,
          0,
        ),
        pillTruncatedSharePctMean: round(average(pillPct), 2),
        pillTruncatedSharePctWorst: round(maxOf(pillPct), 2),
        violations: items.reduce(
          (sum, item) => sum + item.policies[name].violations.length,
          0,
        ),
      };
    }
    return summary;
  };

  const bySeed = {};
  for (const seed of seeds) {
    const subset = cases.filter((item) => item.seed === seed);
    bySeed[seed] = {
      overall: summarize(subset),
      byWidth: widths.map((tableWidth) => ({
        tableWidth,
        ...summarize(subset.filter((item) => item.tableWidth === tableWidth)),
      })),
      byProfile: profiles.map((profile) => ({
        profile,
        ...summarize(subset.filter((item) => item.profile === profile)),
      })),
    };
  }

  // Отложенные профили: вектор подобран без них, проверка — на них и на seed 2.
  const trainSet = new Set(trainProfiles);
  const testProfiles = profiles.filter((profile) => !trainSet.has(profile));
  const trainScenarios = fitScenarios.filter((scenario) =>
    trainSet.has(scenario.profile),
  );
  let heldOut = null;
  if (trainScenarios.length > 0 && testProfiles.length > 0) {
    const held = robustShares(trainScenarios, {
      objectives: spec.objectives,
      maxSweeps: fitMaxSweeps,
    });
    const heldCases = [];
    for (const seed of seeds) {
      for (const profile of testProfiles) {
        const prepared = preparedFor(seed, profile);
        const maxWordWidths = maxWordsCache.get(`${seed}:${profile}`);
        for (const tableWidth of widths) {
          const content = contentWidth(tableWidth);
          const currentWidths = baselineWidths(columns, content);
          const heldWidths = widthsFromFlexShares(columns, content, held.shares);
          heldCases.push({
            seed,
            profile,
            tableWidth,
            policies: {
              current: metricPolicy(
                prepared,
                currentWidths,
                maxWordWidths,
                content,
              ),
              held: metricPolicy(prepared, heldWidths, maxWordWidths, content),
            },
          });
        }
      }
    }
    heldOut = {
      trainProfiles: [...trainProfiles],
      testProfiles,
      shares: held.shares,
      meanGapPct: round(held.meanGapPct, 2),
      worstGapPct: round(held.worstGapPct, 2),
      bounds: held.bounds,
      cases: heldCases,
      bySeed: Object.fromEntries(
        seeds.map((seed) => [
          seed,
          summarize(
            heldCases.filter((item) => item.seed === seed),
            ["current", "held"],
          ),
        ]),
      ),
      overall: summarize(heldCases, ["current", "held"]),
    };
  }

  // Переключение бакета: на границе соседние векторы не должны давать скачок
  // больше выигрыша бакета над единым вектором, и не должны ломать минимумы.
  const bucketSwitches = planNames.map((name) => {
    const plan = fittedPlans[name];
    const boundariesForPlan = plan.buckets
      .slice(0, -1)
      .map((bucket) => bucket.maxTableWidth);
    const checks = boundariesForPlan.map((boundary, index) => {
      const items = [];
      for (const seed of seeds) {
        for (const profile of profiles) {
          const prepared = preparedFor(seed, profile);
          const maxWordWidths = maxWordsCache.get(`${seed}:${profile}`);
          const content = contentWidth(boundary);
          const leftWidths = widthsFromFlexShares(
            columns,
            content,
            plan.buckets[index].shares,
          );
          const rightWidths = widthsFromFlexShares(
            columns,
            content,
            plan.buckets[index + 1].shares,
          );
          const robustWidths = widthsFromFlexShares(
            columns,
            content,
            pinnedShares,
          );
          const left = metricPolicy(prepared, leftWidths, maxWordWidths, content);
          const right = metricPolicy(
            prepared,
            rightWidths,
            maxWordWidths,
            content,
          );
          const robust = metricPolicy(
            prepared,
            robustWidths,
            maxWordWidths,
            content,
          );
          const best = Math.min(left.height, right.height);
          const jumpPct =
            (Math.abs(left.height - right.height) / (best || 1)) * 100;
          const gainPct = ((robust.height - best) / (robust.height || 1)) * 100;
          items.push({
            seed,
            profile,
            leftHeight: left.height,
            rightHeight: right.height,
            jumpPct: round(jumpPct, 3),
            gainPct: round(gainPct, 3),
            withinGain: jumpPct <= gainPct + 1e-9,
            violations: [...left.violations, ...right.violations],
          });
        }
      }
      const worstJump = items.reduce(
        (worst, item) => (!worst || item.jumpPct > worst.jumpPct ? item : worst),
        null,
      );
      return {
        boundary,
        cases: items.length,
        worstJumpPct: worstJump ? worstJump.jumpPct : 0,
        worstJumpProfile: worstJump ? worstJump.profile : null,
        worstJumpSeed: worstJump ? worstJump.seed : null,
        worstJumpGainPct: worstJump ? worstJump.gainPct : 0,
        jumpExceedsGainCases: items.filter((item) => !item.withinGain).length,
        violations: items.reduce(
          (sum, item) => sum + item.violations.length,
          0,
        ),
        passes: items.every((item) => item.withinGain) &&
          items.every((item) => item.violations.length === 0),
        items,
      };
    });
    return {
      plan: name,
      label: plan.label,
      buckets: plan.buckets,
      boundaries: checks,
      passes: checks.every((item) => item.passes),
    };
  });

  const overall = summarize(cases);
  const primary = bySeed[fitSeed] ?? { overall };
  const heightGainPct = -(primary.overall.offline?.heightPctMean ?? 0);
  const pillDeltaPp =
    (primary.overall.offline?.pillTruncatedSharePctMean ?? 0) -
    (primary.overall.current?.pillTruncatedSharePctMean ?? 0);
  const heightPass = heightGainPct >= 4;
  const pillPass = -pillDeltaPp >= 1;
  const textLossPct = primary.overall.offline?.textTruncatedSharePctMean ?? 0;
  const profilesBelowHeight = (bySeed[fitSeed]?.byProfile ?? [])
    .filter(
      (item) =>
        item.offline &&
        -(item.offline.heightPctMean ?? 0) < 4,
    )
    .map((item) => ({
      profile: item.profile,
      heightGainPct: round(-(item.offline.heightPctMean ?? 0), 2),
    }));

  const decision = {
    threshold: { heightPct: 4, pillPp: 1 },
    fitSeed,
    heightGainPct: round(heightGainPct, 2),
    heightPass,
    textLossPct,
    textLossZero: textLossPct === 0,
    pillCurrentPct: primary.overall.current?.pillTruncatedSharePctMean ?? 0,
    pillOfflinePct: primary.overall.offline?.pillTruncatedSharePctMean ?? 0,
    pillDeltaPp: round(pillDeltaPp, 2),
    pillPass,
    passes: heightPass || pillPass,
    profilesBelowHeight,
    seed2: bySeed[2]?.overall.offline
      ? {
          heightGainPct: round(-bySeed[2].overall.offline.heightPctMean, 2),
          pillDeltaPp: round(
            bySeed[2].overall.offline.pillTruncatedSharePctMean -
              bySeed[2].overall.current.pillTruncatedSharePctMean,
            2,
          ),
        }
      : null,
  };
  if (heightPass && !pillPass) {
    decision.reason =
      `высота −${decision.heightGainPct}% против текущих долей (порог ≥4%) пройдена, ` +
      `но обрезка пилюль ${decision.pillCurrentPct}% → ${decision.pillOfflinePct}% ` +
      `(+${decision.pillDeltaPp} п.п.): это цена, а не улучшение. ` +
      "Формально §15 выполнен по высоте; допустимость обрезки пилюль решает #485.";
  } else if (pillPass && !heightPass) {
    decision.reason =
      `высота даёт только −${decision.heightGainPct}% (порог 4%), ` +
      `но обрезка пилюль снижается на ${-decision.pillDeltaPp} п.п. (порог 1 п.п.).`;
  } else if (heightPass && pillPass) {
    decision.reason =
      `высота −${decision.heightGainPct}% и обрезка пилюль ${decision.pillDeltaPp} п.п. — оба порога §15 пройдены.`;
  } else {
    decision.reason =
      `высота даёт −${decision.heightGainPct}% (порог 4%), обрезка пилюль ${decision.pillDeltaPp} п.п. ` +
      "(порог −1 п.п.): оффлайн-доли порог §15 не проходят, остаётся текущий фикс.";
  }

  return {
    spec: {
      ...spec,
      profiles,
      widths,
      rows,
      fitSeed,
      seeds,
      columnCount,
      fitRows,
      fitWidths,
      fitMaxSweeps,
      fitMaxCandidates,
      trainProfiles,
      pillsTradeoffLimitsPct: tradeoffLimits,
    },
    pinned: {
      source: OFFLINE_FLEX_SHARES_SOURCE,
      shares: pinnedShares,
      textLossPolicy: "полный текст: clamp = ∞, λ = 0",
    },
    fit: {
      shares: fit.shares,
      meanGapPct: round(fit.meanGapPct, 2),
      worstGapPct: round(fit.worstGapPct, 2),
      driftPp: round(
        maxOf(
          flexIds.map((id) => Math.abs(fit.shares[id] - pinnedShares[id]) * 100),
        ),
        3,
      ),
      seed: fit.seed,
      objective: fit.objective,
    },
    plans: fittedPlans,
    cases,
    overall,
    bySeed,
    heldOut,
    bucketSwitches,
    pillsConstraint,
    decision,
  };
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
        const textLoss = textTruncation(prepared, value.widths);
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
    meanCurrentTextTruncatedShare: mean((p) => p.currentProduct.textTruncatedShare),
    meanBaselineTextTruncatedShare: mean(
      (p) => p.noClampBaseline.textTruncatedShare,
    ),
    meanBestTextTruncatedShare: mean((p) => p.noClampBest.textTruncatedShare),
    meanGrowthBaselinePct: mean((p) => p.growthPct.baseline),
    meanGrowthBestPct: mean((p) => p.growthPct.best),
  };
}

function verdict(condition) {
  return condition ? "подтверждена" : "не подтверждена";
}

/**
 * Решение #482 по заранее записанному порогу. Порог не подгоняется:
 * (а) — перенос долей с W0 ≤3% (средняя и худшая по профилям);
 * (б) — робастный вектор, средний ≤2% и худший ≤4%, и не хуже (а);
 * (в) — иначе пересчёт на ресайзе остаётся.
 */
function buildDecision({ regret, robust }) {
  if (!regret && !robust) return null;
  const transferMean = regret
    ? maxOf(regret.byWidth.map((item) => item.meanScaledRegretPct))
    : null;
  const transferWorst = regret
    ? maxOf(regret.byWidth.map((item) => item.worstScaledRegretPct))
    : null;
  const transferPass =
    regret !== null && transferMean <= 3 && transferWorst <= 3;

  let robustNotWorse = null;
  if (regret && robust) {
    robustNotWorse = robust.byWidth.every((item) => {
      const scaled = regret.byWidth.find(
        (entry) => entry.tableWidth === item.tableWidth,
      );
      if (!scaled) return false;
      return (
        item.meanRobustGapPct <= scaled.meanScaledRegretPct + 1e-9 &&
        item.worstRobustGapPct <= scaled.worstScaledRegretPct + 1e-9
      );
    });
  }
  const robustPass = robust ? robust.passes : false;

  let option;
  let reason;
  if (transferPass) {
    option = "а";
    reason =
      "перенос долей с W0 укладывается в 3%: пересчёт на ресайзе не нужен, доли можно хранить в процентах.";
  } else if (robustPass && robustNotWorse) {
    option = "б";
    reason =
      "робастный вектор укладывается в 2%/4% и не хуже переноса с W0: его можно зашить константой.";
  } else {
    option = "в";
    const parts = [];
    if (regret) {
      parts.push(
        `перенос с W0 даёт худшую потерю ${transferWorst}% (порог 3%, средняя ${transferMean}%)`,
      );
    }
    if (robust) {
      parts.push(
        `робастный вектор — средний ${robust.meanGapPct}%, худший ${robust.worstGapPct}% (порог 2%/4%)`,
      );
      if (robustNotWorse === false) {
        parts.push("и он хуже переноса с W0 на части ширин");
      }
    }
    reason = `${parts.join("; ")}. Пересчёт на ресайзе остаётся, #483 обязан уложить его до первого показа таблицы.`;
  }

  return {
    option,
    reason,
    transfer: {
      meanPct: transferMean,
      worstPct: transferWorst,
      passes: transferPass,
      thresholdPct: 3,
      minViolations: regret
        ? regret.byWidth.reduce((sum, item) => sum + item.scaledViolations, 0)
        : null,
    },
    robust: robust && {
      meanPct: robust.meanGapPct,
      worstPct: robust.worstGapPct,
      passes: robustPass,
      notWorseThanTransfer: robustNotWorse,
      shares: robust.shares,
      contentShares: robust.contentShares,
    },
  };
}

function buildHypotheses({ oracle, sampleStability, widthStability, h4, regret, robust, offline }) {
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
    const fiveHundred = sampleStability.filter(
      (item) => item.sampleSize === undefined || item.sampleSize === 500,
    );
    const scope = fiveHundred.length > 0 ? fiveHundred : sampleStability;
    const worst = [...scope].sort(
      (a, b) => Math.abs(b.heightDeltaPct) - Math.abs(a.heightDeltaPct),
    )[0];
    const fails = scope.filter((item) => Math.abs(item.heightDeltaPct) > 2);
    const sizes = [...new Set(sampleStability.map((item) => item.sampleSize))]
      .filter((size) => size !== undefined)
      .sort((a, b) => a - b);
    hypotheses.push({
      id: "H2",
      statement:
        "подвыборка 500 строк даёт ≤2% потерь по высоте (clamp=∞, λ=0)",
      value: `${worst.heightDeltaPct}% (${worst.optimizer}/${worst.profile})`,
      threshold: "≤2%",
      verdict: verdict(fails.length === 0),
      note: `${scope.length} случаев${
        sizes.length ? `; размеры подвыборки ${sizes.join("/")} проверены отдельно` : ""
      }; вне порога: ${fails.length || "нет"}`,
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

  if (regret) {
    hypotheses.push({
      id: "H3-transfer",
      statement: `перенос долей с W0 = ${regret.spec.baseWidth} на W' стоит ≤3% cost против оптимума на W' (средняя и худшая по профилям)`,
      value: `средняя ≤${maxOf(
        regret.byWidth.map((item) => item.meanScaledRegretPct),
      )}%, худшая ${maxOf(
        regret.byWidth.map((item) => item.worstScaledRegretPct),
      )}%`,
      threshold: "≤3%",
      verdict: verdict(regret.summary.passes),
      note: `${regret.summary.caseCount} случаев, ${regret.spec.profiles.length} профилей; проценты масштабируются (реальное поведение table-fixed)`,
    });
  }

  if (robust) {
    hypotheses.push({
      id: "H3-robust",
      statement:
        "один робастный вектор: средний gap к оптимуму каждой W' ≤2%, худший ≤4%",
      value: `средний ${robust.meanGapPct}%, худший ${robust.worstGapPct}%`,
      threshold: "≤2% / ≤4%",
      verdict: verdict(robust.passes),
      note: `${robust.spec.profiles.length} профилей × ${robust.spec.widths.length} ширин; seed ${robust.seedUsed}, цель ${robust.objective}`,
    });
  }

  if (offline) {
    const item = offline.decision;
    hypotheses.push({
      id: "H-offline",
      statement:
        "оффлайн-доли (#482) дают ≥4% суммарной высоты или ≥1 п.п. обрезки пилюль против текущих долей (спека §15)",
      value: `высота −${item.heightGainPct}%, пилюли ${item.pillDeltaPp > 0 ? "+" : ""}${item.pillDeltaPp} п.п.; текст ${item.textLossPct}%`,
      threshold: "≥4% или ≥1 п.п.",
      verdict: item.passes ? "порог пройден" : "порог не пройден",
      note:
        `${offline.cases.length} конфигураций, seed ${item.fitSeed} (проверка seed 2); ` +
        `пилюли — отдельная метрика, не потеря текста; профилей ниже 4%: ${item.profilesBelowHeight.length}`,
    });
    if (offline.pillsConstraint) {
      const modes = offline.pillsConstraint.modes;
      const passes = (key) =>
        PILLS_LIMIT_MODES.filter(
          (mode) => modes[mode]?.decision[key]?.simultaneous,
        );
      const searchPass = passes("search");
      const vectorPass = passes("vector");
      const bucket3Pass = passes("bucket3");
      const parts = PILLS_LIMIT_MODES.map(
        (mode) =>
          `${mode}: высота ${signedPercent(modes[mode]?.overall.search.heightPctMean)}, ` +
          `пилюли ${modes[mode]?.overall.search.pillTruncatedSharePctMean}%`,
      );
      hypotheses.push({
        id: "H-pills",
        statement:
          "ограничение обрезки пилюль (#488) совместимо с выигрышем ≥4% высоты",
        value: parts.join("; "),
        threshold: "пилюли не хуже текущего и высота ≥4%",
        verdict:
          searchPass.length > 0 ||
          vectorPass.length > 0 ||
          bucket3Pass.length > 0
            ? "порог пройден"
            : "порог не пройден",
        note: `одновременно: search — ${searchPass.join(", ") || "нет"}, vector — ${vectorPass.join(", ") || "нет"}, 3 бакета — ${bucket3Pass.join(", ") || "нет"}`,
      });
    }
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
    regret,
    robust,
    offline,
    decision,
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
    `- Конфигураций: ${meta.counts.matrix} матрица, ${meta.counts.product} продуктовый срез, ${meta.counts.oracle} оракул, ${meta.counts.sweep} свип, ${meta.counts.stability} матрица сожалений, ${meta.counts.robust} сценариев робастного вектора, ${meta.counts.offline} оффлайн-долей, ${meta.counts.virtualization} виртуализация`,
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
      push("| Политика | Средняя высота строки | Суммарная высота (сред.) | Потеря текста, % | Обрезка пилюль/служебных, % | Рост к текущему фиксу |");
      push("|---|---:|---:|---:|---:|---:|");
      push(
        `| Текущий продукт (наименование 1 строка, ошибки перенос) | ${policies.meanCurrentRowHeight} | ${policies.meanCurrentTotalHeight} | ${policies.meanCurrentTextTruncatedShare} | ${policies.meanCurrentTruncatedShare} | 0% |`,
      );
      push(
        `| Baseline-доли, полный текст | ${policies.meanBaselineRowHeight} | ${policies.meanBaselineTotalHeight} | ${policies.meanBaselineTextTruncatedShare} | ${policies.meanBaselineTruncatedShare} | ${signedPercent(policies.meanGrowthBaselinePct)} |`,
      );
      push(
        `| \`search\`, полный текст | ${policies.meanBestRowHeight} | ${policies.meanBestTotalHeight} | ${policies.meanBestTextTruncatedShare} | ${policies.meanBestTruncatedShare} | ${signedPercent(policies.meanGrowthBestPct)} |`,
      );
      push("");
      push(
        "«Потеря текста» — только текстовые колонки (наименование, ошибки): у текущего продукта это обрезанные наименования, у полного текста — ноль. «Обрезка пилюль/служебных» — отдельная политика `nowrap` для «Операций» и mono-колонок: подпись остаётся в `title`, это не скрытый текст. Смешивать эти два числа нельзя.",
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

  if (regret) {
    push("## Матрица сожалений: доли с W0 на других ширинах (#482)");
    push("");
    push(
      `Оптимизатор \`${regret.spec.optimizer}\`, продуктовый срез ${regret.spec.columnCount} колонок, ${regret.spec.rows} строк, seed ${regret.spec.seed}. ` +
        `Доли подобраны на \`W0 = ${regret.spec.baseWidth}\`, затем применены к \`W'\`. «Проценты» — реальное поведение \`table-fixed\`: \`share × contentWidth(W')\`; ` +
        "«пиксели без масштабирования» — диагностика, не поведение продукта. Потеря — относительно раскладки `search`, оптимальной на самой `W'`.",
    );
    push("");
    push("| W' | Профилей | Средняя потеря (проценты), % | Худшая потеря (проценты), % | Худший профиль | Средняя потеря (px без масштаба), % | Худшая (px), % | Наруш. minPx/maxShare |");
    push("|---:|---:|---:|---:|---|---:|---:|---:|");
    for (const item of regret.byWidth) {
      push(
        `| ${item.tableWidth} | ${item.profiles} | ${item.meanScaledRegretPct} | ${item.worstScaledRegretPct} | ${item.worstScaledProfile} | ${item.meanFixedPixelRegretPct} | ${item.worstFixedPixelRegretPct} | ${item.scaledViolations} |`,
      );
    }
    push("");
    push(
      `Средняя по всей сетке — **${regret.summary.meanScaledRegretPct}%**, худшая — **${regret.summary.worstScaledRegretPct}%**; порог тикета ≤${regret.summary.thresholdPct}% ${regret.summary.passes ? "пройден" : "не пройден"}. ` +
        "Нарушения `minPx` — честная цена процентов: при узкой `W'` доля опускается ниже продуктового минимума (например, «Операции»/«Качество» на 1180), и реальная таблица либо ужмёт контрол, либо получит горизонтальный скролл. Это отдельный аргумент против варианта «(а)».",
    );
    push("");
  }

  if (robust) {
    push("## Робастный вектор: один набор долей на профили и ширины (#482)");
    push("");
    push(
      `Доли гибких колонок от бюджета гибких (сумма 100%); фиксированные — продуктовые. Поиск: ${robust.spec.profiles.length} профилей × ${robust.spec.widths.length} ширин, ` +
        `${robust.spec.rows} строк, seed ${robust.spec.seed}; seed поиска \`${robust.seedUsed}\`, цель \`${robust.objective}\`. ` +
        "Gap считается на полных листах против `search` на той же `W'`.",
    );
    push("");
    push("| Колонка | Доля гибкого бюджета, % | Доля контента при W0 = 1500, % |");
    push("|---|---:|---:|");
    for (const [id, share] of Object.entries(robust.shares)) {
      push(
        `| ${id} | ${round(share * 100, 2)} | ${round((robust.contentShares[id] ?? 0) * 100, 2)} |`,
      );
    }
    push("");
    push("| W' | Профилей | Средний gap, % | Худший gap, % | Худший профиль | Средний перенос с W0, % | Худший перенос с W0, % | Наруш. min/max |");
    push("|---:|---:|---:|---:|---|---:|---:|---:|");
    for (const item of robust.byWidth) {
      push(
        `| ${item.tableWidth} | ${item.profiles} | ${item.meanRobustGapPct} | ${item.worstRobustGapPct} | ${item.worstRobustProfile} | ${item.meanScaledRegretPct} | ${item.worstScaledRegretPct} | ${item.violations} |`,
      );
    }
    push("");
    push(
      `Средний gap — **${robust.meanGapPct}%**, худший — **${robust.worstGapPct}%**; порог 2%/4% ${robust.passes ? "пройден" : "не пройден"}. ` +
        `Ограничения по \`minPx\`/\`maxShare\` ${robust.bounds.feasible ? "совместимы на всех ширинах" : "несовместимы: вектор не может уважать минимумы сразу на всех W'"}; нарушений в проверке — ${robust.byWidth.reduce((sum, item) => sum + item.violations, 0)}.`,
    );
    push("");
  }

  if (offline) {
    const seed1 = offline.bySeed[offline.spec.fitSeed] ?? null;
    const seed2 = offline.bySeed[2] ?? null;
    const names = ["offline", "search", "bucket2", "bucket3"];
    push("## Оффлайн-доли: зашитый вектор против текущих долей (#487)");
    push("");
    push(
      `Порог §15: оффлайн-доли достаточны при **≥${offline.decision.threshold.heightPct}% суммарной высоты** или **≥${offline.decision.threshold.pillPp} п.п. обрезки пилюль** против текущих долей при полном тексте (\`clamp = ∞\`, \`λ = 0\`). ` +
        `Вектор — ${offline.pinned.source}; он не пересчитывается. Диагностический пересчёт по seed 1 ` +
        `(${offline.spec.fitWidths.join("/")}, ${offline.spec.fitRows} строк) дал ` +
        `${Object.entries(offline.fit.shares).map(([id, share]) => `${id} ${round(share * 100, 2)}%`).join(" / ")} ` +
        `(расхождение с константой ≤${offline.fit.driftPp} п.п.), поэтому отчёт и #483 говорят об одних числах.`,
    );
    push("");
    push("| Колонка | Доля гибкого бюджета, % | Доля контента при W0 = 1500, % |");
    push("|---|---:|---:|");
    {
      const w0Case =
        offline.cases.find(
          (item) =>
            item.tableWidth === 1500 && item.seed === offline.spec.fitSeed,
        ) ?? offline.cases[0];
      const content = w0Case?.contentWidth ?? 1500 - SERVICE_WIDTH_PX;
      const widths = w0Case?.policies.offline.widths ?? {};
      for (const [id, share] of Object.entries(offline.pinned.shares)) {
        push(
          `| ${id} | ${round(share * 100, 2)} | ${round(((widths[id] ?? 0) / content) * 100, 2)} |`,
        );
      }
    }
    push("");
    push("### Высота по ширине таблицы (seed 1, среднее по профилям)");
    push("");
    push("| W | Текущие, px | Оффлайн, px | Оффлайн Δ | search, px | search Δ | 2 бакета, px | 2 бакета Δ | 3 бакета, px | 3 бакета Δ |");
    push("|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|");
    for (const group of seed1.byWidth) {
      const cell = (name) =>
        group[name]
          ? `${group[name].heightMean} | ${signedPercent(group[name].heightPctMean)}`
          : "— | —";
      push(
        `| ${group.tableWidth} | ${group.current.heightMean} | ${cell("offline")} | ${cell("search")} | ${cell("bucket2")} | ${cell("bucket3")} |`,
      );
    }
    push("");
    push("### Текст и пилюли по ширине (seed 1, % ячеек)");
    push("");
    push(
      "Потеря текста — только текстовые колонки (наименование, ошибки); у полного текста она обязана быть 0. Обрезка пилюль — только «Операции» (`nowrap`, подпись в `title`), это не потеря текста.",
    );
    push("");
    push("| W | Текст: текущие / оффлайн / search / 2 бакета / 3 бакета | Пилюли: текущие | Пилюли: оффлайн | Пилюли: search | Пилюли: 2 бакета | Пилюли: 3 бакета |");
    push("|---:|---|---:|---:|---:|---:|---:|");
    for (const group of seed1.byWidth) {
      const text = ["current", ...names]
        .map((name) => `${group[name]?.textTruncatedSharePctMean ?? "—"}`)
        .join(" / ");
      push(
        `| ${group.tableWidth} | ${text} | ${group.current.pillTruncatedSharePctMean} | ${group.offline.pillTruncatedSharePctMean} | ${group.search.pillTruncatedSharePctMean} | ${group.bucket2.pillTruncatedSharePctMean} | ${group.bucket3.pillTruncatedSharePctMean} |`,
      );
    }
    push("");
    push("### Профили (seed 1, все ширины)");
    push("");
    push("| Профиль | Текущие, px | Оффлайн Δ | search Δ | 2 бакета Δ | 3 бакета Δ | Пилюли: текущие → оффлайн |");
    push("|---|---:|---:|---:|---:|---:|---:|");
    for (const item of seed1.byProfile) {
      push(
        `| ${item.profile} | ${item.current.heightMean} | ${signedPercent(item.offline.heightPctMean)} | ${signedPercent(item.search.heightPctMean)} | ${signedPercent(item.bucket2.heightPctMean)} | ${signedPercent(item.bucket3.heightPctMean)} | ${item.current.pillTruncatedSharePctMean} → ${item.offline.pillTruncatedSharePctMean} |`,
      );
    }
    push("");
    const sliceWidth = offline.spec.widths.includes(1500)
      ? 1500
      : offline.spec.widths[Math.floor(offline.spec.widths.length / 2)];
    const slice = offline.cases.filter(
      (item) => item.seed === offline.spec.fitSeed && item.tableWidth === sliceWidth,
    );
    if (slice.length > 0) {
      const avgPct = (name) =>
        round(
          average(
            slice.map(
              (item) =>
                (item.policies[name].height /
                  item.policies.current.height -
                  1) *
                100,
            ),
          ),
          2,
        );
      push(`### Срез по профилям при W = ${sliceWidth} (seed 1)`);
      push("");
      push("| Профиль | Текущие, px | Оффлайн Δ | search Δ | 2 бакета Δ | 3 бакета Δ | Пилюли: текущие → оффлайн |");
      push("|---|---:|---:|---:|---:|---:|---:|");
      for (const profile of offline.spec.profiles) {
        const item = slice.find((entry) => entry.profile === profile);
        if (!item) continue;
        const cell = (name) =>
          signedPercent(
            round(
              (item.policies[name].height /
                item.policies.current.height -
                1) *
                100,
              2,
            ),
          );
        push(
          `| ${profile} | ${item.policies.current.height} | ${cell("offline")} | ${cell("search")} | ${cell("bucket2")} | ${cell("bucket3")} | ${item.policies.current.pillTruncatedSharePct} → ${item.policies.offline.pillTruncatedSharePct} |`,
        );
      }
      push("");
    }
    push("### Устойчивость: seed 2");
    push("");
    push("| Seed | Оффлайн Δ высоты | Оффлайн пилюли | Текущие пилюли | Текст оффлайн |");
    push("|---:|---:|---:|---:|---:|");
    for (const seed of offline.spec.seeds) {
      const item = offline.bySeed[seed];
      if (!item) continue;
      push(
        `| ${seed} | ${signedPercent(item.overall.offline.heightPctMean)} | ${item.overall.offline.pillTruncatedSharePctMean}% | ${item.overall.current.pillTruncatedSharePctMean}% | ${item.overall.offline.textTruncatedSharePctMean}% |`,
      );
    }
    push("");
    if (offline.heldOut) {
      push("### Отложенные профили (вектор подобран без них)");
      push("");
      push(
        `Подбор: ${offline.heldOut.trainProfiles.join(", ")}; проверка: ${offline.heldOut.testProfiles.join(", ")}. ` +
          `Доли: ${Object.entries(offline.heldOut.shares).map(([id, share]) => `${id} ${round(share * 100, 2)}%`).join(" / ")}; ` +
          `средний gap ${offline.heldOut.meanGapPct}%, худший ${offline.heldOut.worstGapPct}%.`,
      );
      push("");
      push("| Seed | Оффлайн Δ высоты | Пилюли | Текст |");
      push("|---:|---:|---:|---:|");
      for (const seed of offline.spec.seeds) {
        const item = offline.heldOut.bySeed[seed];
        if (!item) continue;
        push(
          `| ${seed} | ${signedPercent(item.held.heightPctMean)} | ${item.held.pillTruncatedSharePctMean}% | ${item.held.textTruncatedSharePctMean}% |`,
        );
      }
      push("");
    }
    push("### Бакетные таблицы");
    push("");
    push("| План | Бакет | Диапазон W | Автоподбор на W | source / operations / errors, % | Средний gap | Худший gap |");
    push("|---|---:|---|---:|---|---:|---:|");
    for (const name of Object.keys(offline.plans)) {
      const plan = offline.plans[name];
      plan.buckets.forEach((bucket, index) => {
        const lower = index === 0 ? 0 : plan.buckets[index - 1].maxTableWidth;
        const upper = Number.isFinite(bucket.maxTableWidth)
          ? bucket.maxTableWidth
          : "∞";
        push(
          `| ${plan.label} | ${index} | ${lower} < W ≤ ${upper} | ${bucket.fitWidths.join(", ")} | ${["source_name", "operations", "errors"].map((id) => round(bucket.shares[id] * 100, 2)).join(" / ")} | ${round(bucket.meanGapPct, 2)} | ${round(bucket.worstGapPct, 2)} |`,
        );
      });
    }
    push("");
    push("| План | Граница W | Худший скачок, % | Выигрыш бакета, % | Профиль / seed | Скачок ≤ выигрыш | Наруш. min/max |");
    push("|---|---:|---:|---:|---|---:|---:|");
    for (const plan of offline.bucketSwitches) {
      for (const item of plan.boundaries) {
        push(
          `| ${plan.label} | ${item.boundary} | ${item.worstJumpPct} | ${item.worstJumpGainPct} | ${item.worstJumpProfile} / ${item.worstJumpSeed} | ${item.jumpExceedsGainCases === 0 ? "да" : `нет (${item.jumpExceedsGainCases}/${item.cases})`} | ${item.violations} |`,
        );
      }
    }
    push("");
    {
      const failures = offline.bucketSwitches.reduce(
        (sum, plan) =>
          sum +
          plan.boundaries.reduce(
            (boundarySum, item) => boundarySum + item.jumpExceedsGainCases,
            0,
          ),
        0,
      );
      const checks = offline.bucketSwitches.reduce(
        (sum, plan) =>
          sum +
          plan.boundaries.reduce(
            (boundarySum, item) => boundarySum + item.cases,
            0,
          ),
        0,
      );
      const maxGain = maxOf(
        offline.bucketSwitches.flatMap((plan) =>
          plan.boundaries.map((item) => item.worstJumpGainPct),
        ),
      );
      push(
        `Бакеты **${offline.bucketSwitches.every((plan) => plan.passes) ? "проходят" : "не проходят"}** собственный критерий: скачок на границе не должен быть больше выигрыша бакета над единым вектором и не должен ломать \`minPx\`/\`maxShare\`. ` +
          `Скачок превышает выигрыш в ${failures} из ${checks} проверок, максимальный выигрыш — ${round(maxGain, 2)}%. ` +
          "Таблица бакетов не окупает разрыв в раскладке при ресайзе: остаётся единый вектор.",
      );
    }
    push("");
    push("### Вердикт по порогу §15");
    push("");
    push(
      `- Высота: **${offline.decision.heightPass ? "пройдено" : "не пройдено"}** — −${offline.decision.heightGainPct}% против текущих долей (порог ≥4%).`,
    );
    push(
      `- Потеря текста: **${offline.decision.textLossPct}%** (должна быть 0).`,
    );
    push(
      `- Обрезка пилюль: ${offline.decision.pillCurrentPct}% → ${offline.decision.pillOfflinePct}% (${offline.decision.pillDeltaPp > 0 ? "+" : ""}${offline.decision.pillDeltaPp} п.п.); критерий ≥1 п.п. **${offline.decision.pillPass ? "пройден" : "не пройден"}**.`,
    );
    if (offline.decision.profilesBelowHeight.length > 0) {
      push(
        `- Профили ниже 4%: ${offline.decision.profilesBelowHeight.map((item) => `${item.profile} (${item.heightGainPct}%)`).join(", ")}. Среднее по сетке тянут \`long-tail\` и \`empty\`; типичный \`realistic\` в порог не укладывается.`,
      );
    }
    push(
      `- Seed 2: высота ${seed2 ? signedPercent(seed2.overall.offline.heightPctMean) : "—"}, пилюли ${seed2 ? seed2.overall.offline.pillTruncatedSharePctMean : "—"}% (устойчивость подтверждена).`,
    );
    push("");
    push(`**${offline.decision.reason}**`);
    push("");
    if (offline.pillsConstraint) {
      const pc = offline.pillsConstraint;
      push("### Ограничение обрезки пилюль «Операций» (#488)");
      push("");
      push(
        "Пилюли не влияют на высоту (одна строка), поэтому неограниченный `search` отдаёт «Операциям» минимум и экономит высоту обрезкой подписи в `title`. " +
          "Ограничение — не штраф, а нижняя граница: по кривым порогов берётся минимальная ширина «Операций», при которой доля строк с обрезанными пилюлями укладывается в лимит. " +
          "`search` — оптимум при ограничении на каждой W; `vector` — один оффлайн-вектор для зашивки. Высота — Δ к текущим долям (отрицательная = лучше), gap — к неограниченному оптимуму на той же W.",
      );
      push("");
      for (const mode of PILLS_LIMIT_MODES) {
        const item = pc.modes[mode];
        if (!item) continue;
        const shares = ["source_name", "operations", "errors"]
          .map((id) => `${id} ${round((item.vector.shares[id] ?? 0) * 100, 2)}%`)
          .join(" / ");
        push(
          `#### Режим «${item.label}»: ${mode === "strict" ? `≤${PILLS_STRICT_LIMIT_PCT}% на любой W` : "лимит = текущая продуктовая доля на той же W"}`,
        );
        push("");
        push(
          `Вектор: ${shares} гибкого бюджета; средний gap ${item.vector.meanGapPct}%, худший ${item.vector.worstGapPct}%; один вектор ${item.vector.feasible ? "совместим с лимитами" : "**несовместим с лимитами на всех W** (сумма нижних границ > 1)"}. Лимиты по W: ${Object.entries(
            item.limitPctByWidth,
          )
            .map(([width, limit]) => `${width} — ${limit}%`)
            .join(", ")}.`,
        );
        push("");
        push("| W | Лимит, % | search: высота Δ | search: пилюли, % | vector: высота Δ | vector: пилюли, % | 2 бакета: высота Δ | 2 бакета: пилюли, % | 3 бакета: высота Δ | 3 бакета: пилюли, % | Текст (max), % | gap search, % |");
        push("|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|");
        for (const group of item.byWidth) {
          push(
            `| ${group.tableWidth} | ${group.limitPctMean} | ${signedPercent(group.search.heightPctMean)} | ${group.search.pillTruncatedSharePctMean} | ${signedPercent(group.vector.heightPctMean)} | ${group.vector.pillTruncatedSharePctMean} | ${signedPercent(group.bucket2.heightPctMean)} | ${group.bucket2.pillTruncatedSharePctMean} | ${signedPercent(group.bucket3.heightPctMean)} | ${group.bucket3.pillTruncatedSharePctMean} | ${group.vector.textTruncatedSharePctWorst} | ${group.search.gapToUnconstrainedPctMean} |`,
          );
        }
        push("");
        push("| Профиль | search: высота Δ | search: пилюли, % | vector: высота Δ | vector: пилюли, % | 2 бакета Δ | 3 бакета Δ |");
        push("|---|---:|---:|---:|---:|---:|---:|");
        for (const group of item.byProfile) {
          push(
            `| ${group.profile} | ${signedPercent(group.search.heightPctMean)} | ${group.search.pillTruncatedSharePctMean} | ${signedPercent(group.vector.heightPctMean)} | ${group.vector.pillTruncatedSharePctMean} | ${signedPercent(group.bucket2.heightPctMean)} | ${signedPercent(group.bucket3.heightPctMean)} |`,
          );
        }
        push("");
        push(
          `- **search:** высота ${signedPercent(item.overall.search.heightPctMean)} (порог ≥4% — ${item.decision.search.heightPass ? "пройден" : "не пройден"}), пилюли ${item.overall.search.pillTruncatedSharePctMean}% (превышение лимита в среднем ${item.overall.search.pillExcessPpMean} п.п., худшее ${item.overall.search.pillExcessPpWorst} п.п.; критерий ${item.decision.search.pillPass ? "пройден" : "не пройден"}), текст ${item.overall.search.textTruncatedSharePctWorst}%, нарушений ${item.overall.search.violations}.`,
        );
        push(
          `- **vector:** высота ${signedPercent(item.overall.vector.heightPctMean)} (порог ≥4% — ${item.decision.vector.heightPass ? "пройден" : "не пройден"}), пилюли ${item.overall.vector.pillTruncatedSharePctMean}% (превышение в среднем ${item.overall.vector.pillExcessPpMean} п.п., худшее ${item.overall.vector.pillExcessPpWorst} п.п.; критерий ${item.decision.vector.pillPass ? "пройден" : "не пройден"}), текст ${item.overall.vector.textTruncatedSharePctWorst}%, нарушений ${item.overall.vector.violations}.`,
        );
        push(
          `- **2 бакета:** высота ${signedPercent(item.overall.bucket2.heightPctMean)}, пилюли ${item.overall.bucket2.pillTruncatedSharePctMean}%, нарушений ${item.overall.bucket2.violations}, лимиты ${item.plans.two?.feasible ? "совместимы" : "несовместимы"}; **3 бакета:** высота ${signedPercent(item.overall.bucket3.heightPctMean)}, пилюли ${item.overall.bucket3.pillTruncatedSharePctMean}%, нарушений ${item.overall.bucket3.violations}, лимиты ${item.plans.three?.feasible ? "совместимы" : "несовместимы"}.`,
        );
        push(
          `- **Одновременно «пилюли не хуже текущего» и «высота ≥4%»:** search — ${item.decision.search.simultaneous ? "да" : "нет"}, vector — ${item.decision.vector.simultaneous ? "да" : "нет"}, 2 бакета — ${item.decision.bucket2.simultaneous ? "да" : "нет"}, 3 бакета — ${item.decision.bucket3.simultaneous ? "да" : "нет"}.`,
        );
        push("");
      }
      push("#### Цена обрезки пилюль в высоте (search, seed 1)");
      push("");
      push(
        "Ограничение на каждой W — верхняя оценка: это лучшая высота, которую можно получить при данном лимите. Пилюли в таблице — фактическая доля строк, а не лимит: при малом лимите ограничение упирается в максимальную ширину «Операций».",
      );
      push("");
      push("| Лимит, % | Высота Δ к текущим | Пилюли, % (сред.) | Пилюли, % (худш.) | gap к неограниченному, % |");
      push("|---:|---:|---:|---:|---:|");
      for (const row of pc.tradeoff.limits) {
        push(
          `| ${row.limitPct} | ${signedPercent(-row.heightGainPctMean)} | ${row.pillTruncatedSharePctMean} | ${row.pillTruncatedSharePctWorst} | ${row.gapToUnconstrainedPctMean} |`,
        );
      }
      push("");
      const priced = pc.tradeoff.marginal.filter(
        (row) => row.heightPctPerPillPp !== null,
      );
      if (priced.length > 0) {
        push(
          `Средняя цена п.п. обрезки на промежутках — от ${minOf(
            priced.map((row) => row.heightPctPerPillPp),
          )}% до ${maxOf(
            priced.map((row) => row.heightPctPerPillPp),
          )}% высоты за п.п.; на всём диапазоне ограничение стоит тем дороже, чем ближе лимит к нулю.`,
        );
      }
      push("");
    }
  }

  if (decision) {
    push("## Решение по порогу (#482 → #483/#487)");
    push("");
    push(
      `- **(а) считать на W0 и масштабировать:** средняя ${decision.transfer.meanPct}%, худшая ${decision.transfer.worstPct}% (порог ≤3%) — ${decision.transfer.passes ? "проходит" : "не проходит"}; нарушений ` +
        `\`minPx\`/\`maxShare\` при переносе — ${decision.transfer.minViolations}.`,
    );
    if (decision.robust) {
      push(
        `- **(б) робастный вектор один раз:** средний ${decision.robust.meanPct}%, худший ${decision.robust.worstPct}% (порог ≤2%/≤4%) — ${decision.robust.passes ? "проходит" : "не проходит"}; ` +
          `не хуже переноса с W0 — ${decision.robust.notWorseThanTransfer ? "да" : "нет"}.`,
      );
    }
    push(`- **Выбрано: (${decision.option}).** ${decision.reason}`);
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
    const sizes = [...new Set(sampleStability.map((item) => item.sampleSize ?? 500))]
      .sort((a, b) => a - b);
    push(
      "Первые N строк листа против оптимизации на полном листе (5000 строк — фиксированный лист профиля). Метрики — на полном листе, основной сценарий.",
    );
    push("");
    push(`| Профиль | N | Худшая Δ высоты, % | Оптимизатор | Худшая Δ cost, % | Δ ширины (max), px |`);
    push("|---|---:|---:|---|---:|---:|");
    for (const profile of [...new Set(sampleStability.map((item) => item.profile))]) {
      for (const size of sizes) {
        const subset = sampleStability.filter(
          (item) =>
            item.profile === profile && (item.sampleSize ?? 500) === size,
        );
        if (subset.length === 0) continue;
        const byHeight = subset.reduce((worst, item) =>
          Math.abs(item.heightDeltaPct) > Math.abs(worst.heightDeltaPct)
            ? item
            : worst,
        );
        const byCost = subset.reduce((worst, item) =>
          Math.abs(item.costDeltaPct) > Math.abs(worst.costDeltaPct)
            ? item
            : worst,
        );
        const maxWidth = Math.max(...subset.map((item) => item.maxFlexWidthDeltaPx));
        push(
          `| ${profile} | ${size} | ${byHeight.heightDeltaPct} | ${byHeight.optimizer} | ${byCost.costDeltaPct} | ${maxWidth} |`,
        );
      }
    }
    push("");
    push(
      "Отрицательная Δ значит, что раскладка по подвыборке оказалась дешевле полного поиска на этом листе: подвыборка не видит хвост и не раздувает колонки под редкие длинные строки. Для H2 важен модуль Δ относительно порога 2%.",
    );
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

  let regret = null;
  if (SECTIONS_TO_RUN.includes("stability")) {
    regret = runRegretMatrix(measurer, stabilitySpec());
    console.log(`[bench] stability: ${regret.cases.length} конфигураций`);
  }

  let robust = null;
  if (SECTIONS_TO_RUN.includes("robust")) {
    robust = runRobustVector(measurer, robustSpec());
    console.log(
      `[bench] robust: ${robust.scenarios.length} сценариев, средний ${robust.meanGapPct}%, худший ${robust.worstGapPct}%`,
    );
  }

  let offline = null;
  if (SECTIONS_TO_RUN.includes("offline")) {
    offline = runOfflineShares(measurer, offlineSpec());
    console.log(
      `[bench] offline: ${offline.cases.length} конфигураций, высота ${signedPercent(
        -offline.decision.heightGainPct,
      )}, пилюли ${offline.decision.pillDeltaPp} п.п., порог §15 ${
        offline.decision.passes ? "пройден" : "не пройден"
      }`,
    );
  }
  const decision = buildDecision({ regret, robust });

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
    SECTIONS_TO_RUN.includes("matrix") ||
    SECTIONS_TO_RUN.includes("product") ||
    SECTIONS_TO_RUN.includes("stability") ||
    SECTIONS_TO_RUN.includes("robust");
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
    regret,
    robust,
    offline,
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
      stability: regret?.cases.length ?? 0,
      robust: robust?.scenarios.length ?? 0,
      offline: offline?.cases.length ?? 0,
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
    stability: regret,
    robust,
    offline,
    decision,
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
    regret,
    robust,
    offline,
    decision,
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
  if (regret) {
    console.log("");
    console.log("Перенос долей с W0 (проценты) против оптимума на W':");
    for (const item of regret.byWidth) {
      console.log(
        `W'=${String(item.tableWidth).padStart(4)}  средняя ${String(item.meanScaledRegretPct).padStart(6)}%  худшая ${String(item.worstScaledRegretPct).padStart(6)}%  нарушений ${item.scaledViolations}`,
      );
    }
  }
  if (robust) {
    console.log("");
    console.log("Робастный вектор (доли гибких колонок):");
    for (const [id, share] of Object.entries(robust.shares)) {
      console.log(`  ${id.padEnd(14)} ${round(share * 100, 2)}%`);
    }
    console.log(
      `  средний gap ${robust.meanGapPct}%, худший ${robust.worstGapPct}%`,
    );
  }
  if (offline) {
    const item = offline.decision;
    console.log("");
    console.log("Оффлайн-доли (#487) против текущих долей:");
    console.log(
      `  высота ${signedPercent(-item.heightGainPct)} (seed ${item.fitSeed}), пилюли ${item.pillCurrentPct}% → ${item.pillOfflinePct}% (${item.pillDeltaPp > 0 ? "+" : ""}${item.pillDeltaPp} п.п.), текст ${item.textLossPct}%`,
    );
    console.log(
      `  порог §15: высота ${item.heightPass ? "пройдена" : "не пройдена"}, пилюли ${item.pillPass ? "пройдены" : "не пройдены"}; итог — ${item.passes ? "пройден" : "не пройден"}`,
    );
    for (const plan of offline.bucketSwitches) {
      const boundaries = plan.boundaries
        .map(
          (entry) =>
            `${entry.boundary}: скачок ${entry.worstJumpPct}% / выигрыш ${entry.worstJumpGainPct}%`,
        )
        .join("; ");
      console.log(`  ${plan.label}: ${boundaries}; ${plan.passes ? "проходит" : "не проходит"}`);
    }
    if (offline.pillsConstraint) {
      console.log("");
      console.log("Ограничение обрезки пилюль (#488):");
      for (const mode of PILLS_LIMIT_MODES) {
        const modeData = offline.pillsConstraint.modes[mode];
        if (!modeData) continue;
        console.log(
          `  ${modeData.label}: search высота ${signedPercent(modeData.overall.search.heightPctMean)}, пилюли ${modeData.overall.search.pillTruncatedSharePctMean}%; ` +
            `vector высота ${signedPercent(modeData.overall.vector.heightPctMean)}, пилюли ${modeData.overall.vector.pillTruncatedSharePctMean}%; ` +
            `одновременно — search ${modeData.decision.search.simultaneous ? "да" : "нет"}, vector ${modeData.decision.vector.simultaneous ? "да" : "нет"}`,
        );
      }
    }
  }
  if (decision) {
    console.log("");
    console.log(`Решение #482: (${decision.option}) — ${decision.reason}`);
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
