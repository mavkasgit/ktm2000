import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import type { Section } from "@/shared/api/sections";
import type { SectionSummary } from "@/shared/api/shopfloor";
import { SectionSwitcherTiles } from "./SectionSwitcherTiles";

const makeSection = (overrides: Partial<Section>): Section => ({
  id: 1,
  code: "X",
  name: "X",
  description: null,
  is_active: true,
  kind: "production",
  icon: null,
  icon_color: null,
  ...overrides,
});

describe("SectionSwitcherTiles", () => {
  it("renders every section passed in (filtering is the parent's job)", () => {
    const sections: Section[] = [
      makeSection({ id: 1, code: "WH", name: "Склад сырья", kind: "raw_stock" }),
      makeSection({ id: 2, code: "DRILL", name: "Сверление", kind: "production" }),
      makeSection({ id: 3, code: "WIP", name: "Полуфабрикаты", kind: "wip_stock" }),
    ];
    const summary: SectionSummary[] = [
      { section_id: 1, completed_count: 0, in_progress_count: 0, waiting_count: 0, incoming_transfers_count: 0, sort_order: 0 },
      { section_id: 2, completed_count: 0, in_progress_count: 0, waiting_count: 0, incoming_transfers_count: 0, sort_order: 1 },
      { section_id: 3, completed_count: 0, in_progress_count: 0, waiting_count: 0, incoming_transfers_count: 0, sort_order: 2 },
    ];

    const html = renderToStaticMarkup(
      <SectionSwitcherTiles
        sections={sections}
        summary={summary}
        selectedSectionId={2}
        onSelect={vi.fn()}
      />,
    );

    expect(html).toContain("Склад сырья");
    expect(html).toContain("Сверление");
    expect(html).toContain("Полуфабрикаты");
  });

  it("renders an empty state when sections list is empty", () => {
    const html = renderToStaticMarkup(
      <SectionSwitcherTiles
        sections={[]}
        summary={[]}
        selectedSectionId={null}
        onSelect={vi.fn()}
      />,
    );

    expect(html).toContain("Ничего не найдено");
  });
});
