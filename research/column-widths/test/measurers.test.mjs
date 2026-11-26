/**
 * Контракт измерителей (тикет #478).
 *
 * Проверяем не алгоритмы оптимизаторов, а сам слой измерения: единый интерфейс,
 * корректность greedy на краях, работу pretext в Node без DOM и согласие
 * pretext с greedy там, где модели обязаны совпадать. Расхождения, которые
 * являются границей модели, зафиксированы отдельным тестом и в README.
 */
import assert from "node:assert/strict";
import test from "node:test";

import { buildColumns } from "../lib/columns.mjs";
import { generateSheet } from "../lib/generator.mjs";
import {
  FONT_FAMILY,
  FONT_PX,
  MEASURERS,
  createMeasurer,
  createSyntheticMeasurer,
  cssFont,
} from "../lib/measurers.mjs";
import { OffscreenCanvasPolyfill } from "../lib/offscreen-canvas.mjs";
import { clampedLineCount } from "../lib/text.mjs";

/** Был ли canvas до полифилла: Node без него, но будущее может иначе. */
const HAD_NATIVE_CANVAS = Boolean(globalThis.OffscreenCanvas);

const INTERFACE = ["prepare", "lineCount", "naturalWidth", "maxWordWidth"];

function assertInterface(measurer) {
  for (const method of INTERFACE) {
    assert.equal(typeof measurer[method], "function", `${measurer.name}: ${method}`);
  }
  assert.ok(["primary", "baseline"].includes(measurer.role), `${measurer.name}: role`);
}

test("интерфейс один для greedy, ceil и pretext", async () => {
  assert.deepEqual(MEASURERS, ["greedy", "ceil", "pretext"]);

  const greedy = createSyntheticMeasurer("greedy");
  const ceil = createSyntheticMeasurer("ceil");
  const pretext = await createMeasurer("pretext");

  for (const measurer of [greedy, ceil, pretext]) {
    assertInterface(measurer);
    const prepared = measurer.prepare("Плинтус алюминиевый 40 мм", "sans");
    const natural = measurer.naturalWidth(prepared);
    assert.ok(natural > 0, `${measurer.name}: naturalWidth > 0`);
    assert.ok(measurer.maxWordWidth(prepared) > 0, `${measurer.name}: maxWordWidth > 0`);
    assert.ok(
      measurer.maxWordWidth(prepared) <= natural + 0.01,
      `${measurer.name}: maxWordWidth <= naturalWidth`,
    );
    assert.equal(measurer.lineCount(prepared, natural), 1, `${measurer.name}: одна строка`);
  }
});

test("шрифты измерителя синхронизированы с CSS", () => {
  assert.equal(FONT_PX, 11);
  assert.equal(FONT_FAMILY.sans, '"Inter"');
  assert.equal(FONT_FAMILY.mono, '"JetBrains Mono"');
  assert.equal(cssFont(), '11px "Inter"');
  assert.equal(cssFont("sans"), '11px "Inter"');
  assert.equal(cssFont("mono"), '11px "JetBrains Mono"');
});

test("OffscreenCanvas-полифилл реализует контракт pretext", () => {
  const canvas = new OffscreenCanvasPolyfill(1, 1);
  const context = canvas.getContext("2d");
  assert.ok(context);
  assert.equal(canvas.getContext("2d"), context, "контекст переиспользуется");
  assert.equal(canvas.getContext("webgl"), null);

  context.font = '11px "JetBrains Mono"';
  assert.equal(context.font, '11px "JetBrains Mono"', "font читается обратно");
  assert.ok(context.measureText("AAAA").width > 0);
  assert.ok(context.measureText("AAAA").width > context.measureText("AA").width);
  // Без letterSpacing pretext не включает letter-spaced shaping.
  assert.equal(context.letterSpacing, undefined);
});

test("ceil помечен baseline и не является дефолтом", async () => {
  assert.equal(createSyntheticMeasurer("ceil").role, "baseline");
  assert.equal(createSyntheticMeasurer("greedy").role, "primary");
  assert.equal((await createMeasurer()).name, "greedy");
  assert.throws(() => createSyntheticMeasurer("oracle"), /unknown synthetic measurer/);
});

test("greedy: длинное слово, пустая строка и clamp", () => {
  const greedy = createSyntheticMeasurer("greedy");

  const longWord = greedy.prepare("ALS-1234567890-XYZ", "mono");
  assert.ok(greedy.maxWordWidth(longWord) > 20);
  assert.equal(greedy.lineCount(longWord, 20), 1, "слово без пробелов не рвётся");

  const empty = greedy.prepare("", "sans");
  assert.equal(greedy.naturalWidth(empty), 0);
  assert.equal(greedy.maxWordWidth(empty), 0);
  assert.equal(greedy.lineCount(empty, 100), 1);
  assert.equal(greedy.lineCount(empty, 0), Number.MAX_SAFE_INTEGER, "нулевая ширина — неопределённость");

  const text = greedy.prepare(
    "Строка 128: остаток меньше одной штуки, участок не найден, дубликат по артикулу и длине",
    "sans",
  );
  const clamp = 2;
  const raw = greedy.lineCount(text, 120);
  assert.ok(raw > clamp);
  const clamped = clampedLineCount(text, 120, clamp);
  assert.equal(Math.min(raw, clamp), clamp);
  assert.equal(clamped.lines, clamp);
  assert.equal(clamped.truncated, true);
});

test("pretext работает в Node без DOM через OffscreenCanvas-полифилл", async () => {
  assert.equal(typeof document, "undefined", "в Node нет DOM");
  const pretext = await createMeasurer("pretext");
  if (!HAD_NATIVE_CANVAS) {
    assert.equal(globalThis.OffscreenCanvas, OffscreenCanvasPolyfill, "полифилл установлен");
  }

  const prepared = pretext.prepare("Плинтус алюминиевый 40 мм", "sans");
  assert.ok(pretext.naturalWidth(prepared) > 0);
  assert.equal(pretext.lineCount(prepared, 10_000), 1);
  assert.equal(pretext.lineCount(pretext.prepare("", "sans"), 100), 1);

  // Шрифт доходит до canvas: mono меряется моноширинной таблицей.
  const mono = pretext.prepare("AAAAA", "mono");
  assert.ok(Math.abs(pretext.naturalWidth(mono) - 5 * 6.6) < 0.001);
  const sans = pretext.prepare("AAAAA", "sans");
  assert.notEqual(pretext.naturalWidth(sans), pretext.naturalWidth(mono));
});

test("pretext и greedy согласны на синтетике без переносов по дефису", async () => {
  const greedy = createSyntheticMeasurer("greedy");
  const pretext = await createMeasurer("pretext");
  const columns = buildColumns(6);
  const widths = [90, 120, 180, 240];
  let compared = 0;

  for (const profile of ["realistic", "all-short", "outlier"]) {
    const sheet = generateSheet({ profile, rows: 60, columns, seed: 11 });
    for (const column of columns) {
      if (!column.wrap) continue;
      for (const row of sheet.rows) {
        const text = String(row.values[column.id] ?? "");
        // Дефис и soft hyphen — место, где pretext переносит, а greedy нет;
        // это отдельная граница модели, ниже.
        if (/[-\u00ad/]/.test(text)) continue;
        const a = greedy.prepare(text, column.font);
        const b = pretext.prepare(text, column.font);
        const floor = Math.max(greedy.maxWordWidth(a), pretext.maxWordWidth(b)) + 1;
        for (const width of widths) {
          if (width < floor) continue;
          assert.equal(
            pretext.lineCount(b, width),
            greedy.lineCount(a, width),
            `${profile}: "${text}" @ ${width}px`,
          );
          compared += 1;
        }
      }
    }
  }

  assert.ok(compared > 100, `сравнений достаточно: ${compared}`);
});

test("граница модели: pretext переносит по дефису, greedy — нет", async () => {
  const text = "порог AL-6060 КР-01";
  const greedy = createSyntheticMeasurer("greedy");
  const pretext = await createMeasurer("pretext");
  const a = greedy.prepare(text, "sans");
  const b = pretext.prepare(text, "sans");
  assert.ok(pretext.lineCount(b, 60) < greedy.lineCount(a, 60));
  assert.ok(greedy.maxWordWidth(a) > pretext.maxWordWidth(b));
});
