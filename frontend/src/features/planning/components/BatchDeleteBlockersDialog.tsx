import { useState } from "react"
import { AlertTriangle, Ban, Zap } from "lucide-react"
import { Badge, Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/shared/ui"
import type { BatchDeleteConflict } from "@/shared/api/productionPlans"
import { usePermission } from "@/features/auth/hooks/usePermission"
import { blockerReasonLabel } from "../lib/batchDeleteConflict"
import { BatchForceDeleteDialog } from "./BatchForceDeleteDialog"

type Props = {
  open: boolean
  onOpenChange: (open: boolean) => void
  filename: string
  conflict: BatchDeleteConflict
  deleting: boolean
  onConfirmDrafts: () => void
  planId: number
  batchId: number
  onForceDeleted: () => void
}

/** Экран блокировок удаления батча (спека §4.4, тикет #167):
 *  ЧТО мешает → ПОСЛЕДСТВИЯ вариантов → ВЫБОР. «Удалить всё» при блокерах
 *  запрещено бэком (409 без флага обхода) — кнопка disabled с объяснением. */
export function BatchDeleteBlockersDialog({ open, onOpenChange, filename, conflict, deleting, onConfirmDrafts, planId, batchId, onForceDeleted }: Props) {
  const [forceOpen, setForceOpen] = useState(false)
  const { canForceDeleteImport } = usePermission()
  return (
    <>
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="w-[calc(100vw-2rem)] max-w-3xl max-h-[85vh] grid-rows-[auto_minmax(0,1fr)_auto]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-amber-600" />
            Удаление заблокировано
          </DialogTitle>
          <DialogDescription>
            Файл «{filename}» нельзя удалить целиком: ниже — что мешает и какие варианты безопасны.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 text-sm min-h-0 overflow-y-auto">
          <section>
            <h4 className="font-medium mb-2 sticky top-0 bg-background py-1">
              Что мешает ({conflict.blockers.length})
            </h4>
            <ul className="space-y-1.5">
              {conflict.blockers.map((b, i) => (
                <li key={`${b.position_id}-${i}`} className="flex items-start gap-2">
                  <Badge variant="destructive" className="shrink-0 whitespace-nowrap">
                    позиция #{b.position_id}
                  </Badge>
                  <span className="text-muted-foreground">{blockerReasonLabel(b.reason)}</span>
                </li>
              ))}
            </ul>
          </section>

          <section>
            <h4 className="font-medium mb-2">Последствия вариантов</h4>
            <ul className="space-y-1 text-muted-foreground list-disc pl-5">
              <li>Отмена — ничего не меняется, импорт остаётся на месте.</li>
              <li>
                Только черновики ({conflict.drafts}) — удалятся лишь черновые позиции без последствий;
                запущенные позиции, задачи и передачи не тронуты.
              </li>
              {canForceDeleteImport ? (
                <li className="flex items-start gap-1">
                  <Zap className="h-3.5 w-3.5 mt-0.5 shrink-0" />
                  <span>
                    Удалить всё принудительно — снесёт запущенные позиции, задания, передачи и проводки
                    склада; остатки вернутся к состоянию до импорта. Отменить будет нельзя.
                  </span>
                </li>
              ) : (
                <li className="flex items-start gap-1">
                  <Ban className="h-3.5 w-3.5 mt-0.5 shrink-0" />
                  <span>Удалить всё — запрещено: снесло бы запущенные позиции, задачи и передачи без возможности отката.</span>
                </li>
              )}
            </ul>
          </section>
        </div>

        <DialogFooter className="flex-col sm:flex-col gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={deleting}>
            Отмена
          </Button>
          <Button onClick={onConfirmDrafts} disabled={deleting || conflict.drafts === 0}>
            {deleting ? "Удаление…" : `Удалить только черновики (${conflict.drafts})`}
          </Button>
          {canForceDeleteImport ? (
            <Button variant="destructive" disabled={deleting} onClick={() => setForceOpen(true)}>
              <Zap className="mr-1 h-3.5 w-3.5" /> Удалить всё принудительно
            </Button>
          ) : (
            <Button variant="destructive" disabled title="Запрещено: удалило бы запущенные позиции, задачи и передачи">
              Удалить всё
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>

      <BatchForceDeleteDialog
        open={forceOpen}
        onOpenChange={setForceOpen}
        planId={planId}
        batchId={batchId}
        filename={filename}
        conflict={conflict}
        onForceDeleted={() => {
          onOpenChange(false)
          onForceDeleted()
        }}
      />
    </>
  )
}
