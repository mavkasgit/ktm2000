import { test, expect } from "./fixtures";

/**
 * @ui-narrow — Участок пилы: распил одной заготовки на несколько РАЗНЫХ
 * длин (ADR-0002/0003), видимый оператору сценарий на доске участка.
 *
 * Сетап ускорен через API/пресеты (сид, бесфайловый импорт плана
 * `/imports/excel/simulate`: группа раскроя АТ-7121 — вход 150×2,7 м →
 * выходы 0,9 м×350 + 1,8 м×50, утверждение, запуск, передача сырья).
 * В UI проверяется живое действие:
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
  apiEnsureCatalogProduct,
  apiCreateRoute,
  apiGetActiveTemplate,
  apiGetPlanPositions,
  apiGetSectionByCode,
  apiResetAll,
  apiSeedData,
  apiSimulatePlanImport,
  BACKEND_URL,
  unwrapItems,
} from "./api-helpers";

const SAW_SKU = "АТ-7121";

/** Синхронизировать линейный продукт с нормальной длиной 2700 мм (idempotent). */
async function apiEnsureSawProduct(sku: string): Promise<{ id: number; sku: string }> {
  return apiEnsureCatalogProduct({ sku, name: "Стык с дюбелем 30 мм 2,7 анод. серебро матовы", lengthsMm: [2700] });
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

test.describe("@ui @ui-narrow Пила: распил одной задачи на несколько разных длин", () => {
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
    const product = await apiEnsureSawProduct(SAW_SKU);

    const template = await apiGetActiveTemplate();
    const importRes = await apiSimulatePlanImport(
      [
        {
          sku: SAW_SKU,
          name: "Стык с дюбелем 30 мм 2,7 анод. серебро матовы",
          raw_stock: 3250,
          color: "серебро",
          qty_per_27: 150,
          length_m: 2.7,
          packaging: "поф, красная этикетка РП 23*150",
          output_length_m: 0.9,
          output_qty: 350,
          west: 350,
          east: 0,
          kind: "ГП",
        },
        {
          sku: SAW_SKU,
          color: "серебро",
          output_length_m: 1.8,
          output_qty: 50,
          west: 50,
          east: 0,
          kind: "ГП",
        },
      ],
      { templateId: template.id },
    );
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
      // Форс требует причину в теле (ADR-0048): без неё approve вернёт 400.
      await apiJson(
        `/api/production-plans/${importRes.production_plan_id}/positions/${pos!.id}/approve?force=true`,
        "POST",
        { reason: "e2e: распил на несколько длин проверяем на заготовке из упаковочного плана" },
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
    // Строка ЗАДАЧИ, а не шапка группы: раскрой рисуется в поле «Операция»
    // строки задачи (`renderTaskRow`), шапка свёрнутой группы его не содержит.
    // Заодно раскрываем группы: группа с несколькими заданиями свёрнута по умолчанию.
    const taskRow = authenticatedPage
      .locator("tr")
      .filter({ has: authenticatedPage.getByRole("button", { name: "Завершить", exact: true }) })
      .filter({ hasText: SAW_SKU })
      .first();
    await expect(taskRow, "на доске пилы нет строки задачи-раскроя").toBeVisible({ timeout: 15_000 });
    // Доска показывает вход отдельной колонкой («Размер»), а раскрой — сводкой.
    await expect(taskRow.getByText(lengthLabel(inputLength!))).toBeVisible({ timeout: 15_000 });
    for (const output of pos!.outputs ?? []) {
      const mm = output.dimensions?.length_mm;
      if (!mm) continue;
      const label = `${String(mm / 1000).replace(".", ",")}×${qty(output.quantity)}`;
      await expect(taskRow).toContainText(label);
    }

    let task = (await boardTasks(sawing.id)).find((t) => t.product_sku === SAW_SKU);
    expect(task!.transforms_dimensions).toBe(true);
    expect(qty(task!.input_quantity)).toBe(inputQty);
    expect(task!.outputs?.length).toBeGreaterThanOrEqual(2);
    expect(["in_progress", "ready"]).toContain(task!.status);

    // ─── 3. «Внести факт»: первая порция ────────────────────────────────────
    const completeBtn = taskRow.getByRole("button", { name: "Завершить", exact: true }).first();
    await expect(completeBtn).toBeVisible({ timeout: 5_000 });
    await completeBtn.click();
    const drawer = authenticatedPage.getByRole("dialog");
    await expect(drawer).toBeVisible({ timeout: 5_000 });

    // Трансформационная шапка drawer'а: вход в заготовках, метка длины входа.
    await expect(drawer.getByText(/Вход:/)).toBeVisible();
    await expect(drawer.getByText(/Раскроено:/)).toBeVisible();
    await expect(drawer.getByText(lengthLabel(inputLength!))).toBeVisible();

    const portion1 = Math.floor(inputQty / 2);
    // Поле факта в drawer'е — `type="text" inputMode="numeric"` (#192); полей два
    // («Факт (раскроено заготовок)» и «Брак»), берём первое.
    await drawer.locator('input[inputmode="numeric"]').first().fill(String(portion1));
    await drawer.getByRole("button", { name: "Сохранить" }).click();
    await expect(drawer).not.toBeVisible({ timeout: 15_000 });

    // Доска не рефетчится после мутации — перезагружаем страницу.
    await authenticatedPage.reload();
    await expect(taskRow).toBeVisible({ timeout: 15_000 });

    // Прогресс по выходам с доски убран (ADR-0058): строку «0,9 м: N/350 · …»
    // больше не рендерят. Раскрой на доске уже проверен выше (столбик
    // «<длина>×<кол-во>»), а прогресс — по `outputs_progress` из API ниже.

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
      taskRow.getByRole("button", { name: "Завершить", exact: true }).first(),
    ).toBeEnabled({ timeout: 10_000 });
    await completeBtn.click();
    await expect(drawer).toBeVisible({ timeout: 5_000 });
    const rest = inputQty - portion1;
    // Кнопка «Плановое (N)» на трансформации подставляет ПОЛНЫЙ вход, а не
    // остаток — вводим остаток вручную (превышение остатка бракуется бэкендом).
    // Вторая порция — только с «+» (`470a9ce`): голое число означало бы «факт
    // станет 75», то есть уменьшение с уже записанных 75, и сервер отклонил бы
    // ввод с причиной у поля, оставив диалог открытым. Голым числом в этом
    // сценарии проверяется первая порция (см. выше), «+» — вторая.
    await drawer.locator('input[inputmode="numeric"]').first().fill(`+${rest}`);
    await drawer.getByRole("button", { name: "Сохранить" }).click();
    await expect(drawer).not.toBeVisible({ timeout: 15_000 });

    // ─── 5. Контроль: вход раскрыл полностью, ledger и остатки по длинам ────
    task = (await boardTasks(sawing.id)).find((t) => t.product_sku === SAW_SKU);
    // Статус задачи НЕ приравнивается к полному раскрою: он считается от
    // `planned_quantity` позиции (сумма строк Excel = 350 + 50 = 400), а вход
    // раскрыт на 150, поэтому задача уходит в `completed` по факту полного
    // входа (isTaskExecutionComplete) — но контракт распила проверяем по
    // ledger: вход списан целиком и все выходы оприходованы.
    expect(["completed", "partially_completed"]).toContain(task!.status);
    expect(Number(task!.input_consumed_quantity)).toBe(inputQty);
    expect(task!.outputs_progress?.length).toBeGreaterThanOrEqual(2);
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
