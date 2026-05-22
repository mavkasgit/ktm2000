import { Play, X } from "lucide-react";
import { Button } from "@/shared/ui";
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
  /** Selected IDs for eligibility computation */
  selectedIds?: Set<TId>;
  /** Context map for isEligible checks */
  context?: TContext;
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
  selectedIds,
  context,
}: BulkPowerBarProps<TId, TContext>) {
  if (selectedCount === 0) return null;
  const running = Boolean(progress?.running);

  // Compute eligible count for each action
  const eligibleActions = actions
    .map((action) => {
      if (!context || !action.isEligible || !selectedIds || selectedIds.size === 0) {
        return { action, eligibleCount: 0 };
      }
      let count = 0;
      const idsArray = Array.from(selectedIds);
      for (let i = 0; i < idsArray.length; i++) {
        const id = idsArray[i] as TId;
        if (action.isEligible(id, context)) count++;
      }
      return { action, eligibleCount: count };
    })
    .filter(({ eligibleCount }) => eligibleCount > 0);

  if (eligibleActions.length === 0) return null;

  // Action variant mapping
  const actionVariant = (actionId: string): "default" | "destructive" | "outline" | "success" => {
    switch (actionId) {
      case "take-to-work":
        return "success";
      case "cancel":
      case "soft-delete":
        return "destructive";
      case "restore":
        return "outline";
      default:
        return "default";
    }
  };

  return (
    <div className={cn("sticky top-2 z-30 mb-3 rounded-md border bg-background/95 p-2 shadow-sm backdrop-blur", className)}>
      <div className="flex flex-col gap-2 md:flex-row md:items-center">
        <div className="shrink-0 text-sm font-medium">Выбрано: {selectedCount}</div>
        <div className="flex flex-wrap gap-1.5">
          {eligibleActions.map(({ action, eligibleCount }) => {
            const isActive = action.id === selectedActionId;
            const variant = actionVariant(action.id);
            return (
              <Button
                key={action.id}
                size="sm"
                variant={isActive ? (variant === "destructive" ? "destructive" : "default") : variant}
                className="h-8 text-xs"
                onClick={() => onActionChange(action.id)}
                disabled={disabled || running}
              >
                {action.label}
                {eligibleCount < selectedCount && (
                  <span className="ml-1 opacity-60">({eligibleCount})</span>
                )}
              </Button>
            );
          })}
          <Button
            size="sm"
            className="h-8"
            onClick={onRun}
            disabled={disabled || running || eligibleActions.length === 0}
          >
            <Play className="mr-1 h-4 w-4" />
            {running
              ? eligibleActions.find((a) => a.action.id === selectedActionId)?.action.pendingLabel ?? "Выполнение..."
              : eligibleActions.find((a) => a.action.id === selectedActionId)?.action.primaryLabel ?? "Выполнить"}
          </Button>
        </div>
        <Button variant="ghost" size="sm" className="h-8" onClick={onClear} disabled={running}>
          <X className="mr-1 h-4 w-4" />
          Сбросить
        </Button>
        {progress && running && (
          <span className="text-xs text-muted-foreground">
            {progress.completed}/{progress.total}
          </span>
        )}
      </div>
    </div>
  );
}
