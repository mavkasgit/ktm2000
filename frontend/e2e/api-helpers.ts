import fs from "fs";
import path from "path";

export const BACKEND_URL = process.env.E2E_API_URL
  ? process.env.E2E_API_URL.replace(/\/api$/, "")
  : "http://localhost:8012";

export function unwrapItems<T>(body: T[] | { items?: T[] }): T[] {
  return Array.isArray(body) ? body : body.items ?? [];
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
) {
  const res = await fetch(`${BACKEND_URL}/api/stock/adjustment`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      product_id: productId,
      location_id: sectionId,
      quantity,
      reason: "manual_in",
      comment,
    }),
  });
  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`Add remainder failed: ${res.statusText} (${res.status}) - ${errText}`);
  }
  return res.json();
}