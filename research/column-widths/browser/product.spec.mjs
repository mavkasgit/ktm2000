/**
 * H4 на фактическом CSS продукта (#483): вес 500, `leading-snug` 15.125 px,
 * системный стек Tailwind v4. Проверяет, что модель `lines × lineHeight` и
 * натуральная ширина слова сходятся с DOM — без этого предсказанная высота
 * строки для виртуализатора была бы вымыслом.
 */
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test } from "@playwright/test";

const here = path.dirname(fileURLToPath(import.meta.url));
const resultsPath = path.resolve(here, "../results/product.json");

const PERCENT = (value) => `${(value * 100).toFixed(2)}%`;

test("pretext сходится с CSS продукта: перенос обеих текстовых колонок", async ({ page }) => {
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(String(error)));

  await page.goto("/product.html");
  await page.waitForFunction(() => window.__ready === true, null, { timeout: 60_000 });

  const result = await page.evaluate(() => window.runProductValidation());
  expect(pageErrors).toEqual([]);

  mkdirSync(path.dirname(resultsPath), { recursive: true });
  writeFileSync(resultsPath, `${JSON.stringify(result, null, 2)}\n`, "utf8");

  const { h4, meta, byProfile } = result;
  const lines = [
    `CSS name: ${meta.columns.name.weight} ${meta.columns.name.sizePx}px, line-height ${meta.columns.name.lineHeightPx}px`,
    `CSS errors: ${meta.columns.errors.weight} ${meta.columns.errors.sizePx}px, line-height ${meta.columns.errors.lineHeightPx}px`,
    `H4: ${PERCENT(h4.lineMismatchRate)} по строкам, ${PERCENT(h4.heightMismatchRate)} по высоте (порог ${PERCENT(h4.threshold)})`,
    `  наименование: ${PERCENT(h4.byColumn.name.lineMismatchRate)} (${h4.byColumn.name.cells} ячеек)`,
    `  ошибки: ${PERCENT(h4.byColumn.errors.lineMismatchRate)} (${h4.byColumn.errors.cells} ячеек)`,
    `макс. Δстрок ${h4.maxLineDelta}, макс. Δвысоты ${h4.maxAbsHeightDelta} px`,
  ];
  for (const [profile, stats] of Object.entries(byProfile)) {
    lines.push(
      `  ${profile}: ${PERCENT(stats.lineMismatchRate)} строк, ${PERCENT(stats.heightMismatchRate)} высота (${stats.cells} строк)`,
    );
  }
  console.log(lines.join("\n"));

  expect(meta.columns.name.weight, "вес «Наименования» — 400").toBe(400);
  expect(meta.columns.errors.weight, "вес «Ошибок» — 500").toBe(500);
  expect(meta.columns.errors.lineHeightPx, "leading-snug = 1.375 × 11px").toBeCloseTo(15.125, 3);
  expect(meta.columns.name.lineHeightPx, "line-height «Наименования» — 16.5 px").toBeCloseTo(16.5, 3);
  expect(meta.devicePixelRatio, "DPR = 1").toBe(1);
  expect(h4.widthMismatch, "table-fixed даёт ровно заданную ширину контента").toBe(0);
  expect(h4.cells, "выборка не пустая").toBeGreaterThan(500);
  expect(h4.lineMismatchRate, "H4: строки").toBeLessThan(h4.threshold);
  expect(h4.heightMismatchRate, "H4: высота").toBeLessThan(h4.threshold);
});
