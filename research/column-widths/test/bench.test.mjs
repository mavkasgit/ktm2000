import assert from "node:assert/strict";
import test from "node:test";

import { aggregate, loadBrowserH4, parseSections, runConfig } from "../bench.mjs";
import { CELL_PADDING_PX, buildColumns } from "../lib/columns.mjs";
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

test("loadBrowserH4 без файла честно просит browser:test", () => {
  const result = loadBrowserH4("definitely-missing-browser.json");
  assert.equal(result.available, false);
  assert.equal(result.source, "см. browser:test");
});

test("--only парсит секции и all", () => {
  assert.deepEqual(parseSections("product"), ["product"]);
  assert.deepEqual(parseSections("product,oracle"), ["oracle", "product"]);
  assert.deepEqual(parseSections("all"), [
    "matrix",
    "oracle",
    "product",
    "sensitivity",
  ]);
  assert.throws(() => parseSections("matrix,nope"), /неизвестная секция/);
});
