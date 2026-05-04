import { apiClient } from "./client";

export type Techcard = {
  id: number;
  product_id: number | null;
  version: string;
  processing_type: "standart_processing" | "paired_processing";
  is_active: boolean;
  quantity_total?: number | null;
  quantity_a_per_item?: number | null;
  quantity_b_per_item?: number | null;
  hangers_a?: number | null;
  hangers_b?: number | null;
  hangers_total?: number | null;
};

export type TechcardLine = {
  id: number;
  techcard_id: number;
  component_product_id: number;
  quantity: number;
  unit: string;
};

export type CreateTechcardInput = {
  product_id: number | null;
  version: string;
  processing_type?: "standart_processing" | "paired_processing";
  is_active?: boolean;
  quantity_total?: number | null;
  quantity_a_per_item?: number | null;
  quantity_b_per_item?: number | null;
  hangers_a?: number | null;
  hangers_b?: number | null;
  hangers_total?: number | null;
};

export type CreateTechcardLineInput = {
  component_product_id: number;
  quantity: number;
  unit: string;
};

export type PatchTechcardInput = Partial<
  Pick<CreateTechcardInput, "version" | "is_active" | "processing_type" | "quantity_total" | "quantity_a_per_item" | "quantity_b_per_item" | "hangers_a" | "hangers_b" | "hangers_total">
>;

export async function createTechcard(payload: CreateTechcardInput) {
  const { data } = await apiClient.post<Techcard>("/techcards", payload);
  return data;
}

export async function listTechcards() {
  const { data } = await apiClient.get<Techcard[]>("/techcards");
  return data;
}

export async function getTechcard(techcardId: number) {
  const { data } = await apiClient.get<Techcard & { product_article: string; lines: TechcardLine[] }>(`/techcards/${techcardId}`);
  return data;
}

export async function createTechcardLine(techcardId: number, payload: CreateTechcardLineInput) {
  const { data } = await apiClient.post<TechcardLine>(`/techcards/${techcardId}/lines`, payload);
  return data;
}

export async function patchTechcard(techcardId: number, payload: PatchTechcardInput) {
  const { data } = await apiClient.patch<Techcard>(`/techcards/${techcardId}`, payload);
  return data;
}

export async function deleteTechcard(techcardId: number) {
  await apiClient.delete(`/techcards/${techcardId}`);
}
