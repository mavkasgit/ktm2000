import type { BatchDeleteConflict } from "@/shared/api/productionPlans";

function isKnownConflictCode(code: string): code is BatchDeleteConflict["code"] {
  return code === "batch_has_released_positions" || code === "downstream_transfers_exist";
}

function isBatchDeleteBlocker(b: unknown): b is BatchDeleteConflict["blockers"][number] {
  return (
    !!b &&
    typeof b === "object" &&
    "position_id" in b &&
    typeof b.position_id === "number" &&
    "reason" in b &&
    typeof b.reason === "string"
  );
}

/** Разбор 409 удаления батча импорта (спека docs/plan-import-spec.md §4.4, тикет #167):
 *  бэк отвечает голым объектом {code, blockers, safe_action, drafts} (не detail).
 *  Неизвестный code или отсутствующий/неожиданный safe_action → null: экран
 *  блокировок не открываем, действие по умолчанию не выдумываем. */
export function parseBatchDeleteConflict(error: unknown): BatchDeleteConflict | null {
  if (!error || typeof error !== "object" || !("response" in error)) return null;
  const response = error.response;
  if (!response || typeof response !== "object") return null;
  if (!("status" in response) || response.status !== 409) return null;
  if (!("data" in response)) return null;
  const body = response.data;
  if (!body || typeof body !== "object") return null;
  if (!("code" in body) || typeof body.code !== "string" || !isKnownConflictCode(body.code)) return null;
  if (!("safe_action" in body) || body.safe_action !== "delete_drafts_only") return null;
  if (!("blockers" in body) || !Array.isArray(body.blockers)) return null;
  if (!("drafts" in body) || typeof body.drafts !== "number") return null;
  if (!body.blockers.every(isBatchDeleteBlocker)) return null;
  return {
    code: body.code,
    blockers: body.blockers,
    safe_action: body.safe_action,
    drafts: body.drafts,
  };
}

/** Человеческий текст причины блокера для экрана блокировок. */
export function blockerReasonLabel(reason: string): string {
  if (reason === "released") return "Запущена (released) — удаление запрещено";
  const transferPrefix = "transfer №";
  if (reason.startsWith(transferPrefix)) {
    return `Связана с передачей №${reason.slice(transferPrefix.length)} — удаление запрещено`;
  }
  return reason;
}
