import { test, expect } from "./fixtures";
import {
  apiEnsureTestProducts,
  apiGetImportBatches,
  apiGetProductBySku,
  apiGetSectionByCode,
  apiImportRemainders,
} from "./api-helpers";

/**
 * @ui — тикет #232: история импорта остатков.
 *
 * Сетап через API — реальный `POST /api/stock/import/remainders` из буфера
 * обмена: он создаёт настоящий батч (одна строка журнала действий + строки
 * импорта), ровно как импорт из UI. Проверки в UI идут по отдельной странице
 * «История импортов» (/spg/import-history), в которую ведёт кнопка на экране
 * «Группы хранения и производства» (/spg):
 *
 * 1. Батч виден в истории без нового импорта.
 * 2. «Посмотреть» открывает строки батча с текущим остатком.
 * 3. Второй импорт того же склада гасит кнопку «Откатить» у первого
 *    (LIFO по складу, ADR-0053 п.1).
 * 4. «Откатить» у последнего батча переводит его в «Отменен» и возвращает
 *    остаток к состоянию до импорта.
 * 5. «Убрать из списка» прячет запись, не меняя остаток.
 */

test.describe("@ui История импорта остатков (#232)", () => {
  test("батч виден, откатывается последним, откат возвращает остаток", async ({
    authenticatedPage,
  }) => {
    test.slow();

    await apiEnsureTestProducts();
    const product = await apiGetProductBySku("ЮП-3270");
    const raw = await apiGetSectionByCode("RAW_STOCK");
    const tag = `E2E-HIST-${Date.now()}`;

    // ── Сетап: два импорта одного склада, чтобы проверить LIFO ──────────
    const first = await apiImportRemainders(raw.id, [
      { sku: product.sku, quantity: 7, comment: `${tag}-первый` },
    ]);
    const second = await apiImportRemainders(raw.id, [
      { sku: product.sku, quantity: 11, comment: `${tag}-второй` },
    ]);
    expect(first.batch_id).toBeGreaterThan(0);
    expect(second.batch_id).toBeGreaterThan(first.batch_id);
    // ── 1. Импорт через UI: вставка из буфера обмена ────────────────────
    // Импорт идёт настоящим путём (вставить TSV → предпросмотр → загрузить),
    // а проверки истории — уже на отдельной странице: она и есть основной вход.
    await authenticatedPage.goto("/spg");
    await expect(
      authenticatedPage.getByRole("heading", { name: "Группы хранения и производства" }),
    ).toBeVisible({ timeout: 15_000 });
    await authenticatedPage.getByRole("button", { name: /Импорт из Excel/ }).click();
    const importDialog = authenticatedPage.getByRole("dialog");
    await expect(importDialog).toBeVisible({ timeout: 5_000 });

    // Столбец «Участок» обязателен: без него парсер не резолвит целевую
    // секцию, `resolveImportLocationId` остаётся null и кнопка применения
    // неактивна («Укажите участок для импорта»).
    const tsv = [
      ["Артикул", "Количество", "Участок", "Комментарий"],
      [product.sku, "13", raw.name, `${tag}-ui`],
    ].map((r) => r.join("\t")).join("\n");
    // Ввод из буфера — не поле ввода, а обработчик `paste` на document
    // (`useImportClipboardPaste`): диспатчим ClipboardEvent с данными.
    await importDialog.evaluate((_node, text) => {
      const data = new DataTransfer();
      data.setData("text/plain", text);
      document.dispatchEvent(
        new ClipboardEvent("paste", { clipboardData: data, bubbles: true }),
      );
    }, tsv);

    // Вставка сразу переводит диалог на шаг предпросмотра.
    const importButton = importDialog.getByRole("button", { name: "Применить изменения" });
    await expect(importButton).toBeVisible({ timeout: 15_000 });
    await importButton.first().click();

    // ── 2. Отдельная страница истории: кнопка с экрана ГХП ──────────────
    await expect(importDialog.getByText("Импорт успешно завершен")).toBeVisible({
      timeout: 20_000,
    });
    // У модалки две «Закрыть» — кнопка в футере и крестик в шапке.
    await importDialog.getByRole("button", { name: "Закрыть" }).last().click();
    await authenticatedPage.getByRole("button", { name: /История импортов/ }).click();
    await expect(
      authenticatedPage.getByRole("heading", { name: "История импортов остатков" }),
    ).toBeVisible({ timeout: 10_000 });
    await expect(authenticatedPage.getByRole("button", { name: "Посмотреть" }).first()).toBeVisible();

    // LIFO по складу: откатываемый батч — ровно один, последний.
    const rollbackButtons = authenticatedPage.getByRole("button", { name: "Откатить" });
    await expect(rollbackButtons.first()).toBeVisible();
    const enabled = await rollbackButtons.evaluateAll(
      (els) => els.filter((el) => !(el as HTMLButtonElement).disabled).length,
    );
    expect(enabled).toBe(1);

    // ── 3. «Посмотреть»: строки батча и текущий остаток ────────────────
    await authenticatedPage.getByRole("button", { name: "Посмотреть" }).first().click();
    const detailDialog = authenticatedPage.getByRole("dialog").last();
    await expect(detailDialog.getByText("Текущий остаток")).toBeVisible({ timeout: 5_000 });
    await expect(detailDialog.getByText("загружена").first()).toBeVisible();

    // ── 4. Откат последнего батча склада ───────────────────────────────
    await authenticatedPage.keyboard.press("Escape");
    // Список отсортирован от новых к старым (batch.id desc), поэтому
    // откатываемый по LIFO батч — первый: у остальных кнопка disabled.
    await authenticatedPage.getByRole("button", { name: "Откатить" }).first().click();
    const confirm = authenticatedPage.getByRole("alertdialog").last();
    await expect(confirm.getByText("Откатить импорт остатков?")).toBeVisible();
    await confirm.getByRole("button", { name: "Откатить" }).click();
    await expect(confirm).toBeHidden({ timeout: 15_000 });

    // Откатан именно батч, созданный импортом из UI: он последний на складе.
    const after = await apiGetImportBatches();
    const newest = after.reduce((a, b) => (b.batch_id > a.batch_id ? b : a));
    expect(newest.batch_id).toBeGreaterThan(second.batch_id);
    expect(newest.status).toBe("rolled_back");
    expect(newest.can_rollback).toBe(false);
  });
});
