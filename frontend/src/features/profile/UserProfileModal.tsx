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
import {
  applyTheme,
  storeLocale,
  type ProfileLocale,
  type ProfileTheme,
} from "@/shared/lib/profile-prefs"
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
  const [emailDraft, setEmailDraft] = useState(currentUser.email || "")
  const [localeDraft, setLocaleDraft] = useState<ProfileLocale>(
    (currentUser.locale as ProfileLocale) || "ru",
  )
  const [themeDraft, setThemeDraft] = useState<ProfileTheme>(
    (currentUser.theme as ProfileTheme) || "system",
  )
  const [nameSaving, setNameSaving] = useState(false)
  const [nameError, setNameError] = useState<string | null>(null)
  const [nameSaved, setNameSaved] = useState(false)
  const [prefsSaving, setPrefsSaving] = useState(false)
  const [prefsError, setPrefsError] = useState<string | null>(null)
  const [prefsSaved, setPrefsSaved] = useState(false)
  const [avatarOpen, setAvatarOpen] = useState(false)
  const [avatarSaving, setAvatarSaving] = useState(false)
  const [avatarError, setAvatarError] = useState<string | null>(null)

  useEffect(() => {
    if (currentUser) {
      setLocalUser(currentUser)
      setFullNameDraft(currentUser.full_name || "")
      setEmailDraft(currentUser.email || "")
      setLocaleDraft((currentUser.locale as ProfileLocale) || "ru")
      setThemeDraft((currentUser.theme as ProfileTheme) || "system")
      if (currentUser.theme) applyTheme(currentUser.theme)
      if (currentUser.locale) storeLocale(currentUser.locale)
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
        setLocalUser((u) => ({
          ...u,
          avatar_seed: res.avatar_seed,
          full_name: res.full_name,
          email: res.email ?? u.email,
          locale: res.locale ?? u.locale,
          theme: res.theme ?? u.theme,
        }))
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
        setLocalUser((u) => ({
          ...u,
          full_name: res.full_name,
          avatar_seed: res.avatar_seed,
          email: res.email ?? u.email,
          locale: res.locale ?? u.locale,
          theme: res.theme ?? u.theme,
        }))
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

  const handleSavePrefs = useCallback(
    async (e?: React.FormEvent) => {
      e?.preventDefault()
      if (prefsSaving) return
      const payload: {
        email?: string
        locale?: ProfileLocale
        theme?: ProfileTheme
      } = {}
      const nextEmail = emailDraft.trim()
      if (nextEmail && nextEmail !== (localUser.email || "").trim()) {
        payload.email = nextEmail
      }
      if (localeDraft !== (localUser.locale || "ru")) {
        payload.locale = localeDraft
      }
      if (themeDraft !== (localUser.theme || "system")) {
        payload.theme = themeDraft
      }
      if (Object.keys(payload).length === 0) return
      setPrefsSaving(true)
      setPrefsError(null)
      setPrefsSaved(false)
      try {
        const res = await updateMyProfileApi(payload)
        setLocalUser((u) => ({
          ...u,
          email: res.email ?? payload.email ?? u.email,
          locale: res.locale ?? payload.locale ?? u.locale,
          theme: res.theme ?? payload.theme ?? u.theme,
          full_name: res.full_name ?? u.full_name,
          avatar_seed: res.avatar_seed ?? u.avatar_seed,
        }))
        if (res.theme || payload.theme) applyTheme(res.theme ?? payload.theme)
        if (res.locale || payload.locale) storeLocale(res.locale ?? payload.locale)
        await onUpdated()
        setPrefsSaved(true)
        window.setTimeout(() => setPrefsSaved(false), 2000)
      } catch (err: unknown) {
        console.error(err)
        const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail
        setPrefsError(
          typeof detail === "string"
            ? detail
            : "Не удалось сохранить. Проверьте email.",
        )
      } finally {
        setPrefsSaving(false)
      }
    },
    [
      prefsSaving,
      emailDraft,
      localeDraft,
      themeDraft,
      localUser.email,
      localUser.locale,
      localUser.theme,
      onUpdated,
    ],
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
            </form>

            <form onSubmit={handleSavePrefs} className="space-y-3">
              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-muted-foreground" htmlFor="ktm-email">
                  Email
                </label>
                <Input
                  id="ktm-email"
                  type="email"
                  value={emailDraft}
                  onChange={(e) => {
                    setEmailDraft(e.target.value)
                    setPrefsError(null)
                    setPrefsSaved(false)
                  }}
                />
              </div>

              <h4 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
                Оформление
              </h4>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <label className="text-xs font-semibold text-muted-foreground" htmlFor="ktm-locale">
                    Язык
                  </label>
                  <select
                    id="ktm-locale"
                    value={localeDraft}
                    onChange={(e) => {
                      setLocaleDraft(e.target.value as ProfileLocale)
                      setPrefsError(null)
                      setPrefsSaved(false)
                    }}
                    className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  >
                    <option value="ru">Русский</option>
                    <option value="en">English</option>
                  </select>
                </div>
                <div className="space-y-1.5">
                  <label className="text-xs font-semibold text-muted-foreground" htmlFor="ktm-theme">
                    Тема
                  </label>
                  <select
                    id="ktm-theme"
                    value={themeDraft}
                    onChange={(e) => {
                      setThemeDraft(e.target.value as ProfileTheme)
                      setPrefsError(null)
                      setPrefsSaved(false)
                    }}
                    className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  >
                    <option value="system">Системная</option>
                    <option value="light">Светлая</option>
                    <option value="dark">Тёмная</option>
                  </select>
                </div>
              </div>
              <Button type="submit" size="sm" disabled={prefsSaving}>
                {prefsSaving ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : prefsSaved ? (
                  <>
                    <CheckCircle2 className="h-4 w-4 mr-1" />
                    Ок
                  </>
                ) : (
                  "Сохранить email / оформление"
                )}
              </Button>
              {prefsError && <p className="text-xs text-destructive">{prefsError}</p>}
              <p className="text-[11px] text-muted-foreground">
                Общие настройки — сохраняются в IdP (KTM и HRMS).
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
