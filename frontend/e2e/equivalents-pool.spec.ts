import { test, expect, type Page } from "./fixtures";
import type { Locator } from "@playwright/test";
import {
  apiAddRemainder,
  apiApplyChangeSet,
  apiEnsureCatalogProduct,
  apiGetActiveTemplate,
  apiGetPlanPositions,
  apiGetSectionByCode,
  apiGetStockBalanceGroups,
  apiGetStockBalances,
  apiGetStockTransactions,
  apiGetTransferHistory,
  apiResetAll,
  apiSeedData,
  apiSimulatePlanImport,
  type SimulatedPlanRow,
} from "./api-helpers";
import {
  approvePositionViaUI,
  arriveAtRoute,
  waitForPlanningTableViaUI,
  type ApprovablePosition,
} from "./ui-helpers";

/**
 * @ui @ui-narrow — общий пул эквивалентов в кадре (#398, спека §11).
 *
 * Три сценария тикета:
 *  A. Позиция на A видит остаток B, выдаёт его; на участке материал под A,
 *     отмена возвращает B.
 *  B. Две позиции на A и B делят одну кучу и не могут обе выдать больше, чем
 *     есть.
 *  C. Экран остатков показывает A и B одной строкой группы с раскрытием.
 *
 * Сетап — API (продукты, алиасы, остатки, план), бизнес-действия — UI:
 * утверждение, «Взять в работу», отмена выдачи в журнале передач.
 *
 * Проверки ledger идут через `/api/stock/transactions` и `/api/transfers/history`:
 * `transfer_send` несёт фактический SKU источника, `transfer_receive` и
 * `Transfer.product_id` — артикул задания (ADR-0073 п.5).
 */

const SKU_A = "E2E-EQ-A-398";
const SKU_B = "E2E-EQ-B-398";
const NAME_A = "Профиль E2E-EQ-A-398";
const NAME_B = "Профиль E2E-EQ-B-398";
const LENGTH_MM = 3000;
const LENGTH_M = 3;

type PlanPosition = {
  id: number;
  source_sku: string;
  route_id: number | null;
  quantity: string;
};

type Pair = {
  a: { id: number; sku: string };
  b: { id: number; sku: string };
};

/** Оба продукта, затем обратный алиас: сервер дописывает его сам. */
async function ensureEquivalentPair(): Promise<Pair> {
  const a = await apiEnsureCatalogProduct({
    sku: SKU_A,
    name: NAME_A,
    lengthsMm: [LENGTH_MM],
    rawLengthMm: LENGTH_MM + 50,
  });
  const b = await apiEnsureCatalogProduct({
    sku: SKU_B,
    name: NAME_B,
    lengthsMm: [LENGTH_MM],
    rawLengthMm: LENGTH_MM + 50,
  });
  // Повторный вызов на существующем продукте — PATCH: выставляет алиас и
  // заставляет `_enforce_bidirectional_aliases` дописать обратный на B.
  await apiEnsureCatalogProduct({
    sku: SKU_A,
    name: NAME_A,
    lengthsMm: [LENGTH_MM],
    rawLengthMm: LENGTH_MM + 50,
    aliases: [SKU_B],
  });
  return { a, b };
}

function planRow(sku: string, name: string, qty: number): SimulatedPlanRow {
  return {
    sku,
    name,
    raw_stock: qty,
    color: "серебро",
    qty_per_27: qty,
    length_m: LENGTH_M,
    packaging: "стяжка стретч поштучно в пачке 10 штук",
    output_length_m: LENGTH_M,
    output_qty: qty,
    west: qty,
    east: 0,
    kind: "ГП",
  };
}

async function importPlan(rows: SimulatedPlanRow[]) {
  const template = await apiGetActiveTemplate();
  const imported = await apiSimulatePlanImport(rows, { templateId: template.id });
  await apiApplyChangeSet(imported.production_plan_id, imported.change_set_id);
  const positions = (await apiGetPlanPositions(
    imported.production_plan_id,
  )) as PlanPosition[];
  return { imported, positions };
}

async function sumBalances(productId: number): Promise<number> {
  const rows = await apiGetStockBalances(productId);
  return rows.reduce((sum, row) => sum + Number(row.balance_qty), 0);
}

/** Открыть окно «Взять в работу» у позиции на «Контроле выполнения». */
async function openIssueDialog(
  page: Page,
  position: ApprovablePosition,
): Promise<Locator> {
  await page.goto("/execution");
  const search = page.getByPlaceholder("Поиск");
  await expect(search).toBeVisible({ timeout: 10_000 });
  await search.fill(position.sku);

  const row = page.locator(`tr[data-row-key="${position.id}"]`).first();
  await expect(row).toBeVisible({ timeout: 15_000 });
  await row.getByRole("button", { name: "Взять в работу" }).click();

  const dialog = page.getByRole("dialog").filter({ hasText: "Взять в работу" });
  await expect(dialog).toBeVisible({ timeout: 10_000 });
  return dialog;
}

/** Подтвердить подбор источника и дождаться ответа take-to-work. */
async function confirmIssueDialog(page: Page, dialog: Locator) {
  const responsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.url().includes("/take-to-work"),
    { timeout: 30_000 },
  );
  const confirm = dialog.getByTestId("issue-confirm-launch");
  await expect(confirm).toBeEnabled({ timeout: 20_000 });
  await confirm.click();
  const response = await responsePromise;
  expect(
    response.status(),
    `take-to-work: HTTP ${response.status()} ${await response.text().catch(() => "")}`,
  ).toBe(200);
  await expect(dialog).not.toBeVisible({ timeout: 15_000 });
}

/** Отмена выдачи целиком из журнала передач (UI, #282). */
async function cancelIssueViaUI(page: Page, transferId: number) {
  await arriveAtRoute(page, "/transfers");
  await page.getByRole("button", { name: /Журнал передач/ }).click();

  const history = page.getByRole("dialog").filter({ hasText: "Журнал передач" });
  await expect(history).toBeVisible({ timeout: 10_000 });

  const cancelButton = page.getByTestId(`history-cancel-issue-${transferId}`);
  await expect(cancelButton).toBeVisible({ timeout: 15_000 });
  await cancelButton.click();

  const cancelDialog = page.getByTestId("issue-cancel-dialog");
  await expect(cancelDialog).toBeVisible({ timeout: 10_000 });
  // Предпросмотр считает сервер: до его ответа кнопка задизейблена.
  await expect(cancelDialog.getByTestId("issue-cancel-summary")).toBeVisible({
    timeout: 20_000,
  });
  const confirm = cancelDialog.getByTestId("issue-cancel-confirm");
  await expect(confirm).toBeEnabled({ timeout: 20_000 });
  await confirm.click();
  await expect(cancelDialog).not.toBeVisible({ timeout: 15_000 });
}

test.describe("@ui @ui-narrow эквиваленты: общий пул остатков и выдачи", () => {
  test.beforeEach(async ({ page, loginAsAdmin }) => {
    await loginAsAdmin();
    // Порядок обязателен: reset-all чистит и справочники импорта.
    await apiResetAll();
    await apiSeedData();
  });

  test("A видит остаток B, выдаёт его; на участке материал под A, отмена возвращает B", async ({
    page,
  }) => {
    test.slow();
    test.setTimeout(300_000);

    const { a, b } = await ensureEquivalentPair();
    const raw = await apiGetSectionByCode("RAW_STOCK");
    await apiAddRemainder(
      b.id,
      raw.id,
      100,
      "E2E #398: одна куча эквивалента B",
      { length_mm: LENGTH_MM },
    );

    // Группа видна серверу: остаток B — это куча A+B. Поиск идёт по
    // фактической SKU-строке, поэтому ищем B (у A остатка нет).
    const groups = await apiGetStockBalanceGroups({ search: SKU_B });
    expect(groups.total, "остаток B не попал в группу A").toBe(1);
    const pile = groups.balances[0];
    expect(pile.alias_group_skus).toEqual([SKU_A, SKU_B]);
    expect(Number(pile.balance_qty)).toBe(100);
    const pileBalance = pile.items.find((item) => item.product_id === b.id);
    expect(pileBalance, "в группе нет фактической SKU-строки B").toBeTruthy();
    console.log(
      `[setup] A=#${a.id}, B=#${b.id}, куча B=100 (balance #${pileBalance!.balance_id})`,
    );

    const { positions } = await importPlan([planRow(SKU_A, NAME_A, 100)]);
    const positionA = positions.find((position) => position.source_sku === SKU_A);
    expect(positionA, "позиция A не импортировалась").toBeTruthy();
    expect(positionA!.route_id, "позиции A не назначен маршрут").not.toBeNull();

    await page.goto("/planning");
    await expect(page.getByRole("heading", { name: "План", exact: true })).toBeVisible({
      timeout: 10_000,
    });
    await waitForPlanningTableViaUI(page);
    const planRowA = page.locator(`#plan-position-${positionA!.id}`);
    await expect(planRowA.getByTestId("position-sku-available")).toHaveText("100", {
      timeout: 30_000,
    });

    await approvePositionViaUI(page, { id: positionA!.id, sku: SKU_A });

    // На «Контроле выполнения» индикатор позиции A — тоже куча B.
    await page.goto("/execution");
    await expect(page.getByPlaceholder("Поиск")).toBeVisible({ timeout: 10_000 });
    const execRowA = page.locator(`tr[data-row-key="${positionA!.id}"]`).first();
    await expect(execRowA).toBeVisible({ timeout: 15_000 });
    await expect(execRowA.getByTestId("position-sku-available")).toHaveText("100", {
      timeout: 30_000,
    });

    const dialog = await openIssueDialog(page, { id: positionA!.id, sku: SKU_A });
    // Одна куча — одна строка группы; фактический остаток адресуется по
    // `balance_id` (он же пришёл из API до выдачи).
    await expect(
      dialog.getByTestId(`issue-candidate-row-${pileBalance!.balance_id}`),
      "в окне выдачи нет фактической строки остатка B",
    ).toBeVisible({ timeout: 20_000 });
    const groupRow = dialog.locator('[data-testid^="issue-candidate-group-"]').first();
    await expect(groupRow, "в окне выдачи нет строки группы").toBeVisible({
      timeout: 20_000,
    });
    await expect(groupRow).toContainText(SKU_B);
    await expect(groupRow, "строка эквивалента не помечена").toContainText("эквивалент");
    await expect(dialog.getByTestId("issue-collect-line")).toHaveText(
      "Собрано 100 из 100 шт., дефицит 0 шт.",
    );
    await confirmIssueDialog(page, dialog);

    // Ledger: send — фактический SKU B, receive — артикул задания A.
    const sends = (await apiGetStockTransactions(b.id)).filter(
      (tx) => tx.reason === "transfer_send",
    );
    expect(sends, "выдача не дала ровно одну проводку send по B").toHaveLength(1);
    expect(sends[0].product_id, "send должен нести фактический SKU B").toBe(b.id);
    expect(Number(sends[0].quantity)).toBe(100);
    expect(sends[0].transfer_id, "send не привязан к передаче").toBeTruthy();

    const receives = (await apiGetStockTransactions(a.id)).filter(
      (tx) => tx.reason === "transfer_receive",
    );
    expect(receives, "выдача не дала ровно одну проводку receive по A").toHaveLength(1);
    expect(receives[0].product_id, "receive должен нести артикул задания A").toBe(a.id);
    expect(Number(receives[0].quantity)).toBe(100);
    expect(receives[0].transfer_id).toBe(sends[0].transfer_id);

    const transfer = (await apiGetTransferHistory()).find(
      (row) => row.transfer_id === sends[0].transfer_id,
    );
    expect(transfer, "передача выдачи не найдена в журнале").toBeTruthy();
    expect(transfer!.product_sku, "Transfer.product_id должен быть A").toBe(SKU_A);
    expect(transfer!.comment, "комментарий не называет источник-эквивалент").toContain(
      `источник: ${SKU_B} (эквивалент)`,
    );
    console.log(
      `[ledger] transfer #${transfer!.transfer_id}: send B=100, receive A=100, product=${transfer!.product_sku}`,
    );

    // Склад B опустел, на участке материал под A.
    expect(await sumBalances(b.id), "на складе B остался материал").toBe(0);
    expect(await sumBalances(a.id), "на участке нет материала под A").toBe(100);

    await cancelIssueViaUI(page, sends[0].transfer_id!);

    expect(await sumBalances(b.id), "отмена не вернула B на склад").toBe(100);
    expect(await sumBalances(a.id), "отмена не сняла A с участка").toBe(0);
    console.log("[cancel] B вернулся на склад, материал A с участка снят");
  });

  test("две позиции A и B делят одну кучу и не выдают больше, чем есть", async ({
    page,
  }) => {
    test.slow();
    test.setTimeout(300_000);

    const { a, b } = await ensureEquivalentPair();
    const raw = await apiGetSectionByCode("RAW_STOCK");
    await apiAddRemainder(
      b.id,
      raw.id,
      100,
      "E2E #398: одна куча B на две позиции",
      { length_mm: LENGTH_MM },
    );

    const { positions } = await importPlan([
      planRow(SKU_A, NAME_A, 60),
      planRow(SKU_B, NAME_B, 100),
    ]);
    const positionA = positions.find((position) => position.source_sku === SKU_A);
    const positionB = positions.find((position) => position.source_sku === SKU_B);
    expect(positionA, "позиция A не импортировалась").toBeTruthy();
    expect(positionB, "позиция B не импортировалась").toBeTruthy();
    expect(Number(positionA!.quantity)).toBe(60);
    expect(Number(positionB!.quantity)).toBe(100);
    expect(positionA!.route_id).not.toBeNull();
    expect(positionB!.route_id).not.toBeNull();

    await page.goto("/planning");
    await expect(page.getByRole("heading", { name: "План", exact: true })).toBeVisible({
      timeout: 10_000,
    });
    await waitForPlanningTableViaUI(page);

    // До выдачи обе позиции видят одну и ту же кучу 100.
    await expect
      .poll(
        async () => {
          const aText = await page
            .locator(`#plan-position-${positionA!.id}`)
            .getByTestId("position-sku-available")
            .innerText();
          const bText = await page
            .locator(`#plan-position-${positionB!.id}`)
            .getByTestId("position-sku-available")
            .innerText();
          return `${aText}/${bText}`;
        },
        { timeout: 30_000, message: "обе позиции должны видеть кучу 100" },
      )
      .toBe("100/100");

    await approvePositionViaUI(page, { id: positionA!.id, sku: SKU_A });
    await approvePositionViaUI(page, { id: positionB!.id, sku: SKU_B });

    // A забирает 60 из кучи B.
    const dialogA = await openIssueDialog(page, { id: positionA!.id, sku: SKU_A });
    await expect(dialogA.getByTestId("issue-collect-line")).toHaveText(
      "Собрано 60 из 60 шт., дефицит 0 шт.",
    );
    await confirmIssueDialog(page, dialogA);

    // Чужая открытая позиция заняла 60: B видит 40.
    await page.goto("/execution");
    await expect(page.getByPlaceholder("Поиск")).toBeVisible({ timeout: 10_000 });
    await page.getByPlaceholder("Поиск").fill(SKU_B);
    const execRowB = page.locator(`tr[data-row-key="${positionB!.id}"]`).first();
    await expect(execRowB).toBeVisible({ timeout: 15_000 });
    await expect
      .poll(
        async () => (await execRowB.getByTestId("position-sku-available").innerText()).trim(),
        { timeout: 30_000, message: "после выдачи A позиция B должна видеть 40" },
      )
      .toBe("40");

    // B просит 100, но собрать может только 40: стратегия partial.
    const dialogB = await openIssueDialog(page, { id: positionB!.id, sku: SKU_B });
    await expect(dialogB.getByTestId("issue-collect-line")).toHaveText(
      "Собрано 40 из 100 шт., дефицит 60 шт.",
    );
    await confirmIssueDialog(page, dialogB);

    const sends = (await apiGetStockTransactions(b.id)).filter(
      (tx) => tx.reason === "transfer_send",
    );
    expect(sends, "обе выдачи должны списать B двумя проводками").toHaveLength(2);
    expect(sends.map((tx) => Number(tx.quantity)).sort((x, y) => x - y)).toEqual([40, 60]);
    expect(sends.reduce((sum, tx) => sum + Number(tx.quantity), 0)).toBe(100);

    const receiveA = (await apiGetStockTransactions(a.id)).filter(
      (tx) => tx.reason === "transfer_receive",
    );
    const receiveB = (await apiGetStockTransactions(b.id)).filter(
      (tx) => tx.reason === "transfer_receive",
    );
    expect(receiveA).toHaveLength(1);
    expect(receiveA[0].product_id).toBe(a.id);
    expect(Number(receiveA[0].quantity)).toBe(60);
    expect(receiveB).toHaveLength(1);
    expect(receiveB[0].product_id).toBe(b.id);
    expect(Number(receiveB[0].quantity)).toBe(40);

    expect(await sumBalances(b.id), "на складе B должен остаться только выданный материал").toBe(40);
    expect(await sumBalances(a.id), "на участке нет материала под A").toBe(60);
    console.log("[scenario B] A забрала 60, B добрала 40 из 100 — дефицит 60");
  });

  test("экран остатков: A и B — одна строка группы с раскрытием", async ({ page }) => {
    test.slow();
    test.setTimeout(300_000);

    const { a, b } = await ensureEquivalentPair();
    const raw = await apiGetSectionByCode("RAW_STOCK");
    await apiAddRemainder(
      a.id,
      raw.id,
      40,
      "E2E #398: остаток A в общей куче",
      { length_mm: LENGTH_MM },
    );
    await apiAddRemainder(
      b.id,
      raw.id,
      60,
      "E2E #398: остаток B в общей куче",
      { length_mm: LENGTH_MM },
    );

    const groups = await apiGetStockBalanceGroups({ search: SKU_A });
    expect(groups.total, "A и B не свернулись в одну группу").toBe(1);
    const group = groups.balances[0];
    expect(group.alias_group_skus).toEqual([SKU_A, SKU_B]);
    expect(Number(group.balance_qty)).toBe(100);
    expect(group.items.map((item) => item.sku).sort()).toEqual([SKU_A, SKU_B]);
    const itemA = group.items.find((item) => item.product_id === a.id);
    const itemB = group.items.find((item) => item.product_id === b.id);
    expect(itemA, "в группе нет SKU-строки A").toBeTruthy();
    expect(itemB, "в группе нет SKU-строки B").toBeTruthy();

    await page.goto("/spg");
    await expect(page.getByRole("button", { name: "Импорт из Excel" })).toBeVisible({
      timeout: 10_000,
    });
    await page
      .getByPlaceholder("Глобальный поиск по артикулу или названию...")
      .fill(SKU_A);

    const groupRow = page.getByTestId(`stock-balance-group-${group.id}`);
    await expect(groupRow, "группа A+B не показана одной строкой").toBeVisible({
      timeout: 15_000,
    });
    await expect(
      page.locator('tr[data-testid^="stock-balance-group-"]'),
    ).toHaveCount(1);
    await expect(groupRow).toContainText(`${SKU_A}, ${SKU_B} (эквиваленты)`);
    await expect(groupRow.getByTestId("stock-balance-group-qty")).toHaveText("100");

    // Раскрытие — фактические SKU-строки со своими количествами.
    await groupRow.click();
    await expect(
      page.getByTestId(`stock-balance-item-${itemA!.balance_id}`),
    ).toBeVisible({ timeout: 10_000 });
    await expect(
      page
        .getByTestId(`stock-balance-item-${itemA!.balance_id}`)
        .getByTestId("stock-balance-item-qty"),
    ).toHaveText("40");
    await expect(
      page
        .getByTestId(`stock-balance-item-${itemB!.balance_id}`)
        .getByTestId("stock-balance-item-qty"),
    ).toHaveText("60");
    console.log("[scenario C] группа A+B = 100, раскрытие: A=40, B=60");
  });
});
