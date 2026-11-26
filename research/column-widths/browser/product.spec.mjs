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

test("pretext сходится с CSS продукта: вес 500 и leading-snug", async ({ page }) => {
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
    `CSS: ${meta.fontWeight} ${meta.fontPx}px, line-height ${meta.lineHeight}px, min row ${meta.minRowHeightPx}px`,
    `шрифт: ${meta.fontFamily}`,
    `H4: ${PERCENT(h4.lineMismatchRate)} по строкам, ${PERCENT(h4.heightMismatchRate)} по высоте (порог ${PERCENT(h4.threshold)})`,
    `макс. Δстрок ${h4.maxLineDelta}, макс. Δвысоты ${h4.maxAbsHeightDelta} px`,
  ];
  for (const [profile, stats] of Object.entries(byProfile)) {
    lines.push(
      `  ${profile}: ${PERCENT(stats.lineMismatchRate)} строк, ${PERCENT(stats.heightMismatchRate)} высота (${stats.cells} ячеек)`,
    );
  }
  console.log(lines.join("\n"));

  expect(meta.fontWeight, "вес ячейки «Ошибок» — 500").toBe(500);
  expect(meta.lineHeight, "leading-snug = 1.375 × 11px").toBeCloseTo(15.125, 3);
  expect(meta.devicePixelRatio, "DPR = 1").toBe(1);
  expect(h4.widthMismatch, "table-fixed даёт ровно заданную ширину контента").toBe(0);
  expect(h4.cells, "выборка не пустая").toBeGreaterThan(500);
  expect(h4.lineMismatchRate, "H4: строки").toBeLessThan(h4.threshold);
  expect(h4.heightMismatchRate, "H4: высота").toBeLessThan(h4.threshold);
});
