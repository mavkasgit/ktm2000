import { X } from "lucide-react";
import { Badge, Button } from "@/shared/ui";
import { cn } from "@/shared/utils/cn";
import type { BulkActionSummary, BulkRunnerProgress } from "./bulkRunner";
import type { BulkId } from "./selection";
import type { BulkSelectionAction } from "./BulkSelectionTable";

export interface BulkSelectionChip<TId extends BulkId> {
  id: TId;
  label: string;
  meta?: string;
}

interface BulkSelectionPanelProps<TId extends BulkId> {
  selectedCount: number;
  chips: BulkSelectionChip<TId>[];
  actions: BulkSelectionAction[];
  onClose: () => void;
  onRemoveChip?: (id: TId) => void;
  progress?: BulkRunnerProgress | null;
  lastSummary?: BulkActionSummary | null;
  className?: string;
}

export function BulkSelectionPanel<TId extends BulkId>({
  selectedCount,
  chips,
  actions,
  onClose,
  onRemoveChip,
  progress,
  lastSummary,
  className,
}: BulkSelectionPanelProps<TId>) {
  if (selectedCount === 0) return null;

  const running = Boolean(progress?.running);

  return (
    <div className={cn("sticky top-0 z-30 border-b bg-background/95 backdrop-blur shadow-sm", className)}>
      <div className="flex items-center gap-2 p-2">
        <span className="shrink-0 text-sm font-medium">Выбрано: {selectedCount}</span>

        <div className="flex gap-1 overflow-x-auto flex-1 min-w-0">
          {chips.map((chip) => (
            <div
              key={String(chip.id)}
              className="inline-flex items-center gap-1 shrink-0 px-2 py-1 rounded-md bg-muted text-xs max-w-[200px]"
            >
              <span className="truncate font-medium">{chip.label}</span>
              {chip.meta && <span className="text-muted-foreground truncate">{chip.meta}</span>}
              {onRemoveChip && (
                <button
                  type="button"
                  className="shrink-0 ml-0.5 text-muted-foreground hover:text-foreground"
                  onClick={() => onRemoveChip(chip.id)}
                >
                  <X className="h-3 w-3" />
                </button>
              )}
            </div>
          ))}
        </div>

        <div className="flex items-center gap-1 shrink-0">
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
            <Badge variant={lastSummary.failed > 0 ? "destructive" : "secondary"} className="shrink-0">
              {lastSummary.success} ok / {lastSummary.skipped} пропущено / {lastSummary.failed} ошибок
            </Badge>
          )}

          <Button variant="ghost" size="sm" onClick={onClose} disabled={running}>
            <X className="h-3.5 w-3.5 mr-1" />
            Закрыть
          </Button>
        </div>
      </div>
    </div>
  );
}
