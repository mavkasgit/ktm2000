#!/usr/bin/env node
/**
 * Бенч-харнесс исследования ширин колонок.
 *
 * Матрица: профиль × число строк × ширина таблицы × число колонок × seed.
 * Оптимизатор подбирает ширины по подвыборке (не более 500 строк), а метрики
 * считаются по всему листу: так проверяется H2 — что подвыборки достаточно.
 *
 * Запуск:
 *   node research/column-widths/bench.mjs --quick
 *   node research/column-widths/bench.mjs --measurer=pretext
 * Результаты: research/column-widths/results/{bench.json,report.md}
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { PROFILES, generateSheet } from "./lib/generator.mjs";
import { SERVICE_WIDTH_PX, buildColumns, sumWidths } from "./lib/columns.mjs";
import { createMeasurer } from "./lib/measurers.mjs";
import { evaluate, prepareSheet } from "./lib/evaluate.mjs";
import { OPTIMIZERS, oracleOptimizer } from "./lib/optimizers.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const RESULTS_DIR = resolve(HERE, "results");
const LAMBDA = 20;
const FIT_ROWS = 500;

const args = process.argv.slice(2);
const argValue = (name, fallback) => {
  const prefix = `--${name}=`;
  const found = args.find((argument) => argument.startsWith(prefix));
  return found ? found.slice(prefix.length) : fallback;
};
const QUICK = args.includes("--quick");
const MEASURER_KIND = argValue("measurer", "greedy");
const SEEDS = Number(argValue("seeds", QUICK ? "1" : "2"));

const PROFILES_TO_RUN = QUICK
  ? ["realistic", "long-tail", "mono"]
  : PROFILES;
const ROW_COUNTS = QUICK ? [100, 1000] : [100, 1000, 5000];
const WIDTHS = QUICK ? [1180, 1500] : [1180, 1500, 1920];
const COLUMN_COUNTS = QUICK ? [6, 11] : [6, 12, 20];

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

function runOptimizer(name, fitPrepared, width) {
  const optimizer = OPTIMIZERS[name];
  const { value, ms } = measureRuntime(() => optimizer(fitPrepared, width, { lambda: LAMBDA }));
  return { name, widths: value.widths, ms };
}

function runConfig({ profile, rows, tableWidth, columnCount, seed, measurer }) {
  const columns = buildColumns(columnCount);
  const sheet = generateSheet({ profile, rows, columns, seed });
  const fitPrepared = prepareForFit(sheet, measurer);
  const fullPrepared = prepareSheet(sheet, measurer);
  const width = contentWidth(tableWidth);

  const results = {};
  for (const name of Object.keys(OPTIMIZERS)) {
    const run = runOptimizer(name, fitPrepared, width);
    const metrics = evaluate(fullPrepared, run.widths, { lambda: LAMBDA });
    results[name] = {
      widths: run.widths,
      widthSum: round(sumWidths(columns, run.widths), 1),
      ms: round(run.ms, 2),
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

  const baselineHeight = results.baseline.height || 1;
  for (const metrics of Object.values(results)) {
    metrics.heightRatio = round(metrics.height / baselineHeight, 4);
    metrics.costRatio = round(metrics.cost / (results.baseline.cost || 1), 4);
  }
  return { profile, rows, tableWidth, columnCount, seed, results };
}

async function runOracleSet(measurer) {
  const cases = [];
  const profiles = QUICK ? ["realistic", "long-tail"] : PROFILES;
  const names = Object.keys(OPTIMIZERS).filter((name) => name !== "baseline");
  for (const profile of profiles) {
    const rows = 60;
    const columnCount = 11;
    const tableWidth = 1500;
    const columns = buildColumns(columnCount);
    const sheet = generateSheet({ profile, rows, columns, seed: 1 });
    const prepared = prepareSheet(sheet, measurer);
    const width = contentWidth(tableWidth);
    const oracle = oracleOptimizer(prepared, width, { lambda: LAMBDA });
    const oracleMetrics = evaluate(prepared, oracle.widths, { lambda: LAMBDA });
    const heuristics = {};
    for (const name of names) {
      const run = OPTIMIZERS[name](prepared, width, { lambda: LAMBDA });
      const metrics = evaluate(prepared, run.widths, { lambda: LAMBDA });
      heuristics[name] = {
        height: metrics.totalHeight,
        cost: metrics.cost,
        gapHeightPct: round(((metrics.totalHeight - oracleMetrics.totalHeight) / oracleMetrics.totalHeight) * 100, 2),
        gapCostPct: round(((metrics.cost - oracleMetrics.cost) / oracleMetrics.cost) * 100, 2),
      };
    }
    cases.push({
      profile,
      oracle: { height: oracleMetrics.totalHeight, cost: oracleMetrics.cost, thinned: Boolean(oracle.thinned) },
      heuristics,
    });
  }
  return cases;
}

async function runSampleStability(measurer) {
  const cases = [];
  const profiles = QUICK ? ["realistic"] : ["realistic", "long-tail", "outlier"];
  const names = ["narrowing", "breakpoints", "search"];
  for (const profile of profiles) {
    for (const name of names) {
      const columns = buildColumns(12);
      const sheet = generateSheet({ profile, rows: 5000, columns, seed: 1 });
      const width = contentWidth(1500);
      const sample = prepareSheet({ ...sheet, rows: sheet.rows.slice(0, 500) }, measurer);
      const full = prepareSheet(sheet, measurer);
      const sampleRun = OPTIMIZERS[name](sample, width, { lambda: LAMBDA });
      const fullRun = OPTIMIZERS[name](full, width, { lambda: LAMBDA });
      const sampleMetrics = evaluate(full, sampleRun.widths, { lambda: LAMBDA });
      const fullMetrics = evaluate(full, fullRun.widths, { lambda: LAMBDA });
      const deltas = columns
        .filter((column) => column.flex)
        .map((column) => Math.abs(sampleRun.widths[column.id] - fullRun.widths[column.id]));
      cases.push({
        profile,
        optimizer: name,
        sampleHeight: sampleMetrics.totalHeight,
        fullHeight: fullMetrics.totalHeight,
        heightDeltaPct: round(((sampleMetrics.totalHeight - fullMetrics.totalHeight) / fullMetrics.totalHeight) * 100, 2),
        maxFlexWidthDeltaPx: round(Math.max(0, ...deltas), 1),
      });
    }
  }
  return cases;
}

function runStabilityAcrossWidths(measurer) {
  const cases = [];
  const profiles = QUICK ? ["realistic"] : ["realistic", "long-tail"];
  for (const profile of profiles) {
    for (const name of ["narrowing", "breakpoints", "search"]) {
      const columns = buildColumns(11);
      const sheet = generateSheet({ profile, rows: 1000, columns, seed: 1 });
      const prepared = prepareSheet(sheet, measurer);
      const byWidth = WIDTHS.map((tableWidth) => {
        const run = OPTIMIZERS[name](prepared, contentWidth(tableWidth), { lambda: LAMBDA });
        const total = sumWidths(columns, run.widths);
        const shares = {};
        for (const column of columns) shares[column.id] = run.widths[column.id] / total;
        return { tableWidth, shares };
      });
      const maxDeltaPct = Math.max(
        ...columns.map((column) => {
          const values = byWidth.map((entry) => entry.shares[column.id]);
          return (Math.max(...values) - Math.min(...values)) * 100;
        }),
      );
      cases.push({ profile, optimizer: name, maxShareDeltaPct: round(maxDeltaPct, 2) });
    }
  }
  return cases;
}

async function runMeasurerAgreement(measurer) {
  if (measurer.name !== "greedy") return null;
  let pretext;
  try {
    pretext = await createMeasurer("pretext");
  } catch (error) {
    return { skipped: true, reason: String(error?.message ?? error) };
  }
  const columns = buildColumns(11);
  const sheet = generateSheet({ profile: "realistic", rows: 200, columns, seed: 7 });
  const greedy = prepareSheet(sheet, measurer);
  const prepared = prepareSheet(sheet, pretext);
  let compared = 0;
  let different = 0;
  for (let rowIndex = 0; rowIndex < prepared.rows.length; rowIndex += 1) {
    for (let index = 0; index < columns.length; index += 1) {
      const column = columns[index];
      if (!column.wrap) continue;
      const usable = 180 - 12;
      const a = greedy.measurer.lineCount(greedy.rows[rowIndex][index].prepared, usable);
      const b = prepared.measurer.lineCount(prepared.rows[rowIndex][index].prepared, usable);
      compared += 1;
      if (a !== b) different += 1;
    }
  }
  return {
    skipped: false,
    compared,
    different,
    sharePct: round((different / Math.max(1, compared)) * 100, 2),
  };
}

function aggregate(configs) {
  const names = Object.keys(OPTIMIZERS);
  const summary = {};
  for (const name of names) {
    const items = configs.map((config) => config.results[name]);
    summary[name] = {
      meanHeightRatio: round(items.reduce((sum, item) => sum + item.heightRatio, 0) / items.length, 4),
      meanCostRatio: round(items.reduce((sum, item) => sum + item.costRatio, 0) / items.length, 4),
      meanTruncatedShare: round(items.reduce((sum, item) => sum + item.truncatedShare, 0) / items.length, 2),
      meanMultiLineShare: round(items.reduce((sum, item) => sum + item.multiLineShare, 0) / items.length, 2),
      meanRuntimeMs: round(items.reduce((sum, item) => sum + item.ms, 0) / items.length, 2),
      maxRuntimeMs: round(Math.max(...items.map((item) => item.ms)), 2),
      wins: configs.filter((config) => {
        const best = names.reduce(
          (bestName, candidate) =>
            config.results[candidate].cost < config.results[bestName].cost ? candidate : bestName,
          names[0],
        );
        return best === name;
      }).length,
    };
  }
  return summary;
}

function verdict(condition) {
  return condition ? "подтверждена" : "не подтверждена";
}

function buildReport({ configs, summary, oracle, sampleStability, widthStability, measurerAgreement, meta }) {
  const names = Object.keys(summary);
  const bestByMean = [...names].sort(
    (a, b) => summary[a].meanCostRatio - summary[b].meanCostRatio,
  );
  // H1 — про лучшую эвристику: важно, что существует алгоритм не дальше 5%.
  const heuristicNames = names.filter((name) => name !== "baseline");
  const worstGap = {};
  for (const name of heuristicNames) worstGap[name] = Number.NEGATIVE_INFINITY;
  for (const item of oracle) {
    for (const [name, heuristic] of Object.entries(item.heuristics)) {
      if (!(name in worstGap)) continue;
      worstGap[name] = Math.max(worstGap[name], heuristic.gapCostPct);
    }
  }
  const ranked = [...heuristicNames].sort((a, b) => worstGap[a] - worstGap[b]);
  const h1Best = ranked[0];
  const h1 = worstGap[h1Best] <= 5;
  const h2 = sampleStability.every((item) => Math.abs(item.heightDeltaPct) <= 2);
  const h3 = widthStability.every((item) => item.maxShareDeltaPct <= 5);
  const h4 = measurerAgreement && !measurerAgreement.skipped
    ? measurerAgreement.sharePct <= 1
    : null;
  const h2Worst = [...sampleStability].sort(
    (a, b) => Math.abs(b.heightDeltaPct) - Math.abs(a.heightDeltaPct),
  )[0];
  const h3Worst = [...widthStability].sort(
    (a, b) => b.maxShareDeltaPct - a.maxShareDeltaPct,
  )[0];
  const searchH2 = sampleStability
    .filter((item) => item.optimizer === "search")
    .map((item) => Math.abs(item.heightDeltaPct));
  const searchH3 = widthStability
    .filter((item) => item.optimizer === "search")
    .map((item) => item.maxShareDeltaPct);

  const lines = [];
  lines.push("# Отчёт: оптимальное распределение ширин колонок");
  lines.push("");
  lines.push(`- Дата: ${meta.date}`);
  lines.push(`- Ветка: \`${meta.branch}\``);
  lines.push(`- Измеритель: \`${meta.measurer}\``);
  lines.push(`- Seed'ы: ${meta.seeds.join(", ")}`);
  lines.push(`- Конфигураций: ${configs.length}`);
  lines.push("");
  lines.push("## Итог по оптимизаторам");
  lines.push("");
  lines.push("| Оптимизатор | Средняя высота к baseline | Средний cost к baseline | Обрезка, % ячеек | Переносов, % строк | Среднее время, мс | Побед |");
  lines.push("|---|---:|---:|---:|---:|---:|---:|");
  for (const name of names) {
    const item = summary[name];
    lines.push(
      `| ${name} | ${item.meanHeightRatio.toFixed(3)} | ${item.meanCostRatio.toFixed(3)} | ${item.meanTruncatedShare} | ${item.meanMultiLineShare} | ${item.meanRuntimeMs} | ${item.wins} |`,
    );
  }
  lines.push("");
  lines.push(`Лучший по среднему cost: **${bestByMean[0]}** (${summary[bestByMean[0]].meanCostRatio.toFixed(3)} от baseline).`);
  lines.push("");
  lines.push("## Гипотезы");
  lines.push("");
  lines.push(`- **H1 (эвристика в пределах 5% от оракула):** ${verdict(h1)}. Лучшая — \`${h1Best}\`, худший gap ${Number.isFinite(worstGap[h1Best]) ? worstGap[h1Best].toFixed(2) : "—"}%; ${ranked
    .slice(1)
    .map((name) => `${name} ${worstGap[name].toFixed(2)}%`)
    .join(", ")}.`);
  lines.push(`- **H2 (подвыборка 500 строк даёт ≤2% потерь):** ${verdict(h2)}. Худшее — ${h2Worst.optimizer}/${h2Worst.profile}: ${h2Worst.heightDeltaPct}%; у \`search\` максимум ${searchH2.length ? Math.max(...searchH2).toFixed(2) : "—"}%.`);
  lines.push(`- **H3 (раскладка устойчива к W 1180–1920):** ${verdict(h3)}. Худшее — ${h3Worst.optimizer}/${h3Worst.profile}: ${h3Worst.maxShareDeltaPct} п.п.; у \`search\` максимум ${searchH3.length ? Math.max(...searchH3).toFixed(2) : "—"} п.п.`);
  lines.push(
    `- **H4 (pretext vs эталон <1% строк):** ${
      h4 === null ? "не проверялась в этом прогоне (нужен браузер)" : verdict(h4)
    }${measurerAgreement && !measurerAgreement.skipped ? `; расхождение с greedy: ${measurerAgreement.sharePct}%` : ""}.`,
  );
  lines.push("");
  const oracleNames = [...new Set(oracle.flatMap((item) => Object.keys(item.heuristics)))];
  lines.push("## Оракул на малых инстансах");
  lines.push("");
  lines.push(`| Профиль | Oracle cost | ${oracleNames.join(" gap | ")} gap |`);
  lines.push(`|---|---:|${oracleNames.map(() => "---:").join("|")}|`);
  for (const item of oracle) {
    const cells = oracleNames.map((name) => {
      const heuristic = item.heuristics[name];
      return heuristic ? `${heuristic.gapCostPct}%` : "—";
    });
    lines.push(
      `| ${item.profile}${item.oracle.thinned ? " (сетка прорежена)" : ""} | ${item.oracle.cost} | ${cells.join(" | ")} |`,
    );
  }
  lines.push("");
  lines.push("## Подвыборка (H2)");
  lines.push("");
  lines.push("| Профиль | Оптимизатор | 500 строк | 5000 строк | Δ высоты | Δ ширины (max) |");
  lines.push("|---|---|---:|---:|---:|---:|");
  for (const item of sampleStability) {
    lines.push(
      `| ${item.profile} | ${item.optimizer} | ${item.sampleHeight} | ${item.fullHeight} | ${item.heightDeltaPct}% | ${item.maxFlexWidthDeltaPx} px |`,
    );
  }
  lines.push("");
  lines.push("## Устойчивость к ширине (H3)");
  lines.push("");
  lines.push("| Профиль | Оптимизатор | max Δ доли колонки |");
  lines.push("|---|---|---:|");
  for (const item of widthStability) {
    lines.push(`| ${item.profile} | ${item.optimizer} | ${item.maxShareDeltaPct} п.п. |`);
  }
  lines.push("");
  lines.push("## Ограничения");
  lines.push("");
  lines.push("- Модель текста в Node — табличные метрики 11px, а не реальный canvas; H4 проверен в браузере отдельно (#479, 0.19% расхождений).");
  lines.push("- `operations` смоделированы как неразрывные пилюли: ширина покупает отсутствие обрезки, а не строки.");
  lines.push("- Минимум текстовой колонки — `max(minPx, maxWordWidth + padding)` по листу (#479): уже самого широкого слова `pretext` рвёт слово, а CSS с `overflow-wrap: normal` — нет. Если минимумы не влезают в бюджет, раскладка честно переполняется.");
  lines.push("- Поиск идёт по подвыборке ≤500 строк (самые длинные строки по одной на гибкую колонку + равномерная сетка), `cost` считается на полном листе; полная проверка H2 — #482.");
  lines.push("");
  lines.push("## Рекомендация");
  lines.push("");
  const candidate = bestByMean.find((name) => name !== "baseline") ?? bestByMean[0];
  lines.push(
    `Брать **${candidate}**: лучший средний cost (${summary[candidate].meanCostRatio.toFixed(3)} от baseline), среднее время ${summary[candidate].meanRuntimeMs} мс, максимум ${summary[candidate].maxRuntimeMs} мс на конфигурацию.`,
  );
  lines.push("");
  return lines.join("\n");
}

function main() {
  const started = performance.now();
  const measurer = createMeasurer(MEASURER_KIND);
  return Promise.resolve(measurer).then(async (resolvedMeasurer) => {
    console.log(
      `[bench] measurer=${resolvedMeasurer.name} seeds=${SEEDS} profiles=${PROFILES_TO_RUN.length} rows=${ROW_COUNTS.join("/")} widths=${WIDTHS.join("/")} columns=${COLUMN_COUNTS.join("/")}`,
    );
    const configs = [];
    for (const profile of PROFILES_TO_RUN) {
      for (const rows of ROW_COUNTS) {
        for (const tableWidth of WIDTHS) {
          for (const columnCount of COLUMN_COUNTS) {
            for (let seed = 1; seed <= SEEDS; seed += 1) {
              configs.push(
                runConfig({ profile, rows, tableWidth, columnCount, seed, measurer: resolvedMeasurer }),
              );
            }
          }
        }
      }
      console.log(`[bench] ${profile}: готово (${configs.length} конфигураций)`);
    }

    const summary = aggregate(configs);
    const oracle = await runOracleSet(resolvedMeasurer);
    const sampleStability = await runSampleStability(resolvedMeasurer);
    const widthStability = runStabilityAcrossWidths(resolvedMeasurer);
    const measurerAgreement = await runMeasurerAgreement(resolvedMeasurer);

    const date = new Date().toISOString().slice(0, 10);
    const meta = {
      date,
      branch: process.env.GIT_BRANCH ?? "research/column-widths",
      measurer: resolvedMeasurer.name,
      seeds: Array.from({ length: SEEDS }, (_, index) => index + 1),
      lambda: LAMBDA,
      fitRows: FIT_ROWS,
      runtimeMs: round(performance.now() - started, 1),
    };

    mkdirSync(RESULTS_DIR, { recursive: true });
    const payload = { meta, configs, summary, oracle, sampleStability, widthStability, measurerAgreement };
    writeFileSync(resolve(RESULTS_DIR, "bench.json"), `${JSON.stringify(payload, null, 2)}\n`, "utf8");
    const report = buildReport({
      configs,
      summary,
      oracle,
      sampleStability,
      widthStability,
      measurerAgreement,
      meta,
    });
    writeFileSync(resolve(RESULTS_DIR, "report.md"), `${report}\n`, "utf8");

    console.log("");
    console.log("Оптимизатор            высота/baseline   cost/baseline   обрезка%   время(мс)   побед");
    for (const [name, item] of Object.entries(summary)) {
      console.log(
        `${name.padEnd(22)} ${item.meanHeightRatio.toFixed(3).padStart(12)}   ${item.meanCostRatio.toFixed(3).padStart(12)}   ${String(item.meanTruncatedShare).padStart(7)}   ${String(item.meanRuntimeMs).padStart(9)}   ${String(item.wins).padStart(5)}`,
      );
    }
    console.log("");
    console.log(`[bench] ${meta.runtimeMs} мс; отчёт: ${resolve(RESULTS_DIR, "report.md")}`);
  });
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
