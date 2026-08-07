import { useCallback, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

import { cn } from "@/shared/utils/cn";
import { Badge } from "../badge";
import { Button } from "../button";
import type { ImportRawSegment } from "./importRawData";

export function useImportRowExpansion() {
  const [expandAllRaw, setExpandAllRaw] = useState(false);
  const [expandedRows, setExpandedRows] = useState<Set<number>>(new Set());

  const toggleRow = useCallback((idx: number) => {
    setExpandedRows((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) {
        next.delete(idx);
      } else {
        next.add(idx);
      }
      return next;
    });
  }, []);

  const isRowExpanded = useCallback(
    (idx: number) => expandAllRaw || expandedRows.has(idx),
    [expandAllRaw, expandedRows],
  );

  const resetExpansion = useCallback(() => {
    setExpandAllRaw(false);
    setExpandedRows(new Set());
  }, []);

  return {
    expandAllRaw,
    setExpandAllRaw,
    expandedRows,
    toggleRow,
    isRowExpanded,
    resetExpansion,
  };
}

export type ImportRowExpansion = ReturnType<typeof useImportRowExpansion>;

export type ImportRawRowsToggleProps = {
  active: boolean;
  onToggle: () => void;
  className?: string;
  size?: "sm" | "default";
};

export function ImportRawRowsToggle({
  active,
  onToggle,
  className,
  size = "sm",
}: ImportRawRowsToggleProps) {
  return (
    <Button
      type="button"
      size={size}
      variant={active ? "default" : "outline"}
      className={cn(size === "sm" ? "h-8 text-sm" : "h-9", className)}
      onClick={onToggle}
    >
      {active ? (
        <ChevronDown className="h-3.5 w-3.5 mr-1" />
      ) : (
        <ChevronRight className="h-3.5 w-3.5 mr-1" />
      )}
      Сырые строки
    </Button>
  );
}

export type ImportExpandChevronProps = {
  expanded: boolean;
  hasContent?: boolean;
  className?: string;
};

export function ImportExpandChevron({
  expanded,
  hasContent = true,
  className = "h-3.5 w-3.5 text-muted-foreground",
}: ImportExpandChevronProps) {
  if (!hasContent) {
    return <span className={className} aria-hidden />;
  }
  return expanded ? (
    <ChevronDown className={className} />
  ) : (
    <ChevronRight className={className} />
  );
}

export type ImportRawCellsPanelProps = {
  values: string[];
  label?: string;
  className?: string;
};

export function ImportRawCellsPanel({
  values,
  label = "Сырые ячейки:",
  className,
}: ImportRawCellsPanelProps) {
  if (values.length === 0) return null;

  return (
    <div className={className ?? "flex flex-wrap gap-1 items-center"}>
      {label ? (
        <span className="font-bold uppercase tracking-wider text-muted-foreground/60 mr-2 text-[10px]">
          {label}
        </span>
      ) : null}
      {values.map((val, cellIdx) => (
        <Badge
          key={cellIdx}
          variant="secondary"
          className="px-1 py-0 h-4 text-[9px] rounded font-mono border"
        >
          {val || "пусто"}
        </Badge>
      ))}
    </div>
  );
}

export type ImportRawRowDetailProps = {
  colSpan: number;
  values?: string[];
  segments?: ImportRawSegment[];
  displayMode?: "badges" | "inline";
  className?: string;
};

export function ImportRawRowDetail({
  colSpan,
  values,
  segments,
  displayMode = "badges",
  className,
}: ImportRawRowDetailProps) {
  if (values && values.length > 0) {
    return (
      <tr className={cn("bg-muted/20 border-b", className)}>
        <td colSpan={colSpan} className="p-2 pl-10 text-[10px] font-mono text-muted-foreground">
          <ImportRawCellsPanel values={values} />
        </td>
      </tr>
    );
  }

  if (!segments?.length) return null;

  return (
    <>
      {segments.map((seg, i) => (
        <tr
          key={i}
          className={cn(
            "border-b",
            seg.variant === "duplicate"
              ? "bg-red-50/50 dark:bg-red-950/10"
              : "bg-muted/30",
            className,
          )}
        >
          <td colSpan={colSpan} className="p-2 pl-6 text-[11px] leading-relaxed font-mono">
            <div className="flex items-start gap-2">
              <span
                className={cn(
                  "font-bold shrink-0",
                  seg.variant === "duplicate" ? "text-red-600" : "text-muted-foreground",
                )}
              >
                {seg.prefixLabel ?? ""}#{seg.rowNumber}
                {seg.variant === "duplicate" ? " (дубликат):" : ":"}
              </span>
              {displayMode === "inline" ? (
                <span>{seg.values.filter(Boolean).join(" | ")}</span>
              ) : (
                <ImportRawCellsPanel values={seg.values} label="" />
              )}
            </div>
          </td>
        </tr>
      ))}
    </>
  );
}

export const ImportRawRows = {
  Toggle: ImportRawRowsToggle,
  Chevron: ImportExpandChevron,
  Cells: ImportRawCellsPanel,
  Detail: ImportRawRowDetail,
};