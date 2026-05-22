import { Play, X } from "lucide-react";
import { Badge, Button, Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/shared/ui";
import { cn } from "@/shared/utils/cn";
import type { BulkActionDefinition, BulkActionSummary, BulkRunnerProgress } from "./bulkRunner";
import type { BulkId } from "./selection";

interface BulkPowerBarProps<TId extends BulkId, TContext> {
  selectedCount: number;
  actions: BulkActionDefinition<TId, TContext>[];
  selectedActionId: string;
  onActionChange: (actionId: string) => void;
  onRun: () => void;
  onClear: () => void;
  disabled?: boolean;
  progress?: BulkRunnerProgress | null;
  lastSummary?: BulkActionSummary | null;
  className?: string;
}

export function BulkPowerBar<TId extends BulkId, TContext>({
  selectedCount,
  actions,
  selectedActionId,
  onActionChange,
  onRun,
  onClear,
  disabled,
  progress,
  lastSummary,
  className,
}: BulkPowerBarProps<TId, TContext>) {
  if (selectedCount === 0) return null;
  const selectedAction = actions.find((action) => action.id === selectedActionId);
  const running = Boolean(progress?.running);

  return (
    <div className={cn("sticky top-2 z-30 mb-3 rounded-md border bg-background/95 p-2 shadow-sm backdrop-blur", className)}>
      <div className="flex flex-col gap-2 md:flex-row md:items-center">
        <div className="shrink-0 text-sm font-medium">Выбрано: {selectedCount}</div>
        <Select value={selectedActionId} onValueChange={onActionChange} disabled={running || disabled}>
          <SelectTrigger className="h-8 w-full md:w-64">
            <SelectValue placeholder="Выберите действие" />
          </SelectTrigger>
          <SelectContent>
            {actions.map((action) => (
              <SelectItem key={action.id} value={action.id}>
                {action.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button size="sm" className="h-8" onClick={onRun} disabled={disabled || running || !selectedAction}>
          <Play className="mr-1 h-4 w-4" />
          {running ? selectedAction?.pendingLabel ?? "Выполнение..." : selectedAction?.primaryLabel ?? "Выполнить"}
        </Button>
        <Button variant="ghost" size="sm" className="h-8" onClick={onClear} disabled={running}>
          <X className="mr-1 h-4 w-4" />
          Сбросить
        </Button>
        {progress && running && (
          <span className="text-xs text-muted-foreground">
            {progress.completed}/{progress.total}
          </span>
        )}
        {lastSummary && lastSummary.total > 0 && !running && (
          <Badge variant={lastSummary.failed > 0 ? "destructive" : "secondary"} className="w-fit">
            {lastSummary.success} ok / {lastSummary.skipped} пропущено / {lastSummary.failed} ошибок
          </Badge>
        )}
      </div>
    </div>
  );
}
