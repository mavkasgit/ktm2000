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
import {
  OPTIMIZERS,
  oracleOptimizer,
  widthStats,
} from "../lib/optimizers.mjs";

const WIDTH = 1500;
const CONTENT = WIDTH - SERVICE_WIDTH_PX;

async function fixture({ profile = "realistic", rows = 80, columns = 11 } = {}) {
  const measurer = await createMeasurer("greedy");
  const sheet = generateSheet({
    profile,
    rows,
    columns: buildColumns(columns),
    seed: 3,
  });
  return { sheet, prepared: prepareSheet(sheet, measurer) };
}

test("каждый оптимизатор уважает минимумы и бюджет", async () => {
  const { prepared } = await fixture();
  const { columns } = prepared;
  for (const [name, optimizer] of Object.entries(OPTIMIZERS)) {
    const { widths } = optimizer(prepared, CONTENT, { lambda: 20 });
    assert.deepEqual(Object.keys(widths).sort(), columns.map((c) => c.id).sort(), name);
    for (const column of columns) {
      assert.ok(widths[column.id] >= column.minPx - 0.5, `${name}: ${column.id} ниже минимума`);
      assert.ok(widths[column.id] <= maxWidth(column, CONTENT) + 0.5, `${name}: ${column.id} выше максимума`);
    }
    const total = sumWidths(columns, widths);
    assert.ok(total <= CONTENT + 6, `${name}: сумма ${total} больше бюджета ${CONTENT}`);
    assert.ok(total >= CONTENT - 6, `${name}: сумма ${total} сильно меньше бюджета ${CONTENT}`);
  }
});

test("baseline повторяет продуктовые доли", async () => {
  const { prepared } = await fixture();
  const { widths } = OPTIMIZERS.baseline(prepared, CONTENT);
  const name = prepared.columns.find((column) => column.id === "source_name");
  const shareSum = prepared.columns.reduce((sum, column) => sum + column.baselineShare, 0);
  assert.ok(
    Math.abs(widths.source_name - (name.baselineShare / shareSum) * CONTENT) <= 1,
  );
});

test("p90 не выходит за min/max и даёт больше ширины длинным колонкам", async () => {
  const { prepared } = await fixture({ profile: "long-tail" });
  const stats = widthStats(prepared);
  const { widths } = OPTIMIZERS.p90(prepared, CONTENT);
  assert.ok(widths.operations >= prepared.columns.find((c) => c.id === "operations").minPx);
  assert.ok(widths.source_name > widths.row);
  assert.ok(stats.get("source_name").p90 > stats.get("row").p90);
});

test("narrowing и breakpoints снижают высоту относительно baseline", async () => {
  const { prepared } = await fixture({ profile: "realistic", rows: 120 });
  const baseline = evaluate(prepared, OPTIMIZERS.baseline(prepared, CONTENT).widths);
  for (const name of ["narrowing", "breakpoints"]) {
    const { widths } = OPTIMIZERS[name](prepared, CONTENT, { lambda: 20 });
    const metrics = evaluate(prepared, widths);
    assert.ok(
      metrics.totalHeight < baseline.totalHeight,
      `${name}: ${metrics.totalHeight} не меньше baseline ${baseline.totalHeight}`,
    );
  }
});

test("оракул не хуже эвристик на малом инстансе", async () => {
  const { prepared } = await fixture({ profile: "long-tail", rows: 40 });
  const oracle = oracleOptimizer(prepared, CONTENT, { lambda: 20, perColumnLimit: 48 });
  const oracleMetrics = evaluate(prepared, oracle.widths);
  for (const name of ["narrowing", "breakpoints", "p90"]) {
    const { widths } = OPTIMIZERS[name](prepared, CONTENT, { lambda: 20 });
    const metrics = evaluate(prepared, widths);
    assert.ok(
      oracleMetrics.cost <= metrics.cost * 1.05,
      `${name}: cost ${metrics.cost} лучше оракула ${oracleMetrics.cost}`,
    );
  }
});

test("высота строки = max по колонкам, а не сумма", async () => {
  const measurer = await createMeasurer("greedy");
  const columns = buildColumns(6);
  const sheet = {
    columns,
    rows: [
      {
        values: {
          row: "2",
          sku: "A",
          source_name: "очень длинное наименование которое переносится на две строки",
          quantity: "1",
          operations: ["Дробеструй", "Чёрный"],
          errors: "",
        },
      },
    ],
  };
  const prepared = prepareSheet(sheet, measurer);
  const widths = {};
  for (const column of columns) widths[column.id] = column.minPx;
  widths.source_name = 120;
  const metrics = evaluate(prepared, widths);
  assert.equal(metrics.totalHeight, 60);
  assert.equal(metrics.multiLineRows, 1);
});
