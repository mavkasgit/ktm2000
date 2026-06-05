import { apiClient } from "./client";

export type DefectItem = {
  id: number;
  quantity: number;
  defect_type_code_snapshot: string | null;
  defect_type_name_snapshot: string | null;
  description: string | null;
};

export type DefectDecision = {
  id: number;
  decision_type: string;
  quantity: number;
  reason: string | null;
  comment: string | null;
  decided_at: string;
};

export type DefectRouteStage = {
  id: number;
  sequence: number;
  operation_code: string | null;
  operation_name: string;
};

export type DefectOut = {
  id: number;
  status: string;
  product_id: number;
  product_sku: string;
  product_name: string;
  section_id: number;
  section_code: string;
  section_name: string;
  task_id: number | null;
  route_stage_id: number | null;
  route_stage: DefectRouteStage | null;
  spg_remainder_id: number | null;
  responsible_section_id: number | null;
  responsible_section_code: string | null;
  responsible_section_name: string | null;
  comment: string | null;
  created_by: number;
  created_by_user_name: string | null;
  created_at: string;
  total_quantity: number;
  reason: string | null;
  items: DefectItem[];
  decisions: DefectDecision[];
};

export type DefectTypeOut = {
  id: number;
  code: string;
  name: string;
  category: string | null;
  severity: number;
  requires_quality_decision: boolean;
  description: string | null;
};

export type CreateDefectPayload = {
  task_id?: number | null;
  product_id?: number | null;
  section_id?: number | null;
  route_stage_id?: number | null;
  spg_remainder_id?: number | null;
  quantity: number;
  reason?: string | null;
  comment?: string | null;
  idempotency_key?: string | null;
};

export type DefectDecisionPayload = {
  decision_type: string;
  quantity: number;
  target_section_id?: number | null;
  reason?: string | null;
  comment?: string | null;
  idempotency_key?: string | null;
};

export async function getSpgDefects(spgId: number): Promise<DefectOut[]> {
  const { data } = await apiClient.get<DefectOut[]>(`/spg/${spgId}/defects`);
  return data;
}

export async function getDefectTypes(): Promise<DefectTypeOut[]> {
  const { data } = await apiClient.get<DefectTypeOut[]>("/shopfloor/defect-types");
  return data;
}

export async function createDefect(payload: CreateDefectPayload): Promise<{ defect_id: number; item_id: number | null }> {
  const { data } = await apiClient.post<{ defect_id: number; item_id: number | null }>("/shopfloor/defects", payload);
  return data;
}

export async function defectDecide(
  defectId: number,
  payload: DefectDecisionPayload
): Promise<{ defect_id: number; decision_id: number; defect_status: string; rework_task_id: number | null }> {
  const { data } = await apiClient.post<{
    defect_id: number;
    decision_id: number;
    defect_status: string;
    rework_task_id: number | null;
  }>(`/shopfloor/defects/${defectId}/decisions`, payload);
  return data;
}

export type ImportDefectsResponse = {
  success: boolean;
  imported_count: number;
  errors: string[];
};

export async function importDefectsExcel(
  spgId: number,
  file: File,
): Promise<ImportDefectsResponse> {
  const formData = new FormData();
  formData.append("file", file);
  const { data } = await apiClient.post<ImportDefectsResponse>(
    `/spg/${spgId}/defects/import`,
    formData,
    {
      headers: {
        "Content-Type": "multipart/form-data",
      },
    },
  );
  return data;
}

