import { useMemo, useState } from "react"
import { Shuffle } from "lucide-react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/shared/ui/Dialog"
import { Button } from "@/shared/ui/Button"
import { UserAvatar, generateRandomSeed } from "@user/ui"

type AvatarPickerDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  currentSeed: string | null
  onPick: (seed: string | null) => void | Promise<void>
  isSaving?: boolean
}

const PREVIEW_COUNT = 12

function usePreviewSeeds(open: boolean, currentSeed: string | null, batch: number): string[] {
  return useMemo(() => {
    if (!open) return []
    const out = new Set<string>()
    while (out.size < PREVIEW_COUNT) {
      const s = generateRandomSeed()
      if (s !== currentSeed) out.add(s)
    }
    return Array.from(out)
  }, [open, currentSeed, batch])
}

export function AvatarPickerDialog({
  open,
  onOpenChange,
  currentSeed,
  onPick,
  isSaving,
}: AvatarPickerDialogProps) {
  const [batch, setBatch] = useState(0)
  const previews = usePreviewSeeds(open, currentSeed, batch)

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Выберите аватар</DialogTitle>
          <DialogDescription>
            Клик сохраняет аватар в единый профиль.
          </DialogDescription>
        </DialogHeader>
        <div className="grid grid-cols-4 gap-3 py-2">
          {previews.map((seed) => (
            <button
              key={seed}
              type="button"
              disabled={isSaving}
              onClick={() => onPick(seed)}
              className="aspect-square overflow-hidden rounded-2xl bg-muted border border-border/40 hover:ring-2 hover:ring-primary transition-all disabled:opacity-50"
            >
              <UserAvatar seed={seed} size={72} fit="contain" className="!w-full !h-full !rounded-none" />
            </button>
          ))}
        </div>
        <div className="flex justify-between gap-2 pt-1">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={isSaving}
            onClick={() => setBatch((b) => b + 1)}
            className="gap-1.5"
          >
            <Shuffle className="h-3.5 w-3.5" />
            Другие варианты
          </Button>
          <div className="flex gap-2">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={isSaving || !currentSeed}
              onClick={() => onPick(null)}
            >
              Сбросить
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={isSaving}
              onClick={() => onOpenChange(false)}
            >
              Отмена
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
