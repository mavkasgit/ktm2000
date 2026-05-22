import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { VirtualizedTableBody } from "./VirtualizedTableBody";

type VirtualItem = { index: number; start: number; end: number };

const mockGetVirtualItems = vi.fn<() => VirtualItem[]>();
const mockGetTotalSize = vi.fn<() => number>();

vi.mock("@tanstack/react-virtual", () => ({
  useVirtualizer: () => ({
    getVirtualItems: mockGetVirtualItems,
    getTotalSize: mockGetTotalSize,
  }),
}));

describe("VirtualizedTableBody", () => {
  const makeRows = (n: number) =>
    Array.from({ length: n }, (_, i) => ({ id: i + 1, name: `Row ${i + 1}` }));

  beforeEach(() => {
    mockGetVirtualItems.mockReset();
    mockGetTotalSize.mockReset();
    mockGetVirtualItems.mockReturnValue([]);
    mockGetTotalSize.mockReturnValue(0);
  });

  it("renders all rows when below threshold", () => {
    const rows = makeRows(10);
    const html = renderToStaticMarkup(
      <table>
        <VirtualizedTableBody
          rows={rows}
          rowHeight={40}
          colSpan={3}
          scrollContainerRef={{ current: null }}
          renderRow={(row) => (
            <tr key={row.id}>
              <td>{row.name}</td>
            </tr>
          )}
        />
      </table>,
    );

    for (let i = 1; i <= 10; i++) {
      expect(html).toContain(`Row ${i}`);
    }
  });

  it("falls back to full render when virtualizer has no items", () => {
    const rows = makeRows(300);
    mockGetVirtualItems.mockReturnValue([]);
    mockGetTotalSize.mockReturnValue(12000);

    const html = renderToStaticMarkup(
      <table>
        <VirtualizedTableBody
          rows={rows}
          rowHeight={40}
          colSpan={3}
          scrollContainerRef={{ current: null }}
          renderRow={(row) => (
            <tr key={row.id}>
              <td>{row.name}</td>
            </tr>
          )}
        />
      </table>,
    );

    expect(html).toContain("Row 1");
    expect(html).toContain("Row 300");
  });

  it("renders only virtual rows when items are provided", () => {
    const rows = makeRows(300);
    mockGetVirtualItems.mockReturnValue([
      { index: 1, start: 40, end: 80 },
      { index: 2, start: 80, end: 120 },
      { index: 3, start: 120, end: 160 },
    ]);
    mockGetTotalSize.mockReturnValue(12000);

    const html = renderToStaticMarkup(
      <table>
        <VirtualizedTableBody
          rows={rows}
          rowHeight={40}
          colSpan={3}
          scrollContainerRef={{ current: null }}
          renderRow={(row) => (
            <tr key={row.id}>
              <td>{row.name}</td>
            </tr>
          )}
        />
      </table>,
    );

    expect(html).toContain("Row 2");
    expect(html).toContain("Row 3");
    expect(html).toContain("Row 4");
    expect(html).not.toContain("Row 1");
    expect(html).not.toContain("Row 300");
  });

  it("uses colSpan for spacer rows", () => {
    const rows = makeRows(300);
    mockGetVirtualItems.mockReturnValue([{ index: 10, start: 400, end: 440 }]);
    mockGetTotalSize.mockReturnValue(12000);

    const html = renderToStaticMarkup(
      <table>
        <VirtualizedTableBody
          rows={rows}
          rowHeight={40}
          colSpan={12}
          scrollContainerRef={{ current: null }}
          renderRow={(row) => (
            <tr key={row.id}>
              <td>{row.name}</td>
            </tr>
          )}
        />
      </table>,
    );

    expect(html).toContain('colSpan="12"');
  });

  it("passes virtual row indexes to renderRow", () => {
    const rows = makeRows(300);
    const indexes: number[] = [];
    mockGetVirtualItems.mockReturnValue([
      { index: 5, start: 200, end: 240 },
      { index: 6, start: 240, end: 280 },
    ]);
    mockGetTotalSize.mockReturnValue(12000);

    renderToStaticMarkup(
      <table>
        <VirtualizedTableBody
          rows={rows}
          rowHeight={40}
          colSpan={3}
          scrollContainerRef={{ current: null }}
          renderRow={(row, index) => {
            indexes.push(index);
            return (
              <tr key={row.id}>
                <td>{row.name}</td>
              </tr>
            );
          }}
        />
      </table>,
    );

    expect(indexes).toEqual([5, 6]);
  });
});
