import { useAuth } from "./useAuth";
import { POLICIES } from "../policies";

export function usePermission() {
  const { user } = useAuth();
  
  return {
    canEditReferences: POLICIES.editReferences(user?.role),
    canEditSettings: POLICIES.editSettings(user?.role),
    canForceDeleteImport: POLICIES.forceDeleteImport(user?.role),
    canEditPlan: POLICIES.editPlan(user?.role),
    canCreatePlanImport: POLICIES.createPlanImport(user?.role),
    canManagePlanImport: POLICIES.managePlanImport(user?.role),
  };
}
export type UsePermissionResult = ReturnType<typeof usePermission>;
