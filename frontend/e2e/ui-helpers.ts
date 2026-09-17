import { expect, type Locator, type Page } from "@playwright/test";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/**
 * Хранимые xlsx-фикстуры — по одному основному варианту на вид импорта
 * (всё в `testdata/`):
 *  - «Упаковочный план.xlsx» — главный план (~318 строк, десятки артикулов),
 *    живой импорт через UI-визард (`route-workflow.spec.ts`);
 *  - «Каталог E2E.xlsx» — справочник сырья ЮП-009, живой импорт через
 *    визард (`full-cycle.spec.ts`);
 *  - «Склад импорта остатков E2E.xlsx» — остатки ЮП-009, живой импорт через
 *    диалог (`full-cycle.spec.ts`).
 *
 * Остальные сценарии сетапятся бесфайлово (`POST /api/imports/excel/simulate`
 * и прямые вызовы API) и отдельных xlsx не хранят.
 */
export const PACKAGING_PLAN_XLS_PATH = path.resolve(
  __dirname,
  "testdata/Упаковочный план.xlsx",
);
export const E2E_CATALOG_XLS_PATH = path.resolve(__dirname, "testdata/Каталог E2E.xlsx");
export const E2E_REMAINDERS_XLS_PATH = path.resolve(
  __dirname,
  "testdata/Склад импорта остатков E2E.xlsx",
);
export const E2E_SKU = "ЮП-009";

/** Пила в полном цикле (ЮП-2083, сырьевая длина 2,75 м, раскрой на 4 длины). */
export const SAW4_SKU = "ЮП-2083";

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


export async function ensureE2ECatalogViaUI(page: Page) {
  for (const item of E2E_CATALOG_SKUS) {
    await ensureProductViaUI(page, item.sku, item.name, item.lengthMm);
  }
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

  // Тулбар справочника (#177): единая точка входа — меню «Операции»
  // (импорт справочника Excel, импорт фото ZIP, выгрузка справочника Excel).
  const operationsBtn = page.getByRole("button", { name: "Операции", exact: true });
  await expect(operationsBtn).toBeVisible({ timeout: 10_000 });
  await operationsBtn.click();

  await page.getByRole("menuitem", { name: "Импорт: справочник сырья (Excel)" }).click();

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
export async function uploadTestFileViaUI(page: Page, filePath: string) {
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
  // Таблица плана грузится асинхронно: после reload/refetch даём ей отрисоваться,
  // иначе «нет строк» — это ещё не «нет утверждаемых позиций».
  await rows.first().waitFor({ state: "visible", timeout: 10_000 }).catch(() => {});
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

  await expect(approveBtn).not.toBeVisible({ timeout: 8_000 }).catch(async () => {
    // Таблица плана иногда не перерисовывается после approve (refetch успевает
    // раньше коммита). Перезагружаем и проверяем статус строки на свежих данных:
    // если утверждение реально прошло — строки с кнопкой больше нет.
    await page.reload();
    await expect(page.getByPlaceholder("Поиск")).toBeVisible({ timeout: 15_000 });
    if (position.sku) {
      await page.getByPlaceholder("Поиск").fill(singleSku(position.sku));
    }
    await expect(approveBtn).not.toBeVisible({ timeout: 15_000 });
  });
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
  const launchVisible = await launchBtn
    .waitFor({ state: "visible", timeout: 5_000 })
    .then(() => true, () => false);
  if (!launchVisible) {
    const text = ((await execRow.innerText()) ?? "").replace(/\s+/g, " ").trim();
    console.log(
      `[takeToWork] позиция #${position.id}: кнопки «Взять в работу» нет; ` +
        `кнопка рендерится при status=approved && !has_tasks && !is_released && route_id. Строка: ${text}`,
    );
  }
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

/** Кликнуть кнопку в первой живой строке таблицы и дождаться её исчезновения.
 *
 * Строка исчезает после refetch (auto-accept), поэтому индекс по заранее снятому
 * count ненадёжен — каждый раз берём первую живую строку. Ждём исчезновения
 * именно её: адресуем строку её `data-row-key` из разметки. Ключ текстом или
 * «первой живой» строкой не годится: локатор ре-резолвится на каждом действии,
 * и при refetch клик уходит по соседней строке, а ожидание — за строкой,
 * которую никто не передавал. Возвращает `false`, когда строк больше нет;
 * `prepare` — шаг до клика (например, заполнить количество). `prepare`,
 * вернувший `false`, отменяет клик (строку сейчас передавать нельзя).
 */
async function clickFirstRowAndWaitGone(
  rows: Locator,
  buttonName: string,
  prepare?: (row: Locator) => Promise<boolean | void>,
): Promise<boolean> {
  const row = rows.first();
  if ((await row.count()) === 0) return false;

  const rowKey = await row.getAttribute("data-row-key");
  if (!rowKey) {
    throw new Error(`строка «${buttonName}» без data-row-key: нечем её адресовать`);
  }
  const rowLabel = ((await row.innerText()) ?? "").replace(/\s+/g, " ").trim();
  const target = rows.page().locator(`tr[data-row-key="${rowKey}"]`);

  if (prepare && (await prepare(target)) === false) return false;

  const button = target.getByRole("button", { name: buttonName });
  await expect(button).toBeEnabled({ timeout: 5_000 });
  await button.click();

  // Текст строки как признак не подходит: кнопка сразу меняется на «Отправка…»,
  // и сравнение текстов даёт ложное «строка исчезла» до прихода refetch.
  await expect
    .poll(() => target.count(), {
      timeout: 30_000,
      message: `строка «${rowLabel}» осталась в списке после «${buttonName}»`,
    })
    .toBe(0);
  return true;
}

/**
 * Провести все готовые строки SKU на /transfers: обычные передачи («Передать»)
 * на следующий участок и финальные выпуски («Отправить», #96) на финальной
 * стадии. Возвращает суммарное количество проведённых строк (передачи +
 * выпуски) — вызывающий читает `0` как «на маршруте больше нечего делать».
 */
export async function sendReadyTransfersViaUI(page: Page, sku: string): Promise<number> {
  await page.goto("/transfers");
  await expect(page.getByRole("heading", { name: "Передачи между ГХП" })).toBeVisible({
    timeout: 10_000,
  });

  // Ready-строки — в таблице «Готово к передаче»:
  //  • «Передать» — обычная передача на следующий участок;
  //  • «Отправить» — финальный выпуск финальной стадии (#96).
  // Только строки заданий (`data-row-kind="ready-task"`): заголовок свёрнутой
  // группы тоже несёт артикул и кнопку, но его клик отправляет всю группу
  // разом — тогда и счётчик `sent`, и ожидание исчезновения строки врут.
  // Таблица грузится асинхронно (VirtualizedTableBody): ждём либо строки, либо пустое
  // состояние «Нет заданий…» (валидный результат между операциями маршрута).
  const sendRows = page
    .locator('tr[data-row-kind="ready-task"]', { hasText: sku })
    .filter({ has: page.getByRole("button", { name: "Передать" }) });
  const releaseRows = page
    .locator('tr[data-row-kind="ready-task"]', { hasText: sku })
    .filter({ has: page.getByRole("button", { name: "Отправить" }) });
  const emptyState = page.getByText(/Нет заданий, готовых к передаче/);
  let present = false;
  for (let attempt = 0; attempt < 40; attempt++) {
    await expandBoardGroupsViaUI(page);
    if ((await sendRows.count()) > 0 || (await releaseRows.count()) > 0) {
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
  while (
    await clickFirstRowAndWaitGone(sendRows, "Передать", async (row) => {
      const qtyInput = row.locator('input[type="number"]').first();
      await expect(qtyInput).toBeVisible({ timeout: 5_000 });
      // Инпут предзаполнен значением «К передаче» — не перетираем его.
      // «0» — материал к передаче ещё не поступил: строка в ready-списке по
      // плану, отправлять нечего (POST вернёт «exceeds transferable amount»).
      // Пустой инпут — значение UI не выставил: подставляем из ячейки.
      const currentQty = (await qtyInput.inputValue()).trim();
      if (Number(currentQty) === 0) {
        console.log(`[sendReadyTransfers] SKU=${sku} строка без к передаче — пропуск`);
        return false;
      }
      if (!currentQty) {
        const cell = row.locator("td", { hasText: "шт." }).first();
        const match = (await cell.textContent())?.match(/(\d+)\s*шт/);
        if (match) await qtyInput.fill(match[1]);
      }
    })
  ) {
    sent++;
    await expandBoardGroupsViaUI(page);
  }

  // Финальный выпуск (#96): финальная стадия отдаёт готовое в «Отправлено»
  // кнопкой «Отправить» (а не «Передать»). Без него материал застревает на
  // последней стадии. Возможно несколько финальных строк одного SKU.
  while (await clickFirstRowAndWaitGone(releaseRows, "Отправить")) {
    sent++;
    await expandBoardGroupsViaUI(page);
  }

  console.log(`[sendReadyTransfers] SKU=${sku} sent=${sent}`);
  return sent;
}

/**
 * Полная цепочка адресатов («Куда») передач позиции из «Журнала передач» —
 * маршрут материала, прочитанный из UI, а не из хардкода.
 *
 * Журнал отсортирован по времени создания (свежие сверху), поэтому цепочку
 * возвращаем в порядке отправки. Читаем **все** передачи позиции, а не только
 * последнюю: между производственными участками маршрут проходит и складские
 * секции (Склад подготовки, Склад готовой продукции, К отгрузке), и их тоже
 * видно в журнале. Счётчик отправленных строк (`sendReadyTransfersViaUI`) для
 * этого не годится — он считает клики, а не передачи.
 *
 * Журнал показывает человекочитаемые имена участков (`to_section_name`), в
 * отличие от ready-таблицы, где виден только код. Таблица журнала отличается от
 * «Готово к передаче» колонкой получателя — по ней её и находим.
 */
export async function transferRouteChainViaUI(
  page: Page,
  sku: string,
  positionId: number,
  maxSteps = 100,
): Promise<string[]> {
  await page.goto("/transfers");
  await expect(page.getByRole("heading", { name: "Передачи между ГХП" })).toBeVisible({
    timeout: 10_000,
  });

  // «Журнал передач» — боковая панель: без неё таблицы истории нет в DOM.
  const journalOpener = page.locator('button[title="Открыть журнал передач"]');
  if ((await journalOpener.count()) > 0) {
    await journalOpener.click();
  }

  const historyTable = page
    .locator("table")
    .filter({ has: page.getByText("Получатель (Куда)", { exact: true }) });

  const search = page.getByPlaceholder("Поиск по ID, артикулу, участкам, № передачи…");
  await expect(search).toBeVisible({ timeout: 10_000 });
  await search.fill(sku);
  await search.press("Enter");

  const rows = historyTable.locator("tr", { hasText: sku });
  await expect(rows.first()).toBeVisible({ timeout: 20_000 });

  const destinations: string[] = [];
  const count = await rows.count();
  for (let i = 0; i < count && destinations.length < maxSteps; i++) {
    const cells = rows.nth(i).locator("td");
    const rowPositionId = ((await cells.first().textContent()) ?? "").trim().replace(/^#/, "");
    if (rowPositionId !== String(positionId)) continue;
    // Колонки: ID, Отправитель (Откуда), Получатель (Куда), Артикул, …
    // Ячейка участка — имя участка, под ним имя операции: берём первую строку.
    const cell = ((await cells.nth(2).innerText()) ?? "").trim();
    const to = cell.split("\n")[0]?.trim() ?? "";
    if (to) destinations.push(to);
  }
  // DOM отдаёт свежие сверху — разворачиваем в порядок отправки.
  return destinations.reverse();
}

/** Экранирование имени участка для имени-регекспа кнопки-плитки. */
function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Раскрыть свёрнутые группы задач на доске участка.
 *
 * Доска прячет задачи одного артикула/размера/операции в строку-группу
 * (`title="Раскрыть"`): пока группа свёрнута, строк задач с кнопкой
 * «Завершить» в DOM нет, и обход участков их не видит.
 */
export async function expandBoardGroupsViaUI(page: Page, limit = 10): Promise<void> {
  for (let attempt = 0; attempt < limit; attempt++) {
    const expander = page.locator('button[title="Раскрыть"]').first();
    if (!(await expander.isVisible().catch(() => false))) return;
    await expander.click();
  }
}

/** Завершить задачу на участке (доска /section-tasks/:id): «Завершить» → факт = плановое → сохранить. */
export async function completeSectionTaskViaUI(page: Page, sectionId: number, sku: string) {
  await page.goto(`/section-tasks/${sectionId}`);
  await expandBoardGroupsViaUI(page);
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

/** Завершить завершаемые задачи SKU на производственных участках.
 *
 * `sections` — необязательный список имён участков (маршрут конкретного теста):
 * обход только по ним экономит круги по заведомо пустым доскам.
 * Возвращает кол-во завершённых задач.
 */
export async function completeAllSectionTasksViaUI(
  page: Page,
  sku: string,
  sections?: string[],
): Promise<number> {
  await page.goto("/section-tasks");
  await expect(page.getByRole("heading", { name: "Участки" })).toBeVisible({ timeout: 10_000 });

  // Плитки производственных участков (SectionSwitcherTiles) — кнопки с бейджами
  // «ОЖ: N» / «ВР: N». Порядок обхода — с ненулевым бейджем вперёд, но САМ
  // БЕЙДЖ НЕ ФИЛЬТР: счётчики приходят отдельным summary-запросом и отстают от
  // доски (наблюдали 0/0 при живых задачах «В работе»), из-за чего участок
  // молча пропускался и проход завершался ни с чем.
  const tiles = page.getByRole("button").filter({ hasText: /ОЖ:|ВР:/ });
  await expect(tiles.first()).toBeVisible({ timeout: 20_000 });

  // Снимок плиток: поштучный `nth(i).textContent()` висит, когда список
  // перерисовывается.
  const tileTexts = (await tiles.allInnerTexts()).map((text) => text.replace(/\s+/g, " ").trim());
  const sectionNames: string[] = [];
  for (const text of tileTexts) {
    const name = text.split(/\s+ОЖ:/)[0].trim();
    if (name && !sectionNames.includes(name)) sectionNames.push(name);
  }
  const isBusy = (name: string) => {
    const text = tileTexts[sectionNames.indexOf(name)] ?? "";
    return /(?:ОЖ|ВР):\s*[1-9]/.test(text);
  };
  const walkOrder = [
    ...sectionNames.filter(isBusy),
    ...sectionNames.filter((name) => !isBusy(name)),
  ].filter((name) => !sections || sections.includes(name));

  let completed = 0;
  for (const sectionName of walkOrder) {
    // Кириллица: `\b` не работает (граница слова — только вокруг [A-Za-z0-9_]),
    // поэтому имя участка закрываем lookahead'ом «дальше не буква/цифра».
    const tile = page
      .getByRole("button", { name: new RegExp(`^${escapeRegExp(sectionName)}(?!\\S)`) })
      .first();
    if (!(await tile.isVisible().catch(() => false))) continue;

    await tile.click();
    await expect(page).toHaveURL(/\/section-tasks\/\d+/, { timeout: 15_000 }).catch(() => {});
    const sectionUrl = page.url();
    await expandBoardGroupsViaUI(page);

    // Внутри участка завершаем столько задач, сколько доступно за один заход:
    // после каждой мутации доска не рефетчится — перезагружаем страницу участка.
    const rowWaitMs = isBusy(sectionName) ? 6_000 : 2_500;
    for (let guard = 0; guard < 20; guard++) {
      const taskRow = page
        .locator("tr", { hasText: sku })
        .filter({ has: page.getByRole("button", { name: "Завершить" }) })
        .first();
      const found = await taskRow
        .waitFor({ state: "visible", timeout: rowWaitMs })
        .then(() => true, () => false);
      if (!found) break;
      const completeBtn = taskRow.getByRole("button", { name: "Завершить" }).first();
      if (!(await completeBtn.isEnabled().catch(() => false))) break;

      await completeBtn.click();
      const drawer = page.getByRole("dialog");
      await expect(drawer).toBeVisible({ timeout: 5_000 });

      // «В работе: N» — выданное на участок количество. Если 0, материал ещё не
      // пришёл (передача в пути): завершать рано — бэкенд вернёт «Complete quantity
      // exceeds issued quantity». Закрываем «Отмена» и идём дальше.
      const inWorkMatch = (await drawer.textContent())?.match(/В работе:\s*(\d+)/);
      const inWork = inWorkMatch ? Number(inWorkMatch[1]) : 0;
      if (inWork <= 0) {
        await drawer.getByRole("button", { name: "Отмена" }).click().catch(() => {});
        await expect(drawer).not.toBeVisible({ timeout: 8_000 }).catch(() => {});
        break;
      }

      const plannedBtn = drawer.getByRole("button", { name: /Плановое \(\d+\)/ });
      if ((await plannedBtn.count()) > 0) {
        await plannedBtn.click();
      } else {
        // Нет кнопки «Плановое» — берём выданное на участок количество.
        const goodInput = drawer.locator('input[type="number"]').first();
        await goodInput.fill(String(inWork));
      }

      await drawer.getByRole("button", { name: "Сохранить" }).click();
      // Страховка: сохранение могло упасть по валидации — закрываем «Отмена» и
      // не роняем весь проход.
      const saveOk = await expect(drawer).not.toBeVisible({ timeout: 8_000 }).then(
        () => true,
        () => false,
      );
      if (!saveOk) {
        await drawer.getByRole("button", { name: "Отмена" }).click().catch(() => {});
        await expect(drawer).not.toBeVisible({ timeout: 8_000 }).catch(() => {});
        break;
      }
      completed++;
      await page.goto(sectionUrl);
      await expandBoardGroupsViaUI(page);
    }

    await page.goto("/section-tasks");
    await expect(page.getByRole("heading", { name: "Участки" })).toBeVisible({ timeout: 10_000 });
    await expect(tiles.first()).toBeVisible({ timeout: 20_000 });
  }

  console.log(`[completeAllSectionTasks] SKU=${sku} completed=${completed}`);
  return completed;
}

/** Тикеты #88/#176: финальный контроль — материал доехал до «Отправлено» (SHIPPED).
 *
 * Терминальная секция (#136) вне оперативных остатков: ledger хранит полный
 * след, но баланс там не материализуется, поэтому остаток на «Отправлено»
 * проверить нечем. Доезд подтверждаем журналом передач: строкой, где
 * получатель — «Отправлено» (обычная передача «К отгрузке» → «Отправлено»).
 *
 * Строку привязываем к позициям **этого** прогона (`positionIds`), иначе шаг
 * зеленел бы на данных прошлых прогонов в накопительной dev-БД.
 */
export async function expectShippedViaUI(page: Page, sku: string, positionIds: number[]) {
  await page.goto("/transfers");
  await expect(page.getByRole("heading", { name: "Передачи между ГХП" })).toBeVisible({
    timeout: 10_000,
  });

  // «Журнал передач» — боковая панель: открываем её, иначе таблицы в DOM нет.
  const journalOpener = page.locator('button[title="Открыть журнал передач"]');
  if ((await journalOpener.count()) > 0) {
    await journalOpener.click();
  }

  // «Журнал передач» — вторая таблица страницы («Готово к передаче» — первая):
  // различаем по колонке получателя. По умолчанию выбрано «Все ГХП», поэтому
  // журнал не режется по группе хранения.
  const historyTable = page
    .locator("table")
    .filter({ has: page.getByText("Получатель (Куда)", { exact: true }) });

  const search = page.getByPlaceholder("Поиск по ID, артикулу, участкам, № передачи…");
  await expect(search).toBeVisible({ timeout: 10_000 });
  await search.fill(sku);
  await search.press("Enter");

  // Строка журнала: получатель — «Отправлено» (именно он, не статус «Отправлена»).
  const shippedRows = historyTable
    .locator("tr", { hasText: sku })
    .filter({ has: page.getByText("Отправлено", { exact: true }) });
  await expect(shippedRows.first()).toBeVisible({ timeout: 20_000 });

  // Журнал отсортирован по времени создания (свежие сверху), поэтому строки
  // текущего прогона попадают в отрисованное окно виртуализированной таблицы.
  const ownPositionIds = positionIds.map(String);
  const rows = await shippedRows.count();
  let shipped = 0;
  for (let i = 0; i < rows; i++) {
    const cells = shippedRows.nth(i).locator("td");
    const posId = ((await cells.first().textContent()) ?? "").trim().replace(/^#/, "");
    if (!ownPositionIds.includes(posId)) continue;
    // Кол-во — колонка «Кол-во» (6-я ячейка: ID, Откуда, Куда, Артикул, Размер, Кол-во).
    const qty = Number.parseFloat(((await cells.nth(5).textContent()) ?? "").replace(/\s/g, ""));
    expect(Number.isFinite(qty), `позиция #${posId}: кол-во в журнале не читается`).toBe(true);
    expect(qty, `позиция #${posId}: передано на «Отправлено» ${qty} шт`).toBeGreaterThan(0);
    shipped += qty;
  }
  expect(
    shipped,
    `ни одна позиция этого прогона (${positionIds.join(", ")}) не доехала до «Отправлено»`,
  ).toBeGreaterThan(0);
  console.log(`[expectShipped] SKU=${sku} на «Отправлено»: ${shipped} шт`);
}