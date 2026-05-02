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
};

export type CreateProductInput = {
  sku: string;
  name: string;
  type: ProductType;
  unit: string;
  is_active?: boolean;
  notes?: string | null;
};

export type PatchProductInput = Partial<Omit<CreateProductInput, "sku">>;

export async function listProducts() {
  const { data } = await apiClient.get<Product[]>("/products");
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
