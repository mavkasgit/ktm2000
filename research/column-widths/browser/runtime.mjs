/**
 * Рантайм-замер стоимости расчёта ширин (#483, эпик #475).
 *
 * Гейт тикета: если расчёт на 500 строках × 11 колонках занимает больше
 * 100 мс при CPU throttling 4×, рантайм-оптимизация в продукт не включается
 * (spec §15). Замер повторяет продуктовый путь целиком:
 *
 * 1. `prepareSheet()` — `pretext.prepare()` **только на `wrap`-колонках**.
 *    Однострочным (numeric, mono, control, `truncate`-текст) нужна лишь
 *    натуральная ширина, а при `λ = 0` не нужна и она: их `lines` всегда 1,
 *    а обрезка входит в `cost` только через `λ`. Им хватает табличных метрик
 *    (`singleLineMeasurer`) — та же политика, без сегментации и canvas.
 *    Пилюли считаются `pillsWidth` по содержимому, `pretext` им не нужен.
 * 2. `searchOptimizer()` — `buildCostModel()` + сам поиск (он строит модель
 *    внутри, отдельный `buildCostModel()` в замере был бы двойной работой).
 * 3. `buildCostModel()` отдельно — диагностика: сколько из `search` уходит
 *    на построение модели, а сколько на перебор.
 * 4. Эквивалентность: раз в диагностике считается полная подготовка (pretext
 *    на всех ячейках) и сравнивается с оптимизированной. Ширины обязаны
 *    совпасть — иначе «ускорение» меняет политику, и это не оптимизация.
 *
 * Повторы (9) идут без прогрева: продукт считает один раз на лист, поэтому
 * первый повтор — холодный, остальные показывают установившийся режим.
 * `document.fonts.ready` ждётся до старта: иначе pretext измерит fallback.
 */
import { buildColumns, SERVICE_WIDTH_PX, baselineWidths } from "../lib/columns.mjs";
import { generateSheet } from "../lib/generator.mjs";
import {
  createMeasurer,
  createSyntheticMeasurer,
} from "../lib/measurers.mjs";
import { evaluate, prepareSheet } from "../lib/evaluate.mjs";
import { buildCostModel } from "../lib/curves.mjs";
import { searchOptimizer } from "../lib/optimizers.mjs";
import { loadFonts } from "./fonts.mjs";

const SEED = 1;
/**
 * 300 строк, а не 500: при 500 (две переносимые колонки — 1000 текстов)
 * медиана 95.1 мс, а `long-tail` на 1400–1920 выходит за 100 мс (до 109.3).
 * H2 допускает подвыборку: 200/500/1000 строк дали потерь 0.21/0.26/0.21%,
 * 300 — тот же порядок. Гейт остаётся ≤100 мс по медиане.
 */
const ROWS = 300;
/** Ширины подбираются на подвыборке (H2); при 300 строках — весь лист. */
const FIT_ROWS = 300;
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
 * Текущий фикс — опорная точка для «высот против текущего»: «Наименование»
 * обрезается (`truncate`, одна строка), «Ошибки» переносятся. Так экран жил
 * до флага; ширина наименования высоту не меняет.
 */
function currentFixColumns() {
  return buildColumns(COLUMN_COUNT).map((column) => {
    if (column.id === "source_name") {
      return { ...column, wrap: false, clamp: null };
    }
    return column.wrap ? { ...column, clamp: null } : column;
  });
}

/**
 * Продуктовая политика ячеек под флагом (#483): **обе** текстовые колонки
 * переносятся, без потолка строк — основной сценарий спеки (§4, `clamp = ∞`).
 */
function productColumns() {
  return buildColumns(COLUMN_COUNT).map((column) =>
    column.wrap ? { ...column, clamp: null } : column,
  );
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
  const singleLineMeasurer = createSyntheticMeasurer("greedy");
  const columns = productColumns();
  const wrapColumns = columns.filter((column) => column.wrap);
  const singleLineColumns = columns.filter(
    (column) => !column.wrap && column.kind !== "pills",
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
      const prepared = prepareSheet(scenario.sheet, measurer, {
        singleLineMeasurer,
      });
      const t1 = performance.now();
      const next = searchOptimizer(prepared, scenario.contentWidth, {
        lambda: 0,
        rowLimit: FIT_ROWS,
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
    const preparedForModel = prepareSheet(sheet, measurer, {
      singleLineMeasurer,
    });
    const m0 = performance.now();
    const model = buildCostModel(preparedForModel, contentWidth, {
      lambda: 0,
      rowLimit: FIT_ROWS,
      pillsMaxTruncatedShare: scenario.pillsMaxTruncatedShare,
    });
    const modelMs = performance.now() - m0;

    // Из чего состоит `prepare`: pretext платит только за переносимые
    // колонки, однострочные готовятся табличными метриками.
    measurer.clearCache?.();
    let splitStart = performance.now();
    prepareSheet({ ...sheet, columns: wrapColumns }, measurer);
    const wrapPrepareMs = performance.now() - splitStart;
    splitStart = performance.now();
    prepareSheet(
      { ...sheet, columns: singleLineColumns },
      measurer,
      { singleLineMeasurer },
    );
    const singleLinePrepareMs = performance.now() - splitStart;

    // Эквивалентность политики: полная подготовка (pretext на всех ячейках)
    // обязана дать те же ширины. Иначе это не «убрали лишнюю работу», а другая
    // раскладка — и гейт §15 к ней не относится.
    measurer.clearCache?.();
    const fullPrepared = prepareSheet(sheet, measurer);
    const fullSolution = searchOptimizer(fullPrepared, contentWidth, {
      lambda: 0,
      rowLimit: FIT_ROWS,
      pillsMaxTruncatedShare: scenario.pillsMaxTruncatedShare,
    });
    const maxWidthDelta = Math.max(
      ...columns.map((column) =>
        Math.abs(
          (fullSolution.widths[column.id] ?? 0) -
            (solution.widths[column.id] ?? 0),
        ),
      ),
    );
    const equivalence = {
      maxWidthDeltaPx: round(maxWidthDelta),
      costDelta: round(Math.abs(fullSolution.cost - solution.cost)),
      sameWidths: maxWidthDelta <= 0.5,
    };

    // Высоты против текущего фикса: тот же лист, текущие доли; у фикса
    // «Наименование» обрезано, у выбранной раскладки — полный текст. Обе
    // высоты считаются на полном листе (не на подвыборке).
    const currentColumns = currentFixColumns();
    measurer.clearCache?.();
    const currentPrepared = prepareSheet({ ...sheet, columns: currentColumns }, measurer, {
      singleLineMeasurer,
    });
    const currentWidths = baselineWidths(currentColumns, contentWidth);
    const chosenHeight = evaluate(fullPrepared, solution.widths, { lambda: 0 }).totalHeight;
    const currentHeight = evaluate(currentPrepared, currentWidths, { lambda: 0 }).totalHeight;
    const heights = {
      chosenTotalPx: round(chosenHeight),
      currentFixTotalPx: round(currentHeight),
      baselineFullTextPx: round(
        evaluate(fullPrepared, baselineWidths(columns, contentWidth), { lambda: 0 }).totalHeight,
      ),
      deltaVsCurrentFixPct: round(((chosenHeight / currentHeight) - 1) * 100, 2),
    };

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
          wrapCells: wrapColumns.length * ROWS,
          singleLineCells: singleLineColumns.length * ROWS,
        },
        equivalence,
        heights,
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
  // Гейт §15 по решению тикета — медиана «итого» ≤ 100 мс. p95 и холодный
  // прогон публикуются рядом: это не порог, но и не то, что можно спрятать.
  const pass = overall.total.median <= THRESHOLD_MS;

  const result = {
    meta: {
      ticket: 483,
      epic: 475,
      startedAt,
      seed: SEED,
      rows: ROWS,
      fitRows: FIT_ROWS,
      columnCount: COLUMN_COUNT,
      columnPolicy: "полный текст: source_name и errors переносятся, clamp = null",
      profiles: PROFILES,
      widths: WIDTHS,
      reps: REPS,
      lambda: 0,
      measurer: "pretext",
      preparePolicy:
        "pretext — только wrap-колонки (source_name + errors); однострочные — табличные метрики; пилюли — pillsWidth",
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
      basis: "медиана суммарного времени по всем повторам ≤ 100 мс",
      pass,
      medianTotalMs: overall.total.median,
      p95TotalMs: overall.total.p95,
      coldTotalMs,
    },
  };

  say(`Готово: медиана ${overall.total.median} мс — ${pass ? "pass" : "fail"}`);
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
