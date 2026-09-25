import { test, expect } from "./fixtures";
import type { Locator, Page } from "@playwright/test";
import {
  apiAddRemainder,
  apiApplyChangeSet,
  apiEnsureCatalogProduct,
  apiGetActiveTemplate,
  apiGetProductBySku,
  apiGetSectionByCode,
  apiResetAll,
  apiSimulatePlanImport,
} from "./api-helpers";
import {
  SAW4_SKU,
  approvePositionViaUI,
  completeAllSectionTasksViaUI,
  expandBoardGroupsViaUI,
  expectShippedViaUI,
  findApprovablePositionViaUI,
  seedReferenceDataViaUI,
  sendReadyTransfersViaUI,
  takeToWorkViaUI,
  waitForPlanningTableViaUI,
  type ApprovablePosition,
} from "./ui-helpers";

/**
 * @ui — Пила внутри ПОЛНОГО цикла: раскрой сырья 2,7 м на ЧЕТЫРЕ длины.
 *
 * Сетап — бесфайловый (API, xlsx-фикстуры не храним):
 *  - каталог ЮП-2083: нормальная длина 2700 мм, сырьевая длина 2750 мм
 *    используется только для расчёта количества на подвес (ADR-0024);
 *  - остаток: 700 заготовок 2,7 м на «Склад сырья». Потребность по входам —
 *    400 (150 + 50 + 150 + 50), сумма штук ГП по позициям — 650
 *    (250 + 50 + 300 + 50): запас покрывает оба чтения плана. Все количества
 *    кратны норме подвеса (50): вход P1 — 3 подвеса, его выходы — 5. До пилы
 *    материал считается в штуках входа (заготовки нормальной длины) — длины
 *    появляются только на пиле (ADR-0002);
 *  - план (`/imports/excel/simulate`) — четыре позиции артикула:
 *      P1 ГП: вход 150 × 2,7 м → 0,9 × 50 + 1,35 × 100 + 1,8 × 50 + 2,7 × 50
 *             (вход 3 подвеса, выходы 5 подвесов = 250 шт; импорт количество
 *             не подтягивает; баланс группы:
 *             150 × 2700 = 50×900 + 100×1350 + 50×1800 + 50×2700;
 *             схемы раскроя без отхода: 50 → 1,8 + 0,9; 50 → 1,35 + 1,35;
 *             50 → 2,7 целиком);
 *      P2 П/ф: 2,7 м × 50 — пила исключена из маршрута (`pack_spunbond_branch`);
 *      P3 ГП: 150 × 2,7 м → 1,35 × 300 — одиночный выход раскроя;
 *      P4 ГП: 50 × 2,7 м → 2,7 × 50 — только торцевание, длина входа = ГП.
 *
 * Проверяется весь старый цикл (каталог → остатки → план → approve → запуск →
 * маршрут → отгрузка) с дополнением по пиле: сводка трансформации в четырёх
 * длинах, две порции факта с промежуточным и полным прогрессом по каждой длине.
 *
 * Все бизнес-шаги — из UI.
 *
 * Требует запущенного dev-окружения: `npm run dev` из корня проекта.
 */

const SAW_SECTION_NAME = "Пила";
/** Вход позиции-раскроя: 150 заготовок нормальной длины 2,7 м. */
const INPUT_QTY = 150;
const INPUT_LENGTH_MM = 2700;
/** Сырьевая длина нужна только для расчёта количества на подвесе. */
const RAW_LENGTH_MM = 2750;
const OUTPUTS = [
  { mm: 900, total: 50 },
  { mm: 1350, total: 100 },
  { mm: 1800, total: 50 },
  { mm: 2700, total: 50 },
] as const;
/** Порции ввода факта на пиле: 75 + 75 заготовок (ровно половина входа). */
const PORTIONS = [75, 75] as const;
const POSITIONS = 4;
const PACK_GP =
  "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*30 на пачку из 10 шт";
const PACK_SPUN = "смотка спанбондом поштучно в пачке 10 штук";

/** Метка длины как в UI: мм → «1,35 м». */
function lengthLabel(mm: number): string {
  return `${String(mm / 1000).replace(".", ",")} м`;
}

/** Компактная подпись выхода в CutLayoutCell: «0,9×50». */
function cutOutputLabel(mm: number, total: number): string {
  return `${String(mm / 1000).replace(".", ",")}×${total}`;
}

/** Строка P1 на пиле: после первой порции cut_layout может исчезнуть из DOM. */
function splitTaskRow(page: Page): Locator {
  return page
    .locator("tr")
    .filter({ hasText: "250" })
    .filter({ hasText: "150" })
    .first();
}


/**
 * Дождаться строк доски участка.
 *
 * Доска грузится асинхронно (react-query), причём таблица рендерится раньше
 * данных: `tbody tr` появляется примерно на 0,4 с ещё пустым, а строка задачи
 * или группа — только на ~0,7 с. Раскрытие до этого момента кликать не по чему,
 * и задача-раскрой навсегда остаётся скрытой в свёрнутой группе (`saw=false` во
 * всех раундах маршрута).
 */
async function waitForBoardRows(page: Page): Promise<void> {
  await page
    .locator(
      'tbody tr:has(button[title="Раскрыть"]), tbody tr:has(button:has-text("Завершить"))',
    )
    .first()
    .waitFor({ state: "visible", timeout: 10_000 })
    .catch(() => {});
}

/** Открыть доску участка «Пила» плиткой (UI-only) и вернуть id из URL. */
async function openSawBoard(page: Page): Promise<number> {
  await page.goto("/section-tasks");
  await expect(page.getByRole("heading", { name: "Участки" })).toBeVisible({ timeout: 10_000 });
  const tile = page
    .getByRole("button")
    .filter({ hasText: /ОЖ:|ВР:/ })
    .filter({ hasText: SAW_SECTION_NAME })
    .first();
  await expect(tile).toBeVisible({ timeout: 20_000 });
  await tile.click();
  await expect(page).toHaveURL(/\/section-tasks\/\d+/, { timeout: 15_000 });
  const sectionId = Number(page.url().match(/\/section-tasks\/(\d+)/)?.[1] ?? 0);
  expect(sectionId, "id участка пилы не читается из URL").toBeGreaterThan(0);
  return sectionId;
}

/** Прогресс по выходам на доске: текст строки «0,9 м: 40/40 · …». */
async function outputsProgressText(page: Page): Promise<string> {
  const progress = splitTaskRow(page)
    .locator("span")
    .filter({ hasText: /\d+\s*м:\s*\d+\/\d+/ })
    .first();
  await expect(progress).toBeVisible({ timeout: 20_000 });
  return (await progress.textContent()) ?? "";
}

/**
 * Раскроить позицию P1 порциями через доску пилы.
 *
 * Возвращает `false`, когда резать нечего (материал ещё не доехал или задача
 * уже закрыта) — вызывающий повторит в следующем раунде маршрута.
 */
async function splitSawIntoLengthsViaUI(page: Page, sectionId: number): Promise<boolean> {
  await page.goto(`/section-tasks/${sectionId}`);
  await waitForBoardRows(page);
  // Доска прячет однотипные задачи в свёрнутую группу — раскрываем её.
  await expandBoardGroupsViaUI(page);

  // Задача-раскрой ещё не появилась/не раскрылась — вернёмся в следующем раунде.
  const row = splitTaskRow(page);
  const present = await row
    .waitFor({ state: "visible", timeout: 15_000 })
    .then(() => true, () => false);
  if (!present) {
    const texts = await page.locator("tr").allInnerTexts().catch(() => []);
    console.log(
      `[saw] строка раскроя не найдена (ждём «${INPUT_QTY} шт × ${lengthLabel(INPUT_LENGTH_MM)}»); ` +
        `строк на доске: ${texts.length} → ${texts.map((t) => t.replace(/\s+/g, " ").trim()).filter(Boolean).slice(0, 6).join(" | ")}`,
    );
    return false;
  }

  // На доске вход отображается как нормальная длина 2,7 м; сырьевая 2,75 м
  // используется backend только при расчёте количества на подвес.
  await expect(row).toContainText(lengthLabel(INPUT_LENGTH_MM));
  for (const out of OUTPUTS) {
    await expect(row).toContainText(cutOutputLabel(out.mm, out.total));
  }

  const completeBtn = () => splitTaskRow(page).getByRole("button", { name: "Завершить" }).first();
  if (!(await completeBtn().isVisible().catch(() => false))) return false;
  if (!(await completeBtn().isEnabled().catch(() => false))) return false;

  let consumed = 0;
  for (let index = 0; index < PORTIONS.length; index++) {
    await completeBtn().click();
    const drawer = page.getByRole("dialog");
    await expect(drawer).toBeVisible({ timeout: 5_000 });
    // Подписи диалога факта: «Вход: 150 × 2,7 м», «Раскроено: 0», «Осталось: 150».
    const header = (await drawer.textContent()) ?? "";
    const issued = Number(header.match(/Вход:\s*(\d+)/)?.[1] ?? 0);
    const alreadyCut = Number(header.match(/Раскроено:\s*(\d+)/)?.[1] ?? 0);
    const remaining = Math.max(issued - alreadyCut, 0);
    const portion = Math.min(PORTIONS[index], remaining);
    if (portion <= 0) {
      await drawer.getByRole("button", { name: "Отмена" }).click();
      await expect(drawer).not.toBeVisible({ timeout: 10_000 });
      return false;
    }

    await drawer.locator('input[type="number"]').first().fill(String(portion));
    await drawer.getByRole("button", { name: "Сохранить" }).click();
    await expect(drawer).not.toBeVisible({ timeout: 15_000 });

    consumed += portion;

    // Доска не рефетчится после мутации — перезагружаем страницу участка.
    await page.goto(`/section-tasks/${sectionId}`);
    await waitForBoardRows(page);
    await expandBoardGroupsViaUI(page);

    // Кумулятивная пропорция бэкенда: target_i = total_i × раскроено / вход.
    const progress = await outputsProgressText(page);
    for (const out of OUTPUTS) {
      const produced = Math.round((out.total * consumed) / INPUT_QTY);
      await expect(
        progress,
        `после ${consumed} заготовок выход ${lengthLabel(out.mm)}: ${produced}/${out.total}`,
      ).toContain(`${lengthLabel(out.mm)}: ${produced}/${out.total}`);
    }
  }

  console.log(
    `[saw] раскроено ${consumed} заготовок ${lengthLabel(INPUT_LENGTH_MM)} → ` +
      OUTPUTS.map((out) => `${out.total} × ${lengthLabel(out.mm)}`).join(" + "),
  );
  return true;
}

test.describe("@ui Пила: раскрой 2,75 м на четыре длины в полном цикле", () => {
  test.beforeEach(async ({ page, loginAsAdmin }) => {
    await loginAsAdmin();
    // `reset-all` — системный сброс: он чистит и справочники импорта
    // (TRUNCATE ... import_templates), поэтому порядок обязателен — сначала
    // сброс, потом сид справочников, иначе визард плана останется без шаблона.
    await apiResetAll();
    await seedReferenceDataViaUI(page);
  });

  test("каталог → остатки → план → approve → запуск → маршрут с пилой → отгрузка", async ({
    page,
  }) => {
    // Сид + импорт + маршрут четырёх позиций не укладываются в 120с проекта.
    test.setTimeout(900_000);

    // DEBUG (временно): тела неуспешных ответов бизнес-API.
    page.on("response", async (response) => {
      if (response.status() < 400 || !response.url().includes("/api/")) return;
      const body = await response.text().catch(() => "");
      console.log(
        `[api ${response.status()}] ${response.request().method()} ${response.url()} → ${body.slice(0, 1000)}`,
      );
    });

    // ── ШАГ 1. Каталог: нормальная длина 2700 мм, сырьевая 2750 мм ───────
    await apiEnsureCatalogProduct({
      sku: SAW4_SKU,
      name: "Стык 38мм",
      lengthsMm: [INPUT_LENGTH_MM],
      rawLengthMm: RAW_LENGTH_MM,
      perimeterMm: 81.5,
      mountWidthMm: 36.9,
      quantityPerHanger: 50,
    });
    const product = await apiGetProductBySku(SAW4_SKU);
    console.log("[step1] каталог готов");

    // ── ШАГ 2. Остатки: 700 заготовок 2,75 м на «Склад сырья» ──────────────
    const rawStock = await apiGetSectionByCode("RAW_STOCK");
    await apiAddRemainder(product.id, rawStock.id, 700, "E2E остаток сырья 2750 мм", {
      length_mm: INPUT_LENGTH_MM,
    });
    console.log("[step2] остатки готовы");

    // ── ШАГ 3. План из четырёх позиций артикула ────────────────────────────
    const template = await apiGetActiveTemplate();
    const importRes = await apiSimulatePlanImport(
      [
        // P1 ГП: группа раскроя 150 × 2,7 м → 0,9 + 1,35 + 1,8 + 2,7 м
        {
          sku: SAW4_SKU,
          name: "Стык 38 мм 2,7 анод.серебро, матовый",
          raw_stock: 2958,
          color: "серебро",
          qty_per_27: INPUT_QTY,
          length_m: 2.7,
          packaging: PACK_GP,
          output_length_m: 0.9,
          output_qty: 50,
          west: 50,
          east: 0,
          kind: "ГП",
        },
        {
          sku: SAW4_SKU,
          color: "серебро",
          packaging: PACK_GP,
          output_length_m: 1.35,
          output_qty: 100,
          west: 100,
          east: 0,
          kind: "ГП",
        },
        {
          sku: SAW4_SKU,
          color: "серебро",
          packaging: PACK_GP,
          output_length_m: 1.8,
          output_qty: 50,
          west: 50,
          east: 0,
          kind: "ГП",
        },
        {
          sku: SAW4_SKU,
          color: "серебро",
          packaging: PACK_GP,
          output_length_m: 2.7,
          output_qty: 50,
          west: 50,
          east: 0,
          kind: "ГП",
        },
        // P2 П/ф: 2,7 м × 50 — пила исключена из маршрута
        {
          sku: SAW4_SKU,
          name: "Стык 38 мм 2,7 анод.серебро, матовый",
          raw_stock: 2958,
          color: "серебро",
          qty_per_27: 50,
          length_m: 2.7,
          packaging: PACK_SPUN,
          output_length_m: 2.7,
          output_qty: 50,
          west: null,
          east: 50,
          kind: "П/ф",
        },
        // P3 ГП: 150 × 2,7 м → 1,35 × 300 (одиночный выход раскроя, «сверло»)
        {
          sku: SAW4_SKU,
          name: "Стык 38 мм 2,7 анод.серебро, матовый",
          raw_stock: 2958,
          color: "серебро",
          qty_per_27: INPUT_QTY,
          length_m: 2.7,
          operation: "сверло",
          packaging: PACK_GP,
          output_length_m: 1.35,
          output_qty: 300,
          west: 300,
          east: 0,
          kind: "ГП",
        },
        // P4 ГП: 50 × 2,7 м → 2,7 × 50 (только торцевание)
        {
          sku: SAW4_SKU,
          name: "Стык 38 мм 2,7 анод.серебро, матовый",
          raw_stock: 2958,
          color: "серебро",
          qty_per_27: 50,
          length_m: 2.7,
          packaging: PACK_GP,
          output_length_m: 2.7,
          output_qty: 50,
          west: 50,
          east: 0,
          kind: "ГП",
        },
      ],
      { templateId: template.id },
    );
    await apiApplyChangeSet(importRes.production_plan_id, importRes.change_set_id);

    await page.goto("/planning");
    await expect(page.getByRole("heading", { name: "План", exact: true })).toBeVisible({
      timeout: 10_000,
    });
    await waitForPlanningTableViaUI(page);
    console.log("[step3] план импортирован");

    // ── ШАГ 4. Утверждение всех четырёх позиций ────────────────────────────
    const positions: ApprovablePosition[] = [];
    for (let attempt = 0; attempt < POSITIONS; attempt++) {
      const position = await findApprovablePositionViaUI(page);
      if (!position) break;
      expect(position.sku, "в плане неожиданный артикул").toContain(SAW4_SKU);
      await approvePositionViaUI(page, position);
      positions.push(position);
      console.log(`[step4] позиция #${position.id} утверждена`);
    }
    expect(positions.length, "утверждены не все позиции плана").toBe(POSITIONS);

    // ── ШАГ 5. Запуск в работу ─────────────────────────────────────────────
    for (const position of positions) {
      await takeToWorkViaUI(page, position);
      console.log(`[step5] позиция #${position.id} запущена`);
    }

    // ── ШАГ 6. Маршрут: раскрой на пиле порциями + остальные участки ───────
    const sawSectionId = await openSawBoard(page);
    let sawSplitDone = false;
    for (let round = 0; round < 40; round++) {
      console.log("[DEBUG] остановка перед передачами; продолжайте вручную в Playwright Inspector");
      await page.pause();
      const sent = await sendReadyTransfersViaUI(page, SAW4_SKU);
      // Пила — строго до общего завершения задач: иначе П1 уйдёт полной порцией.
      if (!sawSplitDone) {
        sawSplitDone = await splitSawIntoLengthsViaUI(page, sawSectionId);
      }
      // Маршрут назначает система — участки не перечисляем, обходим доски как есть.
      const completed = await completeAllSectionTasksViaUI(page, SAW4_SKU);
      console.log(`[step6] раунд ${round}: sent=${sent} completed=${completed} saw=${sawSplitDone}`);
      if (sent === 0 && completed === 0 && sawSplitDone) break;
    }
    expect(sawSplitDone, "раскрой четырёх длин на пиле не выполнен").toBe(true);
    console.log("[step6] маршрут пройден");

    // ── ШАГ 7. Все четыре позиции доехали до «Отправлено» ──────────────────
    await expectShippedViaUI(
      page,
      SAW4_SKU,
      positions.map((position) => position.id),
    );
    console.log("[step7] отгрузка подтверждена");
  });
});
