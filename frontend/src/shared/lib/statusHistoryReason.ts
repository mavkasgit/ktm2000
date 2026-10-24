import {
  errorPhraseTranslations,
  statusLabels,
} from "@/shared/lib/generated-labels";

const STATUS_TOKEN_IN_QUOTES_RE = /'([a-z_]+)'/gi;

function translateEmbeddedStatusToken(status: string): string {
  return statusLabels[status] || status
}

/**
 * Переводит reason/message из истории смен статуса для UI.
 *
 * Живёт в `shared`, а не в `features/planning`: история статуса читается
 * панелью деталей строки плана, которую используют и планирование, и
 * выполнение (ADR: features не импортирует features).
 */
export function translateStatusHistoryReason(reason: string | null | undefined): string {
  if (!reason?.trim()) return "—"

  const trimmed = reason.trim()
  const exact = errorPhraseTranslations[trimmed]
  if (exact) return exact

  return trimmed.replace(STATUS_TOKEN_IN_QUOTES_RE, (_match, status: string) => {
    const normalized = status.toLowerCase()
    return `'${translateEmbeddedStatusToken(normalized)}'`
  })
}
