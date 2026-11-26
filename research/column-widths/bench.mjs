#!/usr/bin/env node
/**
 * Бенч-харнесс исследования ширин колонок.
 *
 * Прогон состоит из четырёх частей:
 *
 * - `matrix`      — 7 профилей × {100,1000,5000} × {1180,1500,1920} × {6,12,20} × seeds;
 *                   метрики считаются по полному листу, оптимизатор видит ≤500 строк;
 * - `product`     — продуктовый срез `ImportRemaindersDialog` (11 колонок) на тех же
 *                   профилях/строках/ширинах; cost считается с `λ`;
 * - `oracle`      — точный перебор на малых инстансах (60 строк), все оптимизаторы
 *                   рядом с эталоном; отсюда берётся gap для H1;
 * - `sensitivity` — чувствительность продуктового решения к `λ` (10/20/40 px) и
 *                   `line-clamp` у «Ошибок» (2/3/без потолка). Ничего не выбирает
 *                   за заказчика — показывает цену вариантов (вход для #485).
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
 *                                                         # sensitivity|all (или через запятую)
 *   node research/column-widths/bench.mjs --lambda=40     # цена обрезки для cost
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
  SERVICE_WIDTH_PX,
  buildColumns,
  maxWidth,
  sumWidths,
} from "./lib/columns.mjs";
import { createMeasurer } from "./lib/measurers.mjs";
import { evaluate, prepareSheet } from "./lib/evaluate.mjs";
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

const DEFAULT_LAMBDA = 20;
const FIT_ROWS = 500;
const ORACLE_ROWS = 60;

const SECTIONS = ["matrix", "oracle", "product", "sensitivity"];

const args = process.argv.slice(2);
const argValue = (name, fallback) => {
  const prefix = `--${name}=`;
  const found = args.find((argument) => argument.startsWith(prefix));
  return found ? found.slice(prefix.length) : fallback;
};
const QUICK = args.includes("--quick");
const MEASURER_KIND = argValue("measurer", "greedy");
const SEEDS = Number(argValue("seeds", QUICK ? "1" : "2"));
const LAMBDA = Number(argValue("lambda", String(DEFAULT_LAMBDA)));

export function parseSections(value) {
  const requested = String(value)
    .split(",")
    .map((name) => name.trim())
    .filter(Boolean);
  if (requested.length === 0 || requested.includes("all")) return [...SECTIONS];
  for (const name of requested) {
    if (!SECTIONS.includes(name)) {
      throw new Error(
        `--only=${name}: неизвестная секция; доступны ${SECTIONS.join(", ")}, all`,
      );
    }
  }
  return SECTIONS.filter((name) => requested.includes(name));
}

const SECTIONS_TO_RUN = parseSections(argValue("only", "all"));

if (!Number.isInteger(SEEDS) || SEEDS < 1) {
  throw new Error(`--seeds=${SEEDS}: нужно целое ≥ 1`);
}
if (!Number.isFinite(LAMBDA) || LAMBDA < 0) {
  throw new Error(`--lambda=${LAMBDA}: нужно неотрицательное число`);
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

/** Чувствительность: λ × line-clamp «Ошибок» на продуктовом срезе. */
function sensitivitySpec() {
  return {
    profiles: QUICK ? ["realistic"] : ["realistic", "long-tail"],
    rows: 1000,
    widths: QUICK ? [1500] : [1180, 1500, 1920],
    seed: 1,
    lambdas: [10, DEFAULT_LAMBDA, 40],
    clamps: [2, 3, "none"],
  };
}

function contentWidth(tableWidth) {
  return tableWidth - SERVICE_WIDTH_PX;
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

function clampValue(clamp) {
  return clamp === "none" ? Number.POSITIVE_INFINITY : clamp;
}

function clampOrder(clamp) {
  return clamp === "none" ? Number.POSITIVE_INFINITY : Number(clamp);
}

function runOptimizer(name, fitPrepared, width, lambda = LAMBDA) {
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

function collectMetrics(prepared, widths, lambda = LAMBDA) {
  const metrics = evaluate(prepared, widths, { lambda, collectRows: true });
  return {
    height: metrics.totalHeight,
    meanHeight: round(metrics.meanHeight, 2),
    p95Height: metrics.p95Height,
    maxHeight: metrics.maxHeight,
    multiLineShare: round(metrics.multiLineShare * 100, 2),
    rows3PlusShare: round(metrics.rows3PlusShare * 100, 2),
    truncatedCells: metrics.truncatedCells,
    truncatedShare: round(metrics.truncatedShare * 100, 2),
    cost: metrics.cost,
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
}) {
  const columns = buildColumns(columnCount);
  const sheet = generateSheet({ profile, rows, columns, seed });
  const fitPrepared = prepareForFit(sheet, measurer);
  const fullPrepared = prepareSheet(sheet, measurer);
  const width = contentWidth(tableWidth);

  const results = {};
  for (const name of Object.keys(OPTIMIZERS)) {
    const run = runOptimizer(name, fitPrepared, width);
    results[name] = {
      widths: run.widths,
      widthSum: round(sumWidths(columns, run.widths), 1),
      violations: widthViolations(columns, run.widths, width),
      ms: round(run.ms, 2),
      ...collectMetrics(fullPrepared, run.widths),
    };
  }

  const baselineHeight = results.baseline.height || 1;
  const baselineCost = results.baseline.cost || 1;
  for (const metrics of Object.values(results)) {
    metrics.heightRatio = round(metrics.height / baselineHeight, 4);
    metrics.costRatio = round(metrics.cost / baselineCost, 4);
  }
  return {
    profile,
    rows,
    tableWidth,
    contentWidth: width,
    columnCount,
    seed,
    results,
  };
}

/** Оракул на малом инстансе: все оптимизаторы на одном листе рядом с эталоном. */
function runOracleConfig({ profile, tableWidth, columnCount, seed, measurer }) {
  const columns = buildColumns(columnCount);
  const sheet = generateSheet({ profile, rows: ORACLE_ROWS, columns, seed });
  const prepared = prepareSheet(sheet, measurer);
  const width = contentWidth(tableWidth);

  const { value: oracle, ms: oracleMs } = measureRuntime(() =>
    oracleOptimizer(prepared, width, { lambda: LAMBDA }),
  );
  const oracleMetrics = collectMetrics(prepared, oracle.widths);

  const results = {};
  for (const name of Object.keys(OPTIMIZERS)) {
    const { value, ms } = measureRuntime(() =>
      OPTIMIZERS[name](prepared, width, { lambda: LAMBDA }),
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
      const columns = buildColumns(12);
      const sheet = generateSheet({ profile, rows: 5000, columns, seed: 1 });
      const width = contentWidth(1500);
      const sample = prepareSheet(
        { ...sheet, rows: sheet.rows.slice(0, 500) },
        measurer,
      );
      const full = prepareSheet(sheet, measurer);
      const sampleRun = OPTIMIZERS[name](sample, width, { lambda: LAMBDA });
      const fullRun = OPTIMIZERS[name](full, width, { lambda: LAMBDA });
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
      const columns = buildColumns(11);
      const sheet = generateSheet({ profile, rows: 1000, columns, seed: 1 });
      const prepared = prepareSheet(sheet, measurer);
      const byWidth = widths.map((tableWidth) => {
        const run = OPTIMIZERS[name](prepared, contentWidth(tableWidth), {
          lambda: LAMBDA,
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
 * Чувствительность продуктового решения: `λ` (10/20/40) × `line-clamp`
 * «Ошибок» (2/3/без потолка). Метрики — средние по ширинам и профилям,
 * 1000 строк, seed 1, оптимизатор `search`. Cost считается с тем же λ, с
 * которым работал оптимизатор; сравнивать cost между λ нельзя — для этого в
 * таблице отдельно высота, обрезка и переносы.
 */
function runSensitivity(measurer, spec) {
  const cases = [];
  for (const tableWidth of spec.widths) {
    for (const profile of spec.profiles) {
      for (const lambda of spec.lambdas) {
        for (const clamp of spec.clamps) {
          const columns = buildColumns(11).map((column) =>
            column.id === "errors"
              ? { ...column, clamp: clampValue(clamp) }
              : column,
          );
          const sheet = generateSheet({
            profile,
            rows: spec.rows,
            columns,
            seed: spec.seed,
          });
          const prepared = prepareSheet(sheet, measurer);
          const { value, ms } = measureRuntime(() =>
            OPTIMIZERS.search(prepared, contentWidth(tableWidth), { lambda }),
          );
          const metrics = collectMetrics(prepared, value.widths, lambda);
          cases.push({
            profile,
            tableWidth,
            rows: spec.rows,
            lambda,
            clamp: clamp === "none" ? "none" : clamp,
            ms: round(ms, 2),
            cost: metrics.cost,
            totalHeight: metrics.height,
            meanHeight: metrics.meanHeight,
            p95Height: metrics.p95Height,
            maxHeight: metrics.maxHeight,
            truncatedShare: metrics.truncatedShare,
            multiLineShare: metrics.multiLineShare,
            rows3PlusShare: metrics.rows3PlusShare,
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
  }
  return cases;
}

function summarizeSensitivity(cases) {
  const groups = new Map();
  for (const item of cases) {
    const key = `${item.lambda}|${item.clamp}`;
    if (!groups.has(key)) {
      groups.set(key, {
        lambda: item.lambda,
        clamp: item.clamp,
        items: [],
      });
    }
    groups.get(key).items.push(item);
  }
  return [...groups.values()]
    .map(({ lambda, clamp, items }) => {
      const mean = (field) =>
        round(items.reduce((sum, item) => sum + item[field], 0) / items.length, 2);
      return {
        lambda,
        clamp,
        cases: items.length,
        meanCost: mean("cost"),
        meanTotalHeight: mean("totalHeight"),
        meanHeight: mean("meanHeight"),
        meanP95Height: mean("p95Height"),
        meanTruncatedShare: mean("truncatedShare"),
        meanMultiLineShare: mean("multiLineShare"),
        meanRows3PlusShare: mean("rows3PlusShare"),
        meanErrorsWidth: round(
          items.reduce((sum, item) => sum + item.widths.errors, 0) /
            items.length,
          1,
        ),
        meanSourceNameWidth: round(
          items.reduce((sum, item) => sum + item.widths.source_name, 0) /
            items.length,
          1,
        ),
        meanRuntimeMs: mean("ms"),
      };
    })
    .sort(
      (a, b) =>
        a.lambda - b.lambda ||
        clampOrder(a.clamp) - clampOrder(b.clamp),
    );
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
      statement: "лучшая эвристика отстаёт от оракула не более чем на 5% по cost",
      value: `${worst}% (${best})`,
      threshold: "≤5%",
      verdict: verdict(worst <= 5),
      note: `worst по ${oracle.caseCount} конфигурациям, ${oracle.rows} строк`,
    });
  } else {
    hypotheses.push({
      id: "H1",
      statement: "лучшая эвристика отстаёт от оракула не более чем на 5% по cost",
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
      statement: "подвыборка 500 строк даёт ≤2% потерь по высоте",
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
      statement: "подвыборка 500 строк даёт ≤2% потерь по высоте",
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
      statement: "доли колонок устойчивы к W 1180–1920 (Δ ≤ 5 п.п.)",
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
      statement: "доли колонок устойчивы к W 1180–1920 (Δ ≤ 5 п.п.)",
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

function buildReport(data) {
  const { meta, matrix, product, oracle, sampleStability, widthStability, sensitivity, h4, hypotheses, measurerAgreement } = data;
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
  push(`- λ: ${meta.lambda} px за обрезанную ячейку`);
  push(`- Секции: ${meta.sections.join(", ")}`);
  push(`- Конфигураций: ${meta.counts.matrix} матрица, ${meta.counts.product} продуктовый срез, ${meta.counts.oracle} оракул, ${meta.counts.sensitivity} чувствительность`);
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
    push("| Оптимизатор | Высота / baseline | Суммарная высота (сред.) | Средняя высота строки | p95 | max | Обрезка, % | Переносов, % строк | Строк ≥3, % | Время, мс (сред./max) | Побед | Наруш. maxShare |");
    push("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|");
    for (const [name, item] of Object.entries(matrix.summary)) {
      push(
        `| ${name} | ${item.meanHeightRatio.toFixed(3)} | ${item.meanTotalHeight} | ${item.meanRowHeight} | ${item.meanP95Height} | ${item.meanMaxHeight} | ${item.meanTruncatedShare} | ${item.meanMultiLineShare} | ${item.meanRows3PlusShare} | ${item.meanRuntimeMs} / ${item.maxRuntimeMs} | ${item.wins} | ${item.widthViolations} |`,
      );
    }
    push("");
    push(
      "Ничьи в «Побед» достаются первому оптимизатору в списке; раскладки с нарушением «maxShare» в победах не участвуют.",
    );
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
      `Полный перебор порогов на ${oracle.rows} строках; ${oracle.caseCount} конфигураций (профили × ширины × колонки × seed). ` +
        `Прорежена сетка в ${oracle.thinned} случаях.`,
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
      )}. Cost — с λ=${meta.lambda} px.`,
    );
    push("");
    push("| Оптимизатор | Высота / baseline | Cost / baseline | Суммарная высота (сред.) | Cost / 1000 строк | Средняя высота строки | p95 | Обрезка, % | Переносов, % строк | Строк ≥3, % | Время, мс | Побед |");
    push("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|");
    for (const [name, item] of Object.entries(product.summary)) {
      push(
        `| ${name} | ${item.meanHeightRatio.toFixed(3)} | ${item.meanCostRatio.toFixed(3)} | ${item.meanTotalHeight} | ${item.meanCostPer1000Rows} | ${item.meanRowHeight} | ${item.meanP95Height} | ${item.meanTruncatedShare} | ${item.meanMultiLineShare} | ${item.meanRows3PlusShare} | ${item.meanRuntimeMs} | ${item.wins} |`,
      );
    }
    push("");
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

  if (sensitivity) {
    push("## Чувствительность λ и line-clamp «Ошибок»");
    push("");
    push(
      `Оптимизатор \`search\`, продуктовый срез 11 колонок, ${sensitivity.spec.rows} строк, seed ${sensitivity.spec.seed}, ` +
        `средние по профилям (${sensitivity.spec.profiles.join(", ")}) и ширинам (${sensitivity.spec.widths.join(
          "/",
        )}). Cost посчитан с тем же λ, с которым работал оптимизатор, поэтому cost между λ не сравнивать — смотрите высоту, обрезку и переносы.`,
    );
    push("");
    push("| λ, px | line-clamp | Cost, px / 1000 строк | Высота строки | p95 | Обрезка, % | Переносов, % | Строк ≥3, % | «Ошибки», px | «Наименование», px |");
    push("|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|");
    for (const item of sensitivity.summary) {
      push(
        `| ${item.lambda} | ${clampLabel(item.clamp)} | ${item.meanCost} | ${item.meanHeight} | ${item.meanP95Height} | ${item.meanTruncatedShare} | ${item.meanMultiLineShare} | ${item.meanRows3PlusShare} | ${item.meanErrorsWidth} | ${item.meanSourceNameWidth} |`,
      );
    }
    push("");
    push(
      "Читать так: рост λ переносит бюджет от обрезки к переносу (высота растёт, обрезка падает); снятие потолка `line-clamp` у «Ошибок» позволяет длинной причине занять больше строк. Выбор константы — решение заказчика (#485), отчёт показывает цену вариантов.",
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
        .join(", ")}. Это дефект реализации оптимизатора (lib/optimizers.mjs), а не свойство задачи: бенч его только фиксирует, gap таких конфигураций к оракулу невалиден (#481 не правит закрытые файлы).`,
    );
  }
  push(
    "- `operations` смоделированы как неразрывные пилюли: ширина покупает отсутствие обрезки, а не строки.",
  );
  push(
    "- Минимум текстовой колонки — `max(minPx, maxWordWidth + padding)` по листу (#479): уже самого широкого слова `pretext` рвёт слово, а CSS с `overflow-wrap: normal` — нет. Если минимумы не влезают в бюджет, раскладка честно переполняется.",
  );
  push(
    "- Поиск идёт по подвыборке ≤500 строк (самые длинные строки по одной на гибкую колонку + равномерная сетка), `cost` считается на полном листе; полная проверка H2 — #482.",
  );
  push(
    "- H2/H3 в отчёте — честные ограничения текущей эвристики, а не замазанные числа: вердикт «не подтверждена» означает, что политика стабильности — отдельная задача #482.",
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
      `Брать **${candidate}**: лучший средний cost (${item.meanCostRatio.toFixed(
        3,
      )} от baseline), среднее время ${item.meanRuntimeMs} мс, максимум ${
        item.maxRuntimeMs
      } мс на конфигурацию. Константы λ и line-clamp — по таблице чувствительности выше, решение за #485.`,
    );
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
  const sensitivitySchema = sensitivitySpec();

  console.log(
    `[bench] measurer=${measurer.name} seeds=${SEED_LIST.join(",")} lambda=${LAMBDA} quick=${QUICK} sections=${SECTIONS_TO_RUN.join(",")}`,
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
                }),
              );
            }
          }
        }
      }
      console.log(`[bench] product ${profile}: ${configs.length} конфигураций`);
    }
    const summary = aggregate(configs);
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
      spec: { ...productSchema, seeds: SEED_LIST },
      configs,
      summary,
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

  let sensitivity = null;
  if (SECTIONS_TO_RUN.includes("sensitivity")) {
    const cases = runSensitivity(measurer, sensitivitySchema);
    sensitivity = {
      spec: sensitivitySchema,
      cases,
      summary: summarizeSensitivity(cases),
    };
    console.log(`[bench] sensitivity: ${cases.length} конфигураций`);
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
    lambda: LAMBDA,
    fitRows: FIT_ROWS,
    oracleRows: ORACLE_ROWS,
    quick: QUICK,
    sections: SECTIONS_TO_RUN,
    argv: args.join(" "),
    runtimeMs: round(performance.now() - started, 1),
    counts: {
      matrix: matrix?.configs.length ?? 0,
      product: product?.configs.length ?? 0,
      oracle: oracle?.cases.length ?? 0,
      sensitivity: sensitivity?.cases.length ?? 0,
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
      byWidth: product.byWidth,
      layoutExample: product.layoutExample,
    },
    oracle: oracle && {
      spec: oracle.spec,
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
    sensitivity: sensitivity && {
      spec: sensitivity.spec,
      cases: sensitivity.cases,
      summary: sensitivity.summary,
    },
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
    sensitivity,
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
    console.log("Продуктовый срез (11 колонок):");
    for (const [name, item] of Object.entries(product.summary)) {
      console.log(
        `${name.padEnd(22)} cost/baseline ${item.meanCostRatio.toFixed(3)}   обрезка ${String(item.meanTruncatedShare).padStart(5)}%   время ${String(item.meanRuntimeMs).padStart(6)} мс`,
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
