import { test, expect } from "./fixtures";
import {
  apiAddRemainder,
  apiEnsureTestProducts,
  apiGetProductBySku,
  apiGetSectionByCode,
} from "./api-helpers";

/**
 * @smoke — тикет #117: страница «Отмена действий» (/reversal).
 *
 * Сетап через API (manual_in-остаток создаёт действие manual_adjustment
 * в журнале /actions), проверки в UI:
 *
 * 1. Пункт меню «Журнал» и вкладка «Отмена действий» открывают /reversal (#308).
 * 2. Таблица содержит созданное действие manual_adjustment.
 * 3. Кнопка дерева открывает диалог цепочки с узлом действия.
 * 4. Для manual_adjustment кнопка «Изменить» недоступна (только transfer_send).
 *
 * Требует запущенного dev-окружения: `npm run dev` из корня проекта.
 */

test.describe("@smoke Отмена действий — журнал /reversal (#117)", () => {
  test("журнал открывается, дерево цепочки показывает узел", async ({
    authenticatedPage,
  }) => {
    test.slow();

    // Сетап: артикул из фикстуры @smoke + склад RAW_STOCK, ручной приход →
    // Action в журнале. Артикул создаём сами: стенд поднимается на пустой БД,
    // и полагаться на то, что его завёл другой спек, нельзя.
    await apiEnsureTestProducts();
    const product = await apiGetProductBySku("ЮП-3270");
    const raw = await apiGetSectionByCode("RAW_STOCK");
    const comment = `E2E-REVERSAL-${Date.now()}`;
    await apiAddRemainder(product.id, raw.id, 5, comment);

    // 1. Навигация: пункт меню «Журнал» → вкладка «Отмена действий».
    await authenticatedPage.goto("/");
    const journalNavLink = authenticatedPage
      .getByRole("navigation", { name: "Основная навигация" })
      .getByRole("link", { name: "Журнал" });
    await expect(journalNavLink).toBeVisible({ timeout: 15_000 });
    await journalNavLink.click();
    await expect(authenticatedPage).toHaveURL(/\/audit-logs$/);
    const reversalTab = authenticatedPage
      .getByRole("navigation", { name: "Разделы журнала" })
      .getByRole("link", { name: "Отмена действий" });
    await reversalTab.click();
    await expect(authenticatedPage).toHaveURL(/\/reversal$/);
    await expect(
      authenticatedPage.getByRole("heading", { name: "Отмена действий" }),
    ).toBeVisible({ timeout: 10_000 });

    // 2. Строка ручной корректировки: тип в UI показан локализованной
    // подписью (сырых кодов в интерфейсе больше нет), ищем строку по ней.
    const row = authenticatedPage
      .getByTestId(/action-row-\d+/)
      .filter({ hasText: "Ручная корректировка остатка" })
      .first();
    await expect(row).toBeVisible({ timeout: 10_000 });
    await expect(row.getByText("Активно")).toBeVisible();

    // 3. Дерево цепочки: диалог с корневым узлом.
    const rowId = (await row.getAttribute("data-testid"))!.replace("action-row-", "");
    await authenticatedPage.getByTestId(`tree-button-${rowId}`).click();
    const treeDialog = authenticatedPage.getByTestId("tree-dialog");
    await expect(treeDialog).toBeVisible({ timeout: 5_000 });
    await expect(treeDialog.getByText(`Цепочка действия #${rowId}`)).toBeVisible();
    await expect(treeDialog.getByTestId(`tree-node-${rowId}`)).toContainText(
      "manual_adjustment",
    );

    // 4. Amend недоступен для не-transfer_send; отмена доступна (active).
    await expect(
      authenticatedPage.getByTestId(`amend-button-${rowId}`),
    ).toBeDisabled();
    await expect(
      authenticatedPage.getByTestId(`reverse-button-${rowId}`),
    ).toBeEnabled();
  });
});
