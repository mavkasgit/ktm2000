import type { SectionType } from "@/shared/api/sections";

/**
 * Складские типы секций. Склады живут в ГХП и в разделе «Передачи»,
 * но не входят в производственную доску задач `/section-tasks`.
 *
 * ``terminal`` (#136) — терминальная секция («Отправлено»): проводки в
 * ledger хранятся, но баланс не материализуется, поэтому в оперативных
 * остатках её нет. В UI остаётся складской группой ГХП.
 */
export const STOCK_SECTION_TYPES: readonly SectionType[] = [
  "raw_stock",
  "wip_stock",
  "finished_stock",
  "scrap",
  "terminal",
] as const;

/**
 * Предикат: относится ли секция к производственному цеху
 * (т.е. у неё есть операции, на которые назначаются задания).
 */
export function isProductionSection(type: SectionType): boolean {
  return !STOCK_SECTION_TYPES.includes(type);
}
