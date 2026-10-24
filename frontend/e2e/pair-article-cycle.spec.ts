import { test, expect } from "./fixtures";
import {
  apiAddRemainder,
  apiApplyChangeSet,
  apiCreateProductPair,
  apiEnsureCatalogProduct,
  apiGetActiveTemplate,
  apiGetProductBySku,
  apiGetSectionByCode,
  apiResetAll,
  apiSimulatePlanImport,
} from "./api-helpers";
import {
  approvePositionViaUI,
  completeAllSectionTasksViaUI,
  expectShippedViaUI,
  findApprovablePositionViaUI,
  seedReferenceDataViaUI,
  sendReadyTransfersViaUI,
  takeToWorkViaUI,
  transferRouteChainViaUI,
  waitForPlanningTableViaUI,
} from "./ui-helpers";

/**
 * @ui — ПАРА артикулов 2604/2616: полный цикл без склейки (#312).
 *
 * Что проверяет спека (эталон тикета):
 *   1. Импорт двух строк листа даёт ДВЕ позиции плана, а не одну склейку
 *      `ЮП-2616+ЮП-2604`. Артикулы не пересекаются до самого конца.
 *   2. Обе позиции идут раздельно по всем участкам маршрута и всем передачам,
 *      финиш — `SHIPPED`.
 *   3. На печати плана участка две строки сходятся в ОДИН подвес: в шапке группы
 *      один счёт подвесов и норма вида `N×A + N×B`, а не сумма по артикулам.
 *
 * Данные строк плана имитируются через `/imports/excel/simulate` — конкретный
 * xlsx не принципиален (тикет). Каталог, остатки и пара — через API; остальные
 * шаги (утверждение, запуск, передачи, участки) — из UI.
 */

/** Пара тикета: два артикула, один подвес несёт оба. */
const SKU_A = "ЮП-2604";
const SKU_B = "ЮП-2616";
/** Общая нормальная длина пары (ADR-0028) — сырьевая живёт только в карточке. */
const NORMAL_LENGTH_MM = 2700;
/** Сырьевая длина — только параметр расчёта количества на подвесе. */
const RAW_LENGTH_MM = 2750;
/** Ручная N пары: столько каждого артикула уезжает на одном подвесе. */
const PAIR_N = 8;
/** Количество строки листа; округляется импортом до кратности N. */
const ROW_QTY = 150;

test.describe("@ui Пара 2604/2616: сквозной маршрут раздельно, единый подвес на печати", () => {
  test.beforeEach(async ({ page, loginAsAdmin }) => {
    await loginAsAdmin();
    // `reset-all` чистит и справочники импорта (TRUNCATE ... import_templates),
    // поэтому порядок обязателен: сначала сброс, потом сид шаблонов.
    await apiResetAll();
    await seedReferenceDataViaUI(page);
  });

  test("две позиции → маршрут раздельно → SHIPPED, печать одним подвесом", async ({ page }) => {
    test.slow();

    page.on("response", async (response) => {
      if (response.status() < 400 || !response.url().includes("/api/")) return;
      const body = await response.text().catch(() => "");
      console.log(
        `[api ${response.status()}] ${response.request().method()} ${response.url()} → ${body.slice(0, 400)}`,
      );
    });

    // ── ШАГ 1. Каталог: два артикула пары ─────────────────────────────────
    for (const sku of [SKU_A, SKU_B]) {
      await apiEnsureCatalogProduct({
        sku,
        name: `Кант универсальный 47мм 2,7 (${sku})`,
        lengthsMm: [NORMAL_LENGTH_MM],
        rawLengthMm: RAW_LENGTH_MM,
        perimeterMm: 60,
        mountWidthMm: 15,
      });
    }
    const productA = await apiGetProductBySku(SKU_A);
    const productB = await apiGetProductBySku(SKU_B);
    console.log("[step1] каталог пары готов");

    // ── ШАГ 2. Пара в справочнике + ручная N на общей длине ───────────────
    // Именно эта запись сводит две позиции в один подвес на печати.
    const pair = await apiCreateProductPair(productA.id, productB.id, {
      [String(NORMAL_LENGTH_MM)]: { manual: PAIR_N },
    });
    expect(pair.id, "пара не завелась").toBeGreaterThan(0);
    console.log(`[step2] пара #${pair.id}, N=${PAIR_N} на ${NORMAL_LENGTH_MM} мм`);

    // ── ШАГ 3. Остатки на «Склад сырья» под оба артикула ─────────────────
    const rawStock = await apiGetSectionByCode("RAW_STOCK");
    await apiAddRemainder(productA.id, rawStock.id, 400, "E2E остаток 2604", {
      length_mm: NORMAL_LENGTH_MM,
    });
    await apiAddRemainder(productB.id, rawStock.id, 400, "E2E остаток 2616", {
      length_mm: NORMAL_LENGTH_MM,
    });
    console.log("[step3] остатки готовы");

    // ── ШАГ 4. План из ДВУХ строк листа ──────────────────────────────────
    // Строки одинаковые по выходу и количеству — ровно тот случай, который
    // раньше склеивался в одну позицию `A+B`.
    const template = await apiGetActiveTemplate();
    const importRes = await apiSimulatePlanImport(
      [SKU_A, SKU_B].map((sku) => ({
        sku,
        name: `Кант универсальный 47мм 2,7 (${sku})`,
        raw_stock: 400,
        color: "черный",
        qty_per_27: ROW_QTY,
        length_m: 2.7,
        packaging: "смотка спанбондом поштучно в пачке 10 штук",
        output_length_m: 2.7,
        output_qty: ROW_QTY,
        west: ROW_QTY,
        east: 0,
        kind: "П/ф",
      })),
      { templateId: template.id },
    );
    await apiApplyChangeSet(importRes.production_plan_id, importRes.change_set_id);

    await page.goto("/planning");
    await expect(page.getByRole("heading", { name: "План", exact: true })).toBeVisible({
      timeout: 10_000,
    });
    await waitForPlanningTableViaUI(page);

    // ЭТАЛОН №1: импорт дал две позиции, а не одну склейку `A+B`.
    const planRows = page.locator('[id^="plan-position-"]');
    await expect(planRows).toHaveCount(2);
    const planText = (await planRows.allInnerTexts()).join(" | ");
    expect(planText, "в плане нет артикула 2604").toContain(SKU_A);
    expect(planText, "в плане нет артикула 2616").toContain(SKU_B);
    expect(planText, "в плане осталась склейка пары").not.toContain("+");
    console.log("[step4] план: 2 позиции, склейки нет");

    // ── ШАГ 5. Утверждение ОБЕИХ позиций ─────────────────────────────────
    // Каждая позиция утверждается отдельно: это ровно то разделение, ради
    // которого склейка снята (утверждение одной строки на оба артикула).
    const positions: { id: number; sku: string }[] = [];
    for (let attempt = 0; attempt < 2; attempt++) {
      const position = await findApprovablePositionViaUI(page);
      expect(position, `утверждаемых позиций не осталось после ${attempt} шага`).not.toBeNull();
      expect([SKU_A, SKU_B], `неожиданный артикул позиции: ${position!.sku}`).toContain(
        position!.sku,
      );
      await approvePositionViaUI(page, position!);
      positions.push(position!);
    }
    expect(new Set(positions.map((p) => p.id)).size, "позиции не разные").toBe(2);
    console.log(`[step5] утверждены позиции ${positions.map((p) => `#${p.id}`).join(", ")}`);

    // ── ШАГ 6. Запуск в работу ───────────────────────────────────────────
    for (const position of positions) {
      await takeToWorkViaUI(page, position);
    }
    console.log("[step6] обе позиции запущены");

    // ── ШАГ 7. Печать плана участка: пара — ОДИН подвес ─────────────────
    // Задачи пары уже созданы на первом шаге маршрута. Участок ищем по живым
    // заданиям обоих артикулов, а не по имени: маршрут задаёт справочник, и
    // хардкод участка в спеке разошёлся бы с сидами.
    await page.goto("/section-tasks");
    await expect(page.getByRole("heading", { name: "Участки", exact: true })).toBeVisible({
      timeout: 10_000,
    });
    const sectionTiles = page.getByRole("button").filter({ hasText: /ОЖ:|ВР:/ });
    await expect(sectionTiles.first()).toBeVisible({ timeout: 20_000 });

    let pairSectionFound = false;
    const tileCount = await sectionTiles.count();
    for (let i = 0; i < tileCount; i++) {
      await sectionTiles.nth(i).click();
      await expect(page).toHaveURL(/\/section-tasks\/\d+/, { timeout: 15_000 });
      const boardRows = page.locator("tr[data-task-id]");
      const boardReady = await boardRows
        .first()
        .waitFor({ state: "visible", timeout: 5_000 })
        .then(() => true, () => false);
      if (!boardReady) continue;
      const boardText = (await boardRows.allInnerTexts()).join(" | ");
      if (!boardText.includes(SKU_A) || !boardText.includes(SKU_B)) continue;
      pairSectionFound = true;
      break;
    }
    expect(pairSectionFound, "не нашли участок с заданиями обоих артикулов пары").toBe(true);

    await page.getByRole("button", { name: "Печать плана" }).click();
    const planSheet = page.getByRole("dialog", { name: /^План:/ });
    await expect(planSheet).toBeVisible({ timeout: 10_000 });

    // Обе колонки нужны для проверки свёртки: «Подвесы» считаются один раз
    // на пару, «Кол-во на подвес» показывает `N×A + N×B`. Профиль печати
    // участка может их не включать, поэтому включаем кнопками окна.
    for (const column of ["Подвесы", "Кол-во на подвес"]) {
      if ((await planSheet.getByRole("columnheader", { name: column, exact: true }).count()) === 0) {
        await planSheet.getByRole("button", { name: column, exact: true }).click();
        await expect(
          planSheet.getByRole("columnheader", { name: column, exact: true }),
        ).toBeVisible();
      }
    }

    // Шапка группы пары: `A+B · размер`, один счёт подвесов и норма пары.
    const groupHeader = planSheet
      .locator("tbody tr")
      .filter({ hasText: `${SKU_A}+${SKU_B}` });
    await expect(groupHeader).toHaveCount(1);
    await expect(groupHeader).toContainText(new RegExp(`${SKU_A}\\+${SKU_B} · \\d`));
    // Колонки группы: [метки через colSpan], затем числовые в порядке
    // PLAN_COLUMNS — подвесы, норма, остаток, действия.
    const groupHangers = Number((await groupHeader.locator("td").nth(1).innerText()).trim());
    const groupPerHanger = (await groupHeader.locator("td").nth(2).innerText()).trim();
    expect(groupPerHanger).toBe(`${PAIR_N}×${SKU_A} + ${PAIR_N}×${SKU_B}`);

    const headers = (await planSheet.locator("thead th").allInnerTexts()).map((text) => text.trim());
    const hangersColumn = headers.indexOf("Подвесы");
    expect(hangersColumn, "в печати нет колонки «Подвесы»").toBeGreaterThanOrEqual(0);
    const hangersOf = async (sku: string) => {
      const row = planSheet
        .locator("tbody tr")
        .filter({ hasText: sku, hasNotText: "+" });
      await expect(row).toHaveCount(1);
      return Number((await row.locator("td").nth(hangersColumn).innerText()).trim());
    };
    const hangersA = await hangersOf(SKU_A);
    const hangersB = await hangersOf(SKU_B);

    // ЭТАЛОН №3: подвес пары посчитан один раз, а не суммой двух строк.
    expect(hangersA, "строка пары без подвесов").toBeGreaterThan(0);
    expect(groupHangers, "подвесы группы не совпали с подвесами строки").toBe(hangersA);
    expect(groupHangers, "подвесы пары сложились по строкам").not.toBe(hangersA + hangersB);
    console.log(
      `[step7] печать: ${SKU_A}+${SKU_B} → ${groupHangers} подвес(ов), ${groupPerHanger}`,
    );

    // ── ШАГ 8. Маршрут: передачи ↔ участки, по каждому артикулу ─────────
    // Передачи отправляются по ОДНОМУ артикулу за раунд: так видно, что
    // материал двух позиций идёт раздельно, а не одной строкой. Маршрут не
    // хардкодится — следующий участок берётся из «Журнала передач».
    let transferred = 0;
    let idleRounds = 0;
    let routeChain: string[] = [];
    for (const sku of [SKU_A, SKU_B]) {
      const positionId = positions.find((p) => p.sku.includes(sku))!.id;
      for (let round = 0; round < 40; round++) {
        const sent = await sendReadyTransfersViaUI(page, sku);
        transferred += sent;

        routeChain = await transferRouteChainViaUI(page, sku, positionId);
        expect(routeChain, `${sku} раунд ${round}: в журнале нет передач позиции`).not.toHaveLength(0);

        const currentSection = routeChain[routeChain.length - 1];
        const completed = await completeAllSectionTasksViaUI(page, sku, [currentSection]);
        console.log(
          `[step8] ${sku} раунд ${round}: передано ${sent}, до «${currentSection}» (шагов ${routeChain.length}), завершено ${completed}`,
        );

        if (sent === 0 && completed === 0) {
          if (++idleRounds >= 2) break;
        } else {
          idleRounds = 0;
        }
      }
      // ЭТАЛОН №2: материал этой позиции дошёл до «Отправлено».
      await expectShippedViaUI(page, sku, [positionId]);
      console.log(`[step8] ${sku} отгружен`);
    }
    expect(transferred, "маршрут не прошёл ни одной передачи").toBeGreaterThan(0);
  });
});