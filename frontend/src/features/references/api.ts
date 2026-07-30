import { apiClient } from "@/shared/api/client";

export type DimensionType = {
  id: number;
  code: string;
  name: string;
  unit: string;
  value_type: string;
  created_at: string;
};

export type CreateDimensionTypeInput = {
  code: string;
  name: string;
  unit: string;
  value_type?: string;
};

export type PatchDimensionTypeInput = Partial<CreateDimensionTypeInput>;

export type ProductDimension = {
  id: number;
  product_id: number;
  dimension_type_id: number;
  is_required: boolean;
  default_value: number | null;
  dimension_type: DimensionType;
};

export type CreateProductDimensionInput = {
  dimension_type_id: number;
  is_required?: boolean;
  default_value?: number | null;
};

export type PatchProductDimensionInput = {
  is_required?: boolean;
  default_value?: number | null;
};

export async function listDimensionTypes(): Promise<DimensionType[]> {
  const { data } = await apiClient.get<DimensionType[]>("/dimension-types");
  return data;
}

export async function createDimensionType(payload: CreateDimensionTypeInput): Promise<DimensionType> {
  const { data } = await apiClient.post<DimensionType>("/dimension-types", payload);
  return data;
}

export async function patchDimensionType(typeId: number, payload: PatchDimensionTypeInput): Promise<DimensionType> {
  const { data } = await apiClient.patch<DimensionType>(`/dimension-types/${typeId}`, payload);
  return data;
}

export async function deleteDimensionType(typeId: number): Promise<void> {
  await apiClient.delete(`/dimension-types/${typeId}`);
}

export async function listProductDimensions(productId: number): Promise<ProductDimension[]> {
  const { data } = await apiClient.get<ProductDimension[]>(`/products/${productId}/dimensions`);
  return data;
}

export async function createProductDimension(
  productId: number,
  payload: CreateProductDimensionInput,
): Promise<ProductDimension> {
  const { data } = await apiClient.post<ProductDimension>(`/products/${productId}/dimensions`, payload);
  return data;
}

export async function patchProductDimension(
  productId: number,
  linkId: number,
  payload: PatchProductDimensionInput,
): Promise<ProductDimension> {
  const { data } = await apiClient.patch<ProductDimension>(`/products/${productId}/dimensions/${linkId}`, payload);
  return data;
}

export async function deleteProductDimension(productId: number, linkId: number): Promise<void> {
  await apiClient.delete(`/products/${productId}/dimensions/${linkId}`);
}
