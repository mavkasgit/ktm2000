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
import { expect, test } from "./fixtures";
import { E2E_SKU, seedReferenceDataViaUI } from "./ui-helpers";

/**
 * @ui — СВЕЖЕСТЬ ПОСЛЕ УТВЕРЖДЕНИЯ: позиция, утверждённая на «Плане», видна на
 * «Контроле выполнения» сразу, без перезагрузки страницы.
 *
 * Это регресс на конкретный баг: позиция утверждалась, но на `/execution` не
 * появлялась до F5. Причина — рассинхрон инвалидации: одиночное утверждение
 * сбрасывало ключ строк контроля, а массовое (как и импорт, удаление позиции и
 * назначение маршрута) — нет, и запись висела в кэше до истечения `staleTime`.
 *
 * ## Где стоит проверка и почему именно там
 *
 * Проверка инвалидации — на живой странице «Плана», БЕЗ ухода с неё между
 * действием и проверкой. Это единственная точка, где проверка не может
 * «проскочить»:
 *
 * - `PlanPage` не поллит и не перечитывает данные по таймеру, а после approve
 *   никто не перемонтирует маршрут. Единственный способ, которым строка может
 *   узнать, что она утверждена, — `invalidateAfter(queryClient,
 *   "positionApproved")`, сбросивший ключ `all-plan-positions`.
 * - Прежняя версия теста возвращалась на `/execution` кликом по сайдбару. Маршрут
 *   размонтировался и монтировался заново, а react-query при монтировании
 *   refetch-ит устаревшие данные НЕЗАВИСИМО от `invalidateAfter`. Строка
 *   появлялась и при сломанной инвалидации — тест был зелёным всегда и ничего
 *   не ловил.
 *
 * Кнопка «Утвердить» в строке плана исчезает ровно тогда, когда позиция
 * перестала быть утверждаемой (`status` стал `approved` — см. `canApprove` в
 * `PlanPositionRow`). Это проверка, которая обязана падать, если инвалидация
 * не сработает: без неё строка так и останется со статусом `draft`, и
 * `canApprove` останется истинным.
 *
 * ## Зачем после этого ещё переход на «Контроль выполнения»
 *
 * Это исходный пользовательский баг целиком: строка должна быть видна на
 * контроле выполнения. Строгая часть регресса — проверка выше; переход и
 * проверка строки по `data-row-key` подтверждают сквозной результат. Именно
 * поэтому переход сделан ПОСЛЕ инвалидационной проверки, а не вместо неё.
 *
 * ## Почему строка поиска не трогается
 *
 * Ввод в поиск меняет `queryKey` и сам вызывает новый запрос, то есть маскирует
 * кэш ровно так же, как `goto`. Поэтому строка ищется по `#<id>` в таблице без
 * фильтра — в тесте всё равно одна позиция.
 *
 * Сетап данных — через API, в кадре только действия UI: утверждение и переход.
 */
const NORMAL_LENGTH_MM = 3000;

async function seedSinglePlannedPosition() {
  await apiEnsureCatalogProduct({
    sku: E2E_SKU,
    name: "Уголок 15*15",
    lengthsMm: [NORMAL_LENGTH_MM],
    rawLengthMm: 3050,
    perimeterMm: 60,
    mountWidthMm: 15,
  });
  const product = await apiGetProductBySku(E2E_SKU);
  const rawStock = await apiGetSectionByCode("RAW_STOCK");
  await apiAddRemainder(product.id, rawStock.id, 400, "E2E остаток 3000мм", {
    length_mm: NORMAL_LENGTH_MM,
  });

  const template = await apiGetActiveTemplate();
  const importRes = await apiSimulatePlanImport(
    [
      {
        sku: E2E_SKU,
        name: "Уголок 15*15",
        raw_stock: 400,
        color: "серебро",
        qty_per_27: 300,
        length_m: 3,
        packaging: "смотка спанбондом поштучно в пачке 10 штук",
        output_length_m: 3,
        output_qty: 300,
        west: 300,
        east: 0,
        kind: "П/ф",
      },
    ],
    { templateId: template.id },
  );
  await apiApplyChangeSet(importRes.production_plan_id, importRes.change_set_id);
}

/** Строка плана, которую ещё можно утвердить, и её `positionId`. */
interface ApprovableRow {
  row: Locator;
  positionId: number;
}

/**
 * Первая строка с кнопкой «Утвердить».
 *
 * Локатор по `id^="plan-position-"` плюс наличие кнопки, а не по статусу:
 * колонка `id` скрывается набором колонок, и текстовый локатор переставал
 * находить строку ровно тогда, когда её статус менялся.
 */
async function firstApprovablePlanRow(page: Page): Promise<ApprovableRow> {
  const row = page.locator('[id^="plan-position-"]').filter({
    has: page.getByRole("button", { name: "Утвердить" }),
  });
  await row.first().waitFor({ state: "visible", timeout: 15_000 });
  const positionId = Number.parseInt(
    (await row.first().getAttribute("id"))!.replace("plan-position-", ""),
    10,
  );
  return { row, positionId };
}

/** Одиночное утверждение позиции. */
async function approveSingleViaUI(page: Page, row: Locator) {
  await row.first().getByRole("button", { name: "Утвердить" }).click();
  const forceBtn = page.getByRole("button", { name: "Утвердить всё равно" });
  if (await forceBtn.isVisible().catch(() => false)) await forceBtn.click();
  await expect(page.getByText("Позиция утверждена", { exact: true })).toBeVisible({ timeout: 15_000 });
}

/** Массовое утверждение той же позиции: выбор строки + групповая кнопка. */
async function approveBulkViaUI(page: Page, row: Locator) {
  // Групповой режим включается отдельной кнопкой: обработчик выбора позиции
  // передаётся только когда режим включён, клик по строке до этого ничего не
  // делает.
  await page.getByRole("button", { name: "Групповые операции" }).click();
  await row.first().click();
  await expect(page.getByText("Выбрано: 1").first()).toBeVisible({ timeout: 10_000 });

  // Кнопка группового утверждения соседствует со счётчиком «Выбрано: N» в
  // панели фильтров; у позиции кнопка с тем же текстом, поэтому берём именно её.
  const bulkApprove = page
    .locator("span", { hasText: /^Выбрано:/ })
    .locator('xpath=following-sibling::button[normalize-space()="Утвердить"]')
    .first();
  await expect(bulkApprove).toBeVisible({ timeout: 10_000 });
  await bulkApprove.click();
  await expect(page.getByText(/Массовое утверждение|Частичный успех/).first()).toBeVisible({
    timeout: 20_000,
  });
}

/** Способ утверждения — различаются только тесты, общее всё остальное. */
type ApproveFn = (page: Page, row: Locator) => Promise<void>;

/**
 * Сценарий целиком. Различаются тесты только способом утверждения, поэтому
 * сетап, инвалидационная проверка и переход на контроль выполнения — здесь.
 *
 * @param approve     как утверждаем позицию
 * @param staleRowMsg сообщение для шага «контроль выполнения»
 */
async function runApproveFreshnessScenario(
  page: Page,
  approve: ApproveFn,
  staleRowMsg: (positionId: number) => string,
) {
  // Клик по сайдбару, а не `goto`: `goto` пересоздал бы QueryClient, кэш был бы
  // пуст, и проверять было бы нечего.
  await page.getByRole("link", { name: "План", exact: true }).click();
  await expect(page.getByRole("heading", { name: "План", exact: true })).toBeVisible({
    timeout: 15_000,
  });

  const { row, positionId } = await firstApprovablePlanRow(page);
  await approve(page, row);

  // ── Проверка инвалидации, БЕЗ ухода со страницы ─────────────────────────
  // ── Проверка инвалидации, БЕЗ ухода со страницы ─────────────────────────
  // Маршрут не перемонтируется, данные не перечитываются по таймеру: строка
  // теряет «Утвердить» только если сработала инвалидация после approve.
  // Строка адресуется по `id`, а не фильтром «есть кнопка» — иначе проверка
  // выродилась бы в «отфильтрованный локатор ничего не нашёл».
  const approvedRow = page.locator(`#plan-position-${positionId}`);
  await expect(approvedRow).toBeVisible({ timeout: 15_000 });
  await expect(
    approvedRow.getByRole("button", { name: "Утвердить", exact: true }),
    `позиция #${positionId} утверждена, но строка плана всё ещё предлагает «Утвердить»: инвалидация после approve не сработала`,
  ).toHaveCount(0, { timeout: 15_000 });

  // ── Сквозная проверка исходного бага: строка видна на контроле ──────────
  await page.getByRole("link", { name: "Контроль выполнения" }).click();
  await expect(page.getByRole("heading", { name: "Контроль выполнения" })).toBeVisible({
    timeout: 15_000,
  });
  await expect(
    page.locator(`tr[data-row-key="${positionId}"]`).first(),
    staleRowMsg(positionId),
  ).toBeVisible({ timeout: 15_000 });
}

test.describe("@ui Свежесть после утверждения позиции", () => {
  test.beforeEach(async ({ page, loginAsAdmin }) => {
    await loginAsAdmin();
    // `reset-all` чистит и справочники импорта, поэтому порядок обязателен.
    await apiResetAll();
    await seedReferenceDataViaUI(page);
    await seedSinglePlannedPosition();
  });

  test("одиночное утверждение: строка обновляется на месте и видна на контроле", async ({ page }) => {
    test.slow();
    await runApproveFreshnessScenario(
      page,
      approveSingleViaUI,
      (id) => `позиция #${id} утверждена, но на контроле выполнения не появилась`,
    );
  });

  test("массовое утверждение: строка обновляется на месте и видна на контроле", async ({ page }) => {
    test.slow();
    await runApproveFreshnessScenario(
      page,
      approveBulkViaUI,
      (id) => `МАССОВОЕ утверждение позиции #${id}: на контроле выполнения строка не появилась`,
    );
  });
});
