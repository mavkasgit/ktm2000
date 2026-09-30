import {
  apiAddRemainder,
  apiApplyChangeSet,
  apiEnsureCatalogProduct,
  apiGetActiveTemplate,
  apiGetAllPlanPositions,
  apiGetProductBySku,
  apiGetSectionByCode,
  apiGetStockBalances,
  apiResetAll,
  apiSimulatePlanImport,
} from "./api-helpers";
import { expect, test } from "./fixtures";
import { E2E_SKU, seedReferenceDataViaUI } from "./ui-helpers";

/**
 * @ui — история импортов плана (ADR-0054).
 *
 * Таблица батчей ушла со страницы плана на отдельный маршрут
 * `/planning/import-history`; вход — кнопка «История импортов» в шапке плана.
 * Проверяется то, ради чего перенос делался, и то, что перенос мог сломать:
 *
 * 1. Батч виден на новом маршруте, и без прохода по нему заново.
 * 2. Порядок — серверный (`created_at DESC`), свежий импорт сверху. Своей
 *    сортировки на клиенте нет, и перевёрнутый список был бы виден сразу.
 * 3. Откат — LIFO внутри плана: после применения второго батча «Откатить»
 *    живой только у него, у первого кнопка гаснет (ADR-0025).
 * 4. Применение из истории работает: батч из «Распознан» становится
 *    «Применён», а откат возвращает его в «Отменён» — с живой кнопкой
 *    «Применить», потому что отменённый батч снова применим (§4.5).
 * 5. «Убрать из списка» (ADR-0056): строка исчезает, тумблер её возвращает с
 *    пометкой, а позиции и остатки те же — скрытие ничего не сносит.
 *
 * Сетап — через API (два батча одного плана), в кадре — только действия UI.
 */
const NORMAL_LENGTH_MM = 3000;

/** План-строка «Упаковочной карты» того же артикула, что сеет остаток. */
const planRow = (note: string) => ({
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
  note,
});

test.describe("@ui История импортов плана", () => {
  test("батчи видны на отдельной странице, откат — LIFO, применение работает", async ({
    page,
    loginAsAdmin,
  }) => {
    test.slow();
    await loginAsAdmin();
    // `reset-all` чистит и справочники импорта, поэтому порядок обязателен:
    // сначала сброс, потом сид справочников и только затем данные плана.
    await apiResetAll();
    await seedReferenceDataViaUI(page);

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
    // Первый батч — применённый, второй — только распознанный: на нём
    // проверяется и кнопка «Применить» из истории, и смена владельца отката.
    const first = await apiSimulatePlanImport([planRow("E2E-HIST-1")], {
      templateId: template.id,
    });
    await apiApplyChangeSet(first.production_plan_id, first.change_set_id);
    const second = await apiSimulatePlanImport([planRow("E2E-HIST-2")], {
      templateId: template.id,
      productionPlanId: first.production_plan_id,
      mode: "append_to_plan",
    });
    expect(second.import_batch_id).toBeGreaterThan(first.import_batch_id);

    // ── Вход на новую страницу: кнопка в шапке плана ────────────────────
    await page.getByRole("link", { name: "План", exact: true }).click();
    await expect(page.getByRole("heading", { name: "План", exact: true })).toBeVisible({
      timeout: 15_000,
    });
    await page.getByRole("button", { name: "История импортов" }).click();
    await expect(page).toHaveURL(/\/planning\/import-history$/);
    await expect(page.getByRole("heading", { name: "История импортов плана" })).toBeVisible({
      timeout: 15_000,
    });

    // ── Список: свежий сверху, статусы различимы ────────────────────────
    const rows = page.locator("tbody tr");
    await expect(rows).toHaveCount(2, { timeout: 15_000 });
    await expect(rows.first()).toContainText("Распознан");
    await expect(rows.last()).toContainText("Применён");
    // Колонка «План» заполнена у обеих строк (подпись «plan_no · name»):
    // батч без плана в списке выглядел бы как «План #id».
    for (const row of [rows.first(), rows.last()]) {
      await expect(row.locator("td").first()).toContainText("·");
    }

    // ── LIFO до применения второго батча ────────────────────────────────
    const appliedRow = rows.filter({ hasText: "Применён" });
    await expect(appliedRow.getByRole("button", { name: "Откатить" })).toBeEnabled();

    // ── Применение из истории ──────────────────────────────────────────
    const parsedRow = rows.filter({ hasText: "Распознан" });
    await parsedRow.getByRole("button", { name: "Применить" }).click();
    const applyDialog = page.getByRole("alertdialog").last();
    await expect(applyDialog.getByText("Подтвердите применение")).toBeVisible({ timeout: 10_000 });
    await applyDialog.getByRole("button", { name: /^Загрузить( с ошибками)? \(/ }).click();
    await expect(applyDialog).toBeHidden({ timeout: 30_000 });
    await expect(page.getByText("Импорт применён", { exact: true })).toBeVisible({ timeout: 15_000 });

    // ── LIFO после применения: откат перешёл к свежему батчу ────────────
    const nowAppliedRow = rows.filter({ hasText: "Применён" }).first();
    await expect(nowAppliedRow.getByRole("button", { name: "Откатить" })).toBeEnabled({
      timeout: 15_000,
    });
    await expect(
      rows.filter({ hasText: "Применён" }).last().getByRole("button", { name: "Откатить" }),
    ).toBeDisabled();

    // ── Откат из истории возвращает батч в «Отменён» ────────────────────
    await nowAppliedRow.getByRole("button", { name: "Откатить" }).click();
    const rollbackDialog = page.getByRole("alertdialog").last();
    await expect(rollbackDialog.getByText("Откатить импорт?")).toBeVisible({ timeout: 10_000 });
    await rollbackDialog.getByRole("button", { name: "Откатить" }).click();
    await expect(rollbackDialog).toBeHidden({ timeout: 30_000 });
    await expect(page.getByText("Импорт откачен", { exact: false })).toBeVisible({ timeout: 15_000 });
    // Отменённый батч снова применим — иначе откат был бы билетом в одну сторону.
    await expect(
      rows.filter({ hasText: "Отменён" }).getByRole("button", { name: "Применить" }),
    ).toBeVisible({ timeout: 15_000 });
  });

  test("«Убрать из списка» прячет строку, не трогая позиции и остатки", async ({
    page,
    loginAsAdmin,
  }) => {
    test.slow();
    await loginAsAdmin();
    await apiResetAll();
    await seedReferenceDataViaUI(page);

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
    await apiAddRemainder(product.id, rawStock.id, 400, "E2E остаток hide", {
      length_mm: NORMAL_LENGTH_MM,
    });

    const template = await apiGetActiveTemplate();
    const batch = await apiSimulatePlanImport([planRow("E2E-HIDE-1")], {
      templateId: template.id,
    });
    await apiApplyChangeSet(batch.production_plan_id, batch.change_set_id);
    // Снимок по всем планам и БЕЗ фильтра по статусу: иначе отмена позиции
    // выглядела бы как «позиция ушла из обоих снимков», а это похоже на
    // «ничего не изменилось». Сверяем id вместе со статусом.
    const snapshot = async () => {
      const { positions } = await apiGetAllPlanPositions();
      return positions
        .map((p: { id: number; status: string }) => [p.id, p.status])
        .sort((a: [number, string], b: [number, string]) => a[0] - b[0]);
    };
    const positionsBefore = await snapshot();
    const balancesBefore = await apiGetStockBalances(product.id);
    expect(positionsBefore.length).toBeGreaterThan(0);

    await page.getByRole("link", { name: "План", exact: true }).click();
    await page.getByRole("button", { name: "История импортов" }).click();
    await expect(page).toHaveURL(/\/planning\/import-history$/);
    const row = page.locator("tbody tr").filter({ hasText: "Применён" });
    await expect(row).toHaveCount(1, { timeout: 15_000 });

    // ── Скрытие: строка уходит, тумблер её возвращает ──────────────────
    await row.getByRole("button", { name: "Убрать из списка" }).click();
    const hideDialog = page.getByRole("alertdialog").last();
    await expect(hideDialog.getByText("Убрать импорт из списка?")).toBeVisible({ timeout: 10_000 });
    await hideDialog.getByRole("button", { name: "Убрать из списка" }).click();
    await expect(hideDialog).toBeHidden({ timeout: 15_000 });
    await expect(page.locator("tbody tr")).toHaveCount(0, { timeout: 15_000 });

    await page.getByLabel("Показывать убранные из списка").check();
    const hiddenRow = page.locator("tbody tr").filter({ hasText: "Убрана из списка" });
    await expect(hiddenRow).toHaveCount(1, { timeout: 15_000 });
    // Статус у скрытого прежний: скрытость ортогональна статусу (ADR-0056).
    await expect(hiddenRow).toContainText("Применён");
    await expect(hiddenRow.getByRole("button", { name: "Откатить" })).toBeEnabled();

    // ── Данные на месте: скрытие ничего не сносит ─────────────────────
    const balancesAfter = await apiGetStockBalances(product.id);
    expect(await snapshot()).toEqual(positionsBefore);
    expect(balancesAfter).toEqual(balancesBefore);
  });
});
