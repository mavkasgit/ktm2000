import { execFileSync } from "child_process";
import fs from "fs";
import path from "path";

export const BACKEND_URL = process.env.E2E_API_URL
  ? process.env.E2E_API_URL.replace(/\/api$/, "")
  : "http://localhost:8012";

export function unwrapItems<T>(body: T[] | { items?: T[] }): T[] {
  return Array.isArray(body) ? body : body.items ?? [];
}


/**
 * Проверить тестовую БД и при необходимости бутстрапнуть её (единое поведение
 * для всех e2e-тестов). Перезапись — ТОЛЬКО если БД пуста: миграции + базовый
 * сид через backend/.venv. Инициализированная БД не трогается.
 */
export async function ensureDbBootstrapped(): Promise<void> {
  let sections: unknown[] = [];
  try {
    const res = await fetch(`${BACKEND_URL}/api/sections`);
    sections = res.ok ? unwrapItems<unknown>(await res.json()) : [];
  } catch {
    throw new Error(
      `Тест-стек недоступен на ${BACKEND_URL}. Поднимите его: ` +
        `EXTERNAL_PORT=8100 docker compose --env-file .env.test -f infra/compose/docker-compose.test.yml up -d --build`,
    );
  }
  if (sections.length > 0) {
    return; // БД инициализирована — ничего не перезаписываем
  }

  const dbUrl =
    process.env.E2E_TEST_DATABASE_URL ??
    readEnvTestVar("TEST_DATABASE_URL") ??
    process.env.DATABASE_URL;
  if (!dbUrl) {
    throw new Error(
      "БД пуста, но URL не задан: установите E2E_TEST_DATABASE_URL или TEST_DATABASE_URL в .env.test",
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
  console.log("[ensureDbBootstrapped] БД пуста — миграции + базовый сид…");
  execFileSync(py, ["-m", "alembic", "upgrade", "head"], { cwd: backendDir, env, stdio: "inherit" });
  execFileSync(py, ["scripts/seed_all.py"], { cwd: backendDir, env, stdio: "inherit" });
}

/** Прочитать KEY=VALUE из корневого .env.test (без зависимости от dotenv). */
function readEnvTestVar(key: string): string | undefined {
  try {
    const text = fs.readFileSync(path.resolve(process.cwd(), "../.env.test"), "utf8");
    return text.match(new RegExp(`^${key}=(.*)$`, "m"))?.[1]?.trim();
  } catch {
    return undefined;
  }
}

export async function apiSeedData() {
  const res = await fetch(`${BACKEND_URL}/api/routes-seed?force=true`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
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
    lengths_mm: [6000],
    quantity_per_hanger: 100,
  },
  {
    sku: "ЮП-2083",
    name: "Профиль ЮП-2083",
    type: "component",
    lengths_mm: [6000],
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

/** @smoke only — create catalog products if missing (not used in @ui). */
export async function apiEnsureTestProducts() {
  for (const product of E2E_TEST_PRODUCTS) {
    try {
      await apiGetProductBySku(product.sku);
    } catch {
      const res = await fetch(`${BACKEND_URL}/api/products`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sku: product.sku,
          name: product.name,
          type: product.type,
          unit: "pcs",
          is_active: true,
          is_catalog_item: true,
          lengths_mm: product.lengths_mm,
          length_mm: product.lengths_mm[0],
          quantity_per_hanger: product.quantity_per_hanger,
        }),
      });
      if (!res.ok) {
        const errText = await res.text();
        throw new Error(`Create product ${product.sku} failed: ${res.status} ${errText}`);
      }
    }
  }
}

/** @smoke only — active techcard with default line (backend _ensure_default_line). */
export async function apiEnsureTestTechcards() {
  for (const product of E2E_TEST_PRODUCTS) {
    const fg = await apiGetProductBySku(product.sku);
    await apiGetOrCreateTechcard(fg);
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

/** @smoke — свежий продукт без lengths (как в demo-фикстурах) для кастомного роута. */
export async function apiCreateBareProduct(sku: string) {
  const res = await fetch(`${BACKEND_URL}/api/products`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      sku,
      name: `Bare ${sku}`,
      type: "finished_good",
      unit: "pcs",
      is_active: true,
    }),
  });
  if (!res.ok) {
    throw new Error(`Create bare product failed: ${res.status} ${await res.text()}`);
  }
  return res.json();
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

export async function apiGetOrCreateTechcard(product: { id: number; sku: string }) {
  const res = await fetch(
    `${BACKEND_URL}/api/techcards?sku=${encodeURIComponent(product.sku)}&limit=50&is_active=true`,
  );
  if (!res.ok) {
    throw new Error(`Get techcards failed: ${res.statusText} (${res.status})`);
  }
  const techcards = unwrapItems<{ id: number; product_id: number; is_active: boolean }>(
    await res.json(),
  );
  const existing = techcards.find((t) => t.product_id === product.id && t.is_active);
  if (existing) {
    return existing;
  }
  return apiCreateTechcard(product.id);
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

export async function apiImportExcel(templateId: number, filePath: string) {
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

export async function apiApplyChangeSet(planId: number, changeSetId: number) {
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

export async function apiGetPlanPositions(planId: number) {
  const res = await fetch(`${BACKEND_URL}/api/production-plans/${planId}/all-positions`);
  if (!res.ok) {
    throw new Error(`Get plan positions failed: ${res.statusText} (${res.status})`);
  }
  return res.json();
}

export async function apiGetActiveRoutes() {
  const res = await fetch(`${BACKEND_URL}/api/routes`);
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
      headers: { "Content-Type": "application/json" },
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
  const sections = unwrapItems<{ id: number; code: string }>(await res.json());
  const section = sections.find((s) => s.code === code);
  if (!section) {
    throw new Error(`Section not found with code: ${code}`);
  }
  return section;
}

/** @smoke — POST /api/stock/adjustment (замена устаревшего spg/manual-operation). */
export async function apiAddRemainder(
  productId: number,
  sectionId: number,
  quantity: number,
  comment: string,
  dimensions?: Record<string, number> | null,
) {
  const res = await fetch(`${BACKEND_URL}/api/stock/adjustment`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      product_id: productId,
      location_id: sectionId,
      quantity,
      reason: "manual_in",
      dimensions: dimensions ?? null,
      comment,
    }),
  });
  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`Add remainder failed: ${res.statusText} (${res.status}) - ${errText}`);
  }
  return res.json();
}

// ─── Тикет #96: кастомный роут с финальной production-стадией ───────────────

export async function apiCreateRoute(name: string) {
  const res = await fetch(`${BACKEND_URL}/api/routes`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
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
    headers: { "Content-Type": "application/json" },
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

/** @smoke — прогнать позицию по роуту до состояния «задачи завершены, не выпущены». */
export async function apiRunDemoFullRoute(
  token: string,
  payload: {
    initial_quantity: string;
    route_id: number;
    techcard_id: number;
    run_id: string;
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
      techcard_id: payload.techcard_id,
      run_id: payload.run_id,
      stage_preset: "full_route",
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