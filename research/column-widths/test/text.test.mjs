import assert from "node:assert/strict";
import test from "node:test";

import {
  clampedLineCount,
  greedyLineCount,
  naturalWidth,
  prepareText,
} from "../lib/text.mjs";

test("ширина текста положительна и растёт с длиной", () => {
  assert.ok(naturalWidth("Плинтус", "sans") > 0);
  assert.ok(naturalWidth("Плинтус алюминиевый", "sans") > naturalWidth("Плинтус", "sans"));
  assert.ok(naturalWidth("ABCDEF", "mono") > naturalWidth("ABC", "mono"));
});

test("жадный перенос укладывает слова в строку", () => {
  const prepared = prepareText("Плинтус алюминиевый 40 мм");
  const oneLine = greedyLineCount(prepared, prepared.naturalWidth);
  assert.equal(oneLine, 1);

  const narrow = greedyLineCount(prepared, naturalWidth("Плинтус", "sans") + 20);
  assert.ok(narrow >= 2);
});

test("длинное слово без пробелов не рвётся, а занимает одну строку", () => {
  const prepared = prepareText("ALS-1234567890-XYZ", "mono");
  assert.equal(greedyLineCount(prepared, 20), 1);
});

test("пустой текст — одна строка", () => {
  assert.equal(greedyLineCount(prepareText(""), 100), 1);
});

test("clamp считает обрезанные строки", () => {
  const prepared = prepareText(
    "Строка 128: остаток меньше одной штуки, участок не найден, дубликат по артикулу и длине",
  );
  const result = clampedLineCount(prepared, 120, 2);
  assert.equal(result.lines, 2);
  assert.equal(result.truncated, true);

  const fits = clampedLineCount(prepared, prepared.naturalWidth, 2);
  assert.equal(fits.lines, 1);
  assert.equal(fits.truncated, false);
});
