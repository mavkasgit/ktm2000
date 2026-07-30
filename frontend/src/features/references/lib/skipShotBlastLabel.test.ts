import { describe, expect, it } from "vitest";

import type { RouteSelectionRule } from "@/shared/api/routes";
import { skipShotBlastSectionLabel } from "./skipShotBlastLabel";

const makeRule = (overrides: Partial<RouteSelectionRule>): RouteSelectionRule => ({
  id: 1,
  code: null,
  name: "rule",
  profile_id: null,
  profile_code: null,
  profile_name: null,
  priority: 100,
  is_active: true,
  phase: "route_select",
  conditions: [],
  actions: [],
  ...overrides,
});

describe("skipShotBlastSectionLabel", () => {
  it("derives the section name from a rule dedicated to the skip_shot_blast flag", () => {
    const rules = [
      makeRule({
        id: 1,
        conditions: [
          { source: "product", field_path: "skip_shot_blast", operator: "equals", value: true, case_sensitive: false },
        ],
        actions: [
          { action: "exclude_section", section_id: 4, section_code: "BLAST_ZONE", section_name: "Зона очистки" },
        ],
      }),
    ];
    expect(skipShotBlastSectionLabel(rules)).toBe("Зона очистки");
  });

  it("ignores mixed rules where the flag is only one of several conditions", () => {
    const rules = [
      makeRule({
        id: 1,
        conditions: [
          { source: "payload", field_path: "operation", operator: "empty", value: null, case_sensitive: false },
          { source: "product", field_path: "skip_shot_blast", operator: "equals", value: true, case_sensitive: false },
        ],
        actions: [
          { action: "exclude_section", section_id: 5, section_code: "PREP", section_name: "Склад подготовки" },
        ],
      }),
      makeRule({
        id: 2,
        conditions: [
          { source: "product", field_path: "skip_shot_blast", operator: "not_equals", value: true, case_sensitive: false },
        ],
        actions: [
          { action: "require_section", section_id: 4, section_code: "BLAST_ZONE", section_name: "Зона очистки" },
        ],
      }),
    ];
    expect(skipShotBlastSectionLabel(rules)).toBe("Зона очистки");
  });

  it("skips inactive rules and returns null when nothing matches", () => {
    const rules = [
      makeRule({
        id: 1,
        is_active: false,
        conditions: [
          { source: "product", field_path: "skip_shot_blast", operator: "equals", value: true, case_sensitive: false },
        ],
        actions: [
          { action: "exclude_section", section_id: 4, section_code: "BLAST_ZONE", section_name: "Зона очистки" },
        ],
      }),
    ];
    expect(skipShotBlastSectionLabel(rules)).toBeNull();
    expect(skipShotBlastSectionLabel(undefined)).toBeNull();
    expect(skipShotBlastSectionLabel([])).toBeNull();
  });
});
