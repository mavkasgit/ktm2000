import { execFileSync } from "child_process";
import fs from "fs";
import path from "path";

import { workerBackendUrls, workerSlot } from "./worker-slot";

// Без `E2E_API_URL` бьём не в стенд, а в devstack на :8012 — тихий увод
// прогона в чужую БД. Адрес приходит из обёртки `scripts/run-e2e.mjs`
// (свободный порт на каждый прогон), поэтому падать здесь безопасно:
// до сюда дело доходит только при запуске в обход npm-скриптов.
if (!process.env.E2E_API_URL) {
  throw new Error(
    "E2E_API_URL не задан — адрес стенда выбирает scripts/run-e2e.mjs. " +
      "Запускай прогон через npm run test:e2e (или test:e2e:smoke / test:e2e:ui).",
  );
}

// Адрес backend'а **слота этого воркера** (#289). Прямые вызовы из Node идут
// мимо браузера, а значит мимо заголовка `x-e2e-worker`, по которому роутер
// `/api` выбирает backend: адрес выбирается здесь же, по слоту воркера.
//
// Без этого все воркеры сеяли бы в БД backend'а 0, а страница работала бы со
// своей: тест получал «Готово к передаче» по чужой строке, а набор данных для
// проверки лежал в другой базе.
const workerUrls = workerBackendUrls();
const workerApiUrl = workerUrls[workerSlot()];
if (!workerApiUrl) {
  throw new Error(
    `Слот ${workerSlot()} просит backend, а в прогоне их ${workerUrls.length}: ` +
      "адреса backend'ов (E2E_WORKER_API_URLS) не совпадают с числом воркеров.",
  );
}
export const BACKEND_URL = workerApiUrl.replace(/\/api$/, "");

/**
 * Bearer стенда для прямых вызовов из Node. Раньше эти вызовы шли анонимом и
 * проходили только потому, что стенд стоял на `DEV_BYPASS_AUTH=true`; теперь
 * `/api/routes*` и `/api/routes-seed` закрыты гвардом роли, и анонимный вызов
 * получает 401. Токен берём тем же входом, которым заходит UI стенда
 * (break-glass, пароль из `.env.e2e`), один раз на воркер.
 */
let standToken: string | null = null;

export async function apiStandToken(): Promise<string> {
  if (standToken) return standToken;
  const password = process.env.E2E_ADMIN_PASSWORD || process.env.BREAK_GLASS_PASSWORD || "break-glass-dev";
  const res = await fetch(`${BACKEND_URL}/api/auth/break-glass/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password }),
  });
  if (!res.ok) {
    throw new Error(`Break-glass login failed: ${res.statusText} (${res.status})`);
  }
  standToken = (await res.json()).access_token as string;
  return standToken;
}

export async function authHeaders(extra?: Record<string, string>): Promise<Record<string, string>> {
  return { ...extra, Authorization: `Bearer ${await apiStandToken()}` };
}

export function unwrapItems<T>(body: T[] | { items?: T[] }): T[] {
  return Array.isArray(body) ? body : body.items ?? [];
}


/**
 * Проверить тестовую БД и при необходимости бутстрапнуть её (единое поведение
 * для всех e2e-тестов). Перезапись — ТОЛЬКО если не хватает справочников,
 * нужных тестам: миграции + базовый сид через backend/.venv.
 */
export async function ensureDbBootstrapped(): Promise<void> {
  // Два РАЗНЫХ вопроса, и путать их нельзя.
  //
  // 1) Жив ли стенд. Если backend не отвечает — сид бесполезен, а оператор
  //    должен увидеть «поднимите стек», а не «БД пуста, но URL не задан».
  // 2) Хватает ли тестам справочников. Проверяем НЕ секции, а активный
  //    шаблон импорта и маршруты: `reset-all` чистит `import_templates` и
  //    `production_routes`, но секции оставляет. Проверка по секциям
  //    радостно объявляла базу готовой, справочники не восстанавливались,
  //    и следующий тест падал на «No active import template found».
  if (!(await isStackReachable())) {
    throw new Error(
      `Тест-стек недоступен на ${BACKEND_URL}. Поднимите его: ` +
        `EXTERNAL_PORT=8100 docker compose --env-file .env.test -f infra/compose/docker-compose.test.yml up -d --build`,
    );
  }

  const [templatesOk, routesOk] = await Promise.all([
    hasActiveImportTemplate(),
    hasAnyRoute(),
  ]);
  if (templatesOk && routesOk) {
    return; // БД инициализирована — ничего не перезаписываем
  }
  const dbUrl = workerStandEnvVar("DATABASE_URL") ?? workerStandEnvVar("E2E_TEST_DATABASE_URL");
  if (!dbUrl) {
    throw new Error(
      "БД пуста, но URL не задан: установите E2E_TEST_DATABASE_URL или DATABASE_URL в .env.e2e",
    );
  }
  const backendDir = path.resolve(process.cwd(), "../backend");
  const py =
    process.env.BACKEND_PYTHON ??
    [".venv/Scripts/python.exe", ".venv/bin/python"].map((p) => path.join(backendDir, p)).find((p) =>
      fs.existsSync(p),
    ) ??
    "python";
  const env = { ...process.env, DATABASE_URL: dbUrl };
  console.log(
    `[ensureDbBootstrapped] справочники неполны (шаблон=${templatesOk}, маршруты=${routesOk}) — миграции + базовый сид…`,
  );
  execFileSync(py, ["-m", "alembic", "upgrade", "head"], { cwd: backendDir, env, stdio: "inherit" });
  execFileSync(py, ["scripts/seed_all.py"], { cwd: backendDir, env, stdio: "inherit" });
}

/** Жив ли стенд: без backend сид бессмысленен, а ошибка должна называть причину. */
async function isStackReachable(): Promise<boolean> {
  try {
    const res = await fetch(`${BACKEND_URL}/api/sections`);
    return res.ok;
  } catch {
    return false;
  }
}

/** Есть ли активный шаблон импорта — без него не работает ни один импорт. */
async function hasActiveImportTemplate(): Promise<boolean> {
  try {
    const res = await fetch(`${BACKEND_URL}/api/import-templates`);
    if (!res.ok) return false;
    const templates = unwrapItems<{ is_active?: boolean }>(await res.json());
    return templates.some((t) => t.is_active === true);
  } catch {
    return false;
  }
}

/** Есть ли хоть один маршрут — без него позиция плана не запускается. */
async function hasAnyRoute(): Promise<boolean> {
  try {
    const res = await fetch(`${BACKEND_URL}/api/routes?limit=1&offset=0`, {
      headers: await authHeaders(),
    });
    if (!res.ok) return false;
    return unwrapItems<unknown>(await res.json()).length > 0;
  } catch {
    return false;
  }
}


/**
 * Значение из env-файла клона **этого воркера** (#289).
 *
 * `E2E_RUN_ENV_FILES` даёт файлы клонов по воркерам (`run-tier.mjs`),
 * `E2E_ENV_FILE` — файл воркера 0. Прежний чтец брал `.env.e2e`, а там DSN
 * **шаблона**: сид ушёл бы в базу, которой тест не касается.
 */
function workerStandEnvVar(key: string): string | undefined {
  const files = process.env.E2E_RUN_ENV_FILES
    ? (JSON.parse(process.env.E2E_RUN_ENV_FILES) as string[])
    : [];
  const file = files[workerSlot()] ?? process.env.E2E_ENV_FILE;
  if (!file) return undefined;
  try {
    const text = fs.readFileSync(file, "utf8");
    return text.match(new RegExp(`^${key}=(.*)$`, "m"))?.[1]?.trim();
  } catch {
    return undefined;
  }
}

export async function apiSeedData() {
  const res = await fetch(`${BACKEND_URL}/api/routes-seed?force=true`, {
    method: "POST",
    headers: await authHeaders({ "Content-Type": "application/json" }),
  });
  if (!res.ok) {
    throw new Error(`Seed failed: ${res.statusText} (${res.status})`);
  }
  return res.json();
}

const E2E_TEST_PRODUCTS: Array<{
  sku: string;
  name: string;
  type: string;
  lengths_mm: number[];
  quantity_per_hanger: number;
}> = [
  {
    sku: "ЮП-3270",
    name: "Профиль ЮП-3270",
    type: "component",
    // 2700 мм — длина, под которой спеки заводят планы (`length_m: 2.7`).
    // Артикул без такой нормальной длины получает позицию плана
    // `invalid: normal_length_not_found`, и бизнес-шаги не начинаются.
    lengths_mm: [2700],
    quantity_per_hanger: 100,
  },
  {
    sku: "ЮП-2083",
    name: "Профиль ЮП-2083",
    type: "component",
    lengths_mm: [2700],
    quantity_per_hanger: 100,
  },
];

/** @smoke — актуальные коды после seed (старые WH/DRILL/ANOD убраны). */
export const E2E_SECTION = {
  RAW_STOCK: "RAW_STOCK",
  DRILLING: "DRILLING",
  ANODIZING: "ANODIZING",
  WIP_STOCK: "WIP_STOCK",
  PREP_STOCK: "PREP_STOCK",
} as const;

export const E2E_SPG = {
  STOCK: "STOCK",
  PREP: "PREP",
  ANODIZING: "ANODIZING",
} as const;

/**
 * @smoke only — артикулы общих смоук-спеок (не используются в @ui).
 *
 * Через `apiEnsureCatalogProduct`, а не собственным POST: контракт артикула
 * (нормальные длины в `lengths`, «кол-во на подвес» — словарь по длинам)
 * менялся, и отдельная копия сетапа молча уезжала в 422 / в позиции плана
 * без нормальной длины.
 */
export async function apiEnsureTestProducts() {
  for (const product of E2E_TEST_PRODUCTS) {
    await apiEnsureCatalogProduct({
      sku: product.sku,
      name: product.name,
      type: product.type,
      lengthsMm: product.lengths_mm,
      quantityPerHanger: product.quantity_per_hanger,
    });
  }
}

export async function apiGetProductBySku(sku: string) {
  const res = await fetch(`${BACKEND_URL}/api/products?q=${encodeURIComponent(sku)}`);
  if (!res.ok) {
    throw new Error(`Get product by SKU failed: ${res.statusText} (${res.status})`);
  }
  const products = unwrapItems<{ id: number; sku: string }>(await res.json());
  const product = products.find((p) => p.sku === sku);
  if (!product) {
    throw new Error(`Product not found with SKU: ${sku}`);
  }
  return product;
}

/** @smoke — минимальный линейный продукт для кастомного роута. */
export async function apiCreateBareProduct(sku: string) {
  const res = await fetch(`${BACKEND_URL}/api/products`, {
    method: "POST",
    headers: await authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({
      sku,
      name: `Bare ${sku}`,
      type: "finished_good",
      unit: "pcs",
      is_active: true,
      dimension_state: "length",
      lengths: [{ length_mm: 2700, raw_length_mm: null, is_primary: true }],
    }),
  });
  if (!res.ok) {
    throw new Error(`Create bare product failed: ${res.status} ${await res.text()}`);
  }
  return res.json();
}


export async function apiGetSpgs() {
  const res = await fetch(`${BACKEND_URL}/api/spg`);
  if (!res.ok) {
    throw new Error(`Get SPGs failed: ${res.statusText} (${res.status})`);
  }
  return unwrapItems(await res.json());
}

export async function apiGetSections() {
  const res = await fetch(`${BACKEND_URL}/api/sections`);
  if (!res.ok) {
    throw new Error(`Get sections failed: ${res.statusText} (${res.status})`);
  }
  return unwrapItems(await res.json());
}

export async function apiGetActiveTemplate() {
  const res = await fetch(`${BACKEND_URL}/api/import-templates`);
  if (!res.ok) {
    throw new Error(`Get templates failed: ${res.statusText} (${res.status})`);
  }
  const { items: templates } = await res.json();
  const template = templates.find((t: { is_active: boolean }) => t.is_active);
  if (!template) {
    throw new Error("No active import template found");
  }
  return template;
}

/** Строка «Упаковочного плана» для бесфайлового импорта (см. `/imports/excel/simulate`). */
export type SimulatedPlanRow = {
  sku: string;
  replenishment?: string | null;
  name?: string | null;
  raw_stock?: number | null;
  color?: string | null;
  qty_per_27?: number | null;
  length_m?: number | null;
  operation?: string | null;
  packaging?: string | null;
  note?: string | null;
  output_length_m?: number | null;
  output_qty?: number | null;
  west?: number | null;
  east?: number | null;
  kind?: string | null;
};

/**
 * Импорт плана без xlsx: строки уходят в теле запроса, бэкенд собирает
 * workbook в памяти и прогоняет тот же change-set, что и загрузка файла.
 * Заменяет хранимые e2e-фикстуры плана.
 */
export async function apiSimulatePlanImport(
  rows: SimulatedPlanRow[],
  opts: {
    templateId?: number;
    productionPlanId?: number;
    mode?: "create_plan" | "append_to_plan";
    sheetName?: string;
  } = {},
) {
  const res = await fetch(`${BACKEND_URL}/api/imports/excel/simulate`, {
    method: "POST",
    headers: await authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({
      rows,
      template_id: opts.templateId ?? null,
      production_plan_id: opts.productionPlanId ?? null,
      mode: opts.mode ?? "create_plan",
      sheet_name: opts.sheetName ?? "totalplan",
    }),
  });
  if (!res.ok) {
    throw new Error(`Simulate plan import failed: ${res.statusText} (${res.status}) - ${await res.text()}`);
  }
  return res.json() as Promise<{
    import_file_id: number;
    import_batch_id: number;
    production_plan_id: number;
    change_set_id: number;
  }>;
}

/** Создать/дотянуть артикул справочника сырья через API (idempotent, upsert). */
export async function apiEnsureCatalogProduct(spec: {
  sku: string;
  name: string;
  lengthsMm: number[];
  rawLengthMm?: number | null;
  perimeterMm?: number;
  mountWidthMm?: number;
  quantityPerHanger?: number;
  type?: string;
  /**
   * Эквивалентные артикулы (ADR-0073). Передаются в PATCH/POST как есть:
   * сервер (`_enforce_bidirectional_aliases`) сам дописывает обратный алиас,
   * если продукт-партнёр уже существует. Поэтому пару заводят двумя
   * вызовами: сначала оба продукта, затем повторный вызов с `aliases`.
   */
  aliases?: string[];
}) {
  const primary = spec.lengthsMm[0];
  const hanger =
    spec.quantityPerHanger !== undefined
      ? Object.fromEntries(
          spec.lengthsMm.map((l) => [String(l), { auto: spec.quantityPerHanger, manual: null }]),
        )
      : null;
  const fields = {
    sku: spec.sku,
    name: spec.name,
    is_catalog_item: true,
    lengths: spec.lengthsMm.map((lengthMm) => ({
      length_mm: lengthMm,
      raw_length_mm: spec.rawLengthMm ?? null,
      is_primary: lengthMm === primary,
    })),
    perimeter_mm: spec.perimeterMm ?? null,
    mount_width_mm: spec.mountWidthMm ?? null,
    quantity_per_hanger: hanger,
    // `undefined` JSON.stringify отбрасывает: без явного aliases PATCH не
    // трогает существующий список эквивалентов.
    aliases: spec.aliases,
  };
  const search = unwrapItems<{ id: number; sku: string }>(
    await (await fetch(`${BACKEND_URL}/api/products?q=${encodeURIComponent(spec.sku)}`)).json(),
  );
  const existing = search.find((p) => p.sku === spec.sku);
  const res = existing
    ? await fetch(`${BACKEND_URL}/api/products/${existing.id}`, {
        method: "PATCH",
        headers: await authHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify(fields),
      })
    : await fetch(`${BACKEND_URL}/api/products`, {
        method: "POST",
        headers: await authHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({
          ...fields,
          type: spec.type ?? "component",
          unit: "pcs",
          is_active: true,
        }),
      });
  if (!res.ok) {
    throw new Error(`Upsert product ${spec.sku} failed: ${res.status} ${await res.text()}`);
  }
  return (await res.json()) as { id: number; sku: string };
}

export async function apiApplyChangeSet(planId: number, changeSetId: number) {
  const res = await fetch(
    `${BACKEND_URL}/api/production-plans/${planId}/change-sets/${changeSetId}/apply`,
    {
      method: "POST",
      headers: await authHeaders({ "Content-Type": "application/json" }),
    },
  );
  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`Apply change set failed: ${res.statusText} (${res.status}) - ${errText}`);
  }
  return res.json();
}

/**
 * Завести пару сырьевых артикулов с ручной N на общих длинах (#312).
 *
 * Пара — единственное, что сводит две позиции в один подвес на печати,
 * поэтому прогон пары обязан завести её настоящей записью справочника,
 * а не подменять её данными на доске.
 */
export async function apiCreateProductPair(
  productId: number,
  partnerProductId: number,
  quantityPerHanger: Record<string, { manual: number | null }>,
) {
  const res = await fetch(`${BACKEND_URL}/api/products/${productId}/pairs`, {
    method: "POST",
    headers: await authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({
      partner_product_id: partnerProductId,
      quantity_per_hanger: quantityPerHanger,
    }),
  });
  if (!res.ok) {
    throw new Error(`Create product pair failed: ${res.statusText} (${res.status}) - ${await res.text()}`);
  }
  return res.json() as Promise<{
    id: number;
    product_a_id: number;
    product_b_id: number;
    lengths: number[];
  }>;
}

/**
 * «Действие коллеги» для проверок свежести (#206): утвердить позицию плана
 * напрямую по API — из другого контекста/токена, минуя UI и его кэш. Сначала
 * без обхода валидации; сервер находит ошибки — повторяем с `force` и причиной
 * (ADR-0048).
 */
export async function apiApprovePosition(planId: number, positionId: number): Promise<void> {
  let res: Response | null = null;
  // Первая попытка — обычная; сервер нашёл ошибки валидации — вторая с force.
  for (const force of [false, true]) {
    res = await fetch(
      `${BACKEND_URL}/api/production-plans/${planId}/positions/${positionId}/approve${force ? "?force=true" : ""}`,
      {
        method: "POST",
        headers: await authHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify(
          force ? { reason: `e2e #206: проверка опроса, позиция #${positionId} заведена эталонной` } : {},
        ),
      },
    );
    if (res.ok) return;
  }
  throw new Error(`Approve position failed: ${res!.statusText} (${res!.status}) - ${await res!.text()}`);
}

export async function apiGetPlanPositions(planId: number) {
  const res = await fetch(`${BACKEND_URL}/api/production-plans/${planId}/all-positions`, {
    headers: await authHeaders(),
  });
  if (!res.ok) {
    throw new Error(`Get plan positions failed: ${res.statusText} (${res.status})`);
  }
  return res.json();
}

/**
 * @ui — все позиции плана БЕЗ фильтра по статусу (ADR-0056): снимок для
 * проверок «действие ничего не сдвинуло». Ответ `/{id}/all-positions`
 * отсекает `approved`/`released`, и смена статуса позиции выглядела бы там как
 * «позиция исчезла из обоих снимков» — то есть как «ничего не изменилось».
 */
export async function apiGetAllPlanPositions() {
  const res = await fetch(`${BACKEND_URL}/api/production-plans/all-positions?limit=500`, {
    headers: await authHeaders(),
  });
  if (!res.ok) {
    throw new Error(`Get all plan positions failed: ${res.statusText} (${res.status})`);
  }
  return res.json();
}

/**
 * Строка остатка из `GET /api/stock/balance/by-product/{id}`.
 *
 * Поля — ровно `backend/app/stock/api.py::StockBalanceOut` (канон e2e: форму
 * ответа типизировать из контракта сервера, а не оставлять `any`): `res.json()`
 * без типа давал `any`, и `b.id` / `b.location_id` в спеках не проверялись
 * совсем. `quantity` на выводе — строка Decimal, поэтому `balance_qty: string`.
 */
export type StockBalanceRow = {
  id: number;
  product_id: number;
  product_sku?: string | null;
  location_id: number;
  location_name?: string | null;
  quality_state: string;
  balance_qty: string;
  dimensions?: Record<string, unknown> | null;
  dimensions_label?: string;
  completed_operations?: string[] | null;
  refreshed_at?: string | null;
};

/**
 * @ui — снимок остатков артикула для проверок «скрытие ничего не двигает»
 * (#233): список строк баланса по всем локациям, как его отдаёт API.
 */
export async function apiGetStockBalances(productId: number): Promise<StockBalanceRow[]> {
  const res = await fetch(`${BACKEND_URL}/api/stock/balance/by-product/${productId}`, {
    headers: await authHeaders(),
  });
  if (!res.ok) {
    throw new Error(`Get stock balances failed: ${res.statusText} (${res.status})`);
  }
  return (await res.json()) as StockBalanceRow[];
}

/**
 * Строка списка `GET /api/stock/balance` — группа эквивалентов на осях
 * `(участок, качество, размер, операции)` (спека §8, ADR-0073).
 *
 * `balance_qty` — сумма группы, `items` — её фактические SKU-строки. Форма
 * повторяет `backend/app/stock/api.py::StockBalanceGroupOut`; SKU-уровень
 * остаётся у `apiGetStockBalances` (`by-product`).
 */
export type StockBalanceGroupRow = StockBalanceRow & {
  alias_group_key: number;
  alias_group_skus: string[];
  items: Array<{
    balance_id: number;
    product_id: number;
    sku: string | null;
    quantity: string;
  }>;
};

/** Группы остатков с серверной суммой и раскрытием до SKU. */
export async function apiGetStockBalanceGroups(
  params: { search?: string; productId?: number; locationId?: number; limit?: number; offset?: number } = {},
): Promise<{ balances: StockBalanceGroupRow[]; total: number; limit: number; offset: number }> {
  const query = new URLSearchParams();
  if (params.search) query.set("search", params.search);
  if (params.productId !== undefined) query.set("product_id", String(params.productId));
  if (params.locationId !== undefined) query.set("location_id", String(params.locationId));
  query.set("limit", String(params.limit ?? 500));
  query.set("offset", String(params.offset ?? 0));
  const res = await fetch(`${BACKEND_URL}/api/stock/balance?${query.toString()}`, {
    headers: await authHeaders(),
  });
  if (!res.ok) {
    throw new Error(`Get stock balance groups failed: ${res.statusText} (${res.status})`);
  }
  return res.json() as Promise<{
    balances: StockBalanceGroupRow[];
    total: number;
    limit: number;
    offset: number;
  }>;
}

/** Проводка ledger (`GET /api/stock/transactions`). */
export type StockTransactionRow = {
  id: number;
  product_id: number;
  from_location_id: number | null;
  to_location_id: number | null;
  quantity: string;
  reason: string;
  transfer_id: number | null;
  task_id: number | null;
  source_ref: string | null;
  dimensions: Record<string, unknown> | null;
  comment: string | null;
};

export async function apiGetStockTransactions(productId: number): Promise<StockTransactionRow[]> {
  const res = await fetch(
    `${BACKEND_URL}/api/stock/transactions?product_id=${productId}&limit=500`,
    { headers: await authHeaders() },
  );
  if (!res.ok) {
    throw new Error(`Get stock transactions failed: ${res.statusText} (${res.status})`);
  }
  const body = (await res.json()) as { transactions: StockTransactionRow[]; total: number };
  if (body.total > 500) {
    throw new Error(`Stock transactions page is incomplete: total=${body.total}, limit=500`);
  }
  return body.transactions;
}

/** Строка журнала передач: `GET /api/transfers/history`. */
export type TransferHistoryRow = {
  transfer_id: number;
  transfer_no: string;
  issue_no: string | null;
  status: string;
  product_sku: string;
  sent_quantity: string;
  comment: string | null;
  from_section_name: string;
  to_section_name: string;
};

/**
 * Журнал передач (без фильтра по участку — все записи стенда).
 * `Transfer.product_id` читается здесь как `product_sku`: запись передачи
 * несёт артикул задания, а не фактический SKU источника (ADR-0073 п.5).
 */
export async function apiGetTransferHistory(search?: string): Promise<TransferHistoryRow[]> {
  const query = new URLSearchParams({ limit: "500" });
  if (search) query.set("search", search);
  const res = await fetch(`${BACKEND_URL}/api/transfers/history?${query.toString()}`, {
    headers: await authHeaders(),
  });
  if (!res.ok) {
    throw new Error(`Get transfer history failed: ${res.statusText} (${res.status})`);
  }
  const body = (await res.json()) as { transfers: TransferHistoryRow[]; total: number };
  if (body.total > 500) {
    throw new Error(`Transfer history page is incomplete: total=${body.total}, limit=500`);
  }
  return body.transfers;
}

export async function apiGetActiveRoutes() {
  const res = await fetch(`${BACKEND_URL}/api/routes`, { headers: await authHeaders() });
  if (!res.ok) {
    throw new Error(`Get routes failed: ${res.statusText} (${res.status})`);
  }
  const routes = await res.json();
  return routes.filter((r: { is_active: boolean }) => r.is_active);
}

export async function apiBatchAssignRoute(
  planId: number,
  positionIds: number[],
  routeId: number | null,
) {
  const res = await fetch(
    `${BACKEND_URL}/api/production-plans/${planId}/positions/batch-assign-route`,
    {
      method: "POST",
      headers: await authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        position_ids: positionIds,
        route_id: routeId,
      }),
    },
  );
  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`Batch assign route failed: ${res.statusText} (${res.status}) - ${errText}`);
  }
  return res.json();
}

export async function apiResetAll() {
  const res = await fetch(`${BACKEND_URL}/api/production-plans/reset-all`, {
    method: "POST",
    headers: await authHeaders(),
  });
  if (!res.ok && res.status !== 404) {
    throw new Error(`Reset all failed: ${res.statusText} (${res.status})`);
  }
}

export async function apiGetSpgByCode(code: string) {
  const res = await fetch(`${BACKEND_URL}/api/spg`);
  if (!res.ok) {
    throw new Error(`Get SPG failed: ${res.statusText} (${res.status})`);
  }
  const spgs = unwrapItems<{ id: number; code: string }>(await res.json());
  const spg = spgs.find((s) => s.code === code);
  if (!spg) {
    throw new Error(`SPG not found with code: ${code}`);
  }
  return spg;
}

export async function apiGetSectionByCode(code: string) {
  const res = await fetch(`${BACKEND_URL}/api/sections`);
  if (!res.ok) {
    throw new Error(`Get sections failed: ${res.statusText} (${res.status})`);
  }
  // Тип объявлен с `name`, потому что `stock-import-history.spec.ts` печатает
  // имя участка в столбец «Участок» TSV-буфера (`raw.name`): серверное поле
  // есть (`backend/app/api/routes/sections.py::SectionOut.name`), а в локальном
  // типе его не было — `tsc -p tsconfig.e2e.json` красил TS2339. Раньше поле
  // просто не проверялось типами.
  const sections = unwrapItems<{ id: number; code: string; name: string }>(await res.json());
  const section = sections.find((s) => s.code === code);
  if (!section) {
    throw new Error(`Section not found with code: ${code}`);
  }
  return section;
}

/**
 * @smoke — POST /api/stock/adjustment (замена устаревшего spg/manual-operation).
 *
 * `completedOperations` — группа остатка (ADR-0055): приход обязан лечь в ту же
 * группу, из которой его заберёт списание. Складские (транзитные) этапы маршрута
 * секции не несут (`route_stages.section_id = NULL`, склад живёт в
 * `storage_section_id`), поэтому группа склада — «без операций» (`[]`): ровно её
 * выводит `completed_operations_through_stage` для источника проводки. Без неё
 * остаток уходит в NULL-группу «не зафиксировано», и выдача материала отвечает
 * `Insufficient stock … available 0` на полном участке (тикет #262).
 */
export async function apiAddRemainder(
  productId: number,
  sectionId: number,
  quantity: number,
  comment: string,
  dimensions?: Record<string, number> | null,
  completedOperations: string[] | null = [],
) {
  const res = await fetch(`${BACKEND_URL}/api/stock/adjustment`, {
    method: "POST",
    headers: await authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({
      product_id: productId,
      location_id: sectionId,
      quantity,
      reason: "manual_in",
      dimensions: dimensions ?? null,
      completed_operations: completedOperations,
      comment,
    }),
  });
  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`Add remainder failed: ${res.statusText} (${res.status}) - ${errText}`);
  }
  return res.json();
}

/**
 * @ui — тикет #232: импорт остатков из буфера обмена (TSV), тем же
 * эндпоинтом `POST /api/stock/import/remainders`, что и UI, но без файла.
 * Создаёт настоящий батч истории (одна строка журнала + строки импорта),
 * поэтому годен для сетапа сценариев «посмотреть → откатить».
 */
export async function apiImportRemainders(
  sectionId: number,
  rows: Array<{ sku: string; quantity: number; comment?: string }>,
  opts: { clearExisting?: boolean } = {},
) {
  const tsv = rows
    .map((r) => [r.sku, String(r.quantity), r.comment ?? ""].join("\t"))
    .join("\n");
  const form = new FormData();
  form.append("location_id", String(sectionId));
  form.append("clipboard_text", tsv);
  form.append("skip_invalid", "true");
  form.append("clear_existing", String(opts.clearExisting ?? false));
  const res = await fetch(`${BACKEND_URL}/api/stock/import/remainders`, {
    method: "POST",
    headers: await authHeaders(),
    body: form,
  });
  if (!res.ok) {
    const errText = await res.text();
    throw new Error(
      `Import remainders failed: ${res.statusText} (${res.status}) - ${errText}`,
    );
  }
  return res.json() as Promise<{ batch_id: number; imported_count: number }>;
}

/** @ui — тикет #232: список батчей истории импорта остатков. */
export async function apiGetImportBatches() {
  const res = await fetch(
    `${BACKEND_URL}/api/stock/import/remainders/batches`,
    { headers: await authHeaders() },
  );
  if (!res.ok) {
    throw new Error(`Get import batches failed: ${res.statusText} (${res.status})`);
  }
  return res.json() as Promise<
    Array<{
      batch_id: number;
      status: string;
      imported_rows: number;
      can_rollback: boolean;
      filename: string | null;
    }>
  >;
}

// ─── Тикет #96: кастомный роут с финальной production-стадией ───────────────

export async function apiCreateRoute(name: string) {
  const res = await fetch(`${BACKEND_URL}/api/routes`, {
    method: "POST",
    headers: await authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ name, description: "E2E final-release", is_active: true }),
  });
  if (!res.ok) {
    throw new Error(`Create route failed: ${res.status} ${await res.text()}`);
  }
  return res.json();
}

export async function apiAddRouteStep(
  routeId: number,
  step: {
    sequence: number;
    section_id: number;
    operation_code?: string | null;
    operation_name: string;
    is_final?: boolean;
    stage_kind?: "production" | "transit";
    storage_section_id?: number | null;
  },
) {
  const res = await fetch(`${BACKEND_URL}/api/routes/${routeId}/steps`, {
    method: "POST",
    headers: await authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({
      sequence: step.sequence,
      section_id: step.section_id,
      operation_code: step.operation_code ?? null,
      operation_name: step.operation_name,
      is_final: step.is_final ?? false,
      stage_kind: step.stage_kind ?? "production",
      storage_section_id: step.storage_section_id ?? null,
      requires_acceptance: true,
      allow_parallel: false,
    }),
  });
  if (!res.ok) {
    throw new Error(`Add route step failed: ${res.status} ${await res.text()}`);
  }
  return res.json();
}

/**
 * `stage_preset` демо-ручки (`backend/app/api/routes/demo.py::StagePreset`) —
 * на какой стадии остановить тестовый прогон:
 *  * `before_approve` / `after_approve` — до/после утверждения;
 *  * `after_release` — позиция запущена: задания на участках есть, движений
 *    материала ещё нет (в «Готово к передаче» — складская строка);
 *  * `to_step_ready` — всё до указанного этапа, сам этап ждёт факта;
 *  * `full_route` — все стадии пройдены, задачи завершены, последняя не
 *    выпущена.
 */
export type DemoStagePreset =
  | "before_approve"
  | "after_approve"
  | "after_release"
  | "to_step_ready"
  | "full_route";

/**
 * @smoke — прогнать позицию по роуту до состояния «задачи завершены, не выпущены».
 *
 * `stage_preset` по умолчанию `full_route`: поведение прежних спек не меняется.
 * Другая стадия нужна, когда проверке важно промежуточное состояние — например,
 * складская строка «Готово к передаче» существует только до движений
 * материала (`after_release`).
 */
export async function apiRunDemoFullRoute(
  token: string,
  payload: {
    initial_quantity: string;
    route_id: number;
    product_id: number;
    run_id: string;
    stage_preset?: DemoStagePreset;
    target_route_stage_id?: number | null;
  },
) {
  const res = await fetch(`${BACKEND_URL}/api/demo/test-runs/full-route`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({
      initial_quantity: payload.initial_quantity,
      route_id: payload.route_id,
      product_id: payload.product_id,
      run_id: payload.run_id,
      stage_preset: payload.stage_preset ?? "full_route",
      target_route_stage_id: payload.target_route_stage_id ?? null,
    }),
  });
  if (!res.ok) {
    throw new Error(`Demo full-route failed: ${res.status} ${await res.text()}`);
  }
  return res.json();
}

/** @smoke — токен доступа authenticatedPage (localStorage `ktm2000_token` → cookie fallback). */
export async function apiAccessTokenFromPage(page: {
  evaluate: (fn: () => string) => Promise<string>;
  context: () => { cookies: () => Promise<Array<{ name: string; value: string }>> };
}): Promise<string> {
  const fromStorage = await page.evaluate(() => localStorage.getItem("ktm2000_token") ?? "");
  if (fromStorage) return fromStorage;
  const cookies = await page.context().cookies();
  const byCookie = cookies.find(
    (c) => c.name === "ktm2000_token" || c.name === "access_token",
  );
  return byCookie?.value ?? "";
}