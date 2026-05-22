import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { SortableHeader } from "./SortableHeader";

describe("SortableHeader", () => {
  it("exposes inactive state for accessibility and automation", () => {
    const html = renderToStaticMarkup(
      <SortableHeader field="name" currentSorts={[]} onSortChange={vi.fn()}>
        Name
      </SortableHeader>,
    );

    expect(html).toContain('aria-pressed="false"');
    expect(html).toContain('data-sort-order="none"');
  });

  it("exposes active sort order and priority", () => {
    const html = renderToStaticMarkup(
      <SortableHeader
        field="name"
        currentSorts={[
          { field: "id", order: "asc" },
          { field: "name", order: "desc" },
        ]}
        onSortChange={vi.fn()}
      >
        Name
      </SortableHeader>,
    );

    expect(html).toContain('aria-pressed="true"');
    expect(html).toContain('data-sort-order="desc"');
    expect(html).toContain('data-sort-priority="2"');
  });
});

