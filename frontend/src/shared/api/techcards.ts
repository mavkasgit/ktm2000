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
  product_sku?: string | null;
  techcard_lines?: TechcardLineSummary[];
};

export type TechcardLineSummary = {
  id: number;
  component_product_id: number;
  component_product_sku?: string | null;
  quantity: number;
  unit: string;
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

export type TechcardListParams = {
  limit?: number;
  offset?: number;
  search?: string;
  sort_by?: string;
  sort_order?: "asc" | "desc";
  processing_type?: "standart_processing" | "paired_processing";
  is_active?: boolean;
  sku?: string;
  quantity_total?: number;
};

export type TechcardListResponse = {
  items: Techcard[];
  total: number;
  limit: number;
  offset: number;
};

export async function createTechcard(payload: CreateTechcardInput) {
  const { data } = await apiClient.post<Techcard>("/techcards", payload);
  return data;
}

export async function listTechcardsPaginated(
  params: TechcardListParams = {},
): Promise<TechcardListResponse> {
  const limit = params.limit ?? 50;
  const offset = params.offset ?? 0;
  const { data } = await apiClient.get<TechcardListResponse>("/techcards", { params });
  return {
    items: data.items ?? [],
    total: data.total ?? data.items?.length ?? 0,
    limit: data.limit ?? limit,
    offset: data.offset ?? offset,
  };
}

/** Backward-compatible helper: returns all items (paginated, max 500 per request). */
export async function fetchAllTechcards(params: TechcardListParams = {}) {
  const pageSize = 500;
  const all: Techcard[] = [];
  let offset = 0;
  let total = Infinity;

  while (offset < total) {
    const response = await listTechcardsPaginated({ limit: pageSize, offset, ...params });
    all.push(...response.items);
    total = response.total;
    offset += response.items.length;
    if (response.items.length === 0) break;
  }

  return all;
}

/** Used as react-query queryFn — no params to avoid QueryFunction signature clash. */
export async function listTechcards() {
  return fetchAllTechcards();
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