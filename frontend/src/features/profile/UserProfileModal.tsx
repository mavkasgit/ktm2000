import { useCallback, useEffect, useState } from "react"
import { CheckCircle2, Loader2, Pencil } from "lucide-react"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/shared/ui/Dialog"
import { Button } from "@/shared/ui/Button"
import { Input } from "@/shared/ui/Input"
import { UserAvatar } from "@/shared/ui/UserAvatar"
import { getUserSeed } from "@/shared/lib/avatar"
import { AvatarPickerDialog } from "@/features/profile/AvatarPickerDialog"
import {
  updateMyAvatarApi,
  updateMyProfileApi,
  type User,
} from "@/features/auth/api"

type Props = {
  open: boolean
  onOpenChange: (open: boolean) => void
  currentUser: User
  onUpdated: () => void | Promise<void>
}

export function UserProfileModal({ open, onOpenChange, currentUser, onUpdated }: Props) {
  const [localUser, setLocalUser] = useState(currentUser)
  const [fullNameDraft, setFullNameDraft] = useState(currentUser.full_name || "")
  const [nameSaving, setNameSaving] = useState(false)
  const [nameError, setNameError] = useState<string | null>(null)
  const [nameSaved, setNameSaved] = useState(false)
  const [avatarOpen, setAvatarOpen] = useState(false)
  const [avatarSaving, setAvatarSaving] = useState(false)
  const [avatarError, setAvatarError] = useState<string | null>(null)

  useEffect(() => {
    if (currentUser) {
      setLocalUser(currentUser)
      setFullNameDraft(currentUser.full_name || "")
    }
  }, [currentUser])

  const seed = getUserSeed(localUser)

  const handleAvatarPick = useCallback(
    async (next: string | null) => {
      if (avatarSaving) return
      setAvatarSaving(true)
      setAvatarError(null)
      try {
        const res = await updateMyAvatarApi(next)
        setLocalUser((u) => ({ ...u, avatar_seed: res.avatar_seed, full_name: res.full_name }))
        await onUpdated()
        setAvatarOpen(false)
      } catch (e) {
        console.error(e)
        setAvatarError("Не удалось сохранить аватар")
      } finally {
        setAvatarSaving(false)
      }
    },
    [avatarSaving, onUpdated],
  )

  const handleSaveName = useCallback(
    async (e?: React.FormEvent) => {
      e?.preventDefault()
      const next = fullNameDraft.trim()
      if (!next || nameSaving) return
      if (next === (localUser.full_name || "").trim()) return
      setNameSaving(true)
      setNameError(null)
      setNameSaved(false)
      try {
        const res = await updateMyProfileApi({ full_name: next })
        setLocalUser((u) => ({ ...u, full_name: res.full_name, avatar_seed: res.avatar_seed }))
        await onUpdated()
        setNameSaved(true)
        window.setTimeout(() => setNameSaved(false), 2000)
      } catch (err) {
        console.error(err)
        setNameError("Не удалось сохранить имя")
      } finally {
        setNameSaving(false)
      }
    },
    [fullNameDraft, nameSaving, localUser.full_name, onUpdated],
  )

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Настройки профиля</DialogTitle>
          </DialogHeader>

          <div className="flex flex-col gap-6">
            <div className="flex items-center gap-4">
              <button
                type="button"
                className="relative group rounded-full focus:outline-none focus:ring-2 focus:ring-primary"
                onClick={() => setAvatarOpen(true)}
                title="Сменить аватар"
              >
                <UserAvatar seed={seed} size={72} />
                <span className="absolute inset-0 flex items-center justify-center rounded-full bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity">
                  <Pencil className="h-4 w-4 text-white" />
                </span>
              </button>
              <div className="min-w-0">
                <div className="font-semibold truncate">{localUser.full_name}</div>
                <div className="text-xs text-muted-foreground truncate">@{localUser.username}</div>
                {localUser.profile_sot === "authentik" && (
                  <div className="text-[11px] text-muted-foreground mt-1">
                    Единый профиль (Authentik)
                  </div>
                )}
              </div>
            </div>
            {avatarError && <p className="text-xs text-destructive">{avatarError}</p>}

            <form onSubmit={handleSaveName} className="space-y-2">
              <label className="text-xs font-semibold text-muted-foreground" htmlFor="ktm-full-name">
                Полное имя
              </label>
              <div className="flex gap-2">
                <Input
                  id="ktm-full-name"
                  value={fullNameDraft}
                  onChange={(e) => {
                    setFullNameDraft(e.target.value)
                    setNameError(null)
                    setNameSaved(false)
                  }}
                  maxLength={255}
                />
                <Button
                  type="submit"
                  size="sm"
                  disabled={
                    nameSaving ||
                    !fullNameDraft.trim() ||
                    fullNameDraft.trim() === (localUser.full_name || "").trim()
                  }
                >
                  {nameSaving ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : nameSaved ? (
                    <>
                      <CheckCircle2 className="h-4 w-4 mr-1" />
                      Ок
                    </>
                  ) : (
                    "Сохранить"
                  )}
                </Button>
              </div>
              {nameError && <p className="text-xs text-destructive">{nameError}</p>}
              <p className="text-[11px] text-muted-foreground">
                Имя и аватар общие для KTM и HRMS — правка здесь обновляет IdP.
              </p>
            </form>
          </div>
        </DialogContent>
      </Dialog>

      <AvatarPickerDialog
        open={avatarOpen}
        onOpenChange={setAvatarOpen}
        currentSeed={seed}
        onPick={handleAvatarPick}
        isSaving={avatarSaving}
      />
    </>
  )
}
