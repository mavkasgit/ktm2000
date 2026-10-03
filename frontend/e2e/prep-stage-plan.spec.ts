import { test, expect, type Page } from "./fixtures";
import path from "path";
import {
  apiAddRemainder,
  apiGetProductBySku,
  apiGetSectionByCode,
  apiGetStockBalances,
  apiResetAll,
} from "./api-helpers";
import {
  approvePositionViaUI,
  completeAllSectionTasksViaUI,
  E2E_SKU,
  ensureE2ECatalogViaUI,
  findApprovablePositionViaUI,
  seedReferenceDataViaUI,
  sendReadyTransfersViaUI,
  takeToWorkViaUI,
  transferRouteChainViaUI,
  waitForPlanningTableViaUI,
} from "./ui-helpers";

/**
 * @ui — тикет #313: «План подготовительного участка».
 *
 * Самый длинный из трёх вариантов — сверло + дробеструй:
 * файл новым шаблоном → approve → запуск → задания на участках подготовки →
 * завершение всего → материал на `PREP_STOCK` как завершённый.
 *
 * Сценарий САМЫЙ ДЛИННЫЙ из трёх, а не самый короткий, сознательно: чистый
 * дробеструй прогонял бы тот же код без шага DRILLING, и проверка «задания
 * созданы на подготовительных участках» ничего бы не добавила. Маршрут не
 * хардкодится — он читается из «Журнала передач» (`Получатель (Куда)`).
 *
 * Порядок шагов в маршруте — ассерт по шагам pytest
 * (`test_prep_stage_plan_import.py::test_each_file_variant_builds_its_own_route`);
 * здесь проверяется факт прохождения до склада подготовки.
 */

const PREP_TEMPLATE_NAME = "План подготовительного участка";
const PREP_STOCK_SECTION = "Склад подготовки";
const NORMAL_LENGTH_MM = 3000;

// Фикстура и загрузчик живут ЗДЕСЬ, а не в `ui-helpers.ts`: тот файл правит
// параллельный срез (#312), и общая правка разошлась бы при слиянии. Обе
// вещи нужны только этому сценарию.
const PREP_STAGE_PLAN_XLS_PATH = path.resolve(
  __dirname,
  "testdata/План подготовительного участка.xlsx",
);

/**
 * Импорт xlsx через визард плана ВЫБРАННЫМ шаблоном (#313).
 *
 * Копия `uploadTestFileViaUI`, но с другим шаблоном: там имя зашито в два
 * места (кнопка на экране и option в комбобоксе), и параметр заставил бы
 * молча переиспользовать ту же ветку «Упаковочной карты РП».
 */
async function uploadPlanWithTemplateViaUI(
  page: Page,
  filePath: string,
  templateName: string,
) {
  const templateBtn = page.getByRole("button", { name: new RegExp(templateName, "i") });
  if ((await templateBtn.count()) > 0) {
    await templateBtn.first().click();
  } else {
    await page.getByRole("button", { name: "Добавить файл" }).click();
    const uploadWizard = page.getByRole("dialog");
    await expect(uploadWizard).toBeVisible({ timeout: 10_000 });
    await uploadWizard.getByRole("combobox").first().click();
    await page.getByRole("option", { name: new RegExp(templateName, "i") }).click();
  }

  const wizard = page.getByRole("dialog");
  await expect(wizard).toBeVisible({ timeout: 10_000 });
  await wizard.locator('input[type="file"]').setInputFiles(filePath);

  const applyBtn = wizard.getByRole("button", { name: /применить изменения/i });
  await expect(applyBtn).toBeEnabled({ timeout: 120_000 });
  await applyBtn.click();

  const confirmDialog = page.getByRole("alertdialog");
  await expect(confirmDialog).toBeVisible({ timeout: 10_000 });
  await confirmDialog
    .getByRole("button", { name: /загрузить с ошибками|загрузить \(/i })
    .first()
    .click();

  await expect(confirmDialog).not.toBeVisible({ timeout: 30_000 });
  await expect(wizard.getByText("Изменения применены")).toBeVisible({ timeout: 120_000 });
  await wizard.getByRole("button", { name: "Закрыть" }).first().click();
  await expect(wizard).not.toBeVisible({ timeout: 10_000 });
}

test.describe("@ui План подготовительного участка: сверло + дробеструй → PREP_STOCK", () => {
  test.beforeEach(async ({ page, loginAsAdmin }) => {
    await loginAsAdmin();
    // Порядок обязателен: `reset-all` чистит и справочники импорта
    // (TRUNCATE … import_templates), поэтому справочники сеются после сброса.
    await apiResetAll();
    await seedReferenceDataViaUI(page);
  });

  test("импорт новым шаблоном → задания → материал на складе подготовки", async ({ page }) => {
    test.slow();

    page.on("response", async (response) => {
      if (response.status() < 400 || !response.url().includes("/api/")) return;
      const body = await response.text().catch(() => "");
      console.log(
        `[api ${response.status()}] ${response.request().method()} ${response.url()} → ${body.slice(0, 400)}`,
      );
    });

    // ── ШАГ 1. Артикул в справочнике сырья ────────────────────────────────
    await ensureE2ECatalogViaUI(page);
    const product = await apiGetProductBySku(E2E_SKU);
    console.log(`[step1] артикул ${E2E_SKU} → id=${product.id}`);

    // ── ШАГ 2. Остаток на «Склад сырья» ──────────────────────────────────
    // Старт любого подготовительного маршрута — RAW_STOCK: без остатка
    // первая выдача сырья не проходит и цикл передач не начинается.
    const rawStock = await apiGetSectionByCode("RAW_STOCK");
    await apiAddRemainder(product.id, rawStock.id, 600, "E2E остаток подготовки", {
      length_mm: NORMAL_LENGTH_MM / 1000,
    });
    console.log("[step2] остаток на складе сырья готов");

    // ── ШАГ 3. Импорт файла новым шаблоном ───────────────────────────────
    await page.goto("/planning");
    await expect(page.getByRole("heading", { name: "План", exact: true })).toBeVisible({
      timeout: 10_000,
    });
    await uploadPlanWithTemplateViaUI(page, PREP_STAGE_PLAN_XLS_PATH, PREP_TEMPLATE_NAME);
    await waitForPlanningTableViaUI(page);

    // Позиция из файла — со сверловкой: маршрут длиннее двух других, и
    // именно он проверяется целиком. Строка адресуется по `data-row-key`.
    const rows = page.locator('[id^="plan-position-"]');
    await expect(rows.first()).toBeVisible({ timeout: 30_000 });
    expect(await rows.count(), "в плане нет строк импорта").toBeGreaterThan(0);

    // Ни одна строка не должна остаться без маршрута: иначе approve
    // форс-аппрувит расхождение, и проверка «подготовительный маршрут»
    // прошла бы на позиции, которой маршрута нет.
    const planRows = await rows.evaluateAll((els) =>
      els.map((el) => {
        const cells = Array.from(el.children) as HTMLElement[];
        return {
          id: el.id,
          route: cells[6]?.textContent?.trim() ?? "",
          errors: cells[7]?.textContent?.trim() ?? "",
        };
      }),
    );
    expect(
      planRows.filter((r) => /Не назначен|Нажмите для выбора/i.test(r.route)),
      "строки остались без маршрута",
    ).toEqual([]);

    // У позиции со сверловкой маршрут называется «Сверловка - Дробеструй»
    // (имя собирает профиль из операций своих участков).
    const drillRow = planRows.find((r) => /Сверловка/i.test(r.route));
    expect(drillRow, `маршрута со сверловкой нет среди: ${planRows.map((r) => r.route)}`).toBeTruthy();
    console.log(`[step3] маршруты импорта: ${planRows.map((r) => r.route).join(" | ")}`);

    // ── ШАГ 4. Утверждение ───────────────────────────────────────────────
    const position = await findApprovablePositionViaUI(page);
    expect(position, "в плане нет строки для утверждения").not.toBeNull();
    await approvePositionViaUI(page, position!);
    console.log(`[step4] позиция #${position!.id} утверждена`);

    // ── ШАГ 5. Запуск в производство ─────────────────────────────────────
    await takeToWorkViaUI(page, position!);
    console.log(`[step5] позиция #${position!.id} запущена`);

    // ── ШАГ 6. Передачи ↔ участки до склада подготовки ────────────────────
    // Тот же круг, что в `single-line-cycle.spec.ts`: после каждого завершения
    // на /transfers появляется следующая готовая передача. Последний адресат
    // цепочки — участок, где материал лежит сейчас.
    let routeChain: string[] = [];
    let transferred = 0;
    let idleRounds = 0;
    for (let round = 0; round < 30; round++) {
      const sent = await sendReadyTransfersViaUI(page, E2E_SKU);
      transferred += sent;

      routeChain = await transferRouteChainViaUI(page, E2E_SKU, position!.id);
      if (routeChain.length === 0) break;

      const currentSection = routeChain[routeChain.length - 1];
      const completed = await completeAllSectionTasksViaUI(page, E2E_SKU, [currentSection]);
      console.log(
        `[step6] раунд ${round}: передано ${sent}, текущий участок «${currentSection}» (шагов ${routeChain.length}), завершено ${completed}`,
      );

      // Доска отстаёт от auto-accept: заход сразу после передачи может не
      // увидеть задачу. Два раунда без прогресса — маршрут встал.
      if (sent === 0 && completed === 0) {
        if (++idleRounds >= 2) break;
      } else {
        idleRounds = 0;
      }
    }

    expect(transferred, "маршрут не прошёл ни одной передачи").toBeGreaterThan(0);
    console.log(`[step6] путь материала: ${routeChain.join(" → ")}`);

    // ── ШАГ 7. Ассерт: материал на PREP_STOCK как завершённый ───────────
    // Главная проверка тикета: прошёл preparation — материал встал на
    // подготовительный склад. Читаем остаток по API: он отражает ledger,
    // а не текст в UI, и остаётся верным, если подпись раздела поменяется.
    const prepStock = await apiGetSectionByCode("PREP_STOCK");


    const balances = await apiGetStockBalances(product.id);
    const onPrepStock = balances.filter((b) => b.location_id === prepStock.id);
    const prepQty = onPrepStock.reduce((sum, b) => sum + Number(b.balance_qty), 0);
    console.log(
      `[step7] остаток на складе подготовки: ${prepQty} ` +
        `(строк остатка ${onPrepStock.length}, всего локаций ${balances.length})`,
    );
    expect(prepQty, "материал не встал на склад подготовки").toBeGreaterThan(0);

    // Последний адресат цепочки передач — тоже склад подготовки: маршрут
    // обязан закончиться там, а не на участке основного производства.
    expect(
      routeChain[routeChain.length - 1],
      `маршрут закончился не на ${PREP_STOCK_SECTION}: ${routeChain.join(" → ")}`,
    ).toBe(PREP_STOCK_SECTION);
  });
});