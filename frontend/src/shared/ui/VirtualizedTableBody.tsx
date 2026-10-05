import { useLayoutEffect, useRef, useState } from "react";
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
 *
 * Row height: `rowHeight` is the starting estimate (taken from the shared
 * «компактная строка» rule), the real height is measured from the first
 * rendered row. Rows of one table share the same height (GLOSSARY.md,
 * ADR-0030), so a single measurement is enough — and a table with taller
 * content (e.g. the two-line cells of «Передачи») stops lying to the
 * virtualizer.
 */
export function VirtualizedTableBody<T>({
  rows,
  rowHeight,
  overscan = 5,
  scrollContainerRef,
  colSpan,
  renderRow,
}: VirtualizedTableBodyProps<T>) {
  const tbodyRef = useRef<HTMLTableSectionElement | null>(null);
  const [measuredRowHeight, setMeasuredRowHeight] = useState<number | null>(null);

  // Строки таблицы одинаковой высоты, поэтому меряем первую реальную строку
  // (служебные строки-распорки помечены aria-hidden и пропускаются).
  useLayoutEffect(() => {
    const tbody = tbodyRef.current;
    const firstRow = tbody?.querySelector<HTMLTableRowElement>('tr:not([aria-hidden="true"])');
    if (!firstRow) return;
    const measure = () => {
      const height = firstRow.getBoundingClientRect().height;
      if (height <= 0) return;
      setMeasuredRowHeight((prev) =>
        prev !== null && Math.abs(prev - height) < 0.5 ? prev : height,
      );
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(firstRow);
    return () => observer.disconnect();
  }, [rows.length]);

  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollContainerRef.current,
    estimateSize: () => measuredRowHeight ?? rowHeight,
    overscan,
  });

  const virtualItems = virtualizer.getVirtualItems();
  const totalSize = virtualizer.getTotalSize();

  // If below threshold, render normally
  if (rows.length < VIRTUALIZATION_THRESHOLD) {
    return <tbody ref={tbodyRef}>{rows.map((row, i) => renderRow(row, i))}</tbody>;
  }

  // Defensive fallback: when virtualizer has no items (e.g., SSR or unmeasured container),
  // render all rows to avoid an empty table body.
  if (virtualItems.length === 0) {
    return <tbody ref={tbodyRef}>{rows.map((row, i) => renderRow(row, i))}</tbody>;
  }

  const startSpacerHeight = virtualItems.length > 0 ? virtualItems[0].start : totalSize;
  const endSpacerHeight =
    virtualItems.length > 0
      ? totalSize - virtualItems[virtualItems.length - 1].end
      : totalSize;

  return (
    <tbody ref={tbodyRef}>
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
