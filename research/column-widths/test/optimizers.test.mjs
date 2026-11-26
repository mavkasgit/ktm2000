import assert from "node:assert/strict";
import test from "node:test";

import {
  CELL_PADDING_PX,
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
import {
  buildCostModel,
  columnMaxWordWidths,
  effectiveMinWidth,
  roundToBudget,
  selectSampleRows,
  widthsFromIndices,
} from "../lib/curves.mjs";

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

function minimumsFor(prepared, contentWidth = CONTENT) {
  const model = buildCostModel(prepared, contentWidth, {
    lambda: 20,
    rowLimit: Number.POSITIVE_INFINITY,
  });
  return model.minimums;
}

test("каждый оптимизатор уважает минимумы, maxShare и бюджет", async () => {
  const { prepared } = await fixture();
  const { columns } = prepared;
  const minimums = minimumsFor(prepared);
  for (const [name, optimizer] of Object.entries(OPTIMIZERS)) {
    const { widths } = optimizer(prepared, CONTENT, { lambda: 20 });
    assert.deepEqual(Object.keys(widths).sort(), columns.map((c) => c.id).sort(), name);
    for (const column of columns) {
      const floor = column.flex ? minimums[column.id] : column.minPx;
      assert.ok(widths[column.id] >= floor - 0.5, `${name}: ${column.id} ниже минимума`);
      assert.ok(widths[column.id] <= maxWidth(column, CONTENT) + 0.5, `${name}: ${column.id} выше максимума`);
    }
    const total = sumWidths(columns, widths);
    assert.ok(total <= CONTENT + 6, `${name}: сумма ${total} больше бюджета ${CONTENT}`);
    assert.ok(total >= CONTENT - 6, `${name}: сумма ${total} сильно меньше бюджета ${CONTENT}`);
  }
});

test("минимум текстовой колонки — не уже самого широкого слова (#479)", async () => {
  const measurer = await createMeasurer("greedy");
  const columns = buildColumns(6);
  const sheet = generateSheet({ profile: "all-short", rows: 20, columns, seed: 1 });
  sheet.rows[0].values.source_name = "Супердлинноесловобезпробелов";
  const prepared = prepareSheet(sheet, measurer);
  const maxWords = columnMaxWordWidths(prepared);
  const word = maxWords.get("source_name");
  assert.ok(word > 90, `слово должно быть шире minPx, получено ${word}`);
  const floor = effectiveMinWidth(
    columns.find((column) => column.id === "source_name"),
    word,
  );
  assert.equal(floor, Math.ceil(word) + CELL_PADDING_PX);
  for (const name of ["auto", "p90", "narrowing", "breakpoints", "search"]) {
    const { widths } = OPTIMIZERS[name](prepared, CONTENT, { lambda: 20 });
    assert.ok(
      widths.source_name >= floor - 0.5,
      `${name}: source_name ${widths.source_name} ниже слова ${floor}`,
    );
  }
});

test("неразрешимый бюджет — честное переполнение, а не нарушение минимумов", async () => {
  const { prepared } = await fixture({ profile: "realistic", rows: 40, columns: 11 });
  const narrow = 600;
  const minimums = minimumsFor(prepared, narrow);
  const minTotal = sumWidths(
    prepared.columns,
    Object.fromEntries(
      prepared.columns.map((column) => [
        column.id,
        column.flex ? minimums[column.id] : column.minPx,
      ]),
    ),
  );
  assert.ok(minTotal > narrow, "сценарий должен быть неразрешимым");
  for (const [name, optimizer] of Object.entries(OPTIMIZERS)) {
    const { widths } = optimizer(prepared, narrow, { lambda: 20 });
    for (const column of prepared.columns) {
      const floor = column.flex && name !== "baseline" ? minimums[column.id] : column.minPx;
      assert.ok(widths[column.id] >= floor - 0.5, `${name}: ${column.id} ниже минимума`);
    }
    const total = sumWidths(prepared.columns, widths);
    assert.ok(total > narrow, `${name}: бюджет неразрешим, сумма ${total} должна переполняться`);
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

test("roundToBudget сохраняет и сумму бюджета, и доли", async () => {
  const { prepared } = await fixture();
  const targets = {};
  for (const column of prepared.columns) targets[column.id] = CONTENT / prepared.columns.length;
  const widths = roundToBudget(prepared.columns, targets, CONTENT);
  assert.equal(sumWidths(prepared.columns, widths), CONTENT);
});

test("p90 не выходит за min/max и даёт больше ширины длинным колонкам", async () => {
  const { prepared } = await fixture({ profile: "long-tail" });
  const stats = widthStats(prepared);
  const { widths } = OPTIMIZERS.p90(prepared, CONTENT);
  assert.ok(widths.operations >= prepared.columns.find((c) => c.id === "operations").minPx);
  assert.ok(widths.source_name > widths.row);
  assert.ok(stats.get("source_name").p90 > stats.get("row").p90);
});

test("p90 не выходит за maxShare, когда его желаемые ширины уже бюджета (#486)", async () => {
  for (const profile of ["all-short", "realistic", "mixed"]) {
    for (const tableWidth of [1180, 1500, 1920]) {
      for (const count of [6, 11, 12, 20]) {
        const { prepared } = await fixture({ profile, columns: count });
        const content = tableWidth - SERVICE_WIDTH_PX;
        const { widths } = OPTIMIZERS.p90(prepared, content);
        for (const column of prepared.columns) {
          assert.ok(
            widths[column.id] <= maxWidth(column, content) + 0.5,
            `${profile}/${count}@${tableWidth}: ${column.id} = ${widths[column.id]} ` +
              `выше максимума ${maxWidth(column, content)}`,
          );
        }
      }
    }
  }
});

test("narrowing, breakpoints и search не хуже baseline (cost и высота)", async () => {
  const { prepared } = await fixture({ profile: "realistic", rows: 120 });
  const baseline = evaluate(prepared, OPTIMIZERS.baseline(prepared, CONTENT).widths);
  for (const name of ["narrowing", "breakpoints", "search"]) {
    const { widths } = OPTIMIZERS[name](prepared, CONTENT, { lambda: 20 });
    const metrics = evaluate(prepared, widths, { lambda: 20 });
    assert.ok(
      metrics.cost < baseline.cost,
      `${name}: cost ${metrics.cost} не меньше baseline ${baseline.cost}`,
    );
    assert.ok(
      metrics.totalHeight <= baseline.totalHeight,
      `${name}: высота ${metrics.totalHeight} больше baseline ${baseline.totalHeight}`,
    );
  }
});

test("кэш кривых воспроизводит evaluate бит-в-бит", async () => {
  const { prepared } = await fixture({ profile: "realistic", rows: 60 });
  const model = buildCostModel(prepared, CONTENT, {
    lambda: 20,
    rowLimit: Number.POSITIVE_INFINITY,
    maxCandidates: Number.POSITIVE_INFINITY,
  });
  const assignments = [
    model.curves.map(() => 0),
    model.curves.map((curve) => curve.candidates.length - 1),
    model.curves.map((curve) => Math.floor(curve.candidates.length / 2)),
  ];
  for (const indices of assignments) {
    const widths = widthsFromIndices(model, indices);
    const exact = evaluate(prepared, widths, { lambda: 20 });
    assert.equal(
      model.costOf(indices),
      exact.cost,
      `cost модели разошёлся с evaluate при ${JSON.stringify(indices)}`,
    );
  }
});

test("сетка кандидатов: возрастает, начинается с минимума и без дублей", async () => {
  const { prepared } = await fixture({ profile: "long-tail", rows: 60 });
  const model = buildCostModel(prepared, CONTENT, {
    lambda: 20,
    rowLimit: Number.POSITIVE_INFINITY,
    maxCandidates: Number.POSITIVE_INFINITY,
  });
  for (const curve of model.curves) {
    const { candidates, lines, trunc } = curve;
    assert.equal(candidates[0], model.minimums[curve.column.id]);
    for (let index = 1; index < candidates.length; index += 1) {
      assert.ok(candidates[index] > candidates[index - 1], "кандидаты должны возрастать");
      const same =
        trunc[index].every((value, row) => value === trunc[index - 1][row]) &&
        lines[index].every((value, row) => value === lines[index - 1][row]);
      assert.ok(!same, `кандидат ${candidates[index]} доминируется предыдущим`);
    }
  }
});

test("оракул не хуже эвристик на малых инстансах", async () => {
  for (const profile of ["realistic", "long-tail", "outlier", "empty"]) {
    const { prepared } = await fixture({ profile, rows: 48 });
    const oracle = oracleOptimizer(prepared, CONTENT, { lambda: 20 });
    const oracleCost = evaluate(prepared, oracle.widths, { lambda: 20 }).cost;
    for (const name of ["auto", "p90", "narrowing", "breakpoints", "search"]) {
      const { widths } = OPTIMIZERS[name](prepared, CONTENT, { lambda: 20 });
      const cost = evaluate(prepared, widths, { lambda: 20 }).cost;
      assert.ok(
        oracleCost <= cost * 1.001 + 1e-9,
        `${profile}/${name}: эвристика ${cost} лучше оракула ${oracleCost}`,
      );
    }
  }
});

test("search не дальше 5% от оракула на малых инстансах (H1)", async () => {
  const cases = [
    { profile: "realistic", tableWidth: 1180 },
    { profile: "realistic", tableWidth: 1920 },
    { profile: "long-tail", tableWidth: 1180 },
    { profile: "outlier", tableWidth: 1500 },
    { profile: "empty", tableWidth: 1500 },
    { profile: "mixed", tableWidth: 1920 },
  ];
  for (const { profile, tableWidth } of cases) {
    const content = tableWidth - SERVICE_WIDTH_PX;
    const { prepared } = await fixture({ profile, rows: 60 });
    const oracle = oracleOptimizer(prepared, content, { lambda: 20 });
    const oracleCost = evaluate(prepared, oracle.widths, { lambda: 20 }).cost;
    const { widths } = OPTIMIZERS.search(prepared, content, { lambda: 20 });
    const cost = evaluate(prepared, widths, { lambda: 20 }).cost;
    const gap = ((cost - oracleCost) / oracleCost) * 100;
    assert.ok(gap <= 5, `${profile}/${tableWidth}: gap ${gap.toFixed(2)}% > 5%`);
  }
});

test("время search на 5000×11 — в мягком потолке (цель 50 мс)", async () => {
  const measurer = await createMeasurer("greedy");
  const columns = buildColumns(11);
  const sheet = generateSheet({ profile: "long-tail", rows: 5000, columns, seed: 1 });
  const prepared = prepareSheet(sheet, measurer);
  const runs = [];
  for (let index = 0; index < 3; index += 1) {
    const started = performance.now();
    OPTIMIZERS.search(prepared, CONTENT, { lambda: 20 });
    runs.push(performance.now() - started);
  }
  runs.sort((a, b) => a - b);
  const median = runs[1];
  // Цель тикета — 50 мс; запас ×3 на медленную CI-машину и JIT.
  assert.ok(median < 150, `search: медиана ${median.toFixed(1)} мс > 150 мс`);
});

test("оптимизаторы детерминированы", async () => {
  const { prepared } = await fixture({ profile: "mixed", rows: 120 });
  for (const [name, optimizer] of Object.entries(OPTIMIZERS)) {
    const first = optimizer(prepared, CONTENT, { lambda: 20 }).widths;
    const second = optimizer(prepared, CONTENT, { lambda: 20 }).widths;
    assert.deepEqual(second, first, name);
  }
});

test("подвыборка детерминирована, не больше лимита и включает длинные строки", async () => {
  const { prepared } = await fixture({ profile: "long-tail", rows: 2000 });
  const first = selectSampleRows(prepared, 500);
  const second = selectSampleRows(prepared, 500);
  assert.deepEqual(second, first);
  assert.ok(first.length <= 500, `подвыборка ${first.length} > 500`);
  assert.ok(first.length > 0);
  // Самая длинная строка по гибким колонкам обязана попасть в подвыборку.
  const flexIndexes = prepared.columns
    .map((column, index) => (column.flex ? index : -1))
    .filter((index) => index >= 0);
  let longestRow = 0;
  let longestScore = -Infinity;
  prepared.rows.forEach((row, index) => {
    const score = flexIndexes.reduce((sum, i) => sum + Math.log1p(row[i].naturalWidth), 0);
    if (score > longestScore) {
      longestScore = score;
      longestRow = index;
    }
  });
  assert.ok(first.includes(longestRow), "самая длинная строка не попала в подвыборку");
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
