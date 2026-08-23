import { apiClient } from "./client";

/** Клиент журнала действий /actions (ADR-0019, тикет #117).
 *  Типы зеркальны backend/app/reversal/schemas.py. */

export type ActionStatus = "active" | "reversed" | "amended";

/** Базовый набор типов действий журнала для фильтра страницы (#117).
 *  Amend доступен только transfer_send (_AMEND_FIELDS бэка), остальные —
 *  известные UI типы журнала. */
export const AMENDABLE_ACTION_TYPES = [
  "transfer_send",
  "task_complete",
  "manual_adjustment",
  "final_release",
] as const;

export type KnownActionType = (typeof AMENDABLE_ACTION_TYPES)[number];

export type JournalAction = {
  id: number;
  action_type: string;
  ref_id: number | null;
  actor: string | null;
  status: ActionStatus;
  depends_on: number[];
  created_at: string | null;
};

export type GetActionsParams = {
  page?: number;
  page_size?: number;
  action_type?: string | null;
  status?: ActionStatus | null;
};

export type ActionsListResponse = {
  items: JournalAction[];
  total: number;
  page: number;
  page_size: number;
};

export type ActionNode = {
  id: number;
  action_type: string;
  ref_id: number | null;
  status: ActionStatus;
  depends_on: number[];
};

export type ActionTreeNode = ActionNode & { children: ActionTreeNode[] };

export type TreeResponse = {
  root: ActionTreeNode;
  total_nodes: number;
};

export type PreviewBlocker = {
  kind: string;
  node_id: number | null;
  detail: string;
  deficit: string | null;
  chain: number[] | null;
};

export type PreviewResponse = {
  action_id: number;
  cascade: boolean;
  /** 🔴 отменится */
  revert: ActionNode[];
  /** ⚪ останется */
  stays: ActionNode[];
  /** 🚫 блокировки */
  blockers: PreviewBlocker[];
  plan_token: string | null; // None при блокировках
};

export type ReverseResult = {
  action_id: number;
  reversal_action_id: number;
  reversed_action_ids: number[];
  compensated_tx_ids: number[];
};

export type AmendResult = {
  action_id: number;
  new_action_id: number;
  new_ref_id: number | null;
  compensated_tx_ids: number[];
  amended_action_ids: number[];
  reversed_action_ids: number[];
};

export async function getActions(params: GetActionsParams) {
  const { data } = await apiClient.get<ActionsListResponse>("/actions", { params });
  return data;
}

export async function getActionTree(actionId: number) {
  const { data } = await apiClient.get<TreeResponse>(`/actions/${actionId}/tree`);
  return data;
}

export async function previewReverse(actionId: number, cascade: boolean) {
  const { data } = await apiClient.post<PreviewResponse>(
    `/actions/${actionId}/preview-reverse`,
    { cascade },
  );
  return data;
}

export async function reverseAction(
  actionId: number,
  payload: { plan_token: string; reason?: string | null },
) {
  const { data } = await apiClient.post<ReverseResult>(
    `/actions/${actionId}/reverse`,
    payload,
  );
  return data;
}

export async function previewAmend(
  actionId: number,
  changes: Record<string, unknown>,
  cascade: boolean,
) {
  const { data } = await apiClient.post<PreviewResponse>(
    `/actions/${actionId}/preview-amend`,
    { changes, cascade },
  );
  return data;
}

export async function amendAction(
  actionId: number,
  payload: { plan_token: string; reason?: string | null },
) {
  const { data } = await apiClient.post<AmendResult>(
    `/actions/${actionId}/amend`,
    payload,
  );
  return data;
}

export type ReversalErrorInfo = {
  status?: number;
  message: string;
  /** chain из HasDependentActions (409). */
  chain?: number[];
};

/** Разбор ошибки /actions: 409 StalePlanToken/HasDependentActions/…,
 *  403 NotAllowed, 404. detail может быть строкой или {error, chain}. */
export function parseReversalError(error: unknown): ReversalErrorInfo {
  if (error && typeof error === "object" && "response" in error) {
    const axErr = error as {
      response?: { status?: number; data?: { detail?: unknown } };
    };
    const status = axErr.response?.status;
    const detail: unknown = axErr.response?.data?.detail;
    if (detail && typeof detail === "object" && "chain" in (detail as Record<string, unknown>)) {
      const obj = detail as { error?: string; chain?: number[] };
      return {
        status,
        message: obj.error ?? "Есть зависимые действия",
        chain: Array.isArray(obj.chain) ? obj.chain : undefined,
      };
    }
    if (typeof detail === "string" && detail.trim()) {
      return { status, message: detail.trim() };
    }
    if (status != null) return { status, message: `HTTP ${status}` };
  }
  if (error instanceof Error) return { message: error.message };
  return { message: String(error ?? "") };
}
