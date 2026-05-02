import { apiClient } from "./client";

export type Bom = {
  id: number;
  product_id: number;
  version: string;
  is_active: boolean;
};

export type BomLine = {
  id: number;
  bom_id: number;
  component_product_id: number;
  quantity: number;
  unit: string;
};

export type CreateBomInput = {
  product_id: number;
  version: string;
  is_active?: boolean;
};

export type CreateBomLineInput = {
  component_product_id: number;
  quantity: number;
  unit: string;
};

export type PatchBomInput = Partial<Pick<CreateBomInput, "version" | "is_active">>;

export async function createBom(payload: CreateBomInput) {
  const { data } = await apiClient.post<Bom>("/boms", payload);
  return data;
}

export async function createBomLine(bomId: number, payload: CreateBomLineInput) {
  const { data } = await apiClient.post<BomLine>(`/boms/${bomId}/lines`, payload);
  return data;
}

export async function patchBom(bomId: number, payload: PatchBomInput) {
  const { data } = await apiClient.patch<Bom>(`/boms/${bomId}`, payload);
  return data;
}
