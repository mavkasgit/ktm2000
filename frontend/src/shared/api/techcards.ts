import { apiClient } from "./client";

export type Techcard = {
  id: number;
  product_id: number;
  version: string;
  processing_type: "standart_processing" | "paired_processing";
  is_active: boolean;
};

export type TechcardLine = {
  id: number;
  techcard_id: number;
  component_product_id: number;
  quantity: number;
  unit: string;
};

export type TechcardPair = {
  id: number;
  techcard_id: number;
  name: string;
  priority: number;
  is_active: boolean;
};

export type TechcardPairLine = {
  id: number;
  techcard_pair_id: number;
  component_product_id: number;
  quantity: number;
  unit: string;
};

export type CreateTechcardInput = {
  product_id: number;
  version: string;
  processing_type?: "standart_processing" | "paired_processing";
  is_active?: boolean;
};

export type CreateTechcardLineInput = {
  component_product_id: number;
  quantity: number;
  unit: string;
};

export type PatchTechcardInput = Partial<Pick<CreateTechcardInput, "version" | "is_active" | "processing_type">>;

export async function createTechcard(payload: CreateTechcardInput) {
  const { data } = await apiClient.post<Techcard>("/techcards", payload);
  return data;
}

export async function listTechcards() {
  const { data } = await apiClient.get<Techcard[]>("/techcards");
  return data;
}

export async function getTechcard(techcardId: number) {
  const { data } = await apiClient.get<Techcard & { product_article: string; lines: TechcardLine[]; techcard_pairs: TechcardPair[] }>(`/techcards/${techcardId}`);
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

export async function createTechcardPair(
  techcardId: number,
  payload: { name: string; priority?: number; is_active?: boolean }
) {
  const { data } = await apiClient.post<TechcardPair>(`/techcards/${techcardId}/techcard-pairs`, payload);
  return data;
}

export async function patchTechcardPair(
  techcardId: number,
  pairId: number,
  payload: { name?: string; priority?: number; is_active?: boolean }
) {
  const { data } = await apiClient.patch<TechcardPair>(`/techcards/${techcardId}/techcard-pairs/${pairId}`, payload);
  return data;
}

export async function getTechcardPair(techcardId: number, pairId: number) {
  const { data } = await apiClient.get<TechcardPair & { lines: TechcardPairLine[] }>(
    `/techcards/${techcardId}/techcard-pairs/${pairId}`
  );
  return data;
}

export async function createTechcardPairLine(
  techcardId: number,
  pairId: number,
  payload: { component_product_id: number; quantity: number; unit: string }
) {
  const { data } = await apiClient.post<TechcardPairLine>(`/techcards/${techcardId}/techcard-pairs/${pairId}/lines`, payload);
  return data;
}
