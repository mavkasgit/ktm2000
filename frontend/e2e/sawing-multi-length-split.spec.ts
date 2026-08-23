import { test, expect } from "./fixtures";
import path from "path";

/**
 * @ui — Участок пилы: распил одной заготовки на несколько РАЗНЫХ
 * длин (ADR-0002/0003), видимый оператору сценарий на доске участка.
 *
 * Сетап ускорен через API/пресеты (сид, план из «Упаковочный план.xlsx»:
 * группа раскроя АТ-7121 — вход 150×2,7 м → выходы 0,9 м×350 + 1,8 м×50,
 * утверждение, запуск, передача сырья). В UI проверяется живое действие:
 *
 * 1. Доска пилы (/section-tasks/{SAWING}): карточка трансформации
 *    «150 шт × 2,7 м → 350 × 0,9 м + 50 × 1,8 м».
 * 2. «Внести факт»: порция 75 заготовок → прогресс по обоим выходам.
 * 3. Вторая порция до полного раскроя → кнопка «Завершить» исчезает.
 * 4. Контроль ledger и остатков: вход списан, выходы оприходованы по длинам.
 *
 * Требует запущенного dev-окружения: `npm run dev` из корня проекта.
 */

import {
  apiAccessTokenFromPage,
  apiAddRemainder,
  apiAddRouteStep,
  apiApplyChangeSet,
  apiBatchAssignRoute,
  apiCreateBareProduct,
  apiCreateRoute,
  apiGetActiveTemplate,
  apiGetOrCreateTechcard,
  apiGetPlanPositions,
  apiGetProductBySku,
  apiGetSectionByCode,
  apiImportExcel,
  apiResetAll,
  apiSeedData,
  BACKEND_URL,
  unwrapItems,
} from "./api-helpers";

const SAW_SKU = "АТ-7121";

/** Создать продукт без lengths, если его ещё нет (idempotent). */
async function apiEnsureBareProduct(sku: string): Promise<{ id: number; sku: string }> {
  try {
    return await apiGetProductBySku(sku);
  } catch {
    return await apiCreateBareProduct(sku);
  }
}

type PlanOutput = {
  row_number?: number | null;
  quantity?: string | number | null;
  dimensions?: { length_mm?: number } | null;
};

type PlanPositionDto = {
  id: number;
  source_sku: string;
  validation_status: string;
  route_id: number | null;
  quantity: string;
  input_quantity?: string | null;
  input_dimensions?: { length_mm?: number } | null;
  outputs?: PlanOutput[];
};

type BoardTask = {
  id: number;
  product_sku: string;
  status: string;
  transforms_dimensions?: boolean;
  input_quantity?: string | null;
  input_dimensions?: { length_mm?: number } | null;
  outputs?: PlanOutput[];
  outputs_progress?: Array<{
    row_number?: number | null;
    dimensions?: Record<string, unknown> | null;
    quantity: string;
    produced_quantity: string;
  }> | null;
  input_consumed_quantity?: string | null;
};

/** Числовое количество из строкового поля позиции/задачи. */
function qty(value: string | number | null | undefined): number {
  return parseFloat(String(value ?? "0")) || 0;
}

/** Метка длины как в UI: мм → «0,9 м». Используется в 5+ ассертах ниже. */
function lengthLabel(mm: number): string {
  return `${String(mm / 1000).replace(".", ",")} м`;
}

test.describe("@ui Пила: распил одной задачи на несколько разных длин", () => {
  // Сид/импорт на медленном бэкенде превышают дефолтные 30с хуков.
  test.setTimeout(240_000);

  test("трансформация 2,7 м → 0,9 м + 1,8 м порциями через доску пилы", async ({
    authenticatedPage,
  }) => {
    test.slow();

    // Тест-окружение (.env.test) требует авторизацию: логинимся первым делом
    // и патчим глобальный fetch — все api-helpers получают Bearer-токен.
    await authenticatedPage.goto("/");
    const token = await apiAccessTokenFromPage(authenticatedPage);
    expect(token).toBeTruthy();
    const originalFetch = globalThis.fetch.bind(globalThis);
    globalThis.fetch = async (input, init) => {
      const headers = new Headers(init?.headers);
      if (!headers.has("Authorization")) headers.set("Authorization", `Bearer ${token}`);
      return originalFetch(input, { ...init, headers });
    };

    // Свежее состояние: сброс планов и сид справочников/маршрутов.
    await apiResetAll();
    await apiSeedData();

    // ─── 1. API-setup: план с группой раскроя до состояния «сырьё у пилы» ────
    const product = await apiEnsureBareProduct(SAW_SKU);
    await apiGetOrCreateTechcard(product);

    const template = await apiGetActiveTemplate();
    const xlsPath = path.resolve(process.cwd(), "../Упаковочный план.xlsx");
    const importRes = await apiImportExcel(template.id, xlsPath);
    await apiApplyChangeSet(importRes.production_plan_id, importRes.change_set_id);

    const positions = (await apiGetPlanPositions(importRes.production_plan_id)) as PlanPositionDto[];
    const pos = positions.find(
      (p) =>
        p.source_sku === SAW_SKU &&
        p.validation_status === "valid" &&
        (p.outputs?.length ?? 0) >= 2 &&
        new Set((p.outputs ?? []).map((o) => o.dimensions?.length_mm)).size >= 2,
    );
    expect(pos).toBeDefined();
    const inputQty = qty(pos!.input_quantity);
    const inputLength = pos!.input_dimensions?.length_mm;
    expect(inputQty).toBeGreaterThan(0);
    expect(inputLength).toBeTruthy();

    // Короткий маршрут RAW_STOCK (транзит) → SAWING (production): шаг пилы без
    // operation_code наследует маркер трансформации от справочника участка.
    const raw = await apiGetSectionByCode("RAW_STOCK");
    const sawing = await apiGetSectionByCode("SAWING");
    const route = await apiCreateRoute(`E2E-SAW-SPLIT-${Date.now()}`);
    await apiAddRouteStep(route.id, {
      sequence: 1,
      section_id: raw.id,
      operation_code: null,
      operation_name: "Выдача сырья",
      stage_kind: "transit",
      storage_section_id: raw.id,
    });
    await apiAddRouteStep(route.id, {
      sequence: 2,
      section_id: sawing.id,
      operation_code: null,
      operation_name: "Резка профиля",
      is_final: true,
    });
    await apiBatchAssignRoute(importRes.production_plan_id, [pos!.id], route.id);

    await apiAddRemainder(
      product.id,
      raw.id,
      inputQty,
      "E2E saw-split UI: остаток заготовок под раскрой",
      { length_mm: inputLength! },
    );


    async function apiJson(pathname: string, method: "GET" | "POST" = "GET", payload?: unknown) {
      const res = await fetch(`${BACKEND_URL}${pathname}`, {
        method,
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: payload ? JSON.stringify(payload) : undefined,
      });
      if (!res.ok) {
        throw new Error(`${method} ${pathname} failed: ${res.status} ${await res.text()}`);
      }
      return res.json();
    }

    async function approveAndRelease() {
      await apiJson(
        `/api/production-plans/${importRes.production_plan_id}/positions/${pos!.id}/approve?force=true`,
        "POST",
      );
      // Создание батча только фиксирует позиции — задачи создаёт релиз батча.
      const batch = (await apiJson(
        `/api/production-plans/${importRes.production_plan_id}/release-batches`,
        "POST",
        { positions: [{ plan_position_id: pos!.id }] },
      )) as { id: number };
      await apiJson(`/api/release-batches/${batch.id}/release`, "POST");
    }
    async function boardTasks(sectionId: number): Promise<BoardTask[]> {
      const body = (await apiJson(`/api/shopfloor/sections/${sectionId}/board`)) as {
        tasks: BoardTask[];
      };
      return body.tasks ?? [];
    }

    await approveAndRelease();

    // Передача всего входа со склада на пилу: from_task берём из ready-строки,
    // to_task_id не нужен — цель на следующем шаге маршрута находится сама.
    const readyRows = unwrapItems<{ task_id: number; product_sku: string }>(
      (await apiJson("/api/transfers/ready")) as object,
    );
    const rawTask = readyRows.find((r) => r.product_sku === SAW_SKU);
    expect(rawTask).toBeDefined();
    await apiJson("/api/transfers", "POST", {
      from_task_id: rawTask!.task_id,
      quantity: inputQty,
      dimensions: { length_mm: inputLength },
      comment: "E2E saw-split UI: передача заготовок на пилу",
    });

    // ─── 2. Доска пилы: карточка трансформации видна ────────────────────────
    await authenticatedPage.goto(`/section-tasks/${sawing.id}`);
    const taskRow = authenticatedPage.locator("tr", { hasText: SAW_SKU }).first();
    await expect(taskRow).toBeVisible({ timeout: 15_000 });
    // Сводка операции: «{вход} шт × {длина} → …» — вход и все выходы позиции.
    await expect(taskRow.getByText(`${inputQty} шт × ${lengthLabel(inputLength!)}`)).toBeVisible({
      timeout: 15_000,
    });

    let task = (await boardTasks(sawing.id)).find((t) => t.product_sku === SAW_SKU);
    expect(task!.transforms_dimensions).toBe(true);
    expect(qty(task!.input_quantity)).toBe(inputQty);
    expect(task!.outputs?.length).toBeGreaterThanOrEqual(2);
    expect(["in_progress", "ready"]).toContain(task!.status);

    // ─── 3. «Внести факт»: первая порция ────────────────────────────────────
    const completeBtn = taskRow.getByRole("button", { name: "Завершить" }).first();
    await expect(completeBtn).toBeVisible({ timeout: 5_000 });
    await completeBtn.click();
    const drawer = authenticatedPage.getByRole("dialog");
    await expect(drawer).toBeVisible({ timeout: 5_000 });

    // Трансформационная шапка drawer'а: вход в заготовках, метка длины входа.
    await expect(drawer.getByText(/Вход:/)).toBeVisible();
    await expect(drawer.getByText(/Раскроено:/)).toBeVisible();
    await expect(drawer.getByText(lengthLabel(inputLength!))).toBeVisible();

    const portion1 = Math.floor(inputQty / 2);
    await drawer.locator('input[type="number"]').first().fill(String(portion1));
    await drawer.getByRole("button", { name: "Сохранить" }).click();
    await expect(drawer).not.toBeVisible({ timeout: 15_000 });

    // Доска не рефетчится после мутации — перезагружаем страницу.
    await authenticatedPage.reload();
    await expect(taskRow).toBeVisible({ timeout: 15_000 });

    // Прогресс по выходам: карточка рендерит ОДИН span с текстом
    // «0,9 м: N/350 · 1,8 м: M/50» (title содержит слэш, в отличие от сводки).
    const outLengths = [...new Set((task!.outputs ?? []).map((o) => o.dimensions?.length_mm))] as number[];
    const progressLine = taskRow.locator('span[title*="/"]').first();
    await expect(progressLine).toBeVisible({ timeout: 15_000 });
    for (const mm of outLengths) {
      await expect(progressLine).toContainText(lengthLabel(mm));
    }

    // Ledger: вход списан на порцию, оба выхода оприходованы пропорционально.
    task = (await boardTasks(sawing.id)).find((t) => t.product_sku === SAW_SKU);
    expect(Number(task!.input_consumed_quantity)).toBe(portion1);
    expect(task!.outputs_progress?.length).toBeGreaterThanOrEqual(2);
    for (const row of task!.outputs_progress ?? []) {
      const produced = Number(row.produced_quantity);
      expect(produced).toBeGreaterThan(0);
      expect(produced).toBeLessThanOrEqual(Number(row.quantity));
    }

    // ─── 4. Вторая порция: полный раскрой ───────────────────────────────────
    await expect(
      taskRow.getByRole("button", { name: "Завершить" }).first(),
    ).toBeEnabled({ timeout: 10_000 });
    await completeBtn.click();
    await expect(drawer).toBeVisible({ timeout: 5_000 });
    const rest = inputQty - portion1;
    // Кнопка «Плановое» на трансформации подставляет ПОЛНЫЙ вход, а не остаток —
    // вводим остаток вручную (превышение остатка бракуется бэкендом).
    await drawer.locator('input[type="number"]').first().fill(String(rest));
    await drawer.getByRole("button", { name: "Сохранить" }).click();
    await expect(drawer).not.toBeVisible({ timeout: 15_000 });

    await authenticatedPage.reload();
    await expect(taskRow).toBeVisible({ timeout: 15_000 });
    // UI: строка прогресса показывает полные итоги по каждой длине
    // («0,9 м: 350/350 · 1,8 м: 50/50»).
    const progressTotals = taskRow.locator('span[title*="/"]').first();
    await expect(progressTotals).toBeVisible({ timeout: 15_000 });
    for (const out of task!.outputs ?? []) {
      const mm = out.dimensions?.length_mm;
      if (!mm) continue;
      const total = Math.round(qty(out.quantity));
      await expect(progressTotals).toContainText(`${lengthLabel(mm)}: ${total}/${total}`);
    }

    // ─── 5. Контроль: вход раскрыл полностью, ledger и остатки по длинам ────
    task = (await boardTasks(sawing.id)).find((t) => t.product_sku === SAW_SKU);
    // Статус задачи считается от planned_quantity позиции (сумма строк Excel),
    // которая может отличаться от суммы выходов спецификации — контракт
    // распила проверяем по ledger: вход списан, все выходы оприходованы.
    expect(["completed", "partially_completed"]).toContain(task!.status);
    expect(Number(task!.input_consumed_quantity)).toBe(inputQty);
    for (const row of task!.outputs_progress ?? []) {
      expect(Number(row.produced_quantity)).toBe(Number(row.quantity));
    }

    // Остатки склада: размерные группы всех выходов оприходованы на пилу.
    const balancesRes = await fetch(
      `${BACKEND_URL}/api/stock/balance/by-product/${product.id}`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
    expect(balancesRes.ok).toBeTruthy();
    const balances = (await balancesRes.json()) as Array<{
      location_id: number;
      balance_qty: string;
      dimensions: { length_mm?: number } | null;
    }>;
    for (const out of task!.outputs ?? []) {
      const mm = out.dimensions?.length_mm;
      if (!mm) continue;
      const total = balances
        .filter((b) => b.dimensions?.length_mm === mm)
        .reduce((sum, b) => sum + Number(b.balance_qty), 0);
      expect(total).toBeCloseTo(qty(out.quantity), 6);
    }
  });
});
