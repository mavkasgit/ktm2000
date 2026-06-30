import { test, expect } from "./fixtures";
import fs from "fs";
import path from "path";

const BACKEND_URL = process.env.E2E_API_URL 
  ? process.env.E2E_API_URL.replace(/\/api$/, '') 
  : "http://localhost:8010";

// --- API Helpers ---

async function apiSeedData() {
  const res = await fetch(`${BACKEND_URL}/api/routes-seed?force=true`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  if (!res.ok) {
    throw new Error(`Seed failed: ${res.statusText} (${res.status})`);
  }
  return res.json();
}

async function apiGetProductBySku(sku: string) {
  const res = await fetch(`${BACKEND_URL}/api/products?q=${encodeURIComponent(sku)}`);
  if (!res.ok) {
    throw new Error(`Get product by SKU failed: ${res.statusText} (${res.status})`);
  }
  const products = await res.json();
  const product = products.find((p: any) => p.sku === sku);
  if (!product) {
    throw new Error(`Product not found with SKU: ${sku}`);
  }
  return product;
}

async function apiCreateTechcard(productId: number) {
  const res = await fetch(`${BACKEND_URL}/api/techcards`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      product_id: productId,
      version: "v1",
      processing_type: "standart_processing",
      is_active: true,
    }),
  });
  if (!res.ok) {
    throw new Error(`Create techcard failed: ${res.statusText} (${res.status})`);
  }
  return res.json();
}

async function apiGetOrCreateTechcard(productId: number) {
  const res = await fetch(`${BACKEND_URL}/api/techcards`);
  if (!res.ok) {
    throw new Error(`Get techcards failed: ${res.statusText} (${res.status})`);
  }
  const techcards = await res.json();
  const existing = techcards.find((t: any) => t.product_id === productId && t.is_active);
  if (existing) {
    return existing;
  }
  return apiCreateTechcard(productId);
}

async function apiGetSpgs() {
  const res = await fetch(`${BACKEND_URL}/api/spg`);
  if (!res.ok) {
    throw new Error(`Get SPGs failed: ${res.statusText} (${res.status})`);
  }
  return res.json();
}

async function apiGetSections() {
  const res = await fetch(`${BACKEND_URL}/api/sections`);
  if (!res.ok) {
    throw new Error(`Get sections failed: ${res.statusText} (${res.status})`);
  }
  return res.json();
}

async function apiGetActiveTemplate() {
  const res = await fetch(`${BACKEND_URL}/api/import-templates`);
  if (!res.ok) {
    throw new Error(`Get templates failed: ${res.statusText} (${res.status})`);
  }
  const templates = await res.json();
  const template = templates.find((t: any) => t.is_active);
  if (!template) {
    throw new Error("No active import template found");
  }
  return template;
}

async function apiImportExcel(templateId: number, filePath: string) {
  const fileBuffer = fs.readFileSync(filePath);
  const blob = new Blob([fileBuffer], { type: "application/vnd.ms-excel" });
  
  const formData = new FormData();
  formData.append("file", blob, path.basename(filePath));
  formData.append("sheet_index", "0");
  formData.append("mode", "create_plan");
  formData.append("normalize_hanger_quantity", "true");

  const res = await fetch(`${BACKEND_URL}/api/imports/excel?template_id=${templateId}`, {
    method: "POST",
    body: formData,
  });

  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`Import excel failed: ${res.statusText} (${res.status}) - ${errText}`);
  }
  return res.json();
}

async function apiApplyChangeSet(planId: number, changeSetId: number) {
  const res = await fetch(`${BACKEND_URL}/api/production-plans/${planId}/change-sets/${changeSetId}/apply`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`Apply change set failed: ${res.statusText} (${res.status}) - ${errText}`);
  }
  return res.json();
}

async function apiGetActiveRoutes() {
  const res = await fetch(`${BACKEND_URL}/api/routes`);
  if (!res.ok) {
    throw new Error(`Get routes failed: ${res.statusText} (${res.status})`);
  }
  const routes = await res.json();
  return routes.filter((r: any) => r.is_active);
}

async function apiBatchAssignRoute(planId: number, positionIds: number[], routeId: number | null) {
  const res = await fetch(`${BACKEND_URL}/api/production-plans/${planId}/positions/batch-assign-route`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      position_ids: positionIds,
      route_id: routeId,
    }),
  });
  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`Batch assign route failed: ${res.statusText} (${res.status}) - ${errText}`);
  }
  return res.json();
}

async function apiGetPlanPositions(planId: number) {
  const res = await fetch(`${BACKEND_URL}/api/production-plans/${planId}/all-positions`);
  if (!res.ok) {
    throw new Error(`Get plan positions failed: ${res.statusText} (${res.status})`);
  }
  return res.json();
}

async function apiResetAll() {
  const res = await fetch(`${BACKEND_URL}/api/production-plans/reset-all`, {
    method: "POST",
  });
  if (!res.ok && res.status !== 404) {
    throw new Error(`Reset all failed: ${res.statusText} (${res.status})`);
  }
}

test.describe("Total workflow E2E - Step 2: Seed & Verify Remainders", () => {
  test.beforeEach(async () => {
    // Reset DB before each test to guarantee environment isolation
    await apiResetAll();
    // Seed reference data via API before the test
    await apiSeedData();
  });

  test("should seed, get existing product, ensure techcard, add remainders, and verify in SPG UI", async ({ authenticatedPage }) => {
    test.slow();

    // Логируем все ответы с ошибками от API бэкенда для отладки
    authenticatedPage.on("response", async (response) => {
      const url = response.url();
      if (url.includes("/api/") && response.status() >= 400) {
        console.log(`[API ERROR] ${response.status()} ${url}`);
        try {
          console.log("Error body:", JSON.stringify(await response.json()));
        } catch (e) {
          console.log("Error text:", await response.text());
        }
      }
    });

    // 1. Получаем существующие продукты
    const productYu = await apiGetProductBySku("ЮП-3270");
    const product2083 = await apiGetProductBySku("ЮП-2083");
    console.log("Found products: ЮП-3270 =", productYu.id, ", ЮП-2083 =", product2083.id);

    // 2. Убеждаемся, что у них есть техкарта
    const techcardYu = await apiGetOrCreateTechcard(productYu.id);
    const techcard2083 = await apiGetOrCreateTechcard(product2083.id);
    console.log("Techcards ensured");

    // 3. Получаем SPG и секции
    const spgs = await apiGetSpgs();
    const sections = await apiGetSections();

    // Ищем STOCK и PREP
    const spgStock = spgs.find((s: any) => s.code === "STOCK");
    const spgPrep = spgs.find((s: any) => s.code === "PREP");
    expect(spgStock).toBeDefined();
    expect(spgPrep).toBeDefined();

    const sectionWh = sections.find((s: any) => s.code === "WH");
    const sectionDrill = sections.find((s: any) => s.code === "DRILL");
    expect(sectionWh).toBeDefined();
    expect(sectionDrill).toBeDefined();

    // 4. Зачисляем остатки для ЮП-3270
    // 5000 шт в STOCK (секция WH)
    const resRaw = await fetch(`${BACKEND_URL}/api/spg/${spgStock.id}/manual-operation`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        product_id: productYu.id,
        section_id: sectionWh.id,
        operation_type: "in",
        quantity: 5000,
        reason: "Начальный избыток сырья",
      }),
    });
    expect(resRaw.ok).toBe(true);

    // 20 шт в PREP (секция DRILL)
    const resDrill = await fetch(`${BACKEND_URL}/api/spg/${spgPrep.id}/manual-operation`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        product_id: productYu.id,
        section_id: sectionDrill.id,
        operation_type: "in",
        quantity: 20,
        reason: "Задел полуфабрикатов",
      }),
    });
    expect(resDrill.ok).toBe(true);

    // 5. Переходим на страницу остатков /spg
    await authenticatedPage.goto("/spg");
    await expect(authenticatedPage.getByRole("heading", { name: "Группы хранения и производства" })).toBeVisible({ timeout: 10_000 });

    // По умолчанию выбран склад "Склад" (STOCK). Проверим остаток ЮП-3270
    const rowStock = authenticatedPage.locator("tr", { hasText: "ЮП-3270" }).first();
    await expect(rowStock).toBeVisible({ timeout: 10_000 });
    await expect(rowStock.locator("td").nth(1)).toHaveText("5000");

    // Переключаемся на ГХП "Подготовка"
    const prepBtn = authenticatedPage.getByRole("button", { name: /Подготовка/ });
    await expect(prepBtn).toBeVisible({ timeout: 5_000 });
    await prepBtn.click();

    // Проверим, что ЮП-3270 имеет доступный остаток 20
    const rowPrep = authenticatedPage.locator("tr", { hasText: "ЮП-3270" }).first();
    await expect(rowPrep).toBeVisible({ timeout: 10_000 });
    await expect(rowPrep.locator("td").nth(1)).toHaveText("20");

    console.log("Successfully verified initial remainders in STOCK and PREP for ЮП-3270");

    // 6. Импортируем Excel-план
    const template = await apiGetActiveTemplate();
    const xlsPath = path.resolve(process.cwd(), "../Упаковочный план.xlsx");
    console.log("Importing excel plan:", xlsPath);
    const importRes = await apiImportExcel(template.id, xlsPath);
    console.log("Import result:", importRes);

    // 7. Применяем изменения к плану
    const applyRes = await apiApplyChangeSet(importRes.production_plan_id, importRes.change_set_id);
    console.log("Apply changes result:", applyRes);

    // 8. Получаем позиции плана и проверяем/назначаем маршрут для ЮП-3270 и ЮП-2083
    const positions = await apiGetPlanPositions(importRes.production_plan_id);
    const posYu = positions.find((p: any) => p.source_sku === "ЮП-3270");
    const pos2083 = positions.find((p: any) => p.source_sku === "ЮП-2083");
    expect(posYu).toBeDefined();
    expect(pos2083).toBeDefined();

    const activeRoutes = await apiGetActiveRoutes();
    expect(activeRoutes.length).toBeGreaterThan(0);

    if (posYu.route_id === null) {
      console.log("Route for ЮП-3270 is null, assigning active route manually");
      await apiBatchAssignRoute(importRes.production_plan_id, [posYu.id], activeRoutes[0].id);
    }
    if (pos2083.route_id === null) {
      console.log("Route for ЮП-2083 is null, assigning active route manually");
      await apiBatchAssignRoute(importRes.production_plan_id, [pos2083.id], activeRoutes[0].id);
    }

    // 9. Переходим на страницу планирования в UI
    await authenticatedPage.goto("/planning");

    // Утверждаем ЮП-3270
    const planSearch = authenticatedPage.getByPlaceholder("Поиск");
    await expect(planSearch).toBeVisible({ timeout: 10_000 });
    await planSearch.fill("ЮП-3270");

    const planRowYu = authenticatedPage.locator(`#plan-position-${posYu.id}`);
    await expect(planRowYu).toBeVisible({ timeout: 15_000 });

    const approveBtnYu = planRowYu.getByRole("button", { name: "Утвердить" });
    await expect(approveBtnYu).toBeVisible({ timeout: 5_000 });
    await approveBtnYu.click();

    const visibleConfirmBtn = authenticatedPage.locator("button", { hasText: "Утвердить всё равно" }).filter({ visible: true });
    try {
      await expect(visibleConfirmBtn).toBeVisible({ timeout: 3_000 });
      await visibleConfirmBtn.click();
      console.log("Clicked 'Утвердить всё равно' in dialog for ЮП-3270");
      await expect(authenticatedPage.getByRole("alertdialog")).not.toBeVisible({ timeout: 5_000 });
    } catch (e) {
      console.log("No risk confirmation dialog appeared for ЮП-3270, proceeding");
    }
    await expect(approveBtnYu).not.toBeVisible({ timeout: 10_000 });

    // Утверждаем ЮП-2083
    await planSearch.fill("ЮП-2083");
    const planRow2083 = authenticatedPage.locator(`#plan-position-${pos2083.id}`);
    await expect(planRow2083).toBeVisible({ timeout: 15_000 });

    const approveBtn2083 = planRow2083.getByRole("button", { name: "Утвердить" });
    await expect(approveBtn2083).toBeVisible({ timeout: 5_000 });
    await approveBtn2083.click();

    try {
      await expect(visibleConfirmBtn).toBeVisible({ timeout: 3_000 });
      await visibleConfirmBtn.click();
      console.log("Clicked 'Утвердить всё равно' in dialog for ЮП-2083");
      await expect(authenticatedPage.getByRole("alertdialog")).not.toBeVisible({ timeout: 5_000 });
    } catch (e) {
      console.log("No risk confirmation dialog appeared for ЮП-2083, proceeding");
    }
    await expect(approveBtn2083).not.toBeVisible({ timeout: 10_000 });

    // 10. Переходим на страницу контроля выполнения в UI
    await authenticatedPage.goto("/execution");
    const execSearch = authenticatedPage.getByPlaceholder("Поиск");
    await expect(execSearch).toBeVisible({ timeout: 10_000 });

    // Взять в работу ЮП-3270 (это спишет остатки)
    await execSearch.fill("ЮП-3270");
    const execRowYu = authenticatedPage.locator("tr", { hasText: `#${posYu.id}` }).first();
    await expect(execRowYu).toBeVisible({ timeout: 15_000 });

    const launchBtnYu = execRowYu.getByRole("button", { name: "Взять в работу" });
    await expect(launchBtnYu).toBeVisible({ timeout: 5_000 });
    await launchBtnYu.click();

    const statusBadgeYu = execRowYu.locator("span").filter({ hasText: /^Запущен$/ });
    await expect(statusBadgeYu).toBeVisible({ timeout: 15_000 });
    console.log("Successfully released ЮП-3270");

    // Взять в работу ЮП-2083 (без остатков сырья, готов к сквозному проходу)
    await execSearch.fill("ЮП-2083");
    const execRow2083 = authenticatedPage.locator("tr", { hasText: `#${pos2083.id}` }).first();
    await expect(execRow2083).toBeVisible({ timeout: 15_000 });

    const launchBtn2083 = execRow2083.getByRole("button", { name: "Взять в работу" });
    await expect(launchBtn2083).toBeVisible({ timeout: 5_000 });
    await launchBtn2083.click();

    const statusBadge2083 = execRow2083.locator("span").filter({ hasText: /^Запущен$/ });
    await expect(statusBadge2083).toBeVisible({ timeout: 15_000 });
    console.log("Successfully released ЮП-2083");

    // 11. Проверяем, что остатки сырья STOCK для ЮП-3270 уменьшились (5000 -> 3980)
    await authenticatedPage.goto("/spg");
    await expect(authenticatedPage.getByRole("heading", { name: "Группы хранения и производства" })).toBeVisible({ timeout: 10_000 });

    const stockTabBtn = authenticatedPage.getByRole("button", { name: /^Склад \(\d+\)$/ });
    await stockTabBtn.click();

    const rowStockAfter = authenticatedPage.locator("tr", { hasText: "ЮП-3270" }).first();
    await expect(rowStockAfter).not.toBeVisible({ timeout: 10_000 });
    console.log("Successfully verified that the stock remainder was fully consumed (row is no longer visible)");

    // 12. Выполняем сквозной проход для ЮП-2083 (у нее нет автосписаний, так что manual-pass пройдет)
    await authenticatedPage.goto("/execution");
    await expect(execSearch).toBeVisible({ timeout: 10_000 });
    await execSearch.fill("ЮП-2083");
    await expect(execRow2083).toBeVisible({ timeout: 15_000 });

    const manualPassBtn = execRow2083.locator("button[title='Сквозной проход']");
    await expect(manualPassBtn).toBeVisible({ timeout: 5_000 });
    await manualPassBtn.click();

    const selectTrigger = authenticatedPage.getByRole("combobox");
    await expect(selectTrigger).toBeVisible({ timeout: 5_000 });
    await selectTrigger.click();

    const optionComplete = authenticatedPage.getByRole("option", { name: "Полное завершение задачи" });
    await expect(optionComplete).toBeVisible({ timeout: 5_000 });
    await optionComplete.click();

    const submitPassBtn = authenticatedPage.getByRole("button", { name: "Выполнить" });
    await expect(submitPassBtn).toBeVisible({ timeout: 5_000 });
    await submitPassBtn.click();

    // Ждем, пока статус сменится на "Завершён"
    const statusCompleted = execRow2083.locator("span").filter({ hasText: /^Завершён$/ });
    await expect(statusCompleted).toBeVisible({ timeout: 15_000 });
    console.log("Successfully completed task through manual route pass for ЮП-2083");

    // 13. Проверяем, что готовая продукция сдана на склад готовой продукции FG в количестве, равном объему позиции
    await authenticatedPage.goto("/spg");
    await expect(authenticatedPage.getByRole("heading", { name: "Группы хранения и производства" })).toBeVisible({ timeout: 10_000 });

    const fgTabBtn = authenticatedPage.getByRole("button", { name: /Склад готовой продукции/ });
    await expect(fgTabBtn).toBeVisible({ timeout: 5_000 });
    await fgTabBtn.click();

    const rowFgAfter = authenticatedPage.locator("tr", { hasText: "ЮП-2083" }).first();
    await expect(rowFgAfter).toBeVisible({ timeout: 10_000 });
    const expectedQty = Math.round(parseFloat(pos2083.quantity)).toString();
    await expect(rowFgAfter.locator("td").nth(1)).toHaveText(expectedQty);
    console.log(`Successfully verified finished goods release on FG: ${expectedQty} pcs for ЮП-2083`);

    // 14. Переходим в /transfers и убеждаемся, что записи о переводах отображаются
    await authenticatedPage.goto("/transfers");
    await expect(authenticatedPage.getByRole("heading", { name: "Передачи между ГХП" })).toBeVisible({ timeout: 10_000 });

    // Проверяем, что в журнале передач появился наш артикул ЮП-2083
    const historyRow = authenticatedPage.locator("tr", { hasText: "ЮП-2083" }).first();
    await expect(historyRow).toBeVisible({ timeout: 10_000 });
    console.log("Successfully verified transfer records in history for ЮП-2083");
  });

  test("should check material shortage strategies, partial GHP/STOCK loading and scrap replenishment", async ({ authenticatedPage }) => {
    test.slow();

    // Логируем все ответы с ошибками от API бэкенда для отладки
    authenticatedPage.on("response", async (response) => {
      const url = response.url();
      if (url.includes("/api/") && response.status() >= 400) {
        console.log(`[API ERROR] ${response.status()} ${url}`);
        try {
          console.log("Error body:", JSON.stringify(await response.json()));
        } catch (e) {
          console.log("Error text:", await response.text());
        }
      }
    });

    // 1. Получаем продукты и настраиваем техкарты/маршруты
    const productYu = await apiGetProductBySku("ЮП-3270");
    const techcardYu = await apiGetOrCreateTechcard(productYu.id);

    const spgs = await apiGetSpgs();
    const sections = await apiGetSections();

    const spgStock = spgs.find((s: any) => s.code === "STOCK");
    const spgPrep = spgs.find((s: any) => s.code === "PREP");
    const spgAnod = spgs.find((s: any) => s.code === "ANOD");
    const spgWip = spgs.find((s: any) => s.code === "WIP");

    const sectionWh = sections.find((s: any) => s.code === "WH");
    const sectionDrill = sections.find((s: any) => s.code === "DRILL");
    const sectionAnod = sections.find((s: any) => s.code === "ANOD");
    const sectionWipWh = sections.find((s: any) => s.code === "WIP_WH");

    expect(spgStock).toBeDefined();
    expect(spgPrep).toBeDefined();
    expect(spgAnod).toBeDefined();
    expect(spgWip).toBeDefined();

    expect(sectionWh).toBeDefined();
    expect(sectionDrill).toBeDefined();
    expect(sectionAnod).toBeDefined();
    expect(sectionWipWh).toBeDefined();

    // 2. Начисляем ручные остатки для ЮП-3270:
    // - STOCK: 50 шт
    // - PREP: 20 шт
    // - ANOD: 30 шт
    // - WIP: 40 шт
    const initialRemainders = [
      { spgId: spgStock.id, sectionId: sectionWh.id, qty: 50, comment: "STOCK E2E" },
      { spgId: spgPrep.id, sectionId: sectionDrill.id, qty: 20, comment: "PREP E2E" },
      { spgId: spgAnod.id, sectionId: sectionAnod.id, qty: 30, comment: "ANOD E2E" },
      { spgId: spgWip.id, sectionId: sectionWipWh.id, qty: 40, comment: "WIP E2E" },
    ];

    for (const rem of initialRemainders) {
      const res = await fetch(`${BACKEND_URL}/api/spg/${rem.spgId}/manual-operation`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          product_id: productYu.id,
          section_id: rem.sectionId,
          operation_type: "in",
          quantity: rem.qty,
          reason: rem.comment,
        }),
      });
      expect(res.ok).toBe(true);
    }

    // 3. Импортируем Excel-план (чтобы у нас была позиция ЮП-3270 на 60 деталей)
    const template = await apiGetActiveTemplate();
    const xlsPath = path.resolve(process.cwd(), "../Упаковочный план.xlsx");
    const importRes = await apiImportExcel(template.id, xlsPath);
    await apiApplyChangeSet(importRes.production_plan_id, importRes.change_set_id);

    // Получаем позицию ЮП-3270 объемом 60 деталей (она идеально подходит под наш тест)
    const positions = await apiGetPlanPositions(importRes.production_plan_id);
    const posYu = positions.find((p: any) => p.source_sku === "ЮП-3270" && Math.round(parseFloat(p.quantity)) === 540 && p.validation_status === "valid");
    expect(posYu).toBeDefined();

    const activeRoutes = await apiGetActiveRoutes();
    if (posYu.route_id === null) {
      await apiBatchAssignRoute(importRes.production_plan_id, [posYu.id], activeRoutes[0].id);
    }

    // 4. Утверждаем позицию на 60 деталей на странице планирования
    await authenticatedPage.goto("/planning");
    const planSearch = authenticatedPage.getByPlaceholder("Поиск");
    await expect(planSearch).toBeVisible({ timeout: 10_000 });
    await planSearch.fill("ЮП-3270");

    const planRowYu = authenticatedPage.locator(`#plan-position-${posYu.id}`);
    await expect(planRowYu).toBeVisible({ timeout: 15_000 });

    const approveBtnYu = planRowYu.getByRole("button", { name: "Утвердить" });
    await expect(approveBtnYu).toBeVisible({ timeout: 5_000 });
    await approveBtnYu.click();

    // Если всплывет подтверждение рисков
    const visibleConfirmBtn = authenticatedPage.locator("button", { hasText: "Утвердить всё равно" }).filter({ visible: true });
    try {
      await expect(visibleConfirmBtn).toBeVisible({ timeout: 3_000 });
      await visibleConfirmBtn.click();
    } catch (e) {}

    await expect(approveBtnYu).not.toBeVisible({ timeout: 10_000 });

    // 5. Переходим на диспетчеризацию и берем в работу (release)
    await authenticatedPage.goto("/execution");
    const execSearch = authenticatedPage.getByPlaceholder("Поиск");
    await expect(execSearch).toBeVisible({ timeout: 10_000 });
    await execSearch.fill("ЮП-3270");

    const execRowYu = authenticatedPage.locator("tr", { hasText: `#${posYu.id}` }).first();
    await expect(execRowYu).toBeVisible({ timeout: 15_000 });

    const launchBtnYu = execRowYu.getByRole("button", { name: "Взять в работу" });
    await expect(launchBtnYu).toBeVisible({ timeout: 5_000 });
    await launchBtnYu.click();

    const statusBadgeYu = execRowYu.locator("span").filter({ hasText: /^Запущен$/ });
    await expect(statusBadgeYu).toBeVisible({ timeout: 15_000 });

    // 6. Переходим на первый участок (WH) и берем в работу с нехваткой (дефицитом)
    // Задача требует 400 деталей, а на STOCK лежит только 50 деталей.
    await authenticatedPage.goto(`/section-tasks/${sectionWh.id}`);
    const whTaskRow = authenticatedPage.locator('tr:has-text("ЮП-3270")').first();
    await expect(whTaskRow).toBeVisible({ timeout: 15_000 });

    const completeWhBtn = whTaskRow.getByRole("button", { name: "Завершить" });
    await expect(completeWhBtn).toBeVisible({ timeout: 5_000 });
    await completeWhBtn.click();
    const drawer = authenticatedPage.getByRole("dialog");
    try {
      await expect(drawer).toBeVisible({ timeout: 2_000 });
    } catch (e) {
      console.log("Диалог не открылся с первого клика на WH, кликаем повторно...");
      await completeWhBtn.click();
      await expect(drawer).toBeVisible({ timeout: 5_000 });
    }

    // Вводим факт: 400 (вызывает нехватку)
    const goodInput = drawer.locator('input[type="number"]').first();
    await expect(goodInput).toBeVisible({ timeout: 5_000 });
    await goodInput.click();
    await goodInput.fill("400");
    await expect(goodInput).toHaveValue("400", { timeout: 5_000 });

    // Проверяем, что блок нехватки материалов виден
    const shortageBlock = authenticatedPage.getByText("Нехватка материалов").first();
    await expect(shortageBlock).toBeVisible({ timeout: 5_000 });

    // Выбираем стратегию "Зачислить минус на участок" (negative_remainder)
    await authenticatedPage.getByText("Зачислить минус на участок").click();

    const saveWhBtn = drawer.getByRole("button", { name: "Сохранить" });
    await saveWhBtn.click();
    await expect(drawer).not.toBeVisible({ timeout: 10_000 });

    // 7. Проверим, что остаток на STOCK стал равен -350
    await authenticatedPage.goto("/spg");
    await expect(authenticatedPage.getByRole("heading", { name: "Группы хранения и производства" })).toBeVisible({ timeout: 10_000 });

    const stockSpgBtn = authenticatedPage.getByRole("button", { name: /^Склад \(\d+\)$/ });
    await stockSpgBtn.click();

    const rowStock = authenticatedPage.locator("tr", { hasText: "ЮП-3270" }).first();
    await expect(rowStock).toBeVisible({ timeout: 10_000 });
    await expect(rowStock.locator("td").nth(1)).toHaveText("-350");

    // 8. Проверим FIFO-компенсацию минусового остатка:
    // Начисляем приход 500 шт на STOCK
    const resComp = await fetch(`${BACKEND_URL}/api/spg/${spgStock.id}/manual-operation`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        product_id: productYu.id,
        section_id: sectionWh.id,
        operation_type: "in",
        quantity: 500,
        reason: "Пополнение для схлопывания",
      }),
    });
    expect(resComp.ok).toBe(true);

    // Обновим страницу остатков и проверим, что остаток стал 150 штук
    const refreshBtn = authenticatedPage.getByRole("button", { name: "Обновить" }).first();
    await refreshBtn.click();
    await expect(rowStock.locator("td").nth(1)).toHaveText("150");

    // 9. Переходим на второй участок (DRILL), принимаем трансфер и проверяем расход остатка ГХП
    // Принимаем перевод
    await authenticatedPage.goto("/transfers");
    const transferRow = authenticatedPage.locator('tr:has-text("ЮП-3270")').first();
    await expect(transferRow).toBeVisible({ timeout: 10_000 });
    const acceptTransferBtn = transferRow.getByRole("button", { name: "Принять" });
    await expect(acceptTransferBtn).toBeVisible({ timeout: 5_000 });
    await acceptTransferBtn.click();
    const acceptDialog = authenticatedPage.getByRole("dialog");
    try {
      await expect(acceptDialog).toBeVisible({ timeout: 2_000 });
    } catch (e) {
      console.log("Диалог не открылся с первого клика на Принять, кликаем повторно...");
      await acceptTransferBtn.click();
      await expect(acceptDialog).toBeVisible({ timeout: 5_000 });
    }
    await acceptDialog.getByRole("button", { name: "Подтвердить" }).click();
    await expect(acceptDialog).not.toBeVisible({ timeout: 10_000 });

    // Заходим на доску DRILL, начинаем задачу (это спишет 20 шт из PREP)
    await authenticatedPage.goto(`/section-tasks/${sectionDrill.id}`);
    const drillTaskRow = authenticatedPage.locator('tr:has-text("ЮП-3270")').first();
    await expect(drillTaskRow).toBeVisible({ timeout: 10_000 });

    // Берем в работу/начинаем задачу
    const startDrillBtn = drillTaskRow.getByRole("button", { name: "Начать" });
    await expect(startDrillBtn).toBeVisible({ timeout: 5_000 });
    await startDrillBtn.click();

    // Проверяем, что свободные остатки PREP уменьшились до 0
    await authenticatedPage.goto("/spg");
    await expect(authenticatedPage.getByRole("heading", { name: "Группы хранения и производства" })).toBeVisible({ timeout: 10_000 });

    const prepSpgBtn = authenticatedPage.getByRole("button", { name: /Подготовка/ });
    await prepSpgBtn.click();

    // Записей ЮП-3270 быть не должно или остаток равен 0
    const rowPrep = authenticatedPage.locator("tr", { hasText: "ЮП-3270" }).first();
    try {
      await expect(rowPrep).not.toBeVisible({ timeout: 3_000 });
    } catch (e) {
      await expect(rowPrep.locator("td").nth(1)).toHaveText("0");
    }

    // 10. Завершаем задачу на DRILL с браком (10 шт уходят в брак)
    await authenticatedPage.goto(`/section-tasks/${sectionDrill.id}`);
    const completeDrillBtn = drillTaskRow.getByRole("button", { name: "Завершить" });
    await expect(completeDrillBtn).toBeVisible({ timeout: 5_000 });
    await completeDrillBtn.click();
    try {
      await expect(drawer).toBeVisible({ timeout: 2_000 });
    } catch (e) {
      console.log("Диалог не открылся с первого клика на DRILL, кликаем повторно...");
      await completeDrillBtn.click();
      await expect(drawer).toBeVisible({ timeout: 5_000 });
    }

    const goodInputDrill = drawer.locator('input[type="number"]').first();
    await expect(goodInputDrill).toBeVisible({ timeout: 5_000 });
    await goodInputDrill.click();
    await goodInputDrill.fill("410");
    await expect(goodInputDrill).toHaveValue("410", { timeout: 5_000 });

    const scrapInputDrill = drawer.locator('input[type="number"]').nth(1);
    await expect(scrapInputDrill).toBeVisible({ timeout: 5_000 });
    await scrapInputDrill.click();
    await scrapInputDrill.fill("10");
    await expect(scrapInputDrill).toHaveValue("10", { timeout: 5_000 });

    const reasonSelect = drawer.locator("select").first();
    try {
      await reasonSelect.selectOption({ label: "Брак производства" });
    } catch (e) {
      // Если селект сделан через Select UI компоненты
      const selectTrigger = drawer.getByRole("combobox").first();
      await selectTrigger.click();
      await authenticatedPage.getByRole("option").first().click();
    }

    await drawer.getByRole("button", { name: "Сохранить" }).click();
    await expect(drawer).not.toBeVisible({ timeout: 10_000 });

    // 11. Списываем брак в scrap окончательно
    await authenticatedPage.goto("/spg");
    const defectsTabBtn = authenticatedPage.getByRole("button", { name: /Зарегистрированный брак/ }).first();
    await expect(defectsTabBtn).toBeVisible({ timeout: 5_000 });
    
    // Ищем строку дефекта
    const defectRow = authenticatedPage.locator("tr:has-text('ЮП-3270')").first();
    await expect(defectRow).toBeVisible({ timeout: 10_000 });

    const decideBtn = defectRow.getByRole("button", { name: "Решение" });
    await expect(decideBtn).toBeVisible({ timeout: 5_000 });
    await decideBtn.click();

    const decideDialog = authenticatedPage.getByRole("dialog");
    await expect(decideDialog).toBeVisible({ timeout: 5_000 });

    // Выбираем "Списать брак"
    const decideSelect = decideDialog.getByRole("combobox");
    await decideSelect.click();
    await authenticatedPage.getByRole("option", { name: "Списать брак" }).click();

    await decideDialog.getByRole("button", { name: "Применить решение" }).click();
    await expect(decideDialog).not.toBeVisible({ timeout: 10_000 });

    // 12. Выпускаем дополнительное задание (довыпуск) на 10 деталей
    // Для этого программно создаем новую позицию плана с объемом 10
    const activeRoutesForYu = await apiGetActiveRoutes();
    const demoRes = await fetch(`${BACKEND_URL}/api/demo/test-runs/full-route`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        initial_quantity: 10,
        techcard_id: techcardYu.id,
        production_plan_id: importRes.production_plan_id,
        stage_preset: "before_approve",
        route_id: activeRoutesForYu[0].id,
      }),
    });
    expect(demoRes.ok).toBe(true);

    const demoData = await demoRes.json();
    const newPosId = demoData.plan_position_id;

    // Идем на страницу планирования и утверждаем эту новую позицию (довыпуск)
    await authenticatedPage.goto("/planning");
    await expect(planSearch).toBeVisible({ timeout: 10_000 });
    await planSearch.fill("ЮП-3270");

    const newPlanRow = authenticatedPage.locator(`#plan-position-${newPosId}`);
    await expect(newPlanRow).toBeVisible({ timeout: 15_000 });

    const newApproveBtn = newPlanRow.getByRole("button", { name: "Утвердить" });
    await expect(newApproveBtn).toBeVisible({ timeout: 5_000 });
    await newApproveBtn.click();

    // Confirm risks if visible
    const newConfirmBtn = authenticatedPage.locator("button", { hasText: "Утвердить всё равно" }).filter({ visible: true });
    try {
      await expect(newConfirmBtn).toBeVisible({ timeout: 3_000 });
      await newConfirmBtn.click();
    } catch (e) {}

    await expect(newApproveBtn).not.toBeVisible({ timeout: 10_000 });
    console.log("Successfully verified shortage, FIFO compensation, GHP consumption, and scrap replenishment");
  });
});
