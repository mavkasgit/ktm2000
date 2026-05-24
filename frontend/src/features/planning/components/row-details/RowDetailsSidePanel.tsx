import { Dialog, DialogContent } from "@/shared/ui"
import { type RowDetailsData } from "./types"
import { RowDetailsContent } from "./RowDetailsContent"

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
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="!left-auto !right-0 !top-0 !translate-x-0 !translate-y-0 h-screen max-h-screen w-[min(100vw,940px)] max-w-none rounded-none border-l p-0 flex flex-col gap-0">
        <div className="flex-1 overflow-auto p-6">
          {loading && (
            <p className="text-sm text-muted-foreground">Загрузка детализации...</p>
          )}
          {error && !loading && (
            <p className="text-sm text-red-600">Ошибка: {error}</p>
          )}
          {!loading && !error && data && (
            <RowDetailsContent data={data} showPlanLink={showPlanLink} onSaved={onSaved} />
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
