import { apiClient } from "./client";

export type ProductionRoute = {
  id: number;
  name: string;
  description: string | null;
  is_active: boolean;
};

export type RouteStep = {
  id: number;
  route_id: number;
  sequence: number;
  section_id: number;
  section_code: string | null;
  section_name: string | null;
  operation_code: string | null;
  operation_name: string;
  norm_time_minutes: number | null;
  is_final: boolean;
  allow_parallel?: boolean;
  requires_acceptance?: boolean;
};

export type RouteOperationFamily = "NONE" | "DRILL" | "PRESS" | "PACK";
export type RouteOutputKind = "finished_good" | "semi_finished_shipment";

export type RouteSignatureRule = {
  id: number;
  route_id: number;
  priority: number;
  operation_family: RouteOperationFamily;
  output_kind: RouteOutputKind;
  has_pack_ops: boolean | null;
  is_active: boolean;
};

export type RouteDetail = ProductionRoute & {
  steps: RouteStep[];
  rules: RouteSignatureRule[];
};

export type RouteSelectionCondition = {
  source: "excel" | "payload" | "product";
  field_path: string;
  operator: "equals" | "not_equals" | "contains" | "not_contains" | "in" | "not_in" | "empty" | "not_empty" | "regex";
  value: unknown;
  case_sensitive: boolean;
};

export type RouteSelectionAction = {
  action: "require_section" | "exclude_section";
  section_id: number;
  section_code?: string | null;
  section_name?: string | null;
};

export type RouteSelectionRule = {
  id: number;
  code: string | null;
  name: string;
  priority: number;
  is_active: boolean;
  conditions: RouteSelectionCondition[];
  actions: RouteSelectionAction[];
};

export type RouteSelectionRuleInput = {
  code?: string | null;
  name: string;
  priority: number;
  is_active: boolean;
  conditions: RouteSelectionCondition[];
  actions: RouteSelectionAction[];
};

export type CreateRouteInput = {
  name: string;
  description?: string | null;
  is_active?: boolean;
};

export type UpdateRouteInput = {
  name?: string;
  description?: string | null;
  is_active?: boolean;
};

export type StepInput = {
  sequence: number;
  section_id: number;
  operation_code?: string | null;
  operation_name: string;
  norm_time_minutes?: number | null;
  requires_acceptance?: boolean;
  allow_parallel?: boolean;
  is_final?: boolean;
};

export type RuleInput = {
  priority: number;
  operation_family: RouteOperationFamily;
  output_kind: RouteOutputKind;
  has_pack_ops: boolean | null;
  is_active: boolean;
};

export type RuleUpdateInput = RuleInput;

export async function listRoutes(q?: string) {
  const { data } = await apiClient.get<ProductionRoute[]>("/routes", { params: q ? { q } : undefined });
  return data;
}

export async function getRoute(id: number) {
  const { data } = await apiClient.get<RouteDetail>(`/routes/${id}`);
  return data;
}

export async function createRoute(payload: CreateRouteInput) {
  const { data } = await apiClient.post<ProductionRoute>("/routes", payload);
  return data;
}

export async function updateRoute(id: number, payload: UpdateRouteInput) {
  const { data } = await apiClient.put<ProductionRoute>(`/routes/${id}`, payload);
  return data;
}

export async function deleteRoute(id: number, force: boolean = false) {
  await apiClient.delete(`/routes/${id}`, { params: { force } });
}

export async function checkRouteDelete(id: number) {
  const { data } = await apiClient.get(`/routes/${id}/delete-check`);
  return data as { has_relations: boolean; warning: string | null; steps_count: number; rules_count: number; spl_count: number; rbp_count: number; plan_positions_count: number };
}

export async function createStep(routeId: number, payload: StepInput) {
  const { data } = await apiClient.post<RouteStep>(`/routes/${routeId}/steps`, payload);
  return data;
}

export async function replaceSteps(routeId: number, steps: StepInput[]) {
  const { data } = await apiClient.put<RouteStep[]>(`/routes/${routeId}/steps`, steps);
  return data;
}

export async function addRule(routeId: number, payload: RuleInput) {
  const { data } = await apiClient.post<RouteSignatureRule>(`/routes/${routeId}/rules`, payload);
  return data;
}

export async function updateRule(routeId: number, ruleId: number, payload: RuleUpdateInput) {
  const { data } = await apiClient.put<RouteSignatureRule>(`/routes/${routeId}/rules/${ruleId}`, payload);
  return data;
}

export async function deleteRule(routeId: number, ruleId: number) {
  await apiClient.delete(`/routes/${routeId}/rules/${ruleId}`);
}

export async function listRouteSelectionRules() {
  const { data } = await apiClient.get<RouteSelectionRule[]>("/route-selection-rules");
  return data;
}

export async function createRouteSelectionRule(payload: RouteSelectionRuleInput) {
  const { data } = await apiClient.post<RouteSelectionRule>("/route-selection-rules", payload);
  return data;
}

export async function updateRouteSelectionRule(ruleId: number, payload: RouteSelectionRuleInput) {
  const { data } = await apiClient.put<RouteSelectionRule>(`/route-selection-rules/${ruleId}`, payload);
  return data;
}

export async function deleteRouteSelectionRule(ruleId: number) {
  await apiClient.delete(`/route-selection-rules/${ruleId}`);
}

export async function seedRoutes() {
  const { data } = await apiClient.post<RouteDetail[]>("/routes-seed");
  return data;
}

export async function reorderRoutes(ids: number[]) {
  await apiClient.post("/routes/reorder", { ids });
}
