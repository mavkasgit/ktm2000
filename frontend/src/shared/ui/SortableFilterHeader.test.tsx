import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { SortableFilterHeader } from "./SortableFilterHeader";

describe("SortableFilterHeader", () => {
  it("renders closed trigger with label", () => {
    const html = renderToStaticMarkup(
      <SortableFilterHeader
        field="sku"
        label="Артикул"
        currentSorts={[]}
        onSortChange={vi.fn()}
        values={["ЮП-460", "ABC-100"]}
        selectedValues={new Set()}
        onFilterChange={vi.fn()}
      />,
    );

    expect(html).toContain("Артикул");
  });

  it("exposes sort state on sort button", () => {
    const html = renderToStaticMarkup(
      <SortableFilterHeader
        field="sku"
        label="Артикул"
        currentSorts={[{ field: "sku", order: "asc" }]}
        onSortChange={vi.fn()}
        values={[]}
        selectedValues={new Set()}
        onFilterChange={vi.fn()}
      />,
    );

    expect(html).toContain('data-sort-order="asc"');
    expect(html).toContain('aria-pressed="true"');
  });
});