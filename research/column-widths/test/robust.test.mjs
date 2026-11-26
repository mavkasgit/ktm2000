import assert from "node:assert/strict";
import test from "node:test";

import {
  SERVICE_WIDTH_PX,
  buildColumns,
  maxWidth,
  sumWidths,
} from "../lib/columns.mjs";
import { generateSheet } from "../lib/generator.mjs";
import { createMeasurer } from "../lib/measurers.mjs";
import { evaluate, prepareSheet } from "../lib/evaluate.mjs";
import { buildCostModel, costAtWidths } from "../lib/curves.mjs";
import {
  baselineFlexShares,
  buildRobustScenario,
  flexSharesFromWidths,
  robustShares,
  scoreShares,
  widthsFromFlexShares,
} from "../lib/robust.mjs";

const TABLE_WIDTH = 1500;
const CONTENT = TABLE_WIDTH - SERVICE_WIDTH_PX;

async function fixture({
  profile = "realistic",
  rows = 120,
  columns = 11,
  width = TABLE_WIDTH,
} = {}) {
  const measurer = await createMeasurer("greedy");
  const sheet = generateSheet({
    profile,
    rows,
    columns: buildColumns(columns),
    seed: 3,
  });
  return { prepared: prepareSheet(sheet, measurer), contentWidth: width - SERVICE_WIDTH_PX };
}

function scenariosFor(prepared, widths, profile = "realistic") {
  return widths.map((tableWidth) =>
    buildRobustScenario({
      prepared,
      contentWidth: tableWidth - SERVICE_WIDTH_PX,
      lambda: 0,
      rowLimit: Number.POSITIVE_INFINITY,
      maxCandidates: 10,
      profile,
      tableWidth,
    }),
  );
}

test("costAtWidths повторяет evaluate на произвольных (не сеточных) ширинах", async () => {
  const { prepared, contentWidth } = await fixture({ profile: "long-tail", rows: 120 });
  const model = buildCostModel(prepared, contentWidth, {
    lambda: 0,
    rowLimit: Number.POSITIVE_INFINITY,
    maxCandidates: Number.POSITIVE_INFINITY,
  });
  const flex = prepared.columns.filter((column) => column.flex);
  const widths = { ...model.fixedWidths };
  for (const column of flex) {
    // Ширина ниже первого порога и не кратная пиксельной сетке — именно такие
    // даёт доля от бюджета.
    widths[column.id] = model.minimums[column.id] + 3.37;
  }
  const exact = evaluate(prepared, widths, { lambda: 0 });
  assert.equal(costAtWidths(model, widths), exact.cost);

  widths.source_name = model.minimums.source_name + 71.11;
  widths.errors = model.minimums.errors + 13.5;
  assert.equal(
    costAtWidths(model, widths),
    evaluate(prepared, widths, { lambda: 0 }).cost,
  );
});

test("доли гибких колонок: сумма 1 и обратимость ширин", async () => {
  const { prepared, contentWidth } = await fixture();
  const columns = prepared.columns;
  const baseline = baselineFlexShares(columns);
  const total = Object.values(baseline).reduce((sum, value) => sum + value, 0);
  assert.ok(Math.abs(total - 1) < 1e-9, `сумма долей ${total}`);

  const widths = widthsFromFlexShares(columns, contentWidth, baseline);
  const roundTrip = flexSharesFromWidths(columns, contentWidth, widths);
  for (const column of columns.filter((item) => item.flex)) {
    assert.ok(
      Math.abs(roundTrip[column.id] - baseline[column.id]) < 1e-9,
      `${column.id}: доля не вернулась`,
    );
  }
  assert.ok(
    Math.abs(sumWidths(columns, widths) - contentWidth) < 1e-6,
    "ширины по долям не заполняют бюджет",
  );
});

test("robustShares детерминирован и уважает minPx/maxShare на каждой W'", async () => {
  const widths = [1180, 1600];
  const prepareds = await Promise.all([
    fixture({ profile: "realistic", rows: 120 }),
    fixture({ profile: "long-tail", rows: 120 }),
  ]);
  const scenarios = prepareds.flatMap(({ prepared }) =>
    scenariosFor(prepared, widths),
  );
  const first = robustShares(scenarios, { maxSweeps: 4 });
  const second = robustShares(scenarios, { maxSweeps: 4 });
  assert.deepEqual(second.shares, first.shares);
  assert.equal(second.meanGapPct, first.meanGapPct);
  assert.equal(second.worstGapPct, first.worstGapPct);

  const total = Object.values(first.shares).reduce((sum, value) => sum + value, 0);
  assert.ok(Math.abs(total - 1) < 1e-9, `сумма долей ${total}`);
  assert.equal(first.bounds.feasible, true);

  let violations = 0;
  for (const scenario of scenarios) {
    const widthsByShares = widthsFromFlexShares(
      scenario.columns,
      scenario.contentWidth,
      first.shares,
    );
    assert.ok(
      Math.abs(sumWidths(scenario.columns, widthsByShares) - scenario.contentWidth) <
        1e-6,
      "бюджет не заполнен",
    );
    for (const column of scenario.columns) {
      if (column.flex) {
        assert.ok(
          widthsByShares[column.id] >= scenario.model.minimums[column.id] - 0.5,
          `${column.id} ниже эффективного минимума`,
        );
      } else {
        assert.ok(
          widthsByShares[column.id] >= column.minPx - 0.5,
          `${column.id} ниже minPx`,
        );
      }
      const cap = maxWidth(column, scenario.contentWidth);
      assert.ok(
        widthsByShares[column.id] <= cap + 0.5,
        `${column.id} выше maxShare`,
      );
    }
    violations += first.scenarios.find(
      (item) => item.profile === scenario.profile && item.tableWidth === scenario.tableWidth,
    ).violations.length;
  }
  assert.equal(violations, 0);
});

test("robustShares не хуже продуктовых долей по средней стоимости", async () => {
  const widths = [1180, 1600];
  const { prepared } = await fixture({ profile: "mixed", rows: 160 });
  const scenarios = scenariosFor(prepared, widths);
  const baseline = baselineFlexShares(prepared.columns);
  const baselineScore = scoreShares(scenarios, baseline);
  const result = robustShares(scenarios, { maxSweeps: 4 });
  assert.ok(
    result.meanGapPct <= baselineScore.mean + 1e-9,
    `робастный средний ${result.meanGapPct}% хуже baseline ${baselineScore.mean}%`,
  );
  // Ширина произвольна: costAtWidths читает пороги, а не только сетку.
  assert.ok(Math.abs(result.shares.source_name + result.shares.operations + result.shares.errors - 1) < 1e-9);
  assert.ok(result.shares.errors > 0 && result.shares.errors < 1);
});
