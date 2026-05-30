import { apiClient } from "./client";

export type ProductionRoute = {
  id: number;
  code: string | null;
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

export type RouteDetail = ProductionRoute & {
  steps: RouteStep[];
  rules: RouteMatchingRule[];
};

export type RouteMatchingRule = {
  id: number;
  route_id: number;
  priority: number;
};

export type RouteSelectionCondition = {
  source: "excel" | "payload" | "product" | "ctx";
  field_path: string;
  excel_column_index?: number | null;
  excel_column_letter?: string | null;
  excel_header?: string | null;
  operator: "equals" | "not_equals" | "contains" | "not_contains" | "in" | "not_in" | "empty" | "not_empty" | "regex";
  value: unknown;
  case_sensitive: boolean;
};

export type RouteSelectionAction = {
  action: "require_section" | "exclude_section" | "set" | "add" | "remove" | "set_operation" | "resolve_by_type";
  section_id?: number | null;
  section_code?: string | null;
  section_name?: string | null;
  group_code?: string | null;
  operation_code?: string | null;
  operation_name?: string | null;
  path?: string | null;
  value?: unknown;
};

export type RouteSelectionRule = {
  id: number;
  code: string | null;
  name: string;
  profile_id: number | null;
  profile_code: string | null;
  profile_name: string | null;
  priority: number;
  is_active: boolean;
  phase: "normalize" | "route_select" | "resolve_operations";
  conditions: RouteSelectionCondition[];
  actions: RouteSelectionAction[];
};

export type RouteSelectionRuleInput = {
  code?: string | null;
  name: string;
  profile_id?: number | null;
  priority: number;
  is_active: boolean;
  phase?: "normalize" | "route_select" | "resolve_operations";
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

export async function listRouteSelectionRules(params?: { scope?: "global" | "profile" | "all"; profile_id?: number }) {
  const { data } = await apiClient.get<RouteSelectionRule[]>("/route-selection-rules", { params });
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

export type SeedSummary = {
  import_templates: number;
  route_rule_profiles: number;
  routes: number;
  selection_rules: number;
  sections: number;
  section_operations: number;
};

export async function seedRoutes() {
  const { data } = await apiClient.post<SeedSummary>("/routes-seed");
  return data;
}

export async function seedPreview() {
  const { data } = await apiClient.get<SeedSummary>("/routes-seed/preview");
  return data;
}

export async function reseedSystemUser() {
  const { data } = await apiClient.post<{ user_id: number; email: string }>("/routes-seed/reseed-system-user");
  return data;
}

export async function reorderRoutes(ids: number[]) {
  await apiClient.post("/routes/reorder", { ids });
}

export type RouteRuleProfile = {
  id: number;
  code: string;
  name: string;
  is_active: boolean;
  priority: number;
  import_template_id: number | null;
  template_code: string | null;
  template_name: string | null;
  excel_column_passport: Array<{
    index: number;
    letter: string;
    header: string;
    field_path: string;
  }>;
  excel_passport_meta: {
    sheet_name?: string;
    sheet_index?: number;
    source_row_number?: number;
    updated_at?: string;
    import_template_id?: number;
    [key: string]: unknown;
  };
  created_at: string | null;
};

export type RouteRuleProfileInput = {
  code: string;
  name: string;
  is_active: boolean;
  priority: number;
  import_template_id?: number | null;
  excel_column_passport: Array<{
    index: number;
    letter: string;
    header: string;
    field_path: string;
  }>;
  excel_passport_meta: {
    sheet_name?: string;
    sheet_index?: number;
    source_row_number?: number;
    updated_at?: string;
    import_template_id?: number;
    [key: string]: unknown;
  };
};

export async function listRouteRuleProfiles() {
  const { data } = await apiClient.get<RouteRuleProfile[]>("/route-rule-profiles");
  return data;
}

export async function createRouteRuleProfile(payload: RouteRuleProfileInput) {
  const { data } = await apiClient.post<RouteRuleProfile>("/route-rule-profiles", payload);
  return data;
}

export async function updateRouteRuleProfile(profileId: number, payload: RouteRuleProfileInput) {
  const { data } = await apiClient.put<RouteRuleProfile>(`/route-rule-profiles/${profileId}`, payload);
  return data;
}

export async function deleteRouteRuleProfile(profileId: number) {
  await apiClient.delete(`/route-rule-profiles/${profileId}`);
}
