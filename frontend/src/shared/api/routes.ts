import { apiClient } from "./client";

export type ProductionRoute = {
  id: number;
  product_id: number;
  name: string;
  version: string;
  is_active: boolean;
};

export type RouteStep = {
  id: number;
  route_id: number;
  sequence: number;
  section_id: number;
  operation_code: string | null;
  operation_name: string;
  norm_time_minutes: number | null;
  requires_acceptance: boolean;
  allow_parallel: boolean;
  is_final: boolean;
};

export type CreateRouteInput = {
  product_id: number;
  name: string;
  version: string;
  is_active?: boolean;
};

export type PatchRouteInput = Partial<Pick<CreateRouteInput, "name" | "version" | "is_active">>;

export type CreateRouteStepInput = {
  sequence: number;
  section_id: number;
  operation_code?: string | null;
  operation_name: string;
  norm_time_minutes?: number | null;
  requires_acceptance?: boolean;
  allow_parallel?: boolean;
  is_final?: boolean;
};

export async function createRoute(payload: CreateRouteInput) {
  const { data } = await apiClient.post<ProductionRoute>("/routes", payload);
  return data;
}

export async function createRouteStep(routeId: number, payload: CreateRouteStepInput) {
  const { data } = await apiClient.post<RouteStep>(`/routes/${routeId}/steps`, payload);
  return data;
}

export async function patchRoute(routeId: number, payload: PatchRouteInput) {
  const { data } = await apiClient.patch<ProductionRoute>(`/routes/${routeId}`, payload);
  return data;
}
