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

  it("при sortable=false не рендерит кнопку сортировки, но оставляет фильтр", () => {
    const html = renderToStaticMarkup(
      <SortableFilterHeader
        field="route"
        label="Маршрут"
        currentSorts={[{ field: "route", order: "desc" }]}
        onSortChange={vi.fn()}
        values={["Резка"]}
        selectedValues={new Set()}
        onFilterChange={vi.fn()}
        sortable={false}
      />,
    );

    expect(html).toContain("Маршрут");
    expect(html).not.toContain("data-sort-order");
  });
});