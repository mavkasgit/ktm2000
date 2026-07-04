import { useEffect, useState } from "react"
import { Dialog, DialogContent } from "@/shared/ui"
import { fmtQty } from "@/shared/utils/fmtQty"
import { type RowDetailsContentMode, type RowDetailsData } from "./types"
import { RowDetailsContent } from "./RowDetailsContent"
import { RowDetailsPanelToggles } from "./RowDetailsPanelToggles"

function buildPanelTitle(data: RowDetailsData): string {
  const id = String(data.id)
  const qty = fmtQty(data.quantity)
  const hasExecutionStages = (data.stages?.length ?? 0) > 0
  const prefix = hasExecutionStages ? "Выполнение задания" : "Позиция плана"
  return `${prefix} #${id} · артикул ${data.sku} · ${qty} шт.`
}

interface RowDetailsSidePanelProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  data: RowDetailsData | null
  loading?: boolean
  error?: string | null
  showPlanLink?: boolean
  onSaved?: () => void
}

export function RowDetailsSidePanel({
  open,
  onOpenChange,
  data,
  loading = false,
  error = null,
  showPlanLink,
  onSaved,
}: RowDetailsSidePanelProps) {
  const [contentMode, setContentMode] = useState<RowDetailsContentMode>("stages")
  const hasStages = (data?.stages?.length ?? 0) > 0

  useEffect(() => {
    if (!open) {
      setContentMode("stages")
    }
  }, [open])

  useEffect(() => {
    setContentMode("stages")
  }, [data?.id])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="!left-auto !right-0 !top-0 !translate-x-0 !translate-y-0 h-screen max-h-screen w-[min(100vw,940px)] max-w-none rounded-none border-l p-0 flex flex-col gap-0">
        {!loading && !error && data && (
          <div className="shrink-0 border-b bg-background px-6 py-3 space-y-2">
            <h2 className="text-lg font-semibold truncate">
              {buildPanelTitle(data)}
            </h2>
            {hasStages && (
              <RowDetailsPanelToggles mode={contentMode} onChange={setContentMode} />
            )}
          </div>
        )}
        <div className="flex-1 overflow-auto p-6">
          {loading && (
            <p className="text-sm text-muted-foreground">Загрузка детализации...</p>
          )}
          {error && !loading && (
            <p className="text-sm text-red-600">Ошибка: {error}</p>
          )}
          {!loading && !error && data && (
            <RowDetailsContent
              data={data}
              showPlanLink={showPlanLink}
              onSaved={onSaved}
              contentMode={contentMode}
            />
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}