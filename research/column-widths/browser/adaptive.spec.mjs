/**
 * Гейт §15 для адаптивной политики (#489): продуктовая
 * `computePreviewColumnWidths` на 300 строках × 11 колонках при CPU 4×
 * укладывается в 100 мс по медиане, а выбранная политика совпадает с правилом
 * θ = 0.05 при обеих посчитанных высотах.
 *
 * Порог здесь — **проверка**, а не наблюдение: решение «считать обе раскладки»
 * (#489) включается только если цена в рантайме не выросла за гейт. Если
 * прогон краснеет, тикет требует не «поднять порог», а упростить `H_trunc`
 * (усечение = одна строка, ширина известна) и зафиксировать это в спеке.
 *
 * Структурные проверки (шрифты, DPR, троттлинг, число конфигураций) — как в
 * `runtime.spec.mjs`: иначе «быстро» может означать «мерили не то».
 */
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test } from "@playwright/test";

import { buildProductBundle } from "../lib/product-bundle.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));

const THROTTLING = Number(process.env.KTM_RUNTIME_THROTTLE ?? 4);
const resultsPath = path.resolve(
  here,
  THROTTLING === 4 ? "../results/adaptive-runtime.json" : `../results/adaptive-runtime-${THROTTLING}x.json`,
);

test.beforeAll(async () => {
  // Продуктовый модуль собирается до навигации: страница импортирует его
  // относительным путём из `browser/.product-build`.
  await buildProductBundle();
});

test("адаптивная политика укладывается в §15 и выбирает по θ (CPU 4×)", async ({
  page,
}) => {
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(String(error)));
  page.on("console", (message) => {
    if (message.type() === "error") pageErrors.push(message.text());
  });

  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: THROTTLING });

  await page.goto("/adaptive.html");
  await page.evaluate((rate) => {
    window.__throttleRate = rate;
  }, THROTTLING);
  await page.waitForFunction(
    () => window.__ready === true || window.__fontError,
    null,
    { timeout: 60_000 },
  );

  const fontError = await page.evaluate(() => window.__fontError);
  expect(fontError, "webfont должен загрузиться до prepare()").toBeUndefined();

  const result = await page.evaluate(() => window.runAdaptiveBenchmark());
  const bundleError = await page.evaluate(() => window.__bundleError);
  expect(bundleError, "продуктовый бандл собран").toBeUndefined();
  expect(pageErrors).toEqual([]);

  mkdirSync(path.dirname(resultsPath), { recursive: true });
  writeFileSync(resultsPath, `${JSON.stringify(result, null, 2)}\n`, "utf8");

  const { meta, overall, cold, threshold, configs } = result;
  const lines = [
    `seed=${meta.seed} rows=${meta.rows} cols=${meta.columnCount} reps=${meta.reps} CPU=${meta.cpuThrottling}× DPR=${meta.devicePixelRatio}`,
    `total: медиана ${overall.total.median} мс, p95 ${overall.total.p95} мс, max ${overall.total.max} мс`,
    `проверка H_trunc отдельно: медиана ${overall.baselinePass.median} мс, p95 ${overall.baselinePass.p95} мс`,
    `холодный прогон (${cold.profile} @ ${cold.tableWidth}): ${cold.totalMs} мс`,
    `порог ${threshold.ms} мс по медиане: ${threshold.pass ? "PASS" : "FAIL"} (медиана ${threshold.medianTotalMs} мс, p95 ${threshold.p95TotalMs} мс, cold ${threshold.coldTotalMs} мс)`,
  ];
  for (const config of configs) {
    lines.push(
      `  ${config.profile} @ ${config.tableWidth}: ${config.summary.median} мс (p95 ${config.summary.p95}), ` +
        `H_trunc ${config.baselinePassMs} мс, policy=${config.result.policy}, ` +
        `Δ=${config.result.heightDeltaPct}% (H_full ${config.result.fullTextHeightPx} / H_trunc ${config.result.baselineHeightPx})`,
    );
  }
  console.log(lines.join("\n"));

  expect(meta.fonts.sans.loaded, "Inter загружен").toBe(true);
  expect(meta.fonts.mono.loaded, "JetBrains Mono загружен").toBe(true);
  expect(meta.devicePixelRatio, "DPR = 1: иначе px модели и CSS расходятся").toBe(1);
  expect(meta.cpuThrottling, "CPU throttling включён").toBe(THROTTLING);
  expect(configs.length, "все конфигурации промерены").toBe(
    meta.profiles.length * meta.widths.length,
  );
  expect(overall.total.count, "повторы не потерялись").toBe(configs.length * meta.reps);
  expect(overall.total.median, "замер не должен быть нулевым").toBeGreaterThan(0);

  for (const config of configs) {
    expect(
      config.result.ruleSatisfied,
      `${config.profile} @ ${config.tableWidth}: политика должна совпадать с правилом θ`,
    ).toBe(true);
    // Дорогой хвост — это и есть ветка `baseline`: если long-tail стал
    // `full-text`, правило (или модель высоты) сломано, а не «стало быстрее».
    if (config.profile === "long-tail") {
      expect(config.result.policy, "long-tail обязан уходить в baseline").toBe(
        "baseline",
      );
    }
  }

  // Гейт §15: медиана ≤ 100 мс при CPU 4×.
  expect(threshold.pass, `медиана ${threshold.medianTotalMs} мс > ${threshold.ms} мс`).toBe(
    true,
  );
});
