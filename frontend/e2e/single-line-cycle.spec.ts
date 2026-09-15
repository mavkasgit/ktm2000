import { test, expect } from "./fixtures";
import { apiResetAll } from "./api-helpers";
import {
  E2E_CATALOG_XLS_PATH,
  E2E_PLAN_1LINE_XLS_PATH,
  E2E_REMAINDERS_XLS_PATH,
  E2E_SKU,
  approvePositionViaUI,
  completeAllSectionTasksViaUI,
  expectShippedViaUI,
  findApprovablePositionViaUI,
  importCatalogViaUI,
  importRemaindersViaUI,
  seedReferenceDataViaUI,
  sendReadyTransfersViaUI,
  takeToWorkViaUI,
  transferRouteChainViaUI,
  uploadTestFileViaUI,
  waitForPlanningTableViaUI,
} from "./ui-helpers";

/**
 * @ui — ОДНА строка плана, ОДИН артикул: сквозной проход маршрута.
 *
 * Маршрут не хардкодится: на каждом шаге тест идёт на `/transfers`, отправляет
 * готовые передачи и читает из «Журнала передач» (`Получатель (Куда)`) адресатов
 * всех отправленных — это следующие участки маршрута. Затем завершает задачи на
 * каждом из них и снова возвращается на передачи. Цикл идёт, пока есть что
 * отправлять; последний шаг — финальный выпуск в «Отправлено».
 *
 * Фикстуры (корень репо): «Каталог E2E.xlsx», «Склад импорта остатков E2E.xlsx»
 * и «Упаковочный план 1 строка E2E.xlsx» (одна строка ЮП-009, 2,05 м × 300).
 *
 * Сетап — сброс планов dev-API (`reset-all`, как в `sawing-four-lengths-cycle`)
 * плюс сид справочников и импорт через визарды; все бизнес-шаги — из UI.
 *
 * Требует запущенного dev-окружения: `npm run dev` из корня проекта.
 */
test.describe("@ui Одна строка плана: сквозной маршрут передачами и участками", () => {
  test.beforeEach(async ({ page, loginAsAdmin }) => {
    await loginAsAdmin();
    // `reset-all` чистит и справочники импорта (TRUNCATE ... import_templates),
    // поэтому порядок обязателен: сначала сброс, потом сид шаблонов.
    await apiResetAll();
    await seedReferenceDataViaUI(page);
  });

  test("запуск → передачи ↔ участки по кругу → материал в «Отправлено»", async ({ page }) => {
    test.slow();

    page.on("response", async (response) => {
      if (response.status() < 400 || !response.url().includes("/api/")) return;
      const body = await response.text().catch(() => "");
      console.log(
        `[api ${response.status()}] ${response.request().method()} ${response.url()} → ${body.slice(0, 400)}`,
      );
    });

    // ── ШАГ 1. Каталог ─────────────────────────────────────────────────────
    await importCatalogViaUI(page, E2E_CATALOG_XLS_PATH);
    console.log("[step1] каталог импортирован");

    // ── ШАГ 2. Остатки на «Склад сырья» ────────────────────────────────────
    await importRemaindersViaUI(page, E2E_REMAINDERS_XLS_PATH);
    console.log("[step2] остатки импортированы");

    // ── ШАГ 3. План из ОДНОЙ строки ────────────────────────────────────────
    await page.goto("/planning");
    await expect(page.getByRole("heading", { name: "План", exact: true })).toBeVisible({
      timeout: 10_000,
    });
    await uploadTestFileViaUI(page, E2E_PLAN_1LINE_XLS_PATH);
    await waitForPlanningTableViaUI(page);
    await expect(page.locator('[id^="plan-position-"]')).toHaveCount(1);
    console.log("[step3] план импортирован (1 строка)");

    // ── ШАГ 4. Утверждение единственной позиции ────────────────────────────
    const position = await findApprovablePositionViaUI(page);
    expect(position, "в плане нет строки для утверждения").not.toBeNull();
    await approvePositionViaUI(page, position!);
    expect(position!.sku, "в плане неожиданный артикул").toContain(E2E_SKU);
    console.log(`[step4] позиция #${position!.id} утверждена`);

    // ── ШАГ 5. Запуск в работу на «Контроль выполнения» ────────────────────
    await takeToWorkViaUI(page, position!);
    console.log(`[step5] позиция #${position!.id} запущена`);

    // ── ШАГ 6. Маршрут: передачи ↔ участки ────────────────────────────────
    // После каждой операции на /transfers появляется новая готовая передача на
    // следующий участок. Возвращаемся на передачи, отправляем и читаем из
    // журнала ВСЮ цепочку передач позиции — реальный путь материала, включая
    // складские секции (Склад подготовки, Склад готовой продукции, К отгрузке),
    // которых в ready-таблице не видно по имени. Материал сейчас на последнем
    // адресате цепочки — задача может ждать завершения только там; на прежних
    // участках материал уже ушёл.
    // Повторяем, пока есть прогресс; маршрут доходит до «Отправлено»
    // (терминальная секция: задачи там нет, только финальный выпуск).
    let transferred = 0;
    let idleRounds = 0;
    let routeChain: string[] = [];
    for (let round = 0; round < 40; round++) {
      const sent = await sendReadyTransfersViaUI(page, E2E_SKU);
      transferred += sent;

      routeChain = await transferRouteChainViaUI(page, E2E_SKU, position!.id);
      expect(routeChain, `раунд ${round}: в журнале нет передач позиции`).not.toHaveLength(0);

      const currentSection = routeChain[routeChain.length - 1];
      const completed = await completeAllSectionTasksViaUI(page, E2E_SKU, [currentSection]);
      console.log(
        `[step6] раунд ${round}: передано ${sent}, путь до «${currentSection}» (шагов ${routeChain.length}), завершено ${completed}`,
      );

      // Доска отстаёт от auto-accept: первый заход сразу после передачи может
      // увидеть задачу без выданного материала и вернуть 0. Тогда повторяем —
      // два раунда подряд без прогресса означают, что маршрут встал.
      if (sent === 0 && completed === 0) {
        if (++idleRounds >= 2) break;
      } else {
        idleRounds = 0;
      }
    }
    expect(transferred, "маршрут не прошёл ни одной передачи").toBeGreaterThan(0);
    console.log(`[step6] маршрут: Склад сырья → ${routeChain.join(" → ")}`);

    // ── ШАГ 7. Материал доехал до «Отправлено» ─────────────────────────────
    // Проверка привязана к позиции этого прогона — в накопительной dev-БД
    // строки прошлых прогонов иначе давали бы ложный зелёный.
    await expectShippedViaUI(page, E2E_SKU, [position!.id]);
    console.log("[step7] отгрузка подтверждена");
  });
});
