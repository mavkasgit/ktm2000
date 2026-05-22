import { Badge, Button, Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/shared/ui";
import type { BulkActionResultItem, BulkActionSummary } from "./bulkRunner";
import type { BulkId } from "./selection";

const statusLabels = {
  success: "Успешно",
  skipped: "Пропущено",
  failed: "Ошибка",
} as const;

interface BulkResultsDialogProps<TId extends BulkId> {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  summary: BulkActionSummary | null;
  results: BulkActionResultItem<TId>[];
}

export function BulkResultsDialog<TId extends BulkId>({
  open,
  onOpenChange,
  title,
  summary,
  results,
}: BulkResultsDialogProps<TId>) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[560px]">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            {summary
              ? `${summary.success} успешно, ${summary.skipped} пропущено, ${summary.failed} ошибок`
              : "Нет результатов"}
          </DialogDescription>
        </DialogHeader>
        <div className="max-h-[320px] space-y-2 overflow-auto">
          {results.map((result) => (
            <div key={String(result.id)} className="rounded border p-2 text-sm">
              <div className="flex items-center justify-between gap-3">
                <span className="font-medium">{result.label ?? `Позиция #${result.id}`}</span>
                <Badge variant={result.status === "success" ? "default" : result.status === "skipped" ? "secondary" : "destructive"}>
                  {statusLabels[result.status]}
                </Badge>
              </div>
              {result.reason && <div className="mt-1 text-xs text-muted-foreground">{result.reason}</div>}
              {result.meta?.tasks_created != null && (
                <div className="mt-1 text-xs text-muted-foreground">Задач создано: {String(result.meta.tasks_created)}</div>
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
