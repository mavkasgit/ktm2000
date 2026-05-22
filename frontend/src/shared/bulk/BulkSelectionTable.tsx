import { X } from "lucide-react";
import { Badge, Button } from "@/shared/ui";
import { cn } from "@/shared/utils/cn";
import type { BulkActionSummary, BulkRunnerProgress } from "./bulkRunner";
import type { BulkId } from "./selection";

export interface BulkSelectionRow {
  id: BulkId;
  cells: Record<string, string>;
}

export interface BulkSelectionAction {
  id: string;
  label: string;
  variant?: "default" | "destructive" | "outline" | "secondary" | "success";
  onClick: () => void;
  disabled?: boolean;
  pending?: boolean;
}

interface BulkSelectionTableProps {
  selectedCount: number;
  rows: BulkSelectionRow[];
  columns: { key: string; label: string }[];
  actions: BulkSelectionAction[];
  onClose: () => void;
  onRemoveRow?: (id: BulkId) => void;
  progress?: BulkRunnerProgress | null;
  lastSummary?: BulkActionSummary | null;
  className?: string;
}

export function BulkSelectionTable({
  selectedCount,
  rows,
  columns,
  actions,
  onClose,
  onRemoveRow,
  progress,
  lastSummary,
  className,
}: BulkSelectionTableProps) {
  if (selectedCount === 0) return null;

  const running = Boolean(progress?.running);

  return (
    <div className={cn("rounded-lg border bg-card mb-3", className)}>
      <div className="flex items-center justify-between px-4 py-2 border-b">
        <span className="text-sm font-medium">Выбрано: {selectedCount}</span>
        <div className="flex items-center gap-2">
          {actions.map((action) => (
            <Button
              key={action.id}
              size="sm"
              variant={action.variant || "default"}
              onClick={action.onClick}
              disabled={action.disabled || running || action.pending}
            >
              {action.pending ? "Выполнение..." : action.label}
            </Button>
          ))}

          {progress && running && (
            <span className="text-xs text-muted-foreground">
              {progress.completed}/{progress.total}
            </span>
          )}
          {lastSummary && lastSummary.total > 0 && !running && (
            <Badge variant={lastSummary.failed > 0 ? "destructive" : "secondary"}>
              {lastSummary.success} ok / {lastSummary.skipped} пропущено / {lastSummary.failed} ошибок
            </Badge>
          )}

          <Button variant="ghost" size="sm" onClick={onClose} disabled={running}>
            <X className="h-3.5 w-3.5 mr-1" />
            Закрыть
          </Button>
        </div>
      </div>

      <div className="max-h-[200px] overflow-auto">
        <table className="w-full text-sm">
          <thead className="[&_th]:sticky [&_th]:top-0 [&_th]:z-20 [&_th]:bg-muted/50 [&_th]:backdrop-blur [&_th]:border-b">
            <tr>
              {columns.map((col) => (
                <th key={col.key} className="text-left p-2 text-xs font-medium text-muted-foreground">
                  {col.label}
                </th>
              ))}
              <th className="text-left p-2 w-10"></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={String(row.id)} className="border-b last:border-b-0 hover:bg-muted/50">
                {columns.map((col) => (
                  <td key={col.key} className="p-2 truncate max-w-[200px]">
                    {row.cells[col.key]}
                  </td>
                ))}
                <td className="p-2">
                  {onRemoveRow && (
                    <button
                      type="button"
                      className="text-muted-foreground hover:text-destructive transition-colors"
                      onClick={(e) => {
                        e.stopPropagation();
                        onRemoveRow(row.id);
                      }}
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
