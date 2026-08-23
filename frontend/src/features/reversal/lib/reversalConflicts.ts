import type { ReversalErrorInfo } from "@/shared/api/actions";

/** Централизованная обработка конфликтов /actions (#117 ревью):
 *  строковый матчинг StalePlanToken — в одном месте, смена формулировки
 *  бэка правится здесь. */

/** StalePlanToken: бэк отвечает detail «Мир изменился …». */
export function isStaleToken(message: string): boolean {
  return message.includes("Мир изменился");
}

export type ReversalConflictKind = "stale-token" | "dependent-actions";

/** Классификация 409-конфликта по разобранной ошибке /actions. */
export function classifyReversalConflict(
  info: ReversalErrorInfo,
): ReversalConflictKind | null {
  if (info.status !== 409) return null;
  if (isStaleToken(info.message)) return "stale-token";
  if (info.chain && info.chain.length > 0) return "dependent-actions";
  return null;
}

/** Общий заголовок тоста при устаревшем plan_token (оба диалога). */
export const STALE_TOKEN_TOAST_TITLE = "Мир изменился, предпросмотр обновлён";
