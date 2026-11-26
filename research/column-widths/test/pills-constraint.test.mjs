import assert from "node:assert/strict";
import test from "node:test";

import {
  SERVICE_WIDTH_PX,
  buildColumns,
  sumWidths,
} from "../lib/columns.mjs";
import { generateSheet } from "../lib/generator.mjs";
import { createMeasurer } from "../lib/measurers.mjs";
import { prepareSheet } from "../lib/evaluate.mjs";
import { buildCostModel } from "../lib/curves.mjs";
import { OPTIMIZERS } from "../lib/optimizers.mjs";
import {
  PILLS_CURRENT_LIMIT_PCT,
  PILLS_STRICT_LIMIT_PCT,
  pillsLimitForWidth,
  pillsLimitPctForWidth,
  policyMetrics,
} from "../lib/offline-shares.mjs";
import {
  buildRobustScenario,
  robustShares,
  widthsFromFlexShares,
} from "../lib/robust.mjs";
import { runOfflineShares } from "../bench.mjs";

const MAIN_COLUMNS = buildColumns(11).map((column) =>
  column.wrap ? { ...column, clamp: null } : column,
);
const CONTENT = 1500 - SERVICE_WIDTH_PX;

async function fixture({ profile = "realistic", rows = 120, seed = 3 } = {}) {
  const measurer = await createMeasurer("greedy");
  const sheet = generateSheet({
    profile,
    rows,
    columns: MAIN_COLUMNS,
    seed,
  });
  return { measurer, sheet, prepared: prepareSheet(sheet, measurer) };
}

test("лимит пилюль по W: продуктовая кривая, интерполяция и строгий режим", () => {
  for (const [width, limit] of Object.entries(PILLS_CURRENT_LIMIT_PCT)) {
    assert.equal(
      pillsLimitPctForWidth(Number(width), "current"),
      limit,
      `W=${width}`,
    );
  }
  assert.ok(
    Math.abs(pillsLimitPctForWidth(1280, "current") - 26.7445) < 0.01,
    "1280 интерполируется между 1180 и 1400",
  );
  assert.equal(pillsLimitPctForWidth(1000, "current"), PILLS_CURRENT_LIMIT_PCT[1180]);
  assert.equal(pillsLimitPctForWidth(5000, "current"), 0.01);
  for (const width of [1180, 1400, 1500, 1600, 1920]) {
    assert.equal(pillsLimitPctForWidth(width, "strict"), PILLS_STRICT_LIMIT_PCT);
    assert.equal(
      pillsLimitForWidth(width, "strict"),
      PILLS_STRICT_LIMIT_PCT / 100,
    );
  }
});

test("ограничение пилюль задаёт нижнюю границу, а дефолт её не вводит", async () => {
  const { prepared } = await fixture({ profile: "realistic", rows: 120 });
  const free = buildCostModel(prepared, CONTENT, { lambda: 0, rowLimit: 120 });
  assert.ok(free.floors.every((floor) => floor === 0), "без лимита пол не нужен");
  assert.equal(free.pillConstraints.length, 0);

  const constrained = buildCostModel(prepared, CONTENT, {
    lambda: 0,
    rowLimit: 120,
    pillsMaxTruncatedShare: 0.05,
  });
  assert.equal(constrained.pillConstraints.length, 1);
  const pill = constrained.pillConstraints[0];
  assert.equal(pill.column, "operations");
  assert.ok(pill.requiredWidth > 0);
  assert.equal(pill.satisfied, true);
  assert.ok(pill.sampleTruncatedSharePct <= 5 + 1e-9);

  const run = OPTIMIZERS.search(prepared, CONTENT, {
    lambda: 0,
    rowLimit: 120,
    pillsMaxTruncatedShare: 0.05,
  });
  assert.ok(
    run.widths.operations >= pill.requiredWidth - 0.5,
    `operations ${run.widths.operations} < нижней границы ${pill.requiredWidth}`,
  );
  for (const name of ["narrowing", "breakpoints"]) {
    const other = OPTIMIZERS[name](prepared, CONTENT, {
      lambda: 0,
      rowLimit: 120,
      pillsMaxTruncatedShare: 0.05,
    });
    assert.ok(
      other.widths.operations >= pill.requiredWidth - 0.5,
      `${name}: operations ${other.widths.operations} < ${pill.requiredWidth}`,
    );
  }
  const metrics = policyMetrics(prepared, run.widths);
  assert.ok(
    metrics.pillTruncatedSharePct <= 5.01,
    `обрезка пилюль ${metrics.pillTruncatedSharePct}% > 5%`,
  );
  assert.equal(metrics.textTruncatedSharePct, 0);
});

test("лимит 100% воспроизводит неограниченный search", async () => {
  const { prepared } = await fixture({ profile: "long-tail", rows: 120 });
  const free = OPTIMIZERS.search(prepared, CONTENT, { lambda: 0 });
  const full = OPTIMIZERS.search(prepared, CONTENT, {
    lambda: 0,
    pillsMaxTruncatedShare: 1,
  });
  assert.deepEqual(full.widths, free.widths);
});

test("неразрешимый бюджет с лимитом пилюль — переполнение, а не нарушение минимумов", async () => {
  const { prepared } = await fixture({ profile: "long-tail", rows: 120 });
  const narrow = 600;
  const model = buildCostModel(prepared, narrow, {
    lambda: 0,
    rowLimit: 120,
    pillsMaxTruncatedShare: 0,
  });
  assert.equal(model.budgetFeasible, false, "сценарий должен быть неразрешимым");
  assert.ok(model.lowerBoundTotal > model.flexBudget);
  const pill = model.pillConstraints[0];

  const run = OPTIMIZERS.search(prepared, narrow, {
    lambda: 0,
    rowLimit: 120,
    pillsMaxTruncatedShare: 0,
  });
  assert.ok(
    sumWidths(prepared.columns, run.widths) > narrow,
    "неразрешимый бюджет обязан переполняться",
  );
  assert.ok(
    run.widths.operations >= pill.requiredWidth - 0.5,
    `operations ${run.widths.operations} < ${pill.requiredWidth}`,
  );
  for (const column of prepared.columns) {
    assert.ok(
      run.widths[column.id] >= column.minPx - 0.5,
      `${column.id} ниже minPx`,
    );
  }
});

test("робастный вектор уважает нижнюю границу пилюль на сценариях", async () => {
  const { prepared } = await fixture({ profile: "realistic", rows: 120 });
  const widths = [1180, 1500];
  const scenarios = widths.map((tableWidth) =>
    buildRobustScenario({
      prepared,
      contentWidth: tableWidth - SERVICE_WIDTH_PX,
      lambda: 0,
      rowLimit: 120,
      maxCandidates: 40,
      profile: "realistic",
      tableWidth,
      pillsMaxTruncatedShare: 0.2,
    }),
  );
  for (const scenario of scenarios) {
    assert.equal(scenario.pillsConstrained, true);
    assert.equal(scenario.model.pillConstraints.length, 1);
  }
  const result = robustShares(scenarios, { maxSweeps: 3 });
  assert.equal(result.bounds.feasible, true);
  for (const id of Object.keys(result.bounds.lower)) {
    assert.ok(
      result.shares[id] >= result.bounds.lower[id] - 1e-9,
      `${id}: доля ${result.shares[id]} ниже ${result.bounds.lower[id]}`,
    );
  }
  for (const scenario of scenarios) {
    const policyWidths = widthsFromFlexShares(
      scenario.columns,
      scenario.contentWidth,
      result.shares,
    );
    const metrics = policyMetrics(scenario.prepared, policyWidths);
    assert.ok(
      metrics.pillTruncatedSharePct <= 20.5,
      `${scenario.tableWidth}: пилюли ${metrics.pillTruncatedSharePct}% > 20%`,
    );
  }
});

test("runOfflineShares считает оба режима ограничения и цену обрезки", async () => {
  const measurer = await createMeasurer("greedy");
  const spec = {
    profiles: ["realistic", "outlier"],
    widths: [1180, 1500, 1600],
    rows: 120,
    fitSeed: 1,
    seeds: [1],
    columnCount: 11,
    fitRows: 80,
    fitWidths: [1180, 1500, 1600],
    fitMaxSweeps: 2,
    fitMaxCandidates: 6,
    trainProfiles: ["realistic"],
    pillsTradeoffLimitsPct: [5, 30, 100],
  };
  const result = runOfflineShares(measurer, spec);
  assert.ok(result.pillsConstraint, "блок ограничения пилюль должен быть");
  for (const mode of ["current", "strict"]) {
    const item = result.pillsConstraint.modes[mode];
    assert.ok(item, `режим ${mode}`);
    assert.equal(item.overall.search.textTruncatedSharePctWorst, 0);
    assert.equal(item.overall.vector.textTruncatedSharePctWorst, 0);
    assert.ok(item.rows.length > 0);
    for (const entry of item.byWidth) {
      assert.equal(typeof entry.limitPctMean, "number");
      assert.ok(entry.limitPctMean > 0);
    }
    const total = Object.values(item.vector.shares).reduce(
      (sum, share) => sum + share,
      0,
    );
    assert.ok(Math.abs(total - 1) < 1e-6, `сумма долей ${total}`);
  }
  assert.equal(result.pillsConstraint.tradeoff.limits.length, 3);
  assert.equal(result.pillsConstraint.tradeoff.marginal.length, 2);
});
