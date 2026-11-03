import { Badge, Button, Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/shared/ui";
import { bulkStatusLabels } from "@/shared/lib/generated-labels";
import { DIALOG_SIZES } from "@/shared/lib/dialogSizes";
import { cn } from "@/shared/utils/cn";
import type { BulkActionResultItem, BulkActionSummary } from "./bulkRunner";
import type { BulkId } from "./selection";

interface BulkResultsDialogProps<TId extends BulkId> {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  summary: BulkActionSummary | null;
  results: BulkActionResultItem<TId>[];
  /**
   * Общая строка на весь результат (#282: «собрано X из Y шт., дефицит Z»
   * группового запуска). По позициям она не раскладывается: итог один, а
   * выдач в запуске несколько.
   */
  overallNote?: string | null;
}

export function BulkResultsDialog<TId extends BulkId>({
  open,
  onOpenChange,
  title,
  summary,
  results,
  overallNote,
}: BulkResultsDialogProps<TId>) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={cn(DIALOG_SIZES.md.width, DIALOG_SIZES.md.height)}>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            {summary
              ? `${summary.success} успешно, ${summary.skipped} пропущено, ${summary.failed} ошибок`
              : "Нет результатов"}
          </DialogDescription>
          {overallNote ? (
            <p className="text-sm font-medium tabular-nums" data-testid="bulk-overall-note">
              {overallNote}
            </p>
          ) : null}
        </DialogHeader>
        <div className="max-h-[320px] space-y-2 overflow-auto">
          {results.map((result) => (
            <div key={String(result.id)} className="rounded border p-2 text-sm">
              <div className="flex items-center justify-between gap-3">
                <span className="font-medium">{result.label ?? `Позиция #${result.id}`}</span>
                <Badge variant={result.status === "success" ? "default" : result.status === "skipped" ? "secondary" : "destructive"}>
                  {bulkStatusLabels[result.status]}
                </Badge>
              </div>
              {result.reason && <div className="mt-1 text-xs text-muted-foreground">{result.reason}</div>}
              {result.meta?.tasks_created != null && (
                <div className="mt-1 text-xs text-muted-foreground">Задач создано: {String(result.meta.tasks_created)}</div>
              )}
              {result.meta?.issue_line != null && (
                <div className="mt-1 text-xs text-muted-foreground" data-testid={`bulk-issue-line-${result.id}`}>
                  {String(result.meta.issue_line)}
                </div>
              )}
            </div>
          ))}
        </div>
        <div className="flex justify-end pt-2">
          <Button onClick={() => onOpenChange(false)}>Закрыть</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
