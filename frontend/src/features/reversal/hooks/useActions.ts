import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { queryKeys } from "@/shared/api/queryKeys";
import {
  getActions,
  getActionTree,
  type GetActionsParams,
} from "@/shared/api/actions";

export function useActionsList(params: GetActionsParams) {
  return useQuery({
    queryKey: queryKeys.actions.list(params as Record<string, unknown>),
    queryFn: () => getActions(params),
    placeholderData: keepPreviousData,
  });
}

export function useActionTree(actionId: number | null) {
  return useQuery({
    queryKey: queryKeys.actions.tree(actionId ?? 0),
    queryFn: () => getActionTree(actionId!),
    enabled: actionId != null,
  });
}
