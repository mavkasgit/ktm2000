/**
 * Рантайм-замер ширины колонок (#483): `prepare` + `buildCostModel` +
 * `search` на 500 строках × 11 колонках, CPU throttling 4× через CDP.
 *
 * Спека не падает на «медленном» результате: порог §15 — это решение
 * (#485), а не свойство прогона. Она падает на сломанном замере (шрифт не
 * загружен, DPR ≠ 1, выборка пустая), а вердикт печатает и кладёт в JSON.
 */
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test } from "@playwright/test";

const here = path.dirname(fileURLToPath(import.meta.url));

/**
 * Потолок из spec §15 — 4×. Переопределяется только для диагностики:
 * `KTM_RUNTIME_THROTTLE=1` показывает, сколько стоит замер без симуляции
 * слабого CPU; вердикт по порогу всегда считается на 4×.
 */
const THROTTLING = Number(process.env.KTM_RUNTIME_THROTTLE ?? 4);
const resultsPath = path.resolve(
  here,
  THROTTLING === 4 ? "../results/runtime.json" : `../results/runtime-throttle-${THROTTLING}x.json`,
);

test("prepare + search укладываются в порог §15 (CPU 4×)", async ({ page }) => {
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(String(error)));

  // Throttling ставится до навигации, чтобы и первый (холодный) прогон шёл
  // на тех же условиях, что и продуктовый: слабый CPU, не машина агента.
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: THROTTLING });

  await page.goto("/runtime.html");
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

  const result = await page.evaluate(() => window.runRuntimeBenchmark());
  expect(pageErrors).toEqual([]);

  mkdirSync(path.dirname(resultsPath), { recursive: true });
  writeFileSync(resultsPath, `${JSON.stringify(result, null, 2)}\n`, "utf8");

  const { meta, overall, cold, threshold, configs } = result;
  const line = (label, summary) =>
    `${label}: медиана ${summary.median} мс, p95 ${summary.p95} мс, max ${summary.max} мс`;
  const lines = [
    `seed=${meta.seed} rows=${meta.rows} cols=${meta.columnCount} reps=${meta.reps} CPU=${meta.cpuThrottling}× DPR=${meta.devicePixelRatio}`,
    line("prepare", overall.prepare),
    line("search (включая buildCostModel)", overall.search),
    line("итого", overall.total),
    `холодный прогон (${cold.profile} @ ${cold.tableWidth}): ${cold.totalMs} мс`,
    `порог ${threshold.ms} мс: ${threshold.pass ? "PASS" : "FAIL"} (p95 ${threshold.maxP95TotalMs} мс, cold ${threshold.coldTotalMs} мс)`,
    "по конфигурациям:",
  ];
  for (const config of configs) {
    lines.push(
      `  ${config.profile} @ ${config.tableWidth}: prepare ${config.summary.prepare.median} / ` +
        `search ${config.summary.search.median} / итого ${config.summary.total.median} мс (p95 ${config.summary.total.p95})`,
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
  expect(overall.total.count, "повторы не потерялись").toBe(
    configs.length * meta.reps,
  );
  expect(overall.total.median, "замер не должен быть нулевым").toBeGreaterThan(0);

  // Нарушения `minPx` — не «медленно», а сломанная модель: такую раскладку
  // нельзя применять. Честное переполнение бюджета допустимо и остаётся в JSON.
  for (const config of configs) {
    expect(
      config.result.sanity.belowMin,
      `${config.profile} @ ${config.tableWidth}: minPx колонок не нарушен`,
    ).toEqual([]);
  }
});
