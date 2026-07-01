import type { SectionKind } from "@/shared/api/sections";

/**
 * Складские виды секций. Склады живут в ГХП и в разделе «Передачи»,
 * но не входят в производственную доску задач `/section-tasks`.
 */
export const STOCK_SECTION_KINDS: readonly SectionKind[] = [
  "raw_stock",
  "wip_stock",
  "finished_stock",
] as const;

/**
 * Предикат: относится ли секция к производственному цеху
 * (т.е. у неё есть операции, на которые назначаются задания).
 */
export function isProductionSection(kind: SectionKind): boolean {
  return !STOCK_SECTION_KINDS.includes(kind);
}
