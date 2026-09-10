import { AlertTriangle, Ban } from "lucide-react"
import { Badge, Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/shared/ui"
import type { BatchDeleteConflict } from "@/shared/api/productionPlans"
import { blockerReasonLabel } from "../lib/batchDeleteConflict"

type Props = {
  open: boolean
  onOpenChange: (open: boolean) => void
  filename: string
  conflict: BatchDeleteConflict
  deleting: boolean
  onConfirmDrafts: () => void
}

/** Экран блокировок удаления батча (спека §4.4, тикет #167):
 *  ЧТО мешает → ПОСЛЕДСТВИЯ вариантов → ВЫБОР. «Удалить всё» при блокерах
 *  запрещено бэком (409 без флага обхода) — кнопка disabled с объяснением. */
export function BatchDeleteBlockersDialog({ open, onOpenChange, filename, conflict, deleting, onConfirmDrafts }: Props) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-amber-600" />
            Удаление заблокировано
          </DialogTitle>
          <DialogDescription>
            Файл «{filename}» нельзя удалить целиком: ниже — что мешает и какие варианты безопасны.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 text-sm">
          <section>
            <h4 className="font-medium mb-2">Что мешает</h4>
            <ul className="space-y-1.5">
              {conflict.blockers.map((b, i) => (
                <li key={`${b.position_id}-${i}`} className="flex items-center gap-2">
                  <Badge variant="destructive">позиция #{b.position_id}</Badge>
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
              <li className="flex items-start gap-1">
                <Ban className="h-3.5 w-3.5 mt-0.5 shrink-0" />
                <span>Удалить всё — запрещено: снесло бы запущенные позиции, задачи и передачи без возможности отката.</span>
              </li>
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
          <Button variant="destructive" disabled title="Запрещено: удалило бы запущенные позиции, задачи и передачи">
            Удалить всё
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
