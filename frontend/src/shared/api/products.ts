import { apiClient } from "./client";

export type ProductType = "finished_good" | "semi_finished" | "component" | "material";

export type Product = {
  id: number;
  sku: string;
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
  quantity_per_hanger: number | null;
  cross_section: string | null;
  photo_thumb: string | null;
  photo_full: string | null;
  source: string | null;
  is_catalog_item: boolean;
  is_paired_profile: boolean;
  skip_shot_blast: boolean;
  aliases: string[];
};

export type CreateProductInput = {
  sku: string;
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
  quantity_per_hanger?: number | null;
  cross_section?: string | null;
  source?: string | null;
  is_catalog_item?: boolean;
  is_paired_profile?: boolean;
  skip_shot_blast?: boolean;
  aliases?: string[];
};

export type PatchProductInput = Partial<Omit<CreateProductInput, "sku">>;

export type ProductFilters = {
  q?: string;
  type?: ProductType;
  profile_type?: string;
  alloy?: string;
  color?: string;
  is_active?: boolean;
  is_catalog_item?: boolean;
  is_paired_profile?: boolean;
  sort?: string;
  limit?: number;
  offset?: number;
};

export async function listProducts(filters: ProductFilters = {}) {
  const { data } = await apiClient.get<Product[]>("/products", { params: filters });
  return data;
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
  profile_type: string | null;
  length_mm: number | null;
  quantity_per_hanger: number | null;
  has_photo: boolean;
  action: "create" | "update" | "skip";
};

export type CatalogPreview = {
  items: CatalogPreviewItem[];
  stats: { total: number; create: number; update: number; skip: number };
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

export type AliasSuggestion = {
  id: number;
  sku: string;
  name: string;
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
