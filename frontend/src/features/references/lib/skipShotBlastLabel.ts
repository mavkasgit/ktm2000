import type { RouteSelectionRule } from "@/shared/api/routes";

/**
 * Выводит название участка, который пропускается флагом продукта
 * `skip_shot_blast`, из правил выбора маршрута (справочник в БД).
 *
 * Связь «флаг продукта → участок» — заводская настройка: она сидируется
 * правилом с условием по product.skip_shot_blast и действием
 * exclude_section/require_section. Берём название участка из такого правила,
 * чтобы не зашивать русское название операции в код.
 */
export function skipShotBlastSectionLabel(
  rules: RouteSelectionRule[] | undefined,
): string | null {
  for (const rule of rules ?? []) {
    if (!rule.is_active) continue;
    // Только правила, целиком посвящённые этому флагу: у смешанных правил
    // (несколько условий) участок в действии относится к другой логике.
    const dedicated =
      rule.conditions.length > 0 &&
      rule.conditions.every(
        (c) => c.source === "product" && c.field_path === "skip_shot_blast",
      );
    if (!dedicated) continue;
    const action = rule.actions.find(
      (a) =>
        (a.action === "exclude_section" || a.action === "require_section") &&
        a.section_name,
    );
    if (action?.section_name) return action.section_name;
  }
  return null;
}
