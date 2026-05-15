import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/shared/ui"
import { type RowDetailsData } from "./types"
import { RowDetailsContent } from "./RowDetailsContent"

interface RowDetailsSidePanelProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  data: RowDetailsData | null
  loading?: boolean
  error?: string | null
  title?: string
  description?: string
  showPlanLink?: boolean
}

export function RowDetailsSidePanel({
  open,
  onOpenChange,
  data,
  loading = false,
  error = null,
  title = "Детализация строки",
  description = "Подробная информация о позиции плана",
  showPlanLink,
}: RowDetailsSidePanelProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="!left-auto !right-0 !top-0 !translate-x-0 !translate-y-0 h-screen max-h-screen w-[min(100vw,940px)] max-w-none rounded-none border-l p-0 flex flex-col gap-0">
        <div className="p-6 border-b">
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            <DialogDescription>{description}</DialogDescription>
          </DialogHeader>
        </div>

        <div className="flex-1 overflow-auto p-6">
          {loading && (
            <p className="text-sm text-muted-foreground">Загрузка детализации...</p>
          )}
          {error && !loading && (
            <p className="text-sm text-red-600">Ошибка: {error}</p>
          )}
          {!loading && !error && data && (
            <RowDetailsContent data={data} showPlanLink={showPlanLink} />
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
