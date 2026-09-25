import { useEffect, useState } from "react"
import { Loader2 } from "lucide-react"

import type { ProductionPlanDeletePreview } from "@/shared/api/productionPlans"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/shared/ui"

export function DeletePlanConfirmDialog({
  open,
  planNo,
  planName,
  preview,
  previewLoading,
  deleting,
  error,
  onOpenChange,
  onConfirm,
}: {
  open: boolean
  planNo: string
  planName: string
  preview?: ProductionPlanDeletePreview
  previewLoading: boolean
  deleting: boolean
  error?: string | null
  onOpenChange: (open: boolean) => void
  onConfirm: (reason: string) => void
}) {
  const [confirmation, setConfirmation] = useState("")
  const [reason, setReason] = useState("")

  useEffect(() => {
    if (open) {
      setConfirmation("")
      setReason("")
    }
  }, [open])

  const hasBlockers = (preview?.blockers.length ?? 0) > 0
  const canConfirm =
    confirmation === planNo &&
    reason.trim().length >= 3 &&
    preview != null &&
    !previewLoading &&
    !hasBlockers &&
    !deleting

  return (
    <AlertDialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!deleting) onOpenChange(nextOpen)
      }}
    >
      <AlertDialogContent className="max-w-3xl">
        <AlertDialogHeader>
          <AlertDialogTitle className="text-destructive">
            Удалить производственный план?
          </AlertDialogTitle>
          <AlertDialogDescription>
            План «{planName}» ({planNo}) исчезнет из рабочих экранов. Его задания
            и передачи отменятся, дефекты закроются, а операции создадут
            компенсационные проводки и восстановят остатки. Исходный ledger,
            журнал действий и аудит сохранятся; каталоги и настройки не изменятся.
          </AlertDialogDescription>
        </AlertDialogHeader>

        <div className="max-h-[60vh] space-y-4 overflow-y-auto pr-1 text-sm">
          {previewLoading ? (
            <p className="flex items-center gap-2 text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" /> Проверка данных плана...
            </p>
          ) : preview ? (
            <>
              <div className="grid grid-cols-2 gap-2 rounded-md border bg-muted/30 p-3 md:grid-cols-4">
                <span>Позиции: <strong>{preview.positions}</strong></span>
                <span>Задания: <strong>{preview.work_tasks}</strong></span>
                <span>Передачи: <strong>{preview.transfers}</strong></span>
                <span>Операции: <strong>{preview.active_actions}</strong></span>
              </div>

              <section className="rounded-md border p-3">
                <h3 className="font-medium">Уже задействованные строки</h3>
                {preview.used_positions.length === 0 ? (
                  <p className="mt-1 text-muted-foreground">Запущенных строк нет.</p>
                ) : (
                  <ul className="mt-2 max-h-36 space-y-1 overflow-y-auto">
                    {preview.used_positions.map((position) => (
                      <li key={position.position_id} className="flex justify-between gap-3">
                        <span>
                          <strong>{position.source_sku}</strong> · строка {position.position_id}
                        </span>
                        <span className="text-muted-foreground">
                          {position.status} · заданий: {position.task_count} · операций: {position.action_count}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              <section className="rounded-md border p-3">
                <h3 className="font-medium">Что отменится</h3>
                <div className="mt-2 grid grid-cols-2 gap-2 md:grid-cols-3">
                  <span>Позиции: <strong>{preview.cancellations.positions}</strong></span>
                  <span>Задания: <strong>{preview.cancellations.work_tasks}</strong></span>
                  <span>Передачи: <strong>{preview.cancellations.transfers}</strong></span>
                  <span>Брак (закроется): <strong>{preview.cancellations.defects}</strong></span>
                  <span>Переделки: <strong>{preview.cancellations.rework_tasks}</strong></span>
                  <span>Убрать из дневных планов: <strong>{preview.cancellations.daily_plan_items}</strong></span>
                </div>
              </section>

              <section className="rounded-md border p-3">
                <h3 className="font-medium">Что откатится на остатках</h3>
                {preview.stock_effects.length === 0 ? (
                  <p className="mt-1 text-muted-foreground">Операций движения нет.</p>
                ) : (
                  <ul className="mt-2 max-h-40 space-y-2 overflow-y-auto">
                    {preview.stock_effects.map((effect) => (
                      <li key={effect.transaction_id} className="rounded bg-muted/40 px-2 py-1.5">
                        <div className="flex justify-between gap-3">
                          <strong>{effect.product_sku}</strong>
                          <span>{effect.effect === "return" ? "вернётся" : "отменится"}</span>
                        </div>
                        <div>
                          {effect.from_location ?? "—"} → {effect.to_location ?? "—"} · {effect.quantity} · {effect.reason}
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
                <p className="mt-2 text-muted-foreground">
                  Исходные и компенсационные проводки сохранятся в ledger: {preview.ledger_entries}.
                </p>
              </section>
            </>
          ) : null}

          {hasBlockers && (
            <div className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-destructive">
              <p className="font-medium">Удаление заблокировано:</p>
              <ul className="mt-1 list-disc pl-5">
                {preview?.blockers.map((blocker) => (
                  <li key={`${blocker.action_id}:${blocker.kind}:${blocker.detail}`}>
                    {blocker.detail}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {error && <p className="text-destructive">{error}</p>}

          <label className="block space-y-1">
            <span className="font-medium">Причина удаления</span>
            <textarea
              className="min-h-20 w-full rounded-md border bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring"
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder="Например: ошибочно импортированный план"
              disabled={deleting}
            />
          </label>

          <label className="block space-y-1">
            <span className="font-medium">
              Для подтверждения введите <code>{planNo}</code>
            </span>
            <input
              className="h-9 w-full rounded-md border bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-ring"
              value={confirmation}
              onChange={(event) => setConfirmation(event.target.value)}
              autoComplete="off"
              disabled={deleting}
            />
          </label>
        </div>

        <AlertDialogFooter>
          <AlertDialogCancel disabled={deleting}>Отмена</AlertDialogCancel>
          <AlertDialogAction
            className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            disabled={!canConfirm}
            onClick={(event) => {
              event.preventDefault()
              if (canConfirm) onConfirm(reason.trim())
            }}
          >
            {deleting ? "Удаление..." : "Удалить план целиком"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
