import type { BatchDeleteConflict } from "@/shared/api/productionPlans";

/** Разбор 409 удаления батча импорта (спека docs/plan-import-spec.md §4.4, тикет #167):
 *  бэк отвечает голым объектом {code, blockers, safe_action, drafts} (не detail). */
export function parseBatchDeleteConflict(error: unknown): BatchDeleteConflict | null {
  if (!error || typeof error !== "object" || !("response" in error)) return null;
  const response = (error as { response?: { status?: number; data?: unknown } }).response;
  if (response?.status !== 409) return null;
  const data = response.data;
  if (!data || typeof data !== "object") return null;
  const body = data as Record<string, unknown>;
  if (typeof body.code !== "string" || !Array.isArray(body.blockers) || typeof body.drafts !== "number") {
    return null;
  }
  const blockersOk = body.blockers.every(
    (b) =>
      !!b &&
      typeof b === "object" &&
      typeof (b as { position_id?: unknown }).position_id === "number" &&
      typeof (b as { reason?: unknown }).reason === "string",
  );
  if (!blockersOk) return null;
  return body as unknown as BatchDeleteConflict;
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
