/**
 * Рантайм-замер стоимости расчёта ширин (#483, эпик #475).
 *
 * Гейт тикета: если `prepare` всех текстов + `buildCostModel` + `search`
 * на 500 строках × 11 колонках занимает больше 100 мс при CPU throttling 4×,
 * рантайм-оптимизация в продукт не включается (spec §15). Замер поэтому
 * повторяет продуктовый путь целиком, а не только поиск:
 *
 * 1. `prepareSheet()` — `pretext.prepare()` на каждой текстовой ячейке
 *    (пилюли считаются синтетической метрикой, как в продукте);
 * 2. `searchOptimizer()` — `buildCostModel()` + сам поиск (он строит модель
 *    внутри, отдельный `buildCostModel()` в замере был бы двойной работой);
 * 3. `buildCostModel()` отдельно — диагностика: сколько из `search` уходит
 *    на построение модели, а сколько на перебор.
 *
 * Повторы (9) идут без прогрева: продукт считает один раз на лист, поэтому
 * первый повтор — холодный, остальные показывают установившийся режим.
 * `document.fonts.ready` ждётся до старта: иначе pretext измерит fallback.
 */
import { buildColumns, SERVICE_WIDTH_PX } from "../lib/columns.mjs";
import { generateSheet } from "../lib/generator.mjs";
import { createMeasurer, cssFont } from "../lib/measurers.mjs";
import { prepareSheet } from "../lib/evaluate.mjs";
import { buildCostModel } from "../lib/curves.mjs";
import { searchOptimizer } from "../lib/optimizers.mjs";
import { loadFonts } from "./fonts.mjs";

const SEED = 1;
const ROWS = 500;
const COLUMN_COUNT = 11;
const REPS = 9;

/** Профили с разной формой распределения: короткий хвост и тяжёлый. */
const PROFILES = ["realistic", "long-tail"];

/**
 * Текущая доля строк с обрезанными пилюлями «Операций» на этой ширине —
 * дефолтный лимит из #488 («не хуже текущего фикса»). Числа — из отчёта
 * `results/report.md` (#487), на той же сетке W.
 */
const WIDTHS = [
  { tableWidth: 1180, pillsMaxTruncatedShare: 0.3279 },
  { tableWidth: 1400, pillsMaxTruncatedShare: 0.1949 },
  { tableWidth: 1500, pillsMaxTruncatedShare: 0.1297 },
  { tableWidth: 1600, pillsMaxTruncatedShare: 0.0564 },
  { tableWidth: 1920, pillsMaxTruncatedShare: 0.0001 },
];

const THRESHOLD_MS = 100;

/**
 * Продуктовая политика ячеек: у «Наименования» `truncate` (одна строка),
 * у «Ошибок» полный перенос. Повторяет `currentProductColumns` из
 * `bench.mjs` — импортировать бенч в страницу нельзя (он тянет Node API).
 */
function productColumns(count = COLUMN_COUNT) {
  return buildColumns(count).map((column) => {
    if (column.id === "source_name") {
      return { ...column, wrap: false, clamp: null };
    }
    return column.wrap ? { ...column, clamp: null } : column;
  });
}

/** Линейная интерполяция процентиля: при малом n ступенчатая оценка = max. */
function percentile(values, p) {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const position = (sorted.length - 1) * p;
  const lower = Math.floor(position);
  const upper = Math.ceil(position);
  if (lower === upper) return sorted[lower];
  return sorted[lower] + (sorted[upper] - sorted[lower]) * (position - lower);
}

function round(value, digits = 2) {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

function summarize(values) {
  const sorted = [...values].sort((a, b) => a - b);
  return {
    count: values.length,
    min: round(sorted[0]),
    median: round(percentile(values, 0.5)),
    p95: round(percentile(values, 0.95)),
    max: round(sorted[sorted.length - 1]),
  };
}

function sumWidths(columns, widths) {
  return columns.reduce((sum, column) => sum + (widths[column.id] ?? 0), 0);
}

/** Бюджет и минимумы: раскладка не должна тихо «переполниться» без причины. */
function sanity(columns, widths, contentWidth) {
  const belowMin = columns
    .filter((column) => (widths[column.id] ?? 0) + 0.5 < column.minPx)
    .map((column) => column.id);
  return {
    widthSum: round(sumWidths(columns, widths)),
    contentWidth,
    overBudget: sumWidths(columns, widths) > contentWidth + 0.5,
    belowMin,
  };
}

async function runBenchmark() {
  const startedAt = new Date().toISOString();
  const status = document.getElementById("status");
  const say = (text) => {
    if (status) status.textContent = text;
  };

  const fonts = await loadFonts();
  say("Шрифты загружены, создаю измеритель…");
  const measurer = await createMeasurer("pretext");
  const columns = productColumns();
  const wrapColumns = columns.filter((column) => column.wrap);
  const singleLineColumns = columns.filter(
    (column) => column.kind !== "pills" && !column.wrap,
  );

  const scenarios = [];
  for (const profile of PROFILES) {
    const sheet = generateSheet({
      profile,
      rows: ROWS,
      columns,
      seed: SEED,
    });
    for (const width of WIDTHS) {
      scenarios.push({
        profile,
        sheet,
        ...width,
        contentWidth: width.tableWidth - SERVICE_WIDTH_PX,
      });
    }
  }

  // Проход 1 — только измеряемые повторы. Диагностика вынесена в отдельный
  // проход: её аллокации (4500 строк в `measureText`) и GC не должны попадать
  // в соседнюю конфигурацию.
  const allPrepare = [];
  const allSearch = [];
  const allTotal = [];
  let cold = null;

  const measured = [];
  for (const scenario of scenarios) {
    say(`${scenario.profile} @ ${scenario.tableWidth}: замер…`);
    const reps = [];
    let solution = null;

    for (let rep = 0; rep < REPS; rep += 1) {
      // `pretext` кэширует ширины сегментов: без сброса повторы меряют
      // попадание в кэш, а не работу. Продукт считает лист один раз.
      measurer.clearCache?.();
      // Подготовка входит в замер: в продукте она тоже идёт по этому листу.
      const t0 = performance.now();
      const prepared = prepareSheet(scenario.sheet, measurer);
      const t1 = performance.now();
      const next = searchOptimizer(prepared, scenario.contentWidth, {
        lambda: 0,
        pillsMaxTruncatedShare: scenario.pillsMaxTruncatedShare,
      });
      const t2 = performance.now();

      const prepareMs = t1 - t0;
      const searchMs = t2 - t1;
      reps.push({ prepareMs, searchMs, totalMs: prepareMs + searchMs });
      allPrepare.push(prepareMs);
      allSearch.push(searchMs);
      allTotal.push(prepareMs + searchMs);
      if (!cold) {
        cold = {
          profile: scenario.profile,
          tableWidth: scenario.tableWidth,
          prepareMs,
          searchMs,
          totalMs: prepareMs + searchMs,
        };
      }
      solution = next;
    }
    measured.push({ ...scenario, reps, solution });
  }

  // Проход 2 — диагностика: где именно уходит время, без влияния на повторы.
  const configs = measured.map((scenario) => {
    const { sheet, contentWidth, solution } = scenario;

    // `search` строит модель сам; отдельный замер отделяет кривые от перебора.
    measurer.clearCache?.();
    const preparedForModel = prepareSheet(sheet, measurer);
    const m0 = performance.now();
    const model = buildCostModel(preparedForModel, contentWidth, {
      lambda: 0,
      rowLimit: ROWS,
      pillsMaxTruncatedShare: scenario.pillsMaxTruncatedShare,
    });
    const modelMs = performance.now() - m0;

    // Из чего состоит `prepare`: переносимые колонки — те, ради которых
    // считается раскладка; однострочные готовятся только для статистики.
    measurer.clearCache?.();
    let splitStart = performance.now();
    prepareSheet({ ...sheet, columns: wrapColumns }, measurer);
    const wrapPrepareMs = performance.now() - splitStart;
    measurer.clearCache?.();
    splitStart = performance.now();
    prepareSheet({ ...sheet, columns: singleLineColumns }, measurer);
    const singleLinePrepareMs = performance.now() - splitStart;

    // Та же натуральная ширина без pretext — один `canvas.measureText` на
    // ячейку: однострочной колонке не нужна ни сегментация, ни разбор слов.
    const canvas = new OffscreenCanvas(1, 1).getContext("2d");
    const measureStart = performance.now();
    let measuredWidthSum = 0;
    for (const column of singleLineColumns) {
      canvas.font = cssFont(column.font);
      for (const row of sheet.rows) {
        measuredWidthSum += canvas.measureText(
          String(row.values[column.id] ?? ""),
        ).width;
      }
    }
    const singleLineMeasureTextMs = performance.now() - measureStart;

    return {
      profile: scenario.profile,
      tableWidth: scenario.tableWidth,
      contentWidth,
      pillsMaxTruncatedShare: scenario.pillsMaxTruncatedShare,
      reps: scenario.reps.map((rep) => ({
        prepareMs: round(rep.prepareMs),
        searchMs: round(rep.searchMs),
        totalMs: round(rep.totalMs),
      })),
      summary: {
        prepare: summarize(scenario.reps.map((rep) => rep.prepareMs)),
        search: summarize(scenario.reps.map((rep) => rep.searchMs)),
        total: summarize(scenario.reps.map((rep) => rep.totalMs)),
      },
      diagnostics: {
        modelBuildMs: round(modelMs),
        prepareSplit: {
          wrapColumns: wrapColumns.map((column) => column.id),
          wrapMs: round(wrapPrepareMs),
          singleLineColumns: singleLineColumns.map((column) => column.id),
          singleLineMs: round(singleLinePrepareMs),
          singleLineMeasureTextMs: round(singleLineMeasureTextMs),
          measuredWidthSum: round(measuredWidthSum, 1),
          wrapCells: wrapColumns.length * ROWS,
          singleLineCells: singleLineColumns.length * ROWS,
        },
        curveCandidates: model.curves.map((curve) => ({
          column: curve.column.id,
          candidates: curve.candidates.length,
        })),
        budgetFeasible: model.budgetFeasible,
      },
      result: {
        widths: Object.fromEntries(
          Object.entries(solution.widths).map(([id, width]) => [id, round(width)]),
        ),
        cost: round(solution.cost),
        sanity: sanity(columns, solution.widths, contentWidth),
      },
    };
  });

  const overall = {
    prepare: summarize(allPrepare),
    search: summarize(allSearch),
    total: summarize(allTotal),
  };
  const coldTotalMs = round(cold.totalMs);
  const pass = overall.total.p95 <= THRESHOLD_MS && coldTotalMs <= THRESHOLD_MS;

  const result = {
    meta: {
      ticket: 483,
      epic: 475,
      startedAt,
      seed: SEED,
      rows: ROWS,
      columnCount: COLUMN_COUNT,
      columnPolicy: "product (source_name truncate, errors wrap)",
      profiles: PROFILES,
      widths: WIDTHS,
      reps: REPS,
      lambda: 0,
      measurer: "pretext",
      fonts,
      cpuThrottling: window.__throttleRate ?? 4,
      devicePixelRatio: window.devicePixelRatio,
      userAgent: navigator.userAgent,
      hardwareConcurrency: navigator.hardwareConcurrency,
    },
    configs,
    overall,
    cold: {
      profile: cold.profile,
      tableWidth: cold.tableWidth,
      prepareMs: round(cold.prepareMs),
      searchMs: round(cold.searchMs),
      totalMs: coldTotalMs,
    },
    threshold: {
      ms: THRESHOLD_MS,
      basis:
        "p95 суммарного времени по всем повторам и первый (холодный) прогон ≤ 100 мс",
      pass,
      maxP95TotalMs: overall.total.p95,
      coldTotalMs,
    },
  };

  say(`Готово: p95 ${overall.total.p95} мс — ${pass ? "pass" : "fail"}`);
  return result;
}

let benchmark = null;

/** Идемпотентный вход для Playwright: страница не зависит от порядка вызовов. */
window.runRuntimeBenchmark = () => {
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
