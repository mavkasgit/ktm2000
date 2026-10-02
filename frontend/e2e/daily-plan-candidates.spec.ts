import { test, expect } from "./fixtures";
import {
  apiAccessTokenFromPage,
  apiAddRemainder,
  apiAddRouteStep,
  apiCreateBareProduct,
  apiCreateRoute,
  apiGetSectionByCode,
  apiResetAll,
  apiRunDemoFullRoute,
  apiSeedData,
  authHeaders,
  BACKEND_URL,
} from "./api-helpers";
import { fetchBoardViaUI } from "./ui-helpers";

/**
 * @ui — тикет #301: задание, уже включённое в дневной план, не должно
 * показываться кандидатами при создании нового плана и не должно попадать
 * в выборку.
 *
 * Что проверяем (приёмка AC тикета):
 * 1. На доске участка с непустым планом задание этого плана **не появляется**
 *    в кандидатах — строки нет вообще (без заменителя и пояснений).
 * 2. Оно же **не считается в счётчике** «Выбрано N».
 * 3. Подтверждение плана, собранного **из показанных строк**, не даёт `409`:
 *    скрытое задание не уходит ни через клик по строке, ни через
 *    «Выделить все», ни через шапку группы.
 *
 * Сценарий:
 * 1. API-setup: сид, продукт, роут RAW_STOCK → PACKING, остаток, полный
 *    прогон роута — на PACKING появляются задания доски.
 * 2. UI: «План» → «Создать план» → выделить первое задание → «Подтвердить».
 *    План создан, это задание теперь занято.
 * 3. UI: «Создать план» снова — занятое задание отсутствует среди кандидатов,
 *    счётчик его не включает, «Выделить все» его не берёт.
 * 4. UI: «Подтвердить» из показанных строк — план создаётся без `409`.
 */

const PLAN_DATE = "03.10.2026";

/** Кандидаты в режиме создания плана: строки доски, доступные для выбора. */
function candidateRows(page: import("@playwright/test").Page) {
  return page.locator('tr[data-row-kind="board-task"][data-task-id]');
}

/** Задание доски по id — строки доски адресуются `data-task-id`. */
function rowById(page: import("@playwright/test").Page, taskId: number) {
  return page.locator(`tr[data-row-kind="board-task"][data-task-id="${taskId}"]`);
}

async function createPlanViaUI(
  page: import("@playwright/test").Page,
  sectionId: number,
  taskIds: number[],
): Promise<void> {
  await page.goto(`/section-tasks/${sectionId}`);
  await page.getByRole("button", { name: "План", exact: true }).click();
  await page.getByRole("button", { name: "Создать план", exact: true }).click();

  // Дата плана: поле «Дата плана» маскировано, принимает цифры (ДД.ММ.ГГГГ).
  const dateInput = page.getByRole("textbox", { name: "Дата плана" });
  await dateInput.fill("");
  await dateInput.pressSequentially(PLAN_DATE);

  for (const taskId of taskIds) {
    await rowById(page, taskId).click();
  }
  await page.getByRole("button", { name: "Подтвердить", exact: true }).click();
}

test.describe("@ui Дневной план: занятое задание не кандидат (#301)", () => {
  test.beforeEach(async () => {
    await apiResetAll();
    await apiSeedData();
  });

  test("задание из плана скрыто из кандидатов и не уходит в новый план", async ({
    authenticatedPage,
  }) => {
    test.slow();
    const page = authenticatedPage;
    const token = await apiAccessTokenFromPage(page);
    expect(token).toBeTruthy();

    // ── API-setup: задание на участке упаковки ───────────────────────────
    const sku = `E2E-PLAN-${Date.now()}`;
    const product = await apiCreateBareProduct(sku);
    const raw = await apiGetSectionByCode("RAW_STOCK");
    const packing = await apiGetSectionByCode("PACKING");

    const route = await apiCreateRoute(`E2E-PLAN-DAILY-${Date.now()}`);
    await apiAddRouteStep(route.id, {
      sequence: 1,
      section_id: raw.id,
      operation_name: "Выдача сырья",
      is_final: false,
      stage_kind: "transit",
      storage_section_id: raw.id,
    });
    await apiAddRouteStep(route.id, {
      sequence: 2,
      section_id: packing.id,
      operation_name: "Упаковка",
      is_final: true,
    });

    await apiAddRemainder(
      product.id,
      raw.id,
      100,
      "E2E #301: начальный остаток сырья",
      { length_mm: 2700 },
    );
    await apiRunDemoFullRoute(token, {
      initial_quantity: "100",
      route_id: route.id,
      product_id: product.id,
      run_id: `e2e-plan-${Date.now()}`,
    });

    // ── Шаг 0: доска отдаёт признак «занято» у заново созданного плана ──
    const beforeCreate = await fetchBoardViaUI(page, packing.id);
    const freeTasks = beforeCreate.tasks.filter(
      (t) => (t as { in_daily_plan?: boolean }).in_daily_plan !== true,
    );
    expect(freeTasks.length, "на доске есть свободные задания").toBeGreaterThan(0);
    const takenId = Number((freeTasks[0] as { id: number }).id);
    const freeId = Number((freeTasks[1] ?? freeTasks[0] as { id: number }).id);

    // ── Шаг 1: первое задание уходит в дневной план ──────────────────────
    await createPlanViaUI(page, packing.id, [takenId]);

    // План создан: панель показывает его, а задание теперь занято.
    await expect(page.getByText("План №1", { exact: false })).toBeVisible();

    const afterCreate = await fetchBoardViaUI(page, packing.id);
    const takenTask = afterCreate.tasks.find((t) => Number((t as { id: number }).id) === takenId) as
      | { in_daily_plan?: boolean }
      | undefined;
    expect(takenTask, "созданное задание есть на доске").toBeTruthy();
    expect(
      takenTask?.in_daily_plan,
      "задание из плана помечено in_daily_plan на доске",
    ).toBe(true);

    // ── Шаг 2: режим создания плана — занятое задание не кандидат ────────
    await page.getByRole("button", { name: "Создать план", exact: true }).click();
    const dateInput = page.getByRole("textbox", { name: "Дата плана" });
    await dateInput.fill("");
    await dateInput.pressSequentially(PLAN_DATE);

    // 2a. Строки занятое задание не показывает — вообще.
    await expect(
      rowById(page, takenId),
      "задание из плана не должно появляться среди кандидатов",
    ).toHaveCount(0);

    // 2b. И свободное — показывается (иначе проверка выше ничего не значит).
    await expect(rowById(page, freeId)).toHaveCount(1);
    await expect(candidateRows(page).first()).toBeVisible();

    // 2c. «Выделить всё показанное» не должно подтянуть занятое задание.
    const selectAll = page.getByRole("button", { name: /^Выделить все/ });
    await expect(selectAll).toBeVisible();
    await selectAll.click();

    // Счётчик «Выбрано N» равен числу реально доступных кандидатов, а не общему
    // числу строк доски: занятое задание в него не входит.
    const candidateCount = await candidateRows(page).count();
    expect(candidateCount).toBeGreaterThan(0);
    await expect(page.getByText(`Выбрано заданий: ${candidateCount}`)).toBeVisible();

    // ── Шаг 3: подтверждение из показанных строк не даёт 409 ─────────────
    const failedResponses: number[] = [];
    page.on("response", (response) => {
      if (response.url().includes("/api/daily-plans") && response.status() === 409) {
        failedResponses.push(409);
      }
    });
    await page.getByRole("button", { name: "Подтвердить", exact: true }).click();
    await expect(page.getByText("План №2", { exact: false })).toBeVisible();
    expect(failedResponses, "подтверждение из показанных строк не должно дать 409").toEqual([]);

    // Занятое задание осталось в первом плане, второго плана оно не коснулось:
    // серверная защита на месте, и фронт её не обошёл.
    const finalBoard = await fetchBoardViaUI(page, packing.id);
    const plans = await (
      await fetch(`${BACKEND_URL}/api/daily-plans/sections/${packing.id}`, {
        headers: await authHeaders(),
      })
    ).json();
    const planIds = (plans as { id: number; item_count: number }[]).map((p) => p.id);
    expect(planIds.length, "создано два дневных плана").toBeGreaterThanOrEqual(2);
    const takenStillMarked = finalBoard.tasks.find(
      (t) => Number((t as { id: number }).id) === takenId,
    ) as { in_daily_plan?: boolean } | undefined;
    expect(takenStillMarked?.in_daily_plan).toBe(true);
  });
});