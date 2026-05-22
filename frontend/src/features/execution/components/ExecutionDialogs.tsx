import { ProductionPlanningRow, ProductionPlanningRowDetail, StatusHistoryEntry } from "@/shared/api/productionPlans";
import { Badge, Button, Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, Input, Select, SelectContent, SelectItem, SelectTrigger, SelectValue, AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogTitle, AlertDialogDescription, AlertDialogFooter, AlertDialogAction, AlertDialogCancel } from "@/shared/ui";
import { BulkResultsDialog, type BulkActionResultItem, type BulkActionSummary } from "@/shared/bulk";
import { RowDetailsSidePanel, adaptExecutionDetail } from "@/features/planning/components/row-details";
import { positionStatusLabels } from "./execution-utils";

interface ExecutionDialogsProps {
  // Row details
  drawerOpen: boolean;
  onDrawerOpenChange: (open: boolean) => void;
  detail: ProductionPlanningRowDetail | null;
  detailLoading: boolean;
  detailError: unknown;
  selectedPositionId: number | null;

  // Launch dialog
  launchDialog: { open: boolean; mode: "single" | "bulk"; positionIds: number[] };
  onLaunchDialogChange: (state: { open: boolean; mode: "single" | "bulk"; positionIds: number[] }) => void;
  takeToWorkPending: boolean;
  onConfirmLaunch: () => void;

  // Manual pass dialog
  manualPassDialog: { open: boolean; positionId: number | null; targetRouteStepId: string; comment: string };
  onManualPassDialogChange: (state: { open: boolean; positionId: number | null; targetRouteStepId: string; comment: string }) => void;
  manualPassDetail: ProductionPlanningRowDetail | undefined;
  manualPassDetailLoading: boolean;
  manualPassPending: boolean;
  onConfirmManualPass: () => void;

  // Bulk manual pass dialog
  manualPassBulkDialog: { open: boolean; targetRouteStepId: string; comment: string; positionIds: number[] };
  onManualPassBulkDialogChange: (state: { open: boolean; targetRouteStepId: string; comment: string; positionIds: number[] }) => void;
  bulkManualPassPending: boolean;
  onConfirmBulkManualPass: () => void;

  // Cancel dialog
  cancelDialog: { open: boolean; positionId: number | null; isReleased: boolean };
  onCancelDialogChange: (state: { open: boolean; positionId: number | null; isReleased: boolean }) => void;
  cancelPending: boolean;
  onConfirmCancel: () => void;

  // Restore dialog
  restoreDialog: { open: boolean; positionId: number | null; reason: string };
  onRestoreDialogChange: (state: { open: boolean; positionId: number | null; reason: string }) => void;
  restorePending: boolean;
  onConfirmRestore: () => void;

  // Delete dialog
  deleteDialog: { open: boolean; positionId: number | null; reason: string };
  onDeleteDialogChange: (state: { open: boolean; positionId: number | null; reason: string }) => void;
  softDeletePending: boolean;
  onConfirmSoftDelete: () => void;

  // Bulk results
  bulkResultsOpen: boolean;
  onBulkResultsChange: (open: boolean) => void;
  bulkSummary: BulkActionSummary | null;
  bulkResults: BulkActionResultItem<number>[];

  // Bulk delete confirm
  bulkDeleteConfirmOpen: boolean;
  onBulkDeleteConfirmChange: (open: boolean) => void;
  bulkSoftDeleting: boolean;
  bulkSelectedCount: number;
  onConfirmBulkSoftDelete: () => void;

  // History dialog
  historyDialogOpen: boolean;
  onHistoryDialogChange: (open: boolean) => void;
  historyLoading: boolean;
  historyEntries: StatusHistoryEntry[];
}

export function ExecutionDialogs({
  drawerOpen,
  onDrawerOpenChange,
  detail,
  detailLoading,
  detailError,
  selectedPositionId,
  launchDialog,
  onLaunchDialogChange,
  takeToWorkPending,
  onConfirmLaunch,
  manualPassDialog,
  onManualPassDialogChange,
  manualPassDetail,
  manualPassDetailLoading,
  manualPassPending,
  onConfirmManualPass,
  manualPassBulkDialog,
  onManualPassBulkDialogChange,
  bulkManualPassPending,
  onConfirmBulkManualPass,
  cancelDialog,
  onCancelDialogChange,
  cancelPending,
  onConfirmCancel,
  restoreDialog,
  onRestoreDialogChange,
  restorePending,
  onConfirmRestore,
  deleteDialog,
  onDeleteDialogChange,
  softDeletePending,
  onConfirmSoftDelete,
  bulkResultsOpen,
  onBulkResultsChange,
  bulkSummary,
  bulkResults,
  bulkDeleteConfirmOpen,
  onBulkDeleteConfirmChange,
  bulkSoftDeleting,
  bulkSelectedCount,
  onConfirmBulkSoftDelete,
  historyDialogOpen,
  onHistoryDialogChange,
  historyLoading,
  historyEntries,
}: ExecutionDialogsProps) {
  return (
    <>
      <RowDetailsSidePanel
        open={drawerOpen}
        onOpenChange={(open) => {
          onDrawerOpenChange(open);
          if (!open) {
            // setSelectedPositionId handled by parent
          }
        }}
        data={detail ? adaptExecutionDetail(detail) : null}
        loading={detailLoading}
        error={detailError ? String(detailError) : null}
      />

      <Dialog
        open={launchDialog.open}
        onOpenChange={(open) => {
          if (!open) onLaunchDialogChange({ open: false, mode: "single", positionIds: [] });
        }}
      >
        <DialogContent className="sm:max-w-[480px]">
          <DialogHeader>
            <DialogTitle>Взять в работу</DialogTitle>
            <DialogDescription>
              {launchDialog.mode === "single"
                ? "Будут созданы задачи по всем этапам маршрута для выбранной строки."
                : `Будут созданы задачи по всем этапам маршрута для ${launchDialog.positionIds.length} выбранных строк.`}
            </DialogDescription>
          </DialogHeader>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => onLaunchDialogChange({ open: false, mode: "single", positionIds: [] })}>
              Отмена
            </Button>
            <Button onClick={onConfirmLaunch} disabled={takeToWorkPending}>
              {takeToWorkPending ? "Запуск..." : "Запустить"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog
        open={manualPassDialog.open}
        onOpenChange={(open) => {
          if (!open) onManualPassDialogChange({ open: false, positionId: null, targetRouteStepId: "", comment: "" });
        }}
      >
        <DialogContent className="sm:max-w-[560px]">
          <DialogHeader>
            <DialogTitle>Сквозной проход</DialogTitle>
            <DialogDescription>
              Система создаст задачи маршрута при необходимости и оформит предыдущие этапы как ручной пропуск. Выбранный этап останется готовым к работе.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            {manualPassDetailLoading ? (
              <p className="text-sm text-muted-foreground">Загрузка маршрута...</p>
            ) : (
              <>
                <div className="space-y-1.5">
                  <div className="text-sm font-medium">Остановиться на этапе</div>
                  <Select
                    value={manualPassDialog.targetRouteStepId}
                    onValueChange={(value) => onManualPassDialogChange({ ...manualPassDialog, targetRouteStepId: value })}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="Выберите этап маршрута" />
                    </SelectTrigger>
                    <SelectContent>
                      {(manualPassDetail?.stages || []).map((stage) => (
                        <SelectItem key={stage.route_step_id} value={String(stage.route_step_id)}>
                          #{stage.sequence} · {stage.section_name} · {stage.operation_name || "Операция"}
                        </SelectItem>
                      ))}
                      {(manualPassDetail?.stages?.length || 0) > 0 && (
                        <SelectItem value="complete">
                          Полное завершение задачи
                        </SelectItem>
                      )}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <div className="text-sm font-medium">Комментарий</div>
                  <Input
                    placeholder="Необязательно"
                    value={manualPassDialog.comment}
                    onChange={(e) => onManualPassDialogChange({ ...manualPassDialog, comment: e.target.value })}
                  />
                </div>
                {manualPassDialog.targetRouteStepId && manualPassDetail && (
                  <div className="rounded border bg-muted/40 p-3 text-sm text-muted-foreground">
                    {manualPassDialog.targetRouteStepId === "complete"
                      ? "Будут вручную закрыты все этапы маршрута. Все созданные факты получат текущее время выполнения и учёта."
                      : "Будут вручную закрыты этапы до выбранного. Все созданные факты получат текущее время выполнения и учёта."}
                  </div>
                )}
              </>
            )}
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => onManualPassDialogChange({ open: false, positionId: null, targetRouteStepId: "", comment: "" })}>
              Отмена
            </Button>
            <Button
              onClick={onConfirmManualPass}
              disabled={manualPassPending || manualPassDetailLoading || !manualPassDialog.targetRouteStepId}
            >
              {manualPassPending ? "Выполнение..." : "Выполнить"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog
        open={manualPassBulkDialog.open}
        onOpenChange={(open) => {
          if (!open) onManualPassBulkDialogChange({ open: false, targetRouteStepId: "", comment: "", positionIds: [] });
        }}
      >
        <DialogContent className="sm:max-w-[560px]">
          <DialogHeader>
            <DialogTitle>Сквозной проход ({manualPassBulkDialog.positionIds.length} позиций)</DialogTitle>
            <DialogDescription>
              Система создаст задачи маршрута при необходимости и оформит предыдущие этапы как ручной пропуск для всех выбранных позиций.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1.5">
              <div className="text-sm font-medium">Остановиться на этапе</div>
              <Select
                value={manualPassBulkDialog.targetRouteStepId}
                onValueChange={(value) => onManualPassBulkDialogChange({ ...manualPassBulkDialog, targetRouteStepId: value })}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Выберите этап или полное завершение" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="complete">
                    Полное завершение задачи
                  </SelectItem>
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">
                Для массового сквозного прохода выберите «Полное завершение задачи». Этапы маршрута каждой позиции будут закрыты до конца.
              </p>
            </div>
            <div className="space-y-1.5">
              <div className="text-sm font-medium">Комментарий</div>
              <Input
                placeholder="Необязательно"
                value={manualPassBulkDialog.comment}
                onChange={(e) => onManualPassBulkDialogChange({ ...manualPassBulkDialog, comment: e.target.value })}
              />
            </div>
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => onManualPassBulkDialogChange({ open: false, targetRouteStepId: "", comment: "", positionIds: [] })}>
              Отмена
            </Button>
            <Button
              onClick={onConfirmBulkManualPass}
              disabled={bulkManualPassPending || !manualPassBulkDialog.targetRouteStepId}
            >
              {bulkManualPassPending ? "Выполнение..." : "Выполнить"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <AlertDialog
        open={cancelDialog.open}
        onOpenChange={(open) => {
          if (!open) onCancelDialogChange({ open: false, positionId: null, isReleased: false });
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{cancelDialog.isReleased ? "Остановить выполнение?" : "Отменить позицию?"}</AlertDialogTitle>
            <AlertDialogDescription>
              {cancelDialog.isReleased
                ? "Позиция уже запущена. Остановка выполнения переведёт её в статус «Отменен»."
                : "Отмена переведёт позицию в статус «Отменен»."}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Отмена</AlertDialogCancel>
            <AlertDialogAction className="bg-destructive text-destructive-foreground hover:bg-destructive/90" onClick={onConfirmCancel} disabled={cancelPending}>
              {cancelPending ? "Отмена..." : cancelDialog.isReleased ? "Остановить" : "Отменить"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog
        open={restoreDialog.open}
        onOpenChange={(open) => {
          if (!open) onRestoreDialogChange({ open: false, positionId: null, reason: "" });
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Восстановить позицию?</AlertDialogTitle>
            <AlertDialogDescription>
              Позиция будет восстановлена в предыдущий статус. Это действие нельзя отменить.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="py-2">
            <Input
              placeholder="Причина (необязательно)"
              value={restoreDialog.reason}
              onChange={(e) => onRestoreDialogChange({ ...restoreDialog, reason: e.target.value })}
            />
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel>Отмена</AlertDialogCancel>
            <AlertDialogAction onClick={onConfirmRestore} disabled={restorePending}>
              {restorePending ? "Восстановление..." : "Восстановить"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog
        open={deleteDialog.open}
        onOpenChange={(open) => {
          if (!open) onDeleteDialogChange({ open: false, positionId: null, reason: "" });
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Удалить из списка?</AlertDialogTitle>
            <AlertDialogDescription>
              Позиция будет скрыта из всех рабочих списков. История изменений сохранится.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="py-2">
            <Input
              placeholder="Причина (необязательно)"
              value={deleteDialog.reason}
              onChange={(e) => onDeleteDialogChange({ ...deleteDialog, reason: e.target.value })}
            />
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel>Отмена</AlertDialogCancel>
            <AlertDialogAction className="bg-destructive text-destructive-foreground hover:bg-destructive/90" onClick={onConfirmSoftDelete} disabled={softDeletePending}>
              {softDeletePending ? "Удаление..." : "Удалить из списка"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <BulkResultsDialog
        open={bulkResultsOpen}
        onOpenChange={onBulkResultsChange}
        title="Результат массового действия"
        summary={bulkSummary}
        results={bulkResults}
      />

      <AlertDialog open={bulkDeleteConfirmOpen} onOpenChange={onBulkDeleteConfirmChange}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle className="text-destructive">Подтвердить удаление</AlertDialogTitle>
            <AlertDialogDescription>
              Будет скрыто <strong>{bulkSelectedCount}</strong> позиций. Это действие нельзя отменить.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Отмена</AlertDialogCancel>
            <AlertDialogAction
              onClick={(e) => {
                e.preventDefault();
                onConfirmBulkSoftDelete();
              }}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              disabled={bulkSoftDeleting}
            >
              {bulkSoftDeleting ? "Удаление..." : "Удалить"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <Dialog
        open={historyDialogOpen}
        onOpenChange={(open) => {
          if (!open) onHistoryDialogChange(false);
        }}
      >
        <DialogContent className="sm:max-w-[560px]">
          <DialogHeader>
            <DialogTitle>История статусов</DialogTitle>
            <DialogDescription>Хронология изменений статуса позиции</DialogDescription>
          </DialogHeader>
          {historyLoading ? (
            <p className="text-sm text-muted-foreground py-4">Загрузка истории...</p>
          ) : historyEntries.length === 0 ? (
            <p className="text-sm text-muted-foreground py-4">История изменений отсутствует</p>
          ) : (
            <div className="max-h-[400px] overflow-auto space-y-2">
              {historyEntries.map((entry) => (
                <div key={entry.id} className="rounded border p-3 text-sm">
                  <div className="flex items-center justify-between">
                    <span className="font-medium">
                      {positionStatusLabels[entry.from_status] || entry.from_status} → {positionStatusLabels[entry.to_status] || entry.to_status}
                    </span>
                    <Badge variant="secondary">{new Date(entry.changed_at).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" })}</Badge>
                  </div>
                  {entry.reason && <div className="text-xs text-muted-foreground mt-1">{entry.reason}</div>}
                </div>
              ))}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
