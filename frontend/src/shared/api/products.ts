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
};

export type PatchProductInput = Partial<Omit<CreateProductInput, "sku">>;

export type ProductFilters = {
  q?: string;
  type?: ProductType;
  profile_type?: string;
  alloy?: string;
  color?: string;
  is_active?: boolean;
  limit?: number;
  offset?: number;
};

export async function listProducts(filters: ProductFilters = {}) {
  const { data } = await apiClient.get<Product[]>("/products", { params: filters });
  return data;
}

export async function createProduct(payload: CreateProductInput) {
  const { data } = await apiClient.post<Product>("/products", payload);
  return data;
}

export async function getProduct(productId: number) {
  const { data } = await apiClient.get<Product>(`/products/${productId}`);
  return data;
}

export async function patchProduct(productId: number, payload: PatchProductInput) {
  const { data } = await apiClient.patch<Product>(`/products/${productId}`, payload);
  return data;
}

export async function uploadProductPhoto(productId: number, file: File) {
  const formData = new FormData();
  formData.append("file", file);
  const { data } = await apiClient.post<Product>(`/products/${productId}/photo`, formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
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
