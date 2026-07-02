import { test, expect } from "./fixtures";
import fs from "fs";
import path from "path";

/**
 * E2E test for the explicit-transfer 2-step ritual:
 *
 *   1. **Send** (UI on /transfers) — auto-accepts inline, material
 *      arrives on the destination as ``cached_received_quantity``;
 *      the destination task flips ``waiting_previous → ready``.
 *   2. **Issue** (API on /shopfloor/tasks/{id}/issue) — material
 *      moves from ``cached_received_quantity`` to
 *      ``cached_in_work_quantity``; task status ``ready → in_progress``.
 *
 * Reject/partial-accept were removed from the model — see
 * ``docs/superpowers/plans/2026-07-01-explicit-transfers-mandatory.md``.
 *
 * The Issue step is driven through the API because the section-tasks
 * page exposes only a «Завершить» action — the dedicated
 * «Выдать в работу» button is on the roadmap. Once it lands, the
 * Issue step in this test can be promoted to a UI assertion.
 */

const BACKEND_URL = process.env.E2E_API_URL
  ? process.env.E2E_API_URL.replace(/\/api$/, "")
  : "http://localhost:8010";

// --- API helpers ----------------------------------------------------------

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
  const products = (await res.json()) as Array<{ id: number; sku: string }>;
  const product = products.find((p) => p.sku === sku);
  if (!product) {
    throw new Error(`Product not found with SKU: ${sku}`);
  }
  return product;
}

async function apiGetOrCreateTechcard(productId: number) {
  const res = await fetch(`${BACKEND_URL}/api/techcards`);
  if (!res.ok) {
    throw new Error(`Get techcards failed: ${res.statusText} (${res.status})`);
  }
  const techcards = (await res.json()) as Array<{ id: number; product_id: number; is_active: boolean }>;
  const existing = techcards.find((t) => t.product_id === productId && t.is_active);
  if (existing) {
    return existing;
  }
  const createRes = await fetch(`${BACKEND_URL}/api/techcards`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      product_id: productId,
      version: "v1",
      processing_type: "standart_processing",
      is_active: true,
    }),
  });
  if (!createRes.ok) {
    throw new Error(`Create techcard failed: ${createRes.statusText} (${createRes.status})`);
  }
  return createRes.json();
}

async function apiGetActiveTemplate() {
  const res = await fetch(`${BACKEND_URL}/api/import-templates`);
  if (!res.ok) {
    throw new Error(`Get templates failed: ${res.statusText} (${res.status})`);
  }
  const templates = (await res.json()) as Array<{ id: number; is_active: boolean }>;
  const template = templates.find((t) => t.is_active);
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

  const res = await fetch(
    `${BACKEND_URL}/api/imports/excel?template_id=${templateId}`,
    { method: "POST", body: formData },
  );
  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`Import excel failed: ${res.statusText} (${res.status}) - ${errText}`);
  }
  return res.json();
}

async function apiApplyChangeSet(planId: number, changeSetId: number) {
  const res = await fetch(
    `${BACKEND_URL}/api/production-plans/${planId}/change-sets/${changeSetId}/apply`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    },
  );
  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`Apply change set failed: ${res.statusText} (${res.status}) - ${errText}`);
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

async function apiGetActiveRoutes() {
  const res = await fetch(`${BACKEND_URL}/api/routes`);
  if (!res.ok) {
    throw new Error(`Get routes failed: ${res.statusText} (${res.status})`);
  }
  const routes = (await res.json()) as Array<{ id: number; is_active: boolean }>;
  return routes.filter((r) => r.is_active);
}

async function apiBatchAssignRoute(planId: number, positionIds: number[], routeId: number) {
  const res = await fetch(
    `${BACKEND_URL}/api/production-plans/${planId}/positions/batch-assign-route`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ position_ids: positionIds, route_id: routeId }),
    },
  );
  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`Batch assign route failed: ${res.statusText} (${res.status}) - ${errText}`);
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

async function apiGetSpgByCode(code: string) {
  const res = await fetch(`${BACKEND_URL}/api/spg`);
  if (!res.ok) {
    throw new Error(`Get SPG failed: ${res.statusText} (${res.status})`);
  }
  const spgs = (await res.json()) as Array<{ id: number; code: string }>;
  const spg = spgs.find((s) => s.code === code);
  if (!spg) {
    throw new Error(`SPG not found with code: ${code}`);
  }
  return spg;
}

async function apiGetSectionByCode(code: string) {
  const res = await fetch(`${BACKEND_URL}/api/sections`);
  if (!res.ok) {
    throw new Error(`Get sections failed: ${res.statusText} (${res.status})`);
  }
  const sections = (await res.json()) as Array<{ id: number; code: string }>;
  const section = sections.find((s) => s.code === code);
  if (!section) {
    throw new Error(`Section not found with code: ${code}`);
  }
  return section;
}

async function apiAddRemainder(spgId: number, productId: number, sectionId: number, quantity: number, reason: string) {
  const res = await fetch(`${BACKEND_URL}/api/spg/${spgId}/manual-operation`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      product_id: productId,
      section_id: sectionId,
      operation_type: "in",
      quantity,
      reason,
    }),
  });
  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`Add remainder failed: ${res.statusText} (${res.status}) - ${errText}`);
  }
  return res.json();
}

// --- Test -----------------------------------------------------------------

test.describe("Explicit transfer — 2-step ritual (Send + Issue)", () => {
  test.beforeEach(async () => {
    await apiResetAll();
    await apiSeedData();
  });

  test("send auto-accepts, then operator issues on destination", async ({
    authenticatedPage,
    request,
  }) => {
    test.slow();

    // 1. Подготовка данных: продукт, техкарта, импорт Excel, применение, маршрут
    const product2083 = await apiGetProductBySku("ЮП-2083");
    const techcard = await apiGetOrCreateTechcard(product2083.id);

    const template = await apiGetActiveTemplate();
    const xlsPath = path.resolve(process.cwd(), "../Упаковочный план.xlsx");
    const importRes = await apiImportExcel(template.id, xlsPath);
    await apiApplyChangeSet(importRes.production_plan_id, importRes.change_set_id);

    const positions = await apiGetPlanPositions(importRes.production_plan_id);
    const pos2083 = positions.find(
      (p: { source_sku: string; validation_status: string }) =>
        p.source_sku === "ЮП-2083" && p.validation_status === "valid",
    );
    expect(pos2083).toBeDefined();
    expect(pos2083.route_id).toBeTruthy();

    const activeRoutes = await apiGetActiveRoutes();
    expect(activeRoutes.length).toBeGreaterThan(0);
    void techcard;

    // 1a. Пополняем остатки на STOCK (Склад сырья, секция WH) — иначе диалог
    //     «Распределение остатков» показывает «Нет активных остатков...» и
    //     блокирует «Запустить в работу». Кол-во = плановое.
    const spgStock = await apiGetSpgByCode("STOCK");
    const sectionWh = await apiGetSectionByCode("WH");
    const planQty = Math.round(parseFloat(pos2083.quantity));
    await apiAddRemainder(
      spgStock.id,
      product2083.id,
      sectionWh.id,
      planQty,
      "E2E: начальный остаток сырья для transfers-auto-accept",
    );

    // 2. Утверждаем позицию на странице /planning (с обработкой диалога «Утвердить всё равно»)
    await authenticatedPage.goto("/planning");
    const planSearch = authenticatedPage.getByPlaceholder("Поиск");
    await expect(planSearch).toBeVisible({ timeout: 10_000 });
    await planSearch.fill("ЮП-2083");

    const planRow = authenticatedPage.locator(`#plan-position-${pos2083.id}`);
    await expect(planRow).toBeVisible({ timeout: 15_000 });
    const approveBtn = planRow.getByRole("button", { name: "Утвердить" });
    await expect(approveBtn).toBeVisible({ timeout: 5_000 });
    await approveBtn.click();

    const visibleConfirmBtn = authenticatedPage
      .locator("button", { hasText: "Утвердить всё равно" })
      .filter({ visible: true });
    try {
      await expect(visibleConfirmBtn).toBeVisible({ timeout: 3_000 });
      await visibleConfirmBtn.click();
    } catch {
      // no risk dialog
    }
    await expect(approveBtn).not.toBeVisible({ timeout: 10_000 });

    // 3. Берём в работу на /execution
    await authenticatedPage.goto("/execution");
    const execSearch = authenticatedPage.getByPlaceholder("Поиск");
    await expect(execSearch).toBeVisible({ timeout: 10_000 });
    await execSearch.fill("ЮП-2083");
    const execRow = authenticatedPage.locator("tr", { hasText: `#${pos2083.id}` }).first();
    await expect(execRow).toBeVisible({ timeout: 15_000 });
    const launchBtn = execRow.getByRole("button", { name: "Взять в работу" });
    await expect(launchBtn).toBeVisible({ timeout: 5_000 });
    await launchBtn.click();

    // Открывается диалог «Распределение остатков» — указываем количество
    // (нажимаем «Добрать со склада» / «Добрать остаток», чтобы перенести остатки
    // со STOCK на production-цепочку) и подтверждаем запуск.
    const allocationDialog = authenticatedPage.locator('div[role="dialog"]', { hasText: "Распределение остатков" });
    await expect(allocationDialog).toBeVisible({ timeout: 10_000 });
    const fillFromStockBtn = allocationDialog
      .getByRole("button", { name: /Добрать/ })
      .first();
    try {
      await expect(fillFromStockBtn).toBeVisible({ timeout: 3_000 });
      await fillFromStockBtn.click();
    } catch {
      const qtyInput = allocationDialog.locator('input[type="number"]').first();
      await expect(qtyInput).toBeVisible({ timeout: 5_000 });
      await qtyInput.fill(String(planQty));
    }
    const launchInDialog = allocationDialog.getByRole("button", { name: "Запустить в работу" });
    await expect(launchInDialog).toBeEnabled({ timeout: 10_000 });
    await launchInDialog.click();
    await expect(allocationDialog).not.toBeVisible({ timeout: 15_000 });

    await expect(execRow.locator("span").filter({ hasText: /^Запущен$/ })).toBeVisible({
      timeout: 15_000,
    });

    // 4. Завершаем 10 годных на первом production-участке через TaskActionDrawer
    //    Берём первый production-section для этой позиции.
    const sectionsRes = await fetch(`${BACKEND_URL}/api/sections`);
    const sections = (await sectionsRes.json()) as Array<{ id: number; kind: string }>;
    const firstSection = sections.find((s) => s.kind === "production");
    expect(firstSection).toBeDefined();

    await authenticatedPage.goto(`/section-tasks/${firstSection!.id}`);
    const firstRow = authenticatedPage.locator("tr", { hasText: "ЮП-2083" }).first();
    await expect(firstRow).toBeVisible({ timeout: 15_000 });
    const completeBtn = firstRow.getByRole("button", { name: "Завершить" }).first();
    await expect(completeBtn).toBeVisible({ timeout: 5_000 });
    await completeBtn.click();

    const drawer = authenticatedPage.getByRole("dialog");
    await expect(drawer).toBeVisible({ timeout: 5_000 });
    const goodInput = drawer.locator('input[type="number"]').first();
    await goodInput.fill("10");
    await drawer.getByRole("button", { name: "Сохранить" }).click();
    await expect(drawer).not.toBeVisible({ timeout: 10_000 });

    // 5. SEND на /transfers — auto-accepts по новой модели
    await authenticatedPage.goto("/transfers");
    await expect(
      authenticatedPage.getByRole("heading", { name: "Передачи между ГХП" }),
    ).toBeVisible({ timeout: 10_000 });

    const readyRow = authenticatedPage
      .locator("tr", { hasText: "ЮП-2083" })
      .filter({ hasText: "Готово к передаче" })
      .first();
    // «Готово к передаче» — текст в шапке, не в строке. Ищем строку с ЮП-2083 в таблице «ready».
    const readyRowBySku = authenticatedPage
      .locator("table", { hasText: "Готово к передаче" })
      .locator("tr", { hasText: "ЮП-2083" })
      .first();
    await expect(readyRowBySku).toBeVisible({ timeout: 10_000 });

    // Найдём инпут «qty» и кнопку «Передать» в этой строке
    const qtyInput = readyRowBySku.locator('input[type="number"]').first();
    await qtyInput.fill("10");
    const sendBtn = readyRowBySku.getByRole("button", { name: "Передать" });
    await expect(sendBtn).toBeVisible({ timeout: 5_000 });
    await sendBtn.click();

    // После успешной отправки строка должна исчезнуть из «Готово к передаче»
    await expect(readyRowBySku).not.toBeVisible({ timeout: 15_000 });

    // 6. Проверяем, что в «Истории» (правая колонка) появилась запись со статусом «Принята»
    //    — auto-accept произошёл inline внутри transfer_send.
    const historyRow = authenticatedPage
      .locator("table", { hasText: "История" })
      .locator("tr", { hasText: "ЮП-2083" })
      .first();
    await expect(historyRow).toBeVisible({ timeout: 10_000 });
    await expect(historyRow.locator("td").filter({ hasText: "Принята" })).toBeVisible({
      timeout: 5_000,
    });

    // 7. Достаём токен админа из cookies, чтобы дёрнуть /issue через API
    //    (UI-кнопки «Выдать в работу» пока нет, ритуал 2-step завязан на API).
    const cookies = await authenticatedPage.context().cookies();
    const accessCookie = cookies.find((c) => c.name === "access_token");
    const token = accessCookie?.value ?? "";

    // 8. Находим задачу-получатель на втором production-участке
    const secondSection = sections.filter((s) => s.kind === "production")[1];
    expect(secondSection).toBeDefined();

    // 9. Достаём board второго участка — там должна быть наша задача в ready
    const boardRes = await fetch(
      `${BACKEND_URL}/api/shopfloor/sections/${secondSection!.id}/board`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
    if (!boardRes.ok) {
      throw new Error(`Get board failed: ${boardRes.statusText} (${boardRes.status})`);
    }
    const board = (await boardRes.json()) as {
      tasks: Array<{ id: number; product_sku: string; status: string; cache: { received_quantity: string } }>;
    };
    const destinationTask = board.tasks.find(
      (t) => t.product_sku === "ЮП-2083" && t.cache.received_quantity !== "0",
    );
    expect(destinationTask).toBeDefined();
    expect(destinationTask!.status).toBe("ready");
    expect(parseFloat(destinationTask!.cache.received_quantity)).toBeGreaterThanOrEqual(10);

    // 10. ISSUE — оператор явно выдаёт в работу на destination
    const issueRes = await request.post(`${BACKEND_URL}/api/shopfloor/tasks/${destinationTask!.id}/issue`, {
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      data: { quantity: "10", idempotency_key: "e2e-2step:issue" },
    });
    expect(issueRes.status()).toBe(200);
    const issueBody = await issueRes.json();
    expect(issueBody.status).toBe("in_progress");

    // 11. Финальная проверка: задача в работе, in_work = 10
    const finalBoard = await fetch(
      `${BACKEND_URL}/api/shopfloor/sections/${secondSection!.id}/board`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
    const final = (await finalBoard.json()) as {
      tasks: Array<{ id: number; status: string; cache: { in_work_quantity: string } }>;
    };
    const finalTask = final.tasks.find((t) => t.id === destinationTask!.id);
    expect(finalTask).toBeDefined();
    expect(finalTask!.status).toBe("in_progress");
    expect(finalTask!.cache.in_work_quantity).toBe("10");
  });
});
