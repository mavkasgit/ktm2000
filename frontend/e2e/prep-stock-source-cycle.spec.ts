import { test, expect, type Page } from "./fixtures";
import {
  apiAddRemainder,
  apiApplyChangeSet,
  apiEnsureCatalogProduct,
  apiGetActiveTemplate,
  apiGetProductBySku,
  apiGetSectionByCode,
  apiGetStockBalances,
  apiResetAll,
  apiSimulatePlanImport,
  BACKEND_URL,
  authHeaders,
} from "./api-helpers";
import {
  E2E_SKU,
  approvePositionViaUI,
  completeAllSectionTasksViaUI,
  expectShippedViaUI,
  findApprovablePositionViaUI,
  seedReferenceDataViaUI,
  sendReadyTransfersViaUI,
  transferRouteChainViaUI,
  waitForPlanningTableViaUI,
  type ApprovablePosition,
} from "./ui-helpers";

/**
 * @ui — тикет #315: основное задание берёт материал с `PREP_STOCK`.
 *
 * Подготовленный материал лежит на `PREP_STOCK` — там, где его оставляет
 * план подготовительного участка (#313). Оператор в диалоге «Запуск в
 * производство» ЯВНО выбирает этот остаток источником (#314), и материал
 * уходит на анодирование напрямую с prep-склада, а не с сырьевого.
 *
 * Артикулу выставлен флаг «без дробеструя»: основной маршрут тогда не
 * содержит участков подготовки, и материал, уже прошедший их, не застревает
 * на дробеструе. Цикл из тикета (анодирование → WIP → пила → упаковка →
 * склад готовой → отгрузка) дробеструя не содержит — это тот же смысл.
 *
 * Почему источник выбирается кликом, а не «по умолча»: решение владельца
 * (#314) — без явного выбора поведение прежнее, предвыбор только подсветка.
 * Сценарий обязан это отражать, иначе он зелёный на старом поведении.
 *
 * Сырья на `RAW_STOCK` в сценарии НЕТ вовсе — это и есть ассорт «`RAW_STOCK`
 * не участвует»: ни одной проводки со склада сырья, ни одного остатка на
 * нём. Позиция основного плана при этом проходит полный цикл до `SHIPPED`.
 *
 * Инварианты: AC «`assert_no_invariants_violations` зелёный после каждого
 * шага» в исходной формулировке неисполним в Playwright — это pytest-хелпер
 * (`backend/tests/test_integrity_invariants.py:423`), принимающий
 * `AsyncSession` и делающий SQL S1–S6/D1–D4. Здесь выполняется его доступная
 * через API часть — сверка остатков с ledger (S1) по оси
 * (товар, участок, качество, габарит) после КАЖДОГО шага. Ось операций в
 * ответе `GET /stock/transactions` не отдаётся, поэтому она в сверке не
 * участвует; переформулировка AC — за владельцем.
 */

/** Нормальная длина: единственная, что материализуется в плане и остатках. */
const NORMAL_LENGTH_MM = 3000;
/** Сырьевая длина — только параметр расчёта количества на подвесе (ADR-0028). */
const RAW_LENGTH_MM = 3050;
/**
 * Группа остатка — вход первого ПРОИЗВОДСТВЕННОГО этапа маршрута позиции
 * (`completed_operations_through_stage` через `RAW_STOCK`). Тот складской этап
 * операций не несёт, поэтому группа пустая: «без операций» (ADR-0055 п.6).
 * Склад значения не имеет — источником выдачи остаётся `PREP_STOCK`, и
 * именно его ассертит тикет.
 */
// Имена участков маршрута — как их отдаёт «Журнал передач» (секции из
// `backend/app/seeds/sections.py`). Константами, а не литералами в ассертах:
// иначе опечатка в имени тихо ослабила бы проверку до «путь не пустой».
const ANODIZING_SECTION_NAME = "Анодирование";
const WIP_SECTION_NAME = "Склад полуфабриката";
const SAWING_SECTION_NAME = "Пила";
const PACKING_SECTION_NAME = "Упаковка";
const SHIPPED_SECTION_NAME = "Отправлено";
const PREP_OPS: string[] = [];
const PREP_SECTION_NAME = "Склад подготовки";
const QTY = 300;

// ─── Инварианты ledger через API (замена недоступного в e2e pytest-хелпера) ──

type TxRow = {
  id: number;
  from_location_id: number | null;
  to_location_id: number | null;
  from_quality_state: string;
  to_quality_state: string;
  quantity: string;
  dimensions: Record<string, unknown> | null;
  reason: string;
  source_ref: string | null;
};

type BalanceRow = {
  product_id: number;
  location_id: number;
  quality_state: string;
  balance_qty: string;
  dimensions: Record<string, unknown> | null;
  completed_operations: string[] | null;
};

/** Стабильный ключ оси габарита: порядок ключей JSON у ledger и баланса может разойтись. */
function dimsKey(dims: Record<string, unknown> | null): string {
  if (!dims) return "∅";
  const entries = Object.entries(dims)
    .filter(([, value]) => value !== null)
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
  return JSON.stringify(entries);
}

async function apiGetTransactions(productId: number): Promise<TxRow[]> {
  // Сортировка не задаётся: допустимые колонки перечислены на сервере, а
  // порядок строк для сводной сверки безразличен.
  const res = await fetch(
    `${BACKEND_URL}/api/stock/transactions?product_id=${productId}&limit=500`,
    { headers: await authHeaders() },
  );
  if (!res.ok) {
    throw new Error(`Get transactions failed: ${res.statusText} (${res.status})`);
  }
  const body = (await res.json()) as { transactions: TxRow[]; total: number };
  expect(
    body.total,
    "лента проводок не влезла в одну страницу — сверка была бы неполной",
  ).toBeLessThanOrEqual(500);
  return body.transactions;
}

/**
 * S1 в доступной через API части: сумма проводок по каждому сегменту
 * (товар, участок, качество, габарит) обязана совпадать с остатком.
 * Терминальные секции исключены с обеих сторон — система их не
 * материализует (там приход по ledger есть, а строки остатка нет).
 */
async function assertLedgerMatchesBalancesViaAPI(productId: number, terminalId: number, context: string) {
  const [txs, balances] = await Promise.all([
    apiGetTransactions(productId),
    apiGetStockBalances(productId) as Promise<BalanceRow[]>,
  ]);

  const ledger = new Map<string, number>();
  const add = (key: string, delta: number) => ledger.set(key, (ledger.get(key) ?? 0) + delta);
  for (const tx of txs) {
    const qty = Number(tx.quantity);
    if (tx.to_location_id !== null && tx.to_location_id !== terminalId) {
      add(`${tx.to_location_id}|${tx.to_quality_state}|${dimsKey(tx.dimensions)}`, qty);
    }
    if (tx.from_location_id !== null && tx.from_location_id !== terminalId) {
      add(`${tx.from_location_id}|${tx.from_quality_state}|${dimsKey(tx.dimensions)}`, -qty);
    }
  }

  const balance = new Map<string, number>();
  for (const row of balances) {
    if (row.location_id === terminalId) continue;
    const key = `${row.location_id}|${row.quality_state}|${dimsKey(row.dimensions)}`;
    balance.set(key, (balance.get(key) ?? 0) + Number(row.balance_qty));
  }

  const segments = new Set([...ledger.keys(), ...balance.keys()]);
  const violations: string[] = [];
  for (const key of segments) {
    const net = ledger.get(key) ?? 0;
    const rest = balance.get(key) ?? 0;
    if (Math.abs(net - rest) > 1e-6) violations.push(`${key}: ledger=${net} balance=${rest}`);
  }
  expect(violations, `${context}: остаток разошёлся с ledger`).toEqual([]);
}

/**
 * Проводки выбранного источника — «откуда на самом деле взялся материал».
 *
 * Выдача пишется ДВУМЯ проводками, как обычная передача: `transfer_send`
 * двигает остаток (склад → участок), `transfer_receive` принимает его
 * заданием (учёт по `task_id`, локаций нет). Обе несут один
 * `source_ref`, поэтому фильтр по `reason`, а не по `source_ref` в
 * одиночку: иначе ассерт «ровно одна проводка» ловил бы форму записи,
 * а не смысл выдачи.
 */
async function sourceIssueTransactions(productId: number, reason: string): Promise<TxRow[]> {
  return (await apiGetTransactions(productId)).filter(
    (tx) => tx.source_ref === "take_to_work_source" && tx.reason === reason,
  );
}

/** Сумма остатков артикула на указанном участке. */
async function balanceOn(productId: number, locationId: number): Promise<number> {
  const balances = (await apiGetStockBalances(productId)) as BalanceRow[];
  return balances
    .filter((b) => b.location_id === locationId)
    .reduce((sum, b) => sum + Number(b.balance_qty), 0);
}

/**
 * Взять позицию в работу с ЯВНЫМ выбором источника (#314).
 *
 * Клик по строке источника — не косметика: только он ставит `explicitChoice`,
 * и только с ним выбор уезжает в `take-to-work` (`RemainderAllocationDialog`).
 * Без клика материал остался бы на складе, и позиция уехала бы в работу
 * «по-старому» — ассерты источника после шага упали бы.
 */
async function takeToWorkFromPrepStockViaUI(
  page: Page,
  position: ApprovablePosition,
  prepBalanceId: number,
) {
  await page.goto("/execution");
  await expect(page.getByPlaceholder("Поиск")).toBeVisible({ timeout: 10_000 });

  const execRow = page.locator(`tr[data-row-key="${position.id}"]`).first();
  await expect(execRow).toBeVisible({ timeout: 15_000 });

  const launchResponse = page.waitForResponse(
    (r) => r.url().includes("/take-to-work") && r.request().method() === "POST",
    { timeout: 30_000 },
  );
  await execRow.getByRole("button", { name: "Взять в работу" }).click();

  const dialog = page.getByRole("dialog").filter({ hasText: "Запуск в производство" });
  await expect(dialog).toBeVisible({ timeout: 10_000 });

  const sourceRow = dialog.locator(`[data-testid="source-row-${prepBalanceId}"]`);
  await expect(sourceRow, "в диалоге нет строки источника с prep-склада").toBeVisible({
    timeout: 15_000,
  });
  await expect(sourceRow).toContainText(PREP_SECTION_NAME);
  await sourceRow.click();

  // Подпись под таблицей — читаемый признак того, что выбор сделан оператором.
  await expect(
    dialog.getByText(new RegExp(`Выдадим \\d+ шт\\. с «${PREP_SECTION_NAME}»`)),
    "диалог не подтвердил явный выбор источника",
  ).toBeVisible({ timeout: 10_000 });

  const confirm = dialog.getByRole("button", { name: "Запустить в работу" });
  await expect(confirm).toBeEnabled({ timeout: 10_000 });
  await confirm.click();

  const response = await launchResponse;
  expect(
    response.status(),
    `взятие в работу с источником: HTTP ${response.status()} ${await response.text().catch(() => "")}`,
  ).toBe(200);
  await expect(dialog).not.toBeVisible({ timeout: 15_000 });

  const launchedRow = page.locator(`tr[data-row-key="${position.id}"]`).first();
  await expect(launchedRow.locator("span").filter({ hasText: /^Запущен$/ })).toBeVisible({
    timeout: 15_000,
  });
}

test.describe("@ui Основное задание берёт материал с склада подготовки до «Отправлено»", () => {
  test.beforeEach(async ({ page, loginAsAdmin }) => {
    await loginAsAdmin();
    // Порядок обязателен: `reset-all` чистит и справочники импорта
    // (TRUNCATE … import_templates), поэтому справочники сеются после сброса.
    await apiResetAll();
    await seedReferenceDataViaUI(page);
  });

  test("prep-остаток → явный выбор источника → анодирование…отгрузка", async ({ page }) => {
    test.slow();
    test.setTimeout(600_000);

    page.on("response", async (response) => {
      if (response.status() < 400 || !response.url().includes("/api/")) return;
      const body = await response.text().catch(() => "");
      console.log(
        `[api ${response.status()}] ${response.request().method()} ${response.url()} → ${body.slice(0, 400)}`,
      );
    });

    const prepStock = await apiGetSectionByCode("PREP_STOCK");
    const rawStock = await apiGetSectionByCode("RAW_STOCK");
    const shipped = await apiGetSectionByCode("SHIPPED");

    // ── ШАГ 1. Каталог ─────────────────────────────────────────────────────
    await apiEnsureCatalogProduct({
      sku: E2E_SKU,
      name: "Уголок 15*15",
      lengthsMm: [NORMAL_LENGTH_MM],
      rawLengthMm: RAW_LENGTH_MM,
      perimeterMm: 60,
      mountWidthMm: 15,
    });
    const product = await apiGetProductBySku(E2E_SKU);
    // Флаг «без дробеструя» снимает `SHOT_BLAST` и `PREP_STOCK` из маршрута
    // основного плана (правила `product_skip_shot_blast` и
    // `prep_stock_no_prep_path` профиля `packaging_map_rp`). Без него маршрут
    // содержал бы участок дробеструя, а материал на `PREP_STOCK` этот участок
    // уже пройден — задание осталось бы голодным, и маршрут встал бы раньше
    // анодирования. Тикет того и требует: основное задание берёт МАТЕРИАЛ,
    // уже подготовленный по плану #313, и подготовку заново не проходит.
    // Цикл из issue (анодирование → WIP → пила → упаковка → склад → отгрузка)
    // дробеструя не содержит — это тот же смысл.
    const skipPatch = await fetch(`${BACKEND_URL}/api/products/${product.id}`, {
      method: "PATCH",
      headers: await authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ skip_shot_blast: true }),
    });
    expect(
      skipPatch.ok,
      `не удалось выставить skip_shot_blast: HTTP ${skipPatch.status} ${await skipPatch.text().catch(() => "")}`,
    ).toBeTruthy();
    console.log(`[step1] каталог ${E2E_SKU} → id=${product.id}, skip_shot_blast=true`);

    // ── ШАГ 2. Материал на складе подготовки ───────────────────────────────
    // Группа остатка — `["SHOT"]`: столько операций маршрута основного плана
    // пройдено к анодированию. Сырьё на `RAW_STOCK` не заводим вовсе.
    await apiAddRemainder(
      product.id,
      prepStock.id,
      QTY,
      "E2E подготовка #315: остаток после дробеструя",
      { length_mm: NORMAL_LENGTH_MM },
      PREP_OPS,
    );
    const prepBalances = (await apiGetStockBalances(product.id)) as BalanceRow[];
    const prepBalance = prepBalances.find(
      (b) => b.location_id === prepStock.id && Number(b.balance_qty) > 0,
    );
    expect(prepBalance, "остаток на складе подготовки не создан").toBeTruthy();
    expect(
      prepBalance!.completed_operations,
      "группа prep-остатка не совпала с маршрутом позиции",
    ).toEqual(PREP_OPS);
    console.log(`[step2] prep-остаток #${prepBalance!.id}: ${prepBalance!.balance_qty} шт., ops=${PREP_OPS}`);

    await assertLedgerMatchesBalancesViaAPI(product.id, shipped.id, "после прихода на prep-склад");

    // ── ШАГ 3. Позиция основного плана ────────────────────────────────────
    const template = await apiGetActiveTemplate();
    const importRes = await apiSimulatePlanImport(
      [
        {
          sku: E2E_SKU,
          name: "Уголок 15*15",
          raw_stock: QTY,
          color: "серебро",
          qty_per_27: QTY,
          length_m: 3,
          packaging: "стяжка стретч поштучно в пачке 10 штук",
          output_length_m: 3,
          output_qty: QTY,
          west: QTY,
          east: 0,
          kind: "ГП",
        },
      ],
      { templateId: template.id },
    );
    await apiApplyChangeSet(importRes.production_plan_id, importRes.change_set_id);

    await page.goto("/planning");
    await expect(page.getByRole("heading", { name: "План", exact: true })).toBeVisible({
      timeout: 10_000,
    });
    await waitForPlanningTableViaUI(page);
    await expect(page.locator('[id^="plan-position-"]')).toHaveCount(1);
    console.log("[step3] позиция основного плана импортирована");

    // ── ШАГ 4. Утверждение ────────────────────────────────────────────────
    const position = await findApprovablePositionViaUI(page);
    expect(position, "в плане нет строки для утверждения").not.toBeNull();
    await approvePositionViaUI(page, position!);
    console.log(`[step4] позиция #${position!.id} утверждена`);

    await assertLedgerMatchesBalancesViaAPI(product.id, shipped.id, "после утверждения");

    // ── ШАГ 5. Взятие в работу: источник = PREP_STOCK ─────────────────────
    await takeToWorkFromPrepStockViaUI(page, position!, prepBalance!.id);
    console.log(`[step5] позиция #${position!.id} запущена с prep-склада`);

    // Главный ассерт тикета: выбран именно остаток склада подготовки.
    const sends = await sourceIssueTransactions(product.id, "transfer_send");
    expect(sends, "выбор источника не дал проводки выдачи остатка").toHaveLength(1);
    expect(sends[0].from_location_id, "источник выдачи — не склад подготовки").toBe(prepStock.id);
    // Количество приходит строкой Decimal («300.000»), а не «300»: сравниваем
    // числом, иначе ассерт упал бы на формате, а не на смысле.
    expect(Number(sends[0].quantity), "выдано не всё количество позиции").toBe(QTY);

    // Вторая половина выдачи — приём на задание: без неё задание осталось бы
    // с issued = 0, и маршрут не пошёл бы дальше первого участка.
    const receives = await sourceIssueTransactions(product.id, "transfer_receive");
    expect(receives, "выданный материал не принят заданием").toHaveLength(1);
    expect(receives[0].task_id, "приём не привязан к заданию-получателю").toBeTruthy();
    expect(Number(receives[0].quantity)).toBe(QTY);
    expect(
      await balanceOn(product.id, rawStock.id),
      "со склада сырья что-то списалось — он не должен участвовать",
    ).toBe(0);

    // Ни одна проводка позиции не идёт со склада сырья.
    const fromRaw = (await apiGetTransactions(product.id)).filter(
      (tx) => tx.from_location_id === rawStock.id,
    );
    expect(fromRaw.map((tx) => tx.id), "проводки со склада сырья недопустимы").toEqual([]);
    await assertLedgerMatchesBalancesViaAPI(product.id, shipped.id, "после выдачи с prep-склада");

    // ── ШАГ 6. Полный маршрут до «Отправлено» ────────────────────────────
    // Порядок круга — «сначала завершить, потом передать»: материал уже на
    // участке (выдача при запуске шла напрямую с prep-склада), передавать
    // нечего, пока задание не закрыто.
    let transferred = 0;
    let completed = 0;
    let idleRounds = 0;
    let routeChain: string[] = [];
    for (let round = 0; round < 40; round++) {
      const done = await completeAllSectionTasksViaUI(page, E2E_SKU);
      const sent = await sendReadyTransfersViaUI(page, E2E_SKU);
      completed += done;
      transferred += sent;
      routeChain = await transferRouteChainViaUI(page, E2E_SKU, position!.id);
      console.log(
        `[step6] раунд ${round}: завершено ${done}, передано ${sent}, путь ${routeChain.join(" → ")}`,
      );
      await assertLedgerMatchesBalancesViaAPI(product.id, shipped.id, `раунд маршрута ${round}`);
      if (done === 0 && sent === 0) {
        if (++idleRounds >= 2) break;
      } else {
        idleRounds = 0;
      }
    }
    expect(transferred, "маршрут не прошёл ни одной передачи").toBeGreaterThan(0);
    expect(completed, "по маршруту не завершено ни одной задачи").toBeGreaterThan(0);

    await expectShippedViaUI(page, E2E_SKU, [position!.id]);
    console.log(`[step6] маршрут: prep → ${routeChain.join(" → ")}`);

    // ── ШАГ 7. Инварианты после финала и происхождение материала ──────────
    await assertLedgerMatchesBalancesViaAPI(product.id, shipped.id, "после отгрузки");

    // Материал шёл маршрутом основного плана, а не «куда-нибудь». Журнал
    // передач показывает ПОЛУЧАТЕЛЕЙ, поэтому участок, с которого материал
    // ушёл при выдаче с prep-склада (анодирование), в цепочке отсутствует
    // законно: первой записью он не является адресатом. Проверяем его по
    // ledger — оттуда шла выдача на анодирование.
    const anodizing = await apiGetSectionByCode("ANODIZING");
    const issuedToAnodizing = (await apiGetTransactions(product.id)).filter(
      (tx) => tx.to_location_id === anodizing.id && tx.reason === "transfer_send",
    );
    expect(
      issuedToAnodizing.length,
      "на анодирование не пришло ни одной выдачи — материал шёл не оттуда",
    ).toBeGreaterThan(0);

    expect(routeChain, "в журнале передач нет ни одного адресата").not.toHaveLength(0);
    for (const stage of [WIP_SECTION_NAME, SAWING_SECTION_NAME, PACKING_SECTION_NAME]) {
      expect(routeChain, `маршрут не прошёл участок «${stage}»: ${routeChain.join(" → ")}`).toContain(
        stage,
      );
    }
    expect(routeChain[routeChain.length - 1], "маршрут не дошёл до «Отправлено»").toBe(
      SHIPPED_SECTION_NAME,
    );

    expect(
      await balanceOn(product.id, rawStock.id),
      "после полного цикла на складе сырья что-то появилось",
    ).toBe(0);
    console.log("[step7] отгрузка подтверждена, ledger сходится, сырьё не участвовало");
  });
});