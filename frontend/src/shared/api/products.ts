import { apiClient, getErrorMessage } from "./client";

export { getErrorMessage };

export type ProductType = "finished_good" | "semi_finished" | "component" | "material";

export type DimensionState = "length" | "area" | "volume";

export type ProcessingFlag = {
  code: string;
  name: string;
  section_scope: string | null;
};

/** Значение «кол-во на подвес» для одной длины (#60): авто и ручное раздельно. */
export type HangerQuantityValue = {
  auto: number | null;
  manual: number | null;
};

/** Per-length словарь: ключ — длина в мм ("2780"), значение — {auto, manual} (#60). */
export type QuantityPerHangerDict = Record<string, HangerQuantityValue>;

/** Режим подвеса (#126): 'auto' — считается сервером, 'manual' — ручное значение. */
export type HangerMode = "auto" | "manual";

export type Product = {
  id: number;
  sku: string;
  code: string | null;
  name: string;
  type: ProductType;
  unit: string;
  is_active: boolean;
  notes: string | null;
  profile_type: string | null;
  alloy: string | null;
  color: string | null;
  anod_type: string | null;
  length_mm: number | null;
  weight_per_meter: number | null;
  perimeter_mm: number | null;
  mount_width_mm: number | null;
  quantity_per_hanger: QuantityPerHangerDict | null;
  hanger_mode: HangerMode;
  cross_section: string | null;
  photo_thumb: string | null;
  photo_full: string | null;
  source: string | null;
  is_catalog_item: boolean;
  is_paired_profile: boolean;
  dimension_state: DimensionState;
  primary_length_mm: number | null;
  skip_shot_blast: boolean;
  aliases: string[];
  lengths_mm: number[];
  processing_flags: ProcessingFlag[];
  is_laminated: boolean;
  has_standard_techcard?: boolean;
  has_paired_techcard?: boolean;
  dimensions?: Record<string, number> | null;
};

export type CreateProductInput = {
  sku: string;
  code?: string | null;
  name: string;
  type: ProductType;
  unit?: string;
  is_active?: boolean;
  notes?: string | null;
  profile_type?: string | null;
  alloy?: string | null;
  color?: string | null;
  anod_type?: string | null;
  length_mm?: number | null;
  weight_per_meter?: number | null;
  perimeter_mm?: number | null;
  mount_width_mm?: number | null;
  quantity_per_hanger?: QuantityPerHangerDict | null;
  hanger_mode?: HangerMode;
  cross_section?: string | null;
  source?: string | null;
  is_catalog_item?: boolean;
  skip_shot_blast?: boolean;
  dimension_state?: DimensionState;
  primary_length_mm?: number | null;
  aliases?: string[];
  lengths_mm?: number[];
  processing_flag_codes?: string[];
  is_laminated?: boolean;
};

export type PatchProductInput = Partial<CreateProductInput>;

export type ProductFilters = {
  q?: string;
  type?: ProductType;
  profile_type?: string;
  alloy?: string;
  color?: string;
  is_active?: boolean;
  is_catalog_item?: boolean;
  is_paired_profile?: boolean;
  skip_shot_blast?: boolean;
  is_laminated?: boolean;
  sku?: string;
  name?: string;
  length_from?: number;
  length_to?: number;
  qty_from?: number;
  qty_to?: number;
  sort?: string;
  limit?: number;
  offset?: number;
};

export type ProductsListBody = {
  items: Product[];
  total: number;
};

export type ProductListResponse = {
  items: Product[];
  total: number;
  limit: number;
  offset: number;
};

export async function listProducts(filters: ProductFilters = {}) {
  const response = await listProductsPaginated(filters);
  return response.items;
}

/** Backward-compatible helper: returns all items (paginated, max 500 per request). */
export async function fetchAllProducts(params: ProductFilters = {}) {
  const pageSize = 500;
  const all: Product[] = [];
  let offset = 0;
  let total = Infinity;

  while (offset < total) {
    const response = await listProductsPaginated({ limit: pageSize, offset, ...params });
    all.push(...response.items);
    total = response.total;
    offset += response.items.length;
    if (response.items.length === 0) break;
  }

  return all;
}

export async function listProductsPaginated(
  filters: ProductFilters = {},
): Promise<ProductListResponse> {
  const limit = filters.limit ?? 50;
  const offset = filters.offset ?? 0;
  const response = await apiClient.get<ProductsListBody>("/products", { params: filters });
  const { items } = response.data;
  const bodyTotal = response.data.total;
  const headerTotal = response.headers["x-total-count"];
  const total =
    bodyTotal != null && Number.isFinite(bodyTotal)
      ? bodyTotal
      : headerTotal !== undefined
        ? Number(headerTotal)
        : items.length;
  return {
    items,
    total: Number.isFinite(total) ? total : items.length,
    limit,
    offset,
  };
}

export async function createProduct(payload: CreateProductInput) {
  const response = await apiClient.post<Product>("/products", payload);
  const encoded = response.headers["x-activated-aliases"];
  const activatedAliases = encoded ? atob(encoded).split(",").filter(Boolean) : [];
  return {
    data: response.data,
    activatedAliases,
  };
}

export async function getProduct(productId: number) {
  const { data } = await apiClient.get<Product>(`/products/${productId}`);
  return data;
}

export async function patchProduct(productId: number, payload: PatchProductInput) {
  const response = await apiClient.patch<Product>(`/products/${productId}`, payload);
  const encoded = response.headers["x-activated-aliases"];
  const activatedAliases = encoded ? atob(encoded).split(",").filter(Boolean) : [];
  return {
    data: response.data,
    activatedAliases,
  };
}

export async function deleteProduct(productId: number) {
  await apiClient.delete(`/products/${productId}`);
}

/** Пара сырьевых артикулов (ADR-0023, #146): A+B, ручная N по длинам пересечения. */
export type ProductPairPartner = {
  id: number;
  sku: string;
  name: string;
  is_paired_profile: boolean;
};

export type ProductPair = {
  id: number;
  product_a_id: number;
  product_b_id: number;
  partner: ProductPairPartner;
  /** Длины пары — пересечение длин A и B, по возрастанию. */
  lengths: number[];
  /** Ключ — длина в мм ("2500"); auto считается сервером, вводится только manual. */
  quantity_per_hanger: Record<string, HangerQuantityValue>;
};

export type PairHangerManual = { manual: number | null };

export type CreateProductPairInput = {
  partner_product_id: number;
  quantity_per_hanger?: Record<string, PairHangerManual>;
};

export type PatchProductPairInput = {
  quantity_per_hanger: Record<string, PairHangerManual>;
};

/** Элемент каталога всех пар (#150): источник парных строк расчёта подвесов. */
export type ProductPairCatalogEntry = {
  id: number;
  product_a_id: number;
  product_b_id: number;
  /** Длины пары — пересечение длин A и B; пусто — пара «не существует на длине». */
  lengths: number[];
  /** Ключ — длина в мм ("2500"); auto считается сервером, вводится только manual. */
  quantity_per_hanger: Record<string, HangerQuantityValue>;
};

export async function listProductPairCatalog() {
  const { data } = await apiClient.get<ProductPairCatalogEntry[]>("/product-pairs");
  return data;
}

export async function listProductPairs(productId: number) {
  const { data } = await apiClient.get<ProductPair[]>(`/products/${productId}/pairs`);
  return data;
}

export async function createProductPair(productId: number, payload: CreateProductPairInput) {
  const { data } = await apiClient.post<ProductPair>(`/products/${productId}/pairs`, payload);
  return data;
}

export async function patchProductPair(
  productId: number,
  pairId: number,
  payload: PatchProductPairInput,
) {
  const { data } = await apiClient.patch<ProductPair>(`/products/${productId}/pairs/${pairId}`, payload);
  return data;
}

export async function deleteProductPair(productId: number, pairId: number) {
  await apiClient.delete(`/products/${productId}/pairs/${pairId}`);
}

export async function uploadProductPhoto(productId: number, file: File, kind: "full" | "thumb" = "full") {
  const formData = new FormData();
  formData.append("file", file);
  const { data } = await apiClient.post<Product>(`/products/${productId}/photo?kind=${kind}`, formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

export async function uploadCatalogZip(file: File) {
  const formData = new FormData();
  formData.append("file", file);
  const { data } = await apiClient.post<{
    imported: number;
    updated: number;
    skipped: number;
    errors: string[];
    total_in_zip: number;
  }>("/catalog-import/upload-zip", formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

export type CatalogPreviewItem = {
  sku: string;
  name: string;
  length_mm: number | null;
  quantity_per_hanger: number | null;
  has_photo: boolean;
  action: "create" | "update" | "skip";
  row?: number;
  lengths_mm?: number[];
  quantities_per_hanger?: number[] | null;
  /** Состав ГП, который будет записан (#154); null — колонки состава пусты. */
  composition?: { sku: string; quantity: number }[] | null;
  warnings?: string[];
};

export type CatalogImportError = {
  row: number;
  sku: string;
  message: string;
};

export type CatalogPreview = {
  items: CatalogPreviewItem[];
  stats: { total: number; create: number; update: number; skip: number; errors?: number };
  errors?: CatalogImportError[];
};

export async function previewCatalogZip(file: File) {
  const formData = new FormData();
  formData.append("file", file);
  const { data } = await apiClient.post<CatalogPreview>(
    "/catalog-import/preview-zip",
    formData,
    { headers: { "Content-Type": "multipart/form-data" } }
  );
  return data;
}

export async function previewCatalogExcel(file: File) {
  const formData = new FormData();
  formData.append("file", file);
  const { data } = await apiClient.post<CatalogPreview>(
    "/catalog-import/preview-excel",
    formData,
    { headers: { "Content-Type": "multipart/form-data" } }
  );
  return data;
}

export type CatalogExcelApplyResult = {
  imported: number;
  updated: number;
  skipped: number;
  errors: CatalogImportError[];
};

export async function applyCatalogExcel(file: File) {
  const formData = new FormData();
  formData.append("file", file);
  const { data } = await apiClient.post<CatalogExcelApplyResult>(
    "/catalog-import/apply-excel",
    formData,
    { headers: { "Content-Type": "multipart/form-data" } }
  );
  return data;
}

export async function downloadCatalogTemplate() {
  const { data } = await apiClient.get<Blob>("/catalog-import/template-excel", {
    responseType: "blob",
  });
  const url = URL.createObjectURL(data);
  const link = document.createElement("a");
  link.href = url;
  link.download = "catalog_template.xlsx";
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export type AliasSuggestion = {
  id: number;
  sku: string;
  name: string;
  is_paired_profile: boolean;
};

export async function searchProductsForAlias(
  q: string,
  options?: { excludeSku?: string; excludeAliases?: string[]; pairedOnly?: boolean; limit?: number }
) {
  const params: Record<string, string | number | boolean> = { q };
  if (options?.excludeSku) params.exclude_sku = options.excludeSku;
  if (options?.excludeAliases?.length) params.exclude_aliases = options.excludeAliases.join(",");
  if (options?.pairedOnly) params.paired_only = true;
  if (options?.limit) params.limit = options.limit;
  const { data } = await apiClient.get<AliasSuggestion[]>("/products/search/products", { params });
  return data;
}

export async function searchProductSuggestions(
  q: string,
  field: "sku" | "name" | "profile_type" | "alloy" | "color" = "sku",
  limit = 20
) {
  const { data } = await apiClient.get<string[]>("/products/search/suggestions", {
    params: { q, field, limit },
  });
  return data;
}

export async function listProcessingFlags() {
  const { data } = await apiClient.get<ProcessingFlag[]>("/products/processing-flags");
  return data;
}

export type ProductRouteOperationOut = {
  id: number | null;
  operation_code: string | null;
  operation_name: string;
};

export type ProductRouteStageOut = {
  id: number;
  sequence: number;
  section_id: number | null;
  section_code: string;
  section_name: string;
  is_significant: boolean;
  requires_acceptance: boolean;
  is_final: boolean;
  stage_kind?: "production" | "transit";
  storage_section_id?: number | null;
  operations: ProductRouteOperationOut[];
};

export async function getProductRouteStages(productId: number): Promise<ProductRouteStageOut[]> {
  const { data } = await apiClient.get<ProductRouteStageOut[]>(`/products/${productId}/route-stages`);
  return data;
}

export type LastCompletedOperation = {
  section_id: number | null;
  section_code: string | null;
  section_name: string | null;
  operation_code: string | null;
  operation_name: string | null;
  sequence: number | null;
};

export async function getProductLastCompletedOperation(productId: number): Promise<LastCompletedOperation> {
  const { data } = await apiClient.get<LastCompletedOperation>(`/products/${productId}/last-completed-operation`);
  return data;
}
