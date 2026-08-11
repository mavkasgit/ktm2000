import { expect, type Page } from "@playwright/test";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export const TEST_XLS_PATH = path.resolve(__dirname, "../../test.xls");
export const PACKAGING_PLAN_XLS_PATH = path.resolve(__dirname, "../../Упаковочный план.xlsx");

/** Тикет #88: фикстуры полного цикла для ЮП-009 (каталог/остатки/план). */
export const E2E_CATALOG_XLS_PATH = path.resolve(__dirname, "../../Каталог E2E.xlsx");
export const E2E_REMAINDERS_XLS_PATH = path.resolve(__dirname, "../../Склад импорта остатков E2E.xlsx");
export const E2E_PLAN_XLS_PATH = path.resolve(__dirname, "../../Упаковочный план E2E.xlsx");
export const BULK_REMAINDERS_XLS_PATH = path.resolve(__dirname, "../../Склад импорта остатков Bulk E2E.xlsx");
export const E2E_SKU = "ЮП-009";
export const E2E_SECTION = {
  RAW_STOCK: "RAW_STOCK",
  SHOT_BLAST: "SHOT_BLAST",
  ANODIZING: "ANODIZING",
  WIP_STOCK: "WIP_STOCK",
  SAWING: "SAWING",
  PACKING: "PACKING",
  FINISHED_STOCK: "FINISHED_STOCK",
  SHIPMENT: "SHIPMENT",
  SHIPPED: "SHIPPED",
} as const;

export const E2E_CATALOG_SKUS = [
  { sku: "ЮП-3270", name: "Профиль ЮП-3270", lengthMm: 6000 },
  { sku: "ЮП-2083", name: "Профиль ЮП-2083", lengthMm: 6000 },
] as const;

/** Подтвердить диалог «Запуск в производство» после «Взять в работу». */
export async function confirmProductionLaunchViaUI(page: Page) {
  const launchDialog = page.getByRole("dialog").filter({ hasText: "Запуск в производство" });
  await expect(launchDialog).toBeVisible({ timeout: 10_000 });
  const launchBtn = launchDialog.getByRole("button", { name: "Запустить в работу" });
  await expect(launchBtn).toBeEnabled({ timeout: 10_000 });
  await launchBtn.click();
  await expect(launchDialog).not.toBeVisible({ timeout: 15_000 });
}

/** Создать продукт в справочнике сырья через UI, если его ещё нет. */
export async function ensureProductViaUI(
  page: Page,
  sku: string,
  name: string,
  lengthMm = 6000,
) {
  await page.goto("/references/raw-materials");
  await expect(page.getByPlaceholder("Поиск")).toBeVisible({ timeout: 10_000 });

  const search = page.getByPlaceholder("Поиск");
  await search.fill(sku);
  await page.waitForTimeout(800);

  const existingRow = page.locator("tr", { hasText: sku }).first();
  if ((await existingRow.count()) > 0) {
    return;
  }

  await page.getByRole("button", { name: "Добавить" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible({ timeout: 5_000 });
  await expect(dialog.getByRole("heading", { name: "Новое сырье" })).toBeVisible();

  await dialog.locator('input[placeholder="ЮП-1234"]').fill(sku);
  await dialog.locator('input[placeholder="Полное название"]').fill(name);

  const lengthInput = dialog.getByPlaceholder("Введите длину");
  await lengthInput.fill(String(lengthMm));
  await dialog.getByRole("button", { name: "Добавить" }).click();
  await expect(dialog.getByText(`${lengthMm} мм`)).toBeVisible({ timeout: 5_000 });

  await dialog.getByRole("button", { name: "Создать" }).click();
  try {
    await expect(dialog).not.toBeVisible({ timeout: 15_000 });
  } catch {
    // SKU может уже существовать (например finished_good из smoke) — не виден в «Сырьё» (фильтр component).
    await dialog.getByRole("button", { name: "Закрыть" }).first().click();
    await expect(dialog).not.toBeVisible({ timeout: 5_000 });
  }
}

/** Массовое создание стандартных техкарт через UI (backend добавляет default line). */
export async function ensureStandardTechcardsViaUI(page: Page, skus: readonly string[]) {
  await page.goto("/references/techcards");
  await page.getByRole("button", { name: "Массовое создание" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible({ timeout: 10_000 });

  for (const sku of skus) {
    const row = dialog.locator("tr", { hasText: sku });
    if ((await row.count()) > 0) {
      await row.locator('input[type="checkbox"]').check();
    }
  }

  const applyBtn = dialog.getByRole("button", { name: "Применить" });
  if (await applyBtn.isEnabled()) {
    await applyBtn.click();
    await expect(dialog).not.toBeVisible({ timeout: 30_000 });
  } else {
    await dialog.getByRole("button", { name: "Отмена" }).click();
  }
}

export async function ensureE2ECatalogViaUI(page: Page) {
  for (const item of E2E_CATALOG_SKUS) {
    await ensureProductViaUI(page, item.sku, item.name, item.lengthMm);
  }
  await ensureStandardTechcardsViaUI(
    page,
    E2E_CATALOG_SKUS.map((item) => item.sku),
  );
}

/** Seed routes/templates via Dev Settings UI — no direct fetch. */
export async function seedReferenceDataViaUI(page: Page) {
  await page.goto("/settings/dev");
  await expect(page.getByRole("heading", { name: /панель разработчика/i })).toBeVisible({
    timeout: 10_000,
  });

  await page.getByRole("button", { name: "Загрузить справочники" }).click();
  await expect(page.getByRole("dialog")).toBeVisible({ timeout: 5_000 });

  await page.getByRole("dialog").getByRole("button", { name: /^Загрузить$/ }).click();

  const overwriteBtn = page.getByRole("button", { name: "Перезаписать" });
  await expect(overwriteBtn).toBeVisible({ timeout: 5_000 });
  await overwriteBtn.click();

  await expect(page.getByRole("alertdialog")).not.toBeVisible({ timeout: 60_000 });
  await expect(page.getByRole("dialog")).not.toBeVisible({ timeout: 60_000 });
}

/** Импорт справочника сырья через визард на /references/raw-materials (UI-only). */
export async function importCatalogViaUI(page: Page, filePath = E2E_CATALOG_XLS_PATH) {
  await page.goto("/references/raw-materials");
  await expect(page.getByRole("heading", { name: "Справочник сырья" })).toBeVisible({
    timeout: 10_000,
  });

  const importBtn = page.getByRole("button", { name: "Импорт", exact: true });
  await expect(importBtn).toBeVisible({ timeout: 10_000 });
  await importBtn.click();

  const wizard = page.getByRole("dialog");
  await expect(wizard).toBeVisible({ timeout: 10_000 });
  await expect(wizard.getByRole("heading", { name: "Импорт из Excel" })).toBeVisible({
    timeout: 5_000,
  });

  const fileInput = wizard.locator('input[type="file"]');
  await fileInput.setInputFiles(filePath);

  const importApplyBtn = wizard.getByRole("button", { name: "Импортировать" });
  await expect(importApplyBtn).toBeEnabled({ timeout: 120_000 });
  await importApplyBtn.click();

  const closeBtn = wizard.getByTestId("import-result-close");
  await expect(closeBtn).toBeVisible({ timeout: 120_000 });
  await closeBtn.click();
  await expect(wizard).not.toBeVisible({ timeout: 10_000 });
}

/** Импорт остатков через диалог на /spg (UI-only). */
export async function importRemaindersViaUI(page: Page, filePath = E2E_REMAINDERS_XLS_PATH) {
  await page.goto("/spg");
  await expect(page.getByRole("button", { name: "Импорт из Excel" })).toBeVisible({
    timeout: 10_000,
  });
  await page.getByRole("button", { name: "Импорт из Excel" }).click();

  const dialog = page.getByRole("dialog").filter({ hasText: "Импорт остатков" });
  await expect(dialog).toBeVisible({ timeout: 10_000 });

  const fileInput = dialog.locator('input[type="file"]');
  await fileInput.setInputFiles(filePath);

  const applyBtn = dialog.getByRole("button", { name: "Применить изменения" });
  await expect(applyBtn).toBeEnabled({ timeout: 120_000 });
  await applyBtn.click();

  await expect(dialog.getByText("Импорт успешно завершен")).toBeVisible({ timeout: 120_000 });
  await dialog.getByRole("button", { name: "Закрыть", exact: true }).first().click();
  await expect(dialog).not.toBeVisible({ timeout: 10_000 });
}

/** Upload Excel plan via the planning import wizard. */
export async function uploadTestFileViaUI(page: Page, filePath = TEST_XLS_PATH) {
  const templateBtn = page.getByRole("button", { name: /Упаковочная карта РП/i });
  if ((await templateBtn.count()) > 0) {
    await templateBtn.click();
  } else {
    await page.getByRole("button", { name: "Добавить файл" }).click();
    const uploadWizard = page.getByRole("dialog");
    await expect(uploadWizard).toBeVisible({ timeout: 10_000 });
    const templateCombo = uploadWizard.getByRole("combobox").first();
    await templateCombo.click();
    await page.getByRole("option", { name: /Упаковочная карта РП/i }).click();
  }

  const wizard = page.getByRole("dialog");
  await expect(wizard).toBeVisible({ timeout: 10_000 });

  const fileInput = wizard.locator('input[type="file"]');
  await fileInput.setInputFiles(filePath);

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

/** Дождаться активного плана и строк в таблице — без networkidle (polling ломает ожидание). */
export async function waitForPlanningTableViaUI(page: Page) {
  await expect(page.getByText("Нет активного плана")).not.toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("heading", { name: "Общий план" })).toBeVisible({ timeout: 15_000 });
  await expect(page.locator('[id^="plan-position-"]').first()).toBeVisible({ timeout: 30_000 });
}

export type ApprovablePosition = { id: number; sku: string };

/** Одиночный SKU из составного («A+B» → «A») для поиска на execution. */
function singleSku(sku: string): string {
  const [first] = sku.split("+");
  return (first ?? "").trim();
}

/** Find a planning row that exposes the «Утвердить» action (UI-only). */
export async function findApprovablePositionViaUI(page: Page): Promise<ApprovablePosition | null> {
  const rows = page.locator('[id^="plan-position-"]').filter({
    has: page.getByRole("button", { name: "Утвердить" }),
  });
  const count = await rows.count();
  if (count === 0) {
    return null;
  }

  const row = rows.first();
  const rowId = await row.getAttribute("id");
  if (!rowId) {
    return null;
  }

  const positionId = Number.parseInt(rowId.replace("plan-position-", ""), 10);
  // Ряд планирования — CSS-grid из <div>, не <table>: артикул рендерится
  // PositionSkuCell как первый font-mono элемент строки (без «· остаток»).
  const skuEl = row.locator(".font-mono").first();
  const sku = ((await skuEl.textContent()) ?? "").trim();

  return Number.isFinite(positionId) ? { id: positionId, sku } : null;
}

export async function approvePositionViaUI(page: Page, position: ApprovablePosition) {
  const planSearch = page.getByPlaceholder("Поиск");
  await expect(planSearch).toBeVisible({ timeout: 10_000 });
  if (position.sku) {
    await planSearch.fill(singleSku(position.sku));
  }

  const planRow = page.locator(`#plan-position-${position.id}`);
  await expect(planRow).toBeVisible({ timeout: 15_000 });

  const approveBtn = planRow.getByRole("button", { name: "Утвердить" });
  await expect(approveBtn).toBeVisible({ timeout: 5_000 });
  await approveBtn.click();

  const forceBtn = page.locator("button", { hasText: "Утвердить всё равно" }).filter({ visible: true });
  try {
    await expect(forceBtn).toBeVisible({ timeout: 3_000 });
    await forceBtn.click();
    await expect(page.getByRole("alertdialog")).not.toBeVisible({ timeout: 5_000 });
  } catch {
    // no risk dialog — ok
  }

  await expect(approveBtn).not.toBeVisible({ timeout: 15_000 });
}

export async function takeToWorkViaUI(page: Page, position: ApprovablePosition) {
  await page.goto("/execution");
  const execSearch = page.getByPlaceholder("Поиск");
  await expect(execSearch).toBeVisible({ timeout: 10_000 });

  if (position.sku) {
    await execSearch.fill(singleSku(position.sku));
  }

  const execRow = page.locator("tr", { hasText: `#${position.id}` }).first();
  await expect(execRow).toBeVisible({ timeout: 15_000 });

  const launchBtn = execRow.getByRole("button", { name: "Взять в работу" });
  await expect(launchBtn).toBeVisible({ timeout: 5_000 });
  await launchBtn.click();
  await confirmProductionLaunchViaUI(page);

  // Таблица может не перерисоваться после запуска (кэш React Query).
  // Перезагружаем /execution и ждём статус «Запущен» на свежем DOM.
  await page.goto("/execution");
  await expect(page.getByPlaceholder("Поиск")).toBeVisible({ timeout: 10_000 });
  await page.getByPlaceholder("Поиск").fill(singleSku(position.sku));

  const launchedRow = page.locator("tr", { hasText: `#${position.id}` }).first();
  await expect(launchedRow.locator("span").filter({ hasText: /^Запущен$/ })).toBeVisible({
    timeout: 15_000,
  });
}

/** Отправить все готовые передачи для SKU на /transfers (каждый шаг маршрута). Возвращает кол-во отправленных. */
export async function sendReadyTransfersViaUI(page: Page, sku: string): Promise<number> {
  await page.goto("/transfers");
  await expect(page.getByRole("heading", { name: "Передачи между ГХП" })).toBeVisible({
    timeout: 10_000,
  });

  // Ready-строки — в таблице «Готово к передаче», у каждой есть кнопка «Передать».
  // Таблица грузится асинхронно (VirtualizedTableBody): ждём либо строки, либо пустое
  // состояние «Нет заданий…» (валидный результат между операциями маршрута).
  const rows = page
    .locator("tr", { hasText: sku })
    .filter({ has: page.getByRole("button", { name: "Передать" }) });
  const emptyState = page.getByText(/Нет заданий, готовых к передаче/);
  let present = false;
  for (let attempt = 0; attempt < 40; attempt++) {
    if ((await rows.count()) > 0) {
      present = true;
      break;
    }
    if (await emptyState.isVisible().catch(() => false)) break;
    await page.waitForTimeout(500);
  }
  if (!present) {
    console.log(`[sendReadyTransfers] SKU=${sku} sent=0 (нет готовых передач)`);
    return 0;
  }

  // После отправки строка исчезает (auto-accept + refetch), поэтому индекс по
  // заранее снятому count ненадёжен — каждый раз берём первую живую строку.
  let sent = 0;
  for (;;) {
    const row = rows.first();
    if ((await row.count()) === 0) break;

    // Идентификатор конкретной строки (id позиции плана) — чтобы после отправки
    // ждать исчезновения именно её, а не «первой живой» (rows.first() ре-резолвится
    // на следующую строку после refetch).
    const rowPosId = (await row.locator("td").first().textContent())?.trim();

    const qtyInput = row.locator('input[type="number"]').first();
    await expect(qtyInput).toBeVisible({ timeout: 5_000 });
    // Инпут предзаполнен значением «К передаче» — не перетираем его.
    // Ячейка используется только если инпут пустой/нулевой.
    const currentQty = (await qtyInput.inputValue()).trim();
    if (!currentQty || Number(currentQty) <= 0) {
      const cell = row.locator("td", { hasText: "шт." }).first();
      const match = (await cell.textContent())?.match(/(\d+)\s*шт/);
      if (match) await qtyInput.fill(match[1]);
    }

    const sendBtn = row.getByRole("button", { name: "Передать" });
    await expect(sendBtn).toBeEnabled({ timeout: 5_000 });
    await sendBtn.click();
    sent++;

    // Ожидание исчезновения отправленной строки по её id позиции. Исторические
    // передачи тоже содержат id, но у них нет кнопки «Передать» — фильтр остаётся.
    if (rowPosId) {
      await expect(
        rows.filter({ hasText: rowPosId }),
      ).not.toBeVisible({ timeout: 30_000 });
    } else {
      await expect(row).not.toBeVisible({ timeout: 30_000 });
    }
  }

  console.log(`[sendReadyTransfers] SKU=${sku} sent=${sent}`);
  return sent;
}

/** Завершить задачу на участке (доска /section-tasks/:id): «Завершить» → факт = плановое → сохранить. */
export async function completeSectionTaskViaUI(page: Page, sectionId: number, sku: string) {
  await page.goto(`/section-tasks/${sectionId}`);
  const taskRow = page.locator("tr", { hasText: sku }).first();
  await expect(taskRow).toBeVisible({ timeout: 15_000 });

  const completeBtn = taskRow.getByRole("button", { name: "Завершить" }).first();
  await expect(completeBtn).toBeVisible({ timeout: 5_000 });
  await completeBtn.click();

  const drawer = page.getByRole("dialog");
  await expect(drawer).toBeVisible({ timeout: 5_000 });

  const plannedBtn = drawer.getByRole("button", { name: /Плановое \(\d+\)/ });
  if ((await plannedBtn.count()) > 0) {
    await plannedBtn.click();
  } else {
    const goodInput = drawer.locator('input[type="number"]').first();
    await goodInput.fill(String(await taskRow.locator("td").nth(1).textContent() ?? "0"));
  }

  await drawer.getByRole("button", { name: "Сохранить" }).click();
  await expect(drawer).not.toBeVisible({ timeout: 15_000 });
}

/** Завершить завершаемые задачи SKU на всех производственных участках. Возвращает кол-во завершённых. */
export async function completeAllSectionTasksViaUI(page: Page, sku: string): Promise<number> {
  await page.goto("/section-tasks");
  await expect(page.getByRole("heading", { name: "Участки" })).toBeVisible({ timeout: 10_000 });

  // Плитки производственных участков (SectionSwitcherTiles) — кнопки с бейджами
  // «ОЖ: N» / «ВР: N». Таблица и плитки грузятся асинхронно — ждём появления.
  const tiles = page.getByRole("button").filter({ hasText: /ОЖ:|ВР:/ });
  await expect(tiles.first()).toBeVisible({ timeout: 20_000 });

  // Обходим участки, где есть задачи (бейдж ОЖ/ВР ненулевой), и завершаем те,
  // у которых кнопка «Завершить» доступна. Строка доски — только та, что содержит
  // кнопку (на странице есть и таблица «Остатки» с теми же SKU без кнопки).
  let completed = 0;
  for (;;) {
    const tileCount = await tiles.count();
    let didComplete = false;

    for (let i = 0; i < tileCount; i++) {
      const tile = tiles.nth(i);
      const tileText = (await tile.textContent()) ?? "";
      // Скипаем участки без задач в работе/ожидании (уже завершены или пусты).
      if (!/(?:ОЖ|ВР):\s*[1-9]/.test(tileText)) continue;

      await tile.click();

      const taskRow = page
        .locator("tr", { hasText: sku })
        .filter({ has: page.getByRole("button", { name: "Завершить" }) })
        .first();
      const found = await taskRow
        .waitFor({ state: "visible", timeout: 10_000 })
        .then(() => true, () => false);
      if (!found) continue;
      const completeBtn = taskRow.getByRole("button", { name: "Завершить" }).first();
      if (!(await completeBtn.isEnabled().catch(() => false))) continue;

      await completeBtn.click();
      const drawer = page.getByRole("dialog");
      await expect(drawer).toBeVisible({ timeout: 5_000 });

      // «В работе: N» — выданное на участок количество. Если 0, материал ещё не
      // пришёл (передача в пути): завершать рано — бэкенд вернёт «Complete quantity
      // exceeds issued quantity». Закрываем «Отмена» и пробуем в следующем раунде.
      const inWorkMatch = (await drawer.textContent())?.match(/В работе:\s*(\d+)/);
      const inWork = inWorkMatch ? Number(inWorkMatch[1]) : 0;
      if (inWork <= 0) {
        await drawer.getByRole("button", { name: "Отмена" }).click().catch(() => {});
        await expect(drawer).not.toBeVisible({ timeout: 8_000 }).catch(() => {});
        continue;
      }

      const plannedBtn = drawer.getByRole("button", { name: /Плановое \(\d+\)/ });
      if ((await plannedBtn.count()) > 0) {
        await plannedBtn.click();
      } else {
        const goodInput = drawer.locator('input[type="number"]').first();
        await goodInput.fill(String(await taskRow.locator("td").nth(1).textContent() ?? "0"));
      }

      await drawer.getByRole("button", { name: "Сохранить" }).click();
      // Страховка: если сохранение всё же упало по валидации — закрываем «Отмена»
      // и пробуем снова в следующем раунде, не роняя весь проход.
      const saveOk = await expect(drawer).not.toBeVisible({ timeout: 8_000 }).then(
        () => true,
        () => false,
      );
      if (!saveOk) {
        await drawer.getByRole("button", { name: "Отмена" }).click().catch(() => {});
        await expect(drawer).not.toBeVisible({ timeout: 8_000 }).catch(() => {});
        continue;
      }
      completed++;
      didComplete = true;
      // Возвращаемся на список участков, чтобы продолжить обход.
      await page.goto("/section-tasks");
      await expect(page.getByRole("heading", { name: "Участки" })).toBeVisible({ timeout: 10_000 });
      await expect(tiles.first()).toBeVisible({ timeout: 20_000 });
      break;
    }

    if (!didComplete) break;
  }

  console.log(`[completeAllSectionTasks] SKU=${sku} completed=${completed}`);
  return completed;
}

/** Тикет #88: финальный контроль — материал доехал до «Отправлено» (SHIPPED). */
export async function expectShippedViaUI(page: Page, sku: string) {
  await page.goto("/spg");
  await expect(page.getByRole("heading", { name: "Группы хранения и производства" })).toBeVisible({
    timeout: 10_000,
  });

  const search = page.getByPlaceholder("Глобальный поиск по артикулу или названию...");
  await expect(search).toBeVisible({ timeout: 10_000 });
  await search.fill(sku);

  // Строка остатков на участке «Отправлено» (SHIPPED). Таблица остатков
  // грузится асинхронно — ждём появления строки с артикулом и участком.
  const shippedRow = page
    .locator("tr", { hasText: sku })
    .filter({ has: page.getByText("Отправлено", { exact: true }) })
    .first();
  await expect(shippedRow).toBeVisible({ timeout: 20_000 });

  // Кол-во в колонке «Количество» (2-я ячейка) > 0.
  const qtyText = (await shippedRow.locator("td").nth(1).textContent())?.trim() ?? "0";
  const qty = Number.parseFloat(qtyText.replace(/\s/g, ""));
  expect(qty).toBeGreaterThan(0);
  console.log(`[expectShipped] SKU=${sku} на участке «Отправлено»: ${qty} шт`);
}