import assert from "node:assert/strict";
import test from "node:test";

import {
  SERVICE_WIDTH_PX,
  baselineWidths,
  buildColumns,
  sumWidths,
} from "../lib/columns.mjs";
import { columnMaxWordWidths } from "../lib/curves.mjs";
import { generateSheet } from "../lib/generator.mjs";
import { createMeasurer } from "../lib/measurers.mjs";
import { prepareSheet } from "../lib/evaluate.mjs";
import { normalizeShares, widthsFromFlexShares } from "../lib/robust.mjs";
import { buildRobustScenario } from "../lib/robust.mjs";
import {
  OFFLINE_BUCKET_PLANS,
  OFFLINE_FLEX_SHARES,
  bucketIndexForContentWidth,
  bucketIndexForTableWidth,
  fitBucketShares,
  policyMetrics,
  widthViolations,
} from "../lib/offline-shares.mjs";
import { runOfflineShares } from "../bench.mjs";

const MAIN_COLUMNS = buildColumns(11).map((column) =>
  column.wrap ? { ...column, clamp: null } : column,
);
const CONTENT = (tableWidth) => tableWidth - SERVICE_WIDTH_PX;

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

test("оффлайн-вектор #482: сумма долей 1 и заявленные значения", () => {
  const ids = Object.keys(OFFLINE_FLEX_SHARES);
  assert.deepEqual(ids.sort(), ["errors", "operations", "source_name"]);
  const total = ids.reduce((sum, id) => sum + OFFLINE_FLEX_SHARES[id], 0);
  assert.ok(Math.abs(total - 1) < 1e-9, `сумма долей ${total}`);
  assert.equal(OFFLINE_FLEX_SHARES.source_name, 0.38);
  assert.equal(OFFLINE_FLEX_SHARES.operations, 0.1658);
  assert.equal(OFFLINE_FLEX_SHARES.errors, 0.4542);
});

test("оффлайн-вектор укладывается в minPx/maxShare на всей сетке W", async () => {
  const { prepared } = await fixture({ profile: "long-tail" });
  const maxWords = columnMaxWordWidths(prepared);
  const ids = MAIN_COLUMNS.filter((column) => column.flex).map(
    (column) => column.id,
  );
  const shares = normalizeShares(ids, OFFLINE_FLEX_SHARES);
  for (const tableWidth of [1180, 1400, 1500, 1600, 1920]) {
    const content = CONTENT(tableWidth);
    const widths = widthsFromFlexShares(MAIN_COLUMNS, content, shares);
    assert.ok(
      Math.abs(sumWidths(MAIN_COLUMNS, widths) - content) < 1e-6,
      `${tableWidth}: бюджет не заполнен`,
    );
    assert.deepEqual(
      widthViolations(MAIN_COLUMNS, widths, content, maxWords),
      [],
      `${tableWidth}: нарушены границы`,
    );
  }
});

test("границы бакетов полуоткрытые и одинаковы для W и contentWidth", () => {
  const two = OFFLINE_BUCKET_PLANS.two;
  const three = OFFLINE_BUCKET_PLANS.three;
  assert.equal(bucketIndexForTableWidth(1180, two), 0);
  assert.equal(bucketIndexForTableWidth(1600, two), 0);
  assert.equal(bucketIndexForTableWidth(1601, two), 1);
  assert.equal(bucketIndexForTableWidth(1920, two), 1);

  assert.equal(bucketIndexForTableWidth(1180, three), 0);
  assert.equal(bucketIndexForTableWidth(1280, three), 0);
  assert.equal(bucketIndexForTableWidth(1281, three), 1);
  assert.equal(bucketIndexForTableWidth(1600, three), 1);
  assert.equal(bucketIndexForTableWidth(1601, three), 2);

  assert.equal(bucketIndexForContentWidth(CONTENT(1280), three), 0);
  assert.equal(bucketIndexForContentWidth(CONTENT(1281), three), 1);
  assert.equal(bucketIndexForContentWidth(CONTENT(1600), two), 0);
  assert.equal(bucketIndexForContentWidth(CONTENT(1601), two), 1);
});

test("fitBucketShares детерминирован и каждый бакет — вектор с суммой 1", async () => {
  const { prepared } = await fixture({ profile: "realistic", rows: 100 });
  const widths = [1180, 1280, 1400, 1500, 1600, 1920];
  const scenarios = widths.map((tableWidth) =>
    buildRobustScenario({
      prepared,
      contentWidth: CONTENT(tableWidth),
      lambda: 0,
      rowLimit: 100,
      maxCandidates: 8,
      profile: "realistic",
      tableWidth,
    }),
  );
  for (const plan of Object.values(OFFLINE_BUCKET_PLANS)) {
    const first = fitBucketShares(scenarios, plan, { maxSweeps: 2 });
    const second = fitBucketShares(scenarios, plan, { maxSweeps: 2 });
    assert.deepEqual(second, first);
    for (const bucket of first) {
      const total = Object.values(bucket.shares).reduce(
        (sum, share) => sum + share,
        0,
      );
      assert.ok(Math.abs(total - 1) < 1e-9, `бакет ${bucket.index}: ${total}`);
      assert.equal(bucket.bounds.feasible, true);
    }
  }
});

test("потеря текста и обрезка пилюль считаются раздельно", async () => {
  const { measurer, sheet, prepared } = await fixture({
    profile: "outlier",
    rows: 120,
  });
  const content = CONTENT(1180);
  const widths = baselineWidths(MAIN_COLUMNS, content);
  const base = policyMetrics(prepared, widths);
  assert.equal(base.textTruncatedSharePct, 0);
  assert.ok(base.pillTruncatedSharePct > 0, "выброс с 6 пилюлями должен обрезаться");

  const squeezed = { ...widths, operations: 90 };
  const narrow = policyMetrics(prepared, squeezed);
  assert.equal(narrow.textTruncatedSharePct, 0);
  assert.ok(
    narrow.pillTruncatedSharePct > base.pillTruncatedSharePct,
    `${narrow.pillTruncatedSharePct} ≤ ${base.pillTruncatedSharePct}`,
  );

  const truncatedColumns = MAIN_COLUMNS.map((column) =>
    column.id === "source_name"
      ? { ...column, wrap: false, clamp: null }
      : column,
  );
  const truncated = prepareSheet(
    { ...sheet, columns: truncatedColumns },
    measurer,
  );
  const lost = policyMetrics(truncated, widths);
  assert.ok(
    lost.textTruncatedSharePct > 0,
    "truncate наименования должен считаться потерей текста",
  );
  assert.ok(
    Math.abs(lost.pillTruncatedSharePct - base.pillTruncatedSharePct) < 1e-9,
    "потеря текста не должна менять обрезку пилюль",
  );
});

test("runOfflineShares детерминирован и держит инварианты", async () => {
  const measurer = await createMeasurer("greedy");
  const spec = {
    profiles: ["realistic", "outlier"],
    widths: [1180, 1500, 1600],
    rows: 120,
    fitSeed: 1,
    seeds: [1, 2],
    columnCount: 11,
    fitRows: 80,
    fitWidths: [1180, 1500, 1600],
    fitMaxSweeps: 2,
    fitMaxCandidates: 6,
    trainProfiles: ["realistic"],
  };
  const first = runOfflineShares(measurer, spec);
  const second = runOfflineShares(measurer, spec);
  assert.deepEqual(second, first);

  assert.equal(first.decision.textLossPct, 0);
  assert.equal(first.decision.textLossZero, true);
  assert.equal(first.cases.length, spec.profiles.length * spec.widths.length * 2);
  for (const item of first.cases) {
    for (const [name, policy] of Object.entries(item.policies)) {
      assert.ok(
        Math.abs(policy.widthSum - item.contentWidth) < 0.6,
        `${item.profile}@${item.tableWidth}/${name}: сумма ${policy.widthSum} ≠ ${item.contentWidth}`,
      );
      assert.equal(
        policy.textTruncatedSharePct,
        0,
        `${item.profile}@${item.tableWidth}/${name}: потерян текст`,
      );
      if (name === "offline" || name.startsWith("bucket")) {
        assert.deepEqual(
          policy.violations,
          [],
          `${item.profile}@${item.tableWidth}/${name}: нарушены границы`,
        );
      }
    }
  }
  for (const plan of first.bucketSwitches) {
    for (const boundary of plan.boundaries) {
      assert.equal(boundary.violations, 0, `${plan.plan}@${boundary.boundary}`);
    }
  }
  assert.ok(first.heldOut, "отложенные профили должны проверяться");
  assert.deepEqual(first.heldOut.testProfiles, ["outlier"]);
});
