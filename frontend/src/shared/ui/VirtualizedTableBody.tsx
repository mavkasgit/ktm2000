import { useVirtualizer } from "@tanstack/react-virtual";

export interface VirtualizedTableBodyProps<T> {
  rows: T[];
  rowHeight: number;
  overscan?: number;
  /**
   * Ref to the outer scroll container (the div with overflow-auto).
   * The virtualizer listens to scroll events on this element.
   */
  scrollContainerRef: React.RefObject<HTMLElement | null>;
  /**
   * Number of columns in the table. Used for spacer rows to span the full width.
   */
  colSpan: number;
  /**
   * Renders a single row. Must return a ready-made <tr> element (no extra wrapping).
   */
  renderRow: (row: T, index: number) => React.ReactNode;
}

const VIRTUALIZATION_THRESHOLD = 300;

/**
 * Virtualized table body using @tanstack/react-virtual.
 * Falls back to regular tbody when row count is below threshold.
 *
 * Uses spacer rows: top and bottom padding rows keep the full table height,
 * while only visible rows are rendered in between.
 */
export function VirtualizedTableBody<T>({
  rows,
  rowHeight,
  overscan = 5,
  scrollContainerRef,
  colSpan,
  renderRow,
}: VirtualizedTableBodyProps<T>) {
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollContainerRef.current,
    estimateSize: () => rowHeight,
    overscan,
  });

  const virtualItems = virtualizer.getVirtualItems();
  const totalSize = virtualizer.getTotalSize();

  // If below threshold, render normally
  if (rows.length < VIRTUALIZATION_THRESHOLD) {
    return <tbody>{rows.map((row, i) => renderRow(row, i))}</tbody>;
  }

  // Defensive fallback: when virtualizer has no items (e.g., SSR or unmeasured container),
  // render all rows to avoid an empty table body.
  if (virtualItems.length === 0) {
    return <tbody>{rows.map((row, i) => renderRow(row, i))}</tbody>;
  }

  const startSpacerHeight = virtualItems.length > 0 ? virtualItems[0].start : totalSize;
  const endSpacerHeight =
    virtualItems.length > 0
      ? totalSize - virtualItems[virtualItems.length - 1].end
      : totalSize;

  return (
    <tbody>
      {startSpacerHeight > 0 && (
        <tr aria-hidden="true">
          <td colSpan={colSpan} style={{ height: `${startSpacerHeight}px`, padding: 0 }} />
        </tr>
      )}
      {virtualItems.map((virtualRow) => renderRow(rows[virtualRow.index], virtualRow.index))}
      {endSpacerHeight > 0 && (
        <tr aria-hidden="true">
          <td colSpan={colSpan} style={{ height: `${endSpacerHeight}px`, padding: 0 }} />
        </tr>
      )}
    </tbody>
  );
}
