import { test, expect } from "./fixtures";

/**
 * E2E test for the explicit-transfer ritual under the auto-issue model:
 *
 *   1. **Send** (UI on /transfers) — auto-accepts inline: material arrives
 *      on the destination, the destination task flips
 *      `waiting_previous → ready → in_progress` and the received material
 *      is immediately issued to work (`issued == received`), because the
 *      section-tasks page has no dedicated «Выдать в работу» button.
 *   2. The spec sends material onto the next stage of the route: the task of
 *      the stage that holds the material is completed, so its output becomes
 *      «Готово к передаче»; the operator sends it from the ready table.
 *
 * Почему не со склада, как было до #282
 * -------------------------------------
 * Прежняя редакция ждала на «Передачах» складскую строку «Готово к
 * передаче»: до #282 запуск не забирал материал со склада сам. С #282
 * (`c2107f4f`, окно подбора источника в «Взять в работу») выдача со склада
 * — часть запуска, складская строка остаётся с нулём к передаче и больше
 * не появляется. Поэтому передача, которую отправляет оператор, — это
 * результат завершённой задачи участка на следующий этап маршрута.
 * Складская выдача проверяется отдельно: она видна в «Журнале передач»
 * принятой (первая передача позиции), и это тот же auto-accept.
 *
 * План сетапится бесфайлово (`/imports/excel/simulate`) — xlsx не храним.
 */

import {
  apiAccessTokenFromPage,
  apiAddRemainder,
  apiApplyChangeSet,
  apiGetActiveRoutes,
  apiGetActiveTemplate,
  apiGetPlanPositions,
  apiGetProductBySku,
  apiGetSectionByCode,
  apiGetSections,
  apiResetAll,
  apiEnsureTestProducts,
  apiSeedData,
  apiSimulatePlanImport,
  BACKEND_URL,
  E2E_SECTION,
  unwrapItems,
} from "./api-helpers";
import {
  completeAllSectionTasksViaUI,
  confirmForceApproveViaUI,
  confirmProductionLaunchViaUI,
  sendReadyTransfersViaUI,
  transferRouteChainViaUI,
} from "./ui-helpers";

/** Строка позиции плана, нужная этому спеку (api-helpers отдаёт сырой JSON). */
type PlanPositionRow = {
  source_sku: string;
  validation_status: string;
  input_dimensions?: { length_mm?: number } | null;
};

/** Строка «Готово к передаче» — поля, которые читает этот спек. */
type ReadyRow = {
  product_sku?: string;
  plan_position_id?: number | null;
  transferable_quantity?: string | number | null;
  next_section_id?: number | null;
};

/** Задача доски участка — ровно то, что проверяет auto-accept. */
type BoardTask = {
  id: number;
  product_sku: string;
  status: string;
  cache: { received_quantity: string; issued_quantity: string };
};

const SKU = "ЮП-2083";

async function fetchReadyRows(token: string): Promise<ReadyRow[]> {
  const res = await fetch(`${BACKEND_URL}/api/transfers/ready?limit=500`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    throw new Error(`Get ready transfers failed: ${res.statusText} (${res.status})`);
  }
  return unwrapItems<ReadyRow>(await res.json());
}

/**
 * Строки «Готово к передаче» по нашему артикулу — с ожиданием.
 *
 * `beforeEach` чистит производство (`reset-all`), поэтому в базе прогона есть
 * только позиция этого теста: фильтр по артикулу не размывает вердикт и не
 * зависит от того, заполнено ли в строке `plan_position_id`. Ожидание нужно
 * потому, что бюджет строки считается по ledger, а запись факта и чтение
 * ready-списка — два разных запроса.
 */
async function waitForReadyRows(token: string, timeoutMs = 20_000): Promise<ReadyRow[]> {
  const deadline = Date.now() + timeoutMs;
  let rows: ReadyRow[] = [];
  while (Date.now() < deadline) {
    rows = (await fetchReadyRows(token)).filter((row) =>
      String(row.product_sku ?? "").includes(SKU),
    );
    if (rows.length > 0) return rows;
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  return rows;
}

/**
 * Задача получателя: на доске **производственного** участка, in_progress и с
 * принятым материалом. Маршрут может идти через складские секции (`wip_stock`,
 * `finished_stock`) — у них задачи нет, поэтому обходятся все производственные.
 *
 * Опрос, а не один запрос: auto-accept идёт в той же транзакции, что и
 * `transfer_send`, но доска читается отдельным запросом, и первый заход сразу
 * после клика ещё видит прежнее состояние.
 */
async function waitForReceivingTask(
  token: string,
  positionId: number,
  timeoutMs = 20_000,
): Promise<BoardTask> {
  const sections = ((await apiGetSections()) as Array<{
    id: number;
    code: string;
    name: string;
    type?: string;
  }>).filter((section) => section.type === "production");
  const deadline = Date.now() + timeoutMs;
  const seen: string[] = [];
  while (Date.now() < deadline) {
    for (const section of sections) {
      const res = await fetch(`${BACKEND_URL}/api/shopfloor/sections/${section.id}/board`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) continue;
      const board = (await res.json()) as { tasks?: BoardTask[] };
      const task = (board.tasks ?? []).find(
        (candidate) =>
          candidate.product_sku === SKU &&
          candidate.status === "in_progress" &&
          Number(candidate.cache?.received_quantity) > 0,
      );
      if (task) return task;
      seen.push(`${section.name}: нет задачи в работе с материалом`);
    }
    await new Promise((resolve) => setTimeout(resolve, 1_000));
  }
  throw new Error(
    `Позиция #${positionId}: ни на одном производственном участке нет задачи ` +
      `«в работе» с принятым материалом за ${timeoutMs} мс. Проверено: ${sections
        .map((section) => section.name)
        .join(", ")}`,
  );
}

// --- Test -----------------------------------------------------------------

/** @smoke — API-assisted setup; не канон E2E. См. @ui в route-workflow.spec.ts */
test.describe("@smoke Explicit transfer — 2-step ritual (Send + Issue)", () => {
  test.beforeEach(async () => {
    await apiResetAll();
    await apiSeedData();
    await apiEnsureTestProducts();
  });

  test("send auto-accepts, then material is issued on the destination", async ({
    authenticatedPage,
    request,
  }) => {
    test.slow();

    // 1. Подготовка данных: продукт, бесфайловый импорт плана, маршрут
    const product2083 = await apiGetProductBySku(SKU);

    const template = await apiGetActiveTemplate();
    const importRes = await apiSimulatePlanImport(
      [
        {
          sku: SKU,
          name: "Стык 38 мм 2,7 анод.серебро, матовый",
          raw_stock: 2958,
          color: "серебро",
          qty_per_27: 200,
          length_m: 2.7,
          packaging: "смотка спанбондом поштучно в пачке 10 штук",
          output_length_m: 2.7,
          output_qty: 200,
          west: 200,
          east: 0,
          kind: "ГП",
        },
      ],
      { templateId: template.id },
    );
    await apiApplyChangeSet(importRes.production_plan_id, importRes.change_set_id);

    const positions = await apiGetPlanPositions(importRes.production_plan_id);
    const pos2083 = positions.find(
      (p: PlanPositionRow) => p.source_sku === SKU && p.validation_status === "valid",
    );
    expect(pos2083).toBeDefined();
    expect(pos2083.route_id).toBeTruthy();

    const activeRoutes = await apiGetActiveRoutes();
    expect(activeRoutes.length).toBeGreaterThan(0);

    // 1a. Пополняем остатки на STOCK (Склад сырья) — из них #282 выдаёт
    //     материал при запуске. Габарит обязателен: выдача ищет остаток по
    //     размеру плана, поэтому берём его из самой позиции
    //     (`input_dimensions`). Хардкод расходился с планом по длине, и
    //     материал не находился.
    const sectionWh = await apiGetSectionByCode(E2E_SECTION.RAW_STOCK);
    const planQty = Math.round(parseFloat(pos2083.quantity));
    const planDims = pos2083.input_dimensions;
    // Габарит обязателен и берётся из позиции: безразмерный остаток не
    // находится подбором — падать надо здесь, а не на загадочном «нет готовых
    // передач» (ср. sawing-multi-length-split.spec.ts:140).
    expect(planDims?.length_mm).toBeTruthy();
    await apiAddRemainder(
      product2083.id,
      sectionWh.id,
      planQty,
      "E2E: начальный остаток сырья для transfers-auto-accept",
      planDims,
    );

    // 2. Утверждаем позицию на странице /planning (с обработкой диалога «Утвердить всё равно»)
    await authenticatedPage.goto("/planning");
    const planSearch = authenticatedPage.getByPlaceholder("Поиск");
    await expect(planSearch).toBeVisible({ timeout: 10_000 });
    await planSearch.fill(SKU);

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
      await confirmForceApproveViaUI(
        authenticatedPage,
        "e2e: проверяем auto-accept передачи, позиция заведена вручную и сверена",
      );
    } catch {
      // no risk dialog
    }
    await expect(approveBtn).not.toBeVisible({ timeout: 10_000 });

    // 3. Берём в работу на /execution: с #282 запуск сам подбирает источник
    //    и выдаёт материал со склада на первый участок маршрута.
    await authenticatedPage.goto("/execution");
    const execSearch = authenticatedPage.getByPlaceholder("Поиск");
    await expect(execSearch).toBeVisible({ timeout: 10_000 });
    await execSearch.fill(SKU);
    const execRow = authenticatedPage.locator(`tr[data-row-key="${pos2083.id}"]`).first();
    await expect(execRow).toBeVisible({ timeout: 15_000 });
    const launchBtn = execRow.getByRole("button", { name: "Взять в работу" });
    await expect(launchBtn).toBeVisible({ timeout: 5_000 });
    await launchBtn.click();

    await confirmProductionLaunchViaUI(authenticatedPage);

    await expect(execRow.locator("span").filter({ hasText: /^Запущен$/ })).toBeVisible({
      timeout: 15_000,
    });

    // Достаём токен админа для API-запросов (localStorage ktm2000_token).
    const userToken = await apiAccessTokenFromPage(authenticatedPage);

    // 3a. Первая передача — выдача со склада при запуске (#282). Он же первый
    //     auto-accept: материал уже принят на первом участке маршрута.
    const issuedChain = await transferRouteChainViaUI(authenticatedPage, SKU, pos2083.id);
    expect(issuedChain.length, "запуск не оставил выдачи со склада в журнале").toBeGreaterThan(0);
    const currentSection = issuedChain[issuedChain.length - 1];

    // 4. Завершаем задачу участка, который держит материал: его результат и
    //    есть «Готово к передаче» на следующий этап. Без этого шага ready-строка
    //    не появится вовсе (со склада материал уже выдан запуском).
    const completed = await completeAllSectionTasksViaUI(authenticatedPage, SKU, [currentSection]);
    expect(completed, `на участке «${currentSection}» нечего завершать`).toBeGreaterThan(0);

    // 5. Сколько отправляем — из ready-API по позиции: ровно то, что видит
    //    оператор в колонке «К передаче».
    const readyRows = await waitForReadyRows(userToken);
    console.log(
      `[ready] строк к передаче: ${readyRows.length} — ` +
        readyRows
          .map(
            (row) =>
              `${row.product_sku} (позиция ${row.plan_position_id ?? "?"}, ` +
              `к передаче ${row.transferable_quantity}, далее участок ${row.next_section_id ?? "?"})`,
          )
          .join("; "),
    );
    const sending = readyRows.reduce(
      (sum, row) => sum + Number(row.transferable_quantity ?? 0),
      0,
    );
    expect(sending, "после завершения задачи к передаче нечего").toBeGreaterThan(0);

    // 6. SEND на /transfers — auto-accepts по новой модели. UI-путь оператора:
    //    инпут количества предзаполнен, кнопка «Передать» отправляет строку.
    const sent = await sendReadyTransfersViaUI(authenticatedPage, SKU);
    expect(sent, "передача не отправилась").toBeGreaterThan(0);

    // 7. «Журнал передач»: передача принята — auto-accept произошёл inline
    //    внутри transfer_send, оператор ничего не подтверждал.
    //    Журнал живёт в боковой панели и в DOM появляется только когда открыт.
    const journalOpener = authenticatedPage.locator('button[title="Открыть журнал передач"]');
    if ((await journalOpener.count()) > 0) {
      await journalOpener.click();
    }
    const journalTable = authenticatedPage
      .locator("table")
      .filter({ has: authenticatedPage.getByRole("columnheader").filter({ hasText: "Статус" }) })
      .first();
    const historyRow = journalTable.locator("tr", { hasText: SKU }).first();
    await expect(historyRow).toBeVisible({ timeout: 15_000 });
    await expect(historyRow.locator("td").filter({ hasText: "Принята" })).toBeVisible({
      timeout: 10_000,
    });

    // 8. Доска получателя: задача in_progress, принято == выдано == отправлено.
    //    Это и есть проверяемое свойство ритуала: материал не «ждёт приёмки»
    //    и не остаётся невыданным — на участке он сразу в работе.
    const receiving = await waitForReceivingTask(userToken, pos2083.id);
    expect(receiving.status).toBe("in_progress");
    expect(Number(receiving.cache.received_quantity)).toBe(sending);
    expect(Number(receiving.cache.issued_quantity)).toBe(sending);

    // Тест завершён: передача принята, материал выдан в работу на получателе.
  });
});
