/**
 * Мобильный ярус E2E (#342): что именно он прогоняет и что об этом пишет.
 *
 * Зачем тест на «строчку отчёта». Ярус `mobile` — единственный, который
 * отличается от остальных не набором спеков, а **окном браузера**, и по
 * выводу прогона это не видно: `=== ярус mobile: Ns, код 0 ===` одинаков для
 * любого viewport. Поэтому прогон обязан назвать окно сам, а цифры в отчёте —
 * брать из того же объекта, который уходит в проект Playwright. Разошедшиеся
 * копии дали бы отчёт «390×844» при проекте 1280×720, то есть зелёный
 * прогон, доказывающий не то, что заявлено в тикете.
 *
 * `mobile-project.mjs` вынесен из `run-tier.mjs` ровно ради этих тестов: сам
 * скрипт — точка входа прогона, его импорт запускает стенд (как
 * `run-workers.mjs`, см. `run-workers.test.ts`).
 */
import { describe, expect, it } from "vitest";

import {
  MOBILE_PROJECT,
  MOBILE_TAG,
  MOBILE_USE,
  formatMobileReport,
  selectMobileSpecs,
} from "./mobile-project.mjs";

/** Спеки мобильного яруса, как их видит каталог `e2e/`. */
const MOBILE_SPEC_FILES = ["mobile-sections.spec.ts", "mobile-transfers.spec.ts"];

describe("selectMobileSpecs — состав мобильного яруса", () => {
  it("берёт ровно спеки с тегом @mobile, по алфавиту", () => {
    expect(
      selectMobileSpecs([
        { file: "final-release.spec.ts", content: 'test.describe("@smoke Финальный выпуск", …' },
        { file: "mobile-transfers.spec.ts", content: 'test.describe("@mobile Передачи", …' },
        { file: "mobile-sections.spec.ts", content: 'test.describe("@mobile Участки", …' },
      ]),
    ).toEqual(MOBILE_SPEC_FILES);
  });

  it("тег ищется как тег, а не как подстрока чужого слова", () => {
    // `@mobile-smoke` — другой ярус; совпадение по префиксу утащило бы его сюда.
    expect(
      selectMobileSpecs([{ file: "other.spec.ts", content: "test.describe(\"@mobile-smoke\", …" }]),
    ).toEqual([]);
  });

  it("файл без тега в ярус не попадает", () => {
    expect(
      selectMobileSpecs([{ file: "full-cycle.spec.ts", content: 'test.describe("@ui Полный цикл", …' }]),
    ).toEqual([]);
  });
});

describe("formatMobileReport — что видно в отчёте прогона", () => {
  it("называет окно телефона, touch и список @mobile-спеков", () => {
    const text = formatMobileReport(MOBILE_SPEC_FILES).join("\n");
    expect(text).toContain("390×844");
    expect(text).toContain("isMobile=true");
    expect(text).toContain("hasTouch=true");
    expect(text).toContain("deviceScaleFactor=2");
    expect(text).toContain("mobile-sections.spec.ts");
    expect(text).toContain("mobile-transfers.spec.ts");
    expect(text).toContain(MOBILE_PROJECT);
  });

  it("пустой набор спеков называет пустоту прямо, а не молчит", () => {
    // Пустой список — это не «всё хорошо»: прогон отработает вхолостую и
    // покажет зелёный код. Отчёт обязан это сказать.
    const text = formatMobileReport([]).join("\n");
    expect(text).toContain(MOBILE_PROJECT);
    expect(text).toMatch(/нет/i);
  });
});

describe("MOBILE_USE — цифры тикета #342", () => {
  it("окно 390×844, мобильный браузер с touch и DPR 2", () => {
    expect(MOBILE_USE).toEqual({
      viewport: { width: 390, height: 844 },
      isMobile: true,
      hasTouch: true,
      deviceScaleFactor: 2,
    });
    expect(MOBILE_TAG).toBe("@mobile");
  });
});
