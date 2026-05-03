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
};

export type RuleCondition = {
  field: string;
  operator: "=" | "!=" | "in" | "contains";
  value: string;
};

export type MatchingRule = {
  id: number;
  route_id: number;
  priority: number;
  conditions: RuleCondition[];
};

export type RouteDetail = ProductionRoute & {
  steps: RouteStep[];
  rules: MatchingRule[];
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
  conditions: RuleCondition[];
};

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

export async function deleteRoute(id: number) {
  await apiClient.delete(`/routes/${id}`);
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
  const { data } = await apiClient.post<MatchingRule>(`/routes/${routeId}/rules`, payload);
  return data;
}

export async function deleteRule(routeId: number, ruleId: number) {
  await apiClient.delete(`/routes/${routeId}/rules/${ruleId}`);
}
