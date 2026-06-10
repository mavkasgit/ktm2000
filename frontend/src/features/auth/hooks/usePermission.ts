import { useAuth } from "./useAuth";
import { POLICIES } from "../policies";

export function usePermission() {
  const { user } = useAuth();
  
  return {
    canEditReferences: POLICIES.editReferences(user?.role),
    canEditSettings: POLICIES.editSettings(user?.role),
  };
}
export type UsePermissionResult = ReturnType<typeof usePermission>;
