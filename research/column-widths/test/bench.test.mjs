import assert from "node:assert/strict";
import test from "node:test";

import {
  aggregate,
  clampColumns,
  loadBrowserH4,
  mainColumns,
  parseSections,
  runConfig,
  runRegretMatrix,
  runSampleStability,
  runSweep,
} from "../bench.mjs";
import {
  CELL_PADDING_PX,
  LINE_HEIGHT_PX,
  ROW_PADDING_PX,
  buildColumns,
} from "../lib/columns.mjs";
import { generateSheet } from "../lib/generator.mjs";
import { evaluate, prepareSheet } from "../lib/evaluate.mjs";
import { createMeasurer } from "../lib/measurers.mjs";

const OPTIONS = {
  profile: "realistic",
  rows: 200,
  tableWidth: 1500,
  columnCount: 11,
  seed: 7,
};

/** Время — единственное, что может отличаться между одинаковыми прогонами. */
function withoutTiming(config) {
  const copy = structuredClone(config);
  for (const metrics of Object.values(copy.results)) delete metrics.ms;
  return copy;
}

test("runConfig детерминирован: одинаковый seed даёт одинаковые числа", async () => {
  const measurer = await createMeasurer("greedy");
  const first = runConfig({ ...OPTIONS, measurer });
  const second = runConfig({ ...OPTIONS, measurer });
  assert.deepEqual(withoutTiming(second), withoutTiming(first));
});

test("aggregate не зависит от времени прогона", async () => {
  const measurer = await createMeasurer("greedy");
  const configs = [
    runConfig({ ...OPTIONS, measurer }),
    runConfig({ ...OPTIONS, rows: 100, seed: 3, measurer }),
  ];
  const first = aggregate(configs);
  const second = aggregate(configs);
  for (const name of Object.keys(first)) {
    delete first[name].meanRuntimeMs;
    delete first[name].maxRuntimeMs;
    delete second[name].meanRuntimeMs;
    delete second[name].maxRuntimeMs;
  }
  assert.deepEqual(second, first);
});

test("runConfig отдаёт ширины всех колонок и не выходит за бюджет", async () => {
  const measurer = await createMeasurer("greedy");
  const config = runConfig({ ...OPTIONS, measurer });
  const ids = buildColumns(OPTIONS.columnCount)
    .map((column) => column.id)
    .sort();
  for (const [name, metrics] of Object.entries(config.results)) {
    assert.deepEqual(Object.keys(metrics.widths).sort(), ids, name);
    assert.ok(
      metrics.widthSum <= config.contentWidth + 1,
      `${name}: сумма ширин ${metrics.widthSum} > ${config.contentWidth}`,
    );
    for (const [id, width] of Object.entries(metrics.widths)) {
      assert.ok(
        width >= CELL_PADDING_PX,
        `${name}/${id}: ширина ${width} меньше паддинга`,
      );
    }
  }
});

test("основной режим: clamp=null, свип задаёт потолок", async () => {
  const measurer = await createMeasurer("greedy");
  for (const column of mainColumns(12)) {
    if (column.wrap) assert.equal(column.clamp, null, column.id);
  }
  for (const column of clampColumns(12, 3)) {
    if (column.wrap) assert.equal(column.clamp, 3, column.id);
  }

  const columns = mainColumns(11);
  const sheet = generateSheet({
    profile: "long-tail",
    rows: 200,
    columns,
    seed: 1,
  });
  const free = prepareSheet(sheet, measurer);
  const clamped = prepareSheet(
    { ...sheet, columns: clampColumns(11, 3) },
    measurer,
  );
  const widths = Object.fromEntries(
    columns.map((column) => [column.id, column.minPx]),
  );
  const freeMetrics = evaluate(free, widths, { lambda: 0, collectRows: true });
  const clampedMetrics = evaluate(clamped, widths, {
    lambda: 0,
    collectRows: true,
  });
  assert.ok(
    freeMetrics.maxHeight > clampedMetrics.maxHeight,
    `без clamp высота ${freeMetrics.maxHeight}, с clamp 3 — ${clampedMetrics.maxHeight}`,
  );
});

test("свип: без потолка нет потери текста, clamp 2 держит высоту", async () => {
  const measurer = await createMeasurer("greedy");
  const cases = runSweep(measurer, {
    profiles: ["long-tail"],
    rows: 200,
    widths: [1500],
    seed: 1,
    clamps: ["none", 2],
    lambda: 20,
  });
  assert.equal(cases.length, 2);
  const free = cases.find((item) => item.clamp === "none");
  const capped = cases.find((item) => item.clamp === 2);
  assert.equal(free.textTruncatedShare, 0);
  assert.equal(free.textTruncatedCells, 0);
  assert.ok(
    capped.maxHeight <= 2 * LINE_HEIGHT_PX + ROW_PADDING_PX,
    `clamp 2: maxHeight ${capped.maxHeight}`,
  );
  assert.ok(free.rows4PlusShare > 0, "long-tail без clamp должен давать 4+ строк");
});

test("продуктовый срез сравнивает политики и считает рост", async () => {
  const measurer = await createMeasurer("greedy");
  const config = runConfig({ ...OPTIONS, measurer, policies: true });
  const policy = config.policies;
  assert.ok(policy, "policies должны быть посчитаны");
  assert.ok(policy.currentProduct.height > 0);
  assert.ok(policy.noClampBaseline.height > 0);
  assert.ok(policy.noClampBest.height > 0);
  assert.equal(Number.isFinite(policy.growthPct.best), true);
  assert.equal(Number.isFinite(policy.growthPct.baseline), true);
});

test("loadBrowserH4 без файла честно просит browser:test", () => {
  const result = loadBrowserH4("definitely-missing-browser.json");
  assert.equal(result.available, false);
  assert.equal(result.source, "см. browser:test");
});

test("--only парсит секции и all", () => {
  assert.deepEqual(parseSections("product"), ["product"]);
  assert.deepEqual(parseSections("product,oracle"), ["oracle", "product"]);
  assert.deepEqual(parseSections("sensitivity"), ["sweep"]);
  assert.deepEqual(parseSections("all"), [
    "matrix",
    "oracle",
    "product",
    "sweep",
    "stability",
    "robust",
    "offline",
  ]);
  assert.deepEqual(parseSections("offline"), ["offline"]);
  assert.throws(() => parseSections("matrix,nope"), /неизвестная секция/);
});

test("матрица сожалений детерминирована, а перенос с W0 в проценты держит бюджет", async () => {
  const measurer = await createMeasurer("greedy");
  const spec = {
    profiles: ["realistic", "long-tail"],
    rows: 120,
    baseWidth: 1500,
    widths: [1180, 1500, 1600],
    seed: 1,
    columnCount: 11,
    optimizer: "search",
  };
  const first = runRegretMatrix(measurer, spec);
  const second = runRegretMatrix(measurer, spec);
  assert.deepEqual(second.cases, first.cases);
  assert.deepEqual(second.byWidth, first.byWidth);
  assert.equal(first.cases.length, spec.profiles.length * spec.widths.length);

  for (const item of first.cases) {
    if (item.tableWidth === spec.baseWidth) {
      assert.equal(item.scaledRegretPct, 0, "на W0 перенос должен быть нейтральным");
    }
    assert.ok(
      Math.abs(item.scaledWidthSum - item.contentWidth) < 0.5,
      `${item.profile}@${item.tableWidth}: сумма ${item.scaledWidthSum} ≠ ${item.contentWidth}`,
    );
    const shareTotal = Object.values(item.baseShares).reduce(
      (sum, value) => sum + value,
      0,
    );
    assert.ok(Math.abs(shareTotal - 1) < 1e-6, `сумма долей ${shareTotal}`);
  }
});

test("H2 пересчитывается на размерах подвыборки 200/500", async () => {
  const measurer = await createMeasurer("greedy");
  const cases = runSampleStability(measurer, {
    profiles: ["long-tail"],
    sampleSizes: [200, 500],
    rows: 700,
  });
  assert.equal(cases.length, 2 * 3);
  for (const size of [200, 500]) {
    const subset = cases.filter((item) => item.sampleSize === size);
    assert.equal(subset.length, 3);
    assert.equal(new Set(subset.map((item) => item.profile)).size, 1);
  }
  for (const optimizer of ["narrowing", "breakpoints", "search"]) {
    const heights = [200, 500].map(
      (size) =>
        cases.find(
          (item) => item.sampleSize === size && item.optimizer === optimizer,
        ).fullHeight,
    );
    // Полный лист один и тот же независимо от размера подвыборки.
    assert.equal(new Set(heights).size, 1, optimizer);
  }
});
