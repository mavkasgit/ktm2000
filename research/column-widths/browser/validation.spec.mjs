/**
 * H4: предсказание `pretext` против реального DOM.
 *
 * Спека живёт в research-песочнице (не в `frontend/e2e/`): ей не нужен
 * backend, база и общий стенд. Playwright поднимает Vite на свободном порту,
 * страница меряет те же строки дважды — моделью и браузером.
 */
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test } from "@playwright/test";

const here = path.dirname(fileURLToPath(import.meta.url));
const resultsPath = path.resolve(here, "../results/browser.json");

const PERCENT = (value) => `${(value * 100).toFixed(2)}%`;

test("pretext lineCount и высота совпадают с DOM (H4)", async ({ page }) => {
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(String(error)));

  await page.goto("/");
  await page.waitForFunction(() => window.__ready === true || window.__fontError, null, {
    timeout: 60_000,
  });

  const fontError = await page.evaluate(() => window.__fontError);
  expect(fontError, "webfont должен загрузиться до prepare()").toBeUndefined();

  const result = await page.evaluate(() => window.runBrowserValidation());
  expect(pageErrors).toEqual([]);

  mkdirSync(path.dirname(resultsPath), { recursive: true });
  writeFileSync(resultsPath, `${JSON.stringify(result, null, 2)}\n`, "utf8");

  const { h4, product, meta } = result;
  const lines = [
    `seed=${meta.seed} rows=${meta.rowsPerProfile} font=${meta.fontPx}px`,
    `H4: ${PERCENT(h4.lineMismatchRate)} по строкам, ${PERCENT(h4.heightMismatchRate)} по высоте (порог ${PERCENT(h4.threshold)})`,
    `word-fit: ${PERCENT(h4.wordFitLineMismatchRate)} (${h4.wordFitCells} ячеек)`,
    `ниже maxWordWidth: ${PERCENT(h4.belowWordWidthLineMismatchRate)} (${h4.belowWordWidthCells} ячеек)`,
    `ширина ячейки разошлась: ${product.widthMismatch} из ${product.cells}`,
    "по профилям:",
  ];
  for (const [profile, stats] of Object.entries(result.byProfile)) {
    lines.push(
      `  ${profile}: ${PERCENT(stats.product.lineMismatchRate)} строк, ` +
        `${PERCENT(stats.product.heightMismatchRate)} высота, ` +
        `word-fit ${PERCENT(stats.product.wordFitMismatchRate)}`,
    );
  }
  console.log(lines.join("\n"));

  expect(meta.fonts.sans.loaded, "Inter загружен").toBe(true);
  expect(meta.fonts.mono.loaded, "JetBrains Mono загружен").toBe(true);
  expect(product.widthMismatch, "table-fixed даёт ровно заданную ширину контента").toBe(0);
  expect(product.nonEmpty, "выборка не должна быть пустой").toBeGreaterThan(1000);

  expect(h4.lineMismatchRate, "H4: строки").toBeLessThan(h4.threshold);
  expect(h4.heightMismatchRate, "H4: высота").toBeLessThan(h4.threshold);
});
