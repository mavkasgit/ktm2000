import { useCallback, useEffect, useRef, useState } from "react"
import { Pencil } from "lucide-react"

import {
  Dialog,
  DialogContent,
} from "@/shared/ui/Dialog"
import { UserAvatar, getUserSeed, applyTheme, storeLocale, type ProfileLocale, type ProfileTheme } from "@user/ui"
import { AvatarPickerDialog } from "@/features/profile/AvatarPickerDialog"
import { useRoleLabel } from "@/features/profile/lib/roleLabels"
import { idpUserSettingsUrlFromIssuer } from "@/features/profile/lib/idpUserSettingsUrl"
import { ProfileSection } from "@/features/profile/sections/ProfileSection"
import { AppearanceSection } from "@/features/profile/sections/AppearanceSection"
import { SecuritySection } from "@/features/profile/sections/SecuritySection"
import { fetchOidcConfig } from "@/features/auth/api/oidcAuth"
import {
  updateMyAvatarApi,
  updateMyProfileApi,
  type User,
} from "@/features/auth/api"
import {
  fetchSessions,
  revokeSession,
  revokeOtherSessions,
  type SessionDto,
} from "@/features/profile/api/sessionsApi"

type Props = {
  open: boolean
  onOpenChange: (open: boolean) => void
  currentUser: User
  onUpdated: () => void | Promise<void>
}

const getErrorMessage = (err: unknown, defaultMessage: string): string => {
  if (typeof err === "object" && err !== null) {
    const response = (err as any).response
    if (response && typeof response === "object" && response.data) {
      const detail = response.data.detail
      if (typeof detail === "string") return detail
    }
    if (err instanceof Error) return err.message
    if ("message" in err) {
      return String((err as any).message)
    }
  }
  return defaultMessage
}

export function UserProfileModal({ open, onOpenChange, currentUser, onUpdated }: Props) {
  const [localUser, setLocalUser] = useState(currentUser)
  const roleLabel = useRoleLabel(localUser.role)
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

  const nameTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const prefsTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    return () => {
      if (nameTimerRef.current) clearTimeout(nameTimerRef.current)
      if (prefsTimerRef.current) clearTimeout(prefsTimerRef.current)
    }
  }, [])

  // Вкладки: profile, appearance, security
  const [activeTab, setActiveTab] = useState<"profile" | "appearance" | "security">("profile")
  const [sessions, setSessions] = useState<SessionDto[]>([])
  const [sessionsLoading, setSessionsLoading] = useState(false)
  const [sessionsError, setSessionsError] = useState<string | null>(null)
  const [revokingId, setRevokingId] = useState<string | null>(null)
  const [revokingOthers, setRevokingOthers] = useState(false)

  // OIDC State
  const [oidcEnabled, setOidcEnabled] = useState(false)
  const [userSettingsUrl, setUserSettingsUrl] = useState<string | null>(null)

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

  // Reset tab when modal opens, load OIDC config
  useEffect(() => {
    if (open) {
      setActiveTab("profile")
      fetchOidcConfig()
        .then((cfg) => {
          setOidcEnabled(!!cfg.enabled)
          setUserSettingsUrl(idpUserSettingsUrlFromIssuer(cfg.issuer))
        })
        .catch((err) => {
          console.error("Failed to load OIDC config:", err)
          setOidcEnabled(false)
          setUserSettingsUrl(null)
        })
    }
  }, [open])

  // Revert previewed theme if closed without saving
  useEffect(() => {
    if (!open) {
      const savedTheme = (currentUser.theme as ProfileTheme) || "system"
      if (themeDraft !== savedTheme) {
        applyTheme(savedTheme)
      }
    }
  }, [open, themeDraft, currentUser.theme])

  const loadSessions = useCallback(async () => {
    setSessionsLoading(true)
    setSessionsError(null)
    try {
      const data = await fetchSessions()
      setSessions(data)
    } catch (err) {
      console.error(err)
      setSessionsError("Не удалось загрузить активные сессии")
    } finally {
      setSessionsLoading(false)
    }
  }, [])

  useEffect(() => {
    if (open && activeTab === "security") {
      loadSessions()
    }
  }, [open, activeTab, loadSessions])

  const handleRevokeSession = useCallback(
    async (id: string) => {
      const session = sessions.find((s) => s.id === id)
      const confirmed = window.confirm(
        `Вы действительно хотите завершить сеанс на устройстве "${session?.device_label || "Неизвестное устройство"}"?`
      )
      if (!confirmed) return
      setRevokingId(id)
      try {
        await revokeSession(id)
        await loadSessions()
      } catch (err) {
        console.error(err)
        alert("Не удалось завершить сеанс")
      } finally {
        setRevokingId(null)
      }
    },
    [sessions, loadSessions],
  )

  const handleRevokeOthers = useCallback(async () => {
    const confirmed = window.confirm(
      "Вы действительно хотите завершить все остальные активные сеансы?"
    )
    if (!confirmed) return
    setRevokingOthers(true)
    try {
      await revokeOtherSessions()
      await loadSessions()
    } catch (err) {
      console.error(err)
      alert("Не удалось завершить другие сеансы")
    } finally {
      setRevokingOthers(false)
    }
  }, [loadSessions])

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

  const handleSaveProfile = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault()
      setNameSaving(true)
      setNameError(null)
      setNameSaved(false)
      try {
        const res = await updateMyProfileApi({
          full_name: fullNameDraft.trim(),
          email: emailDraft.trim(),
        })
        setLocalUser((u) => ({
          ...u,
          full_name: res.full_name,
          email: res.email ?? u.email,
          avatar_seed: res.avatar_seed ?? u.avatar_seed,
        }))
        await onUpdated()
        setNameSaved(true)
        if (nameTimerRef.current) clearTimeout(nameTimerRef.current)
        nameTimerRef.current = setTimeout(() => setNameSaved(false), 2000)
      } catch (err: unknown) {
        console.error(err)
        setNameError(getErrorMessage(err, "Не удалось сохранить профиль"))
      } finally {
        setNameSaving(false)
      }
    },
    [fullNameDraft, emailDraft, onUpdated],
  )

  const handleSavePrefs = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault()
      setPrefsSaving(true)
      setPrefsError(null)
      setPrefsSaved(false)
      try {
        const res = await updateMyProfileApi({
          locale: localeDraft,
          theme: themeDraft,
        })
        setLocalUser((u) => ({
          ...u,
          locale: res.locale ?? localeDraft,
          theme: res.theme ?? themeDraft,
        }))
        if (res.theme || themeDraft) applyTheme((res.theme ?? themeDraft) as ProfileTheme)
        if (res.locale || localeDraft) storeLocale((res.locale ?? localeDraft) as ProfileLocale)
        await onUpdated()
        setPrefsSaved(true)
        if (prefsTimerRef.current) clearTimeout(prefsTimerRef.current)
        prefsTimerRef.current = setTimeout(() => setPrefsSaved(false), 2000)
      } catch (err: unknown) {
        console.error(err)
        setPrefsError(getErrorMessage(err, "Не удалось сохранить оформление"))
      } finally {
        setPrefsSaving(false)
      }
    },
    [localeDraft, themeDraft, onUpdated],
  )

  // Live theme preview
  const handleThemeChange = (nextTheme: ProfileTheme) => {
    setThemeDraft(nextTheme)
    applyTheme(nextTheme)
    setPrefsError(null)
    setPrefsSaved(false)
  }

  const handleOpenChange = (isOpen: boolean) => {
    if (!isOpen) {
      const savedTheme = (currentUser.theme as ProfileTheme) || "system"
      if (themeDraft !== savedTheme) {
        applyTheme(savedTheme)
      }
    }
    onOpenChange(isOpen)
  }

  return (
    <>
      <Dialog open={open} onOpenChange={handleOpenChange}>
        <DialogContent className="max-w-3xl w-[min(100vw-1.5rem,48rem)] h-[min(90vh,560px)] p-0 overflow-hidden flex flex-col md:flex-row rounded-2xl">
          {/* Sidebar - Desktop */}
          <aside className="hidden md:flex md:w-[240px] border-r border-border/50 bg-muted/20 p-6 flex-col gap-6 shrink-0">
            {/* User Avatar + Profile Info */}
            <div className="flex flex-col items-center text-center gap-3">
              <button
                type="button"
                className="relative group rounded-full focus:outline-none focus:ring-2 focus:ring-primary shrink-0"
                onClick={() => setAvatarOpen(true)}
                title="Сменить аватар"
              >
                <UserAvatar seed={seed} size={80} />
                <span className="absolute inset-0 flex items-center justify-center rounded-full bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity">
                  <Pencil className="h-5 w-5 text-white" />
                </span>
              </button>
              <div className="min-w-0 w-full">
                <div className="font-semibold truncate text-foreground text-sm">
                  {localUser.full_name}
                </div>
                <div className="text-[11px] text-muted-foreground truncate">
                  @{localUser.username}
                </div>
              </div>
            </div>

            {/* Navigation Menu */}
            <nav className="flex flex-col gap-1 flex-1">
              <button
                type="button"
                onClick={() => setActiveTab("profile")}
                className={`flex items-center px-3 py-2 text-sm font-medium rounded-lg transition-colors text-left ${
                  activeTab === "profile"
                    ? "bg-accent text-accent-foreground font-semibold"
                    : "text-muted-foreground hover:bg-muted/50 hover:text-foreground"
                }`}
              >
                Профиль
              </button>
              <button
                type="button"
                onClick={() => setActiveTab("appearance")}
                className={`flex items-center px-3 py-2 text-sm font-medium rounded-lg transition-colors text-left ${
                  activeTab === "appearance"
                    ? "bg-accent text-accent-foreground font-semibold"
                    : "text-muted-foreground hover:bg-muted/50 hover:text-foreground"
                }`}
              >
                Оформление
              </button>
              <button
                type="button"
                onClick={() => setActiveTab("security")}
                className={`flex items-center px-3 py-2 text-sm font-medium rounded-lg transition-colors text-left ${
                  activeTab === "security"
                    ? "bg-accent text-accent-foreground font-semibold"
                    : "text-muted-foreground hover:bg-muted/50 hover:text-foreground"
                }`}
              >
                Безопасность
              </button>
            </nav>

            {/* Bottom Panel */}
            <div className="mt-auto pt-4 border-t border-border/50 text-[11px] text-muted-foreground space-y-1">
              <div className="truncate">
                MES: <span className="font-medium text-foreground">{roleLabel || localUser.role}</span>
              </div>
              <div className="truncate">Юзернейм: @{localUser.username}</div>
            </div>
          </aside>

          {/* Header/Tabs - Mobile */}
          <header className="flex md:hidden flex-col border-b border-border p-4 gap-3 bg-muted/10 shrink-0">
            <div className="flex items-center gap-3">
              <button
                type="button"
                className="relative group rounded-full focus:outline-none focus:ring-2 focus:ring-primary shrink-0"
                onClick={() => setAvatarOpen(true)}
                title="Сменить аватар"
              >
                <UserAvatar seed={seed} size={48} />
                <span className="absolute inset-0 flex items-center justify-center rounded-full bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity">
                  <Pencil className="h-3 w-3 text-white" />
                </span>
              </button>
              <div className="min-w-0">
                <div className="font-semibold truncate text-sm text-foreground">
                  {localUser.full_name}
                </div>
                <div className="text-[11px] text-muted-foreground truncate">
                  @{localUser.username} · {roleLabel || localUser.role}
                </div>
              </div>
            </div>

            <div className="flex gap-1 overflow-x-auto pb-1 border-t border-border/50 pt-2 scrollbar-none">
              <button
                type="button"
                onClick={() => setActiveTab("profile")}
                className={`px-3 py-1.5 text-xs font-semibold rounded-full whitespace-nowrap transition-colors ${
                  activeTab === "profile"
                    ? "bg-primary text-primary-foreground"
                    : "bg-muted text-muted-foreground hover:text-foreground"
                }`}
              >
                Профиль
              </button>
              <button
                type="button"
                onClick={() => setActiveTab("appearance")}
                className={`px-3 py-1.5 text-xs font-semibold rounded-full whitespace-nowrap transition-colors ${
                  activeTab === "appearance"
                    ? "bg-primary text-primary-foreground"
                    : "bg-muted text-muted-foreground hover:text-foreground"
                }`}
              >
                Оформление
              </button>
              <button
                type="button"
                onClick={() => setActiveTab("security")}
                className={`px-3 py-1.5 text-xs font-semibold rounded-full whitespace-nowrap transition-colors ${
                  activeTab === "security"
                    ? "bg-primary text-primary-foreground"
                    : "bg-muted text-muted-foreground hover:text-foreground"
                }`}
              >
                Безопасность
              </button>
            </div>
          </header>

          {/* Content Pane */}
          <main className="flex-1 overflow-y-auto p-6 md:p-8 flex flex-col min-w-0">
            <h2 className="text-xl font-bold tracking-tight mb-6 text-foreground">
              {activeTab === "profile" && "Настройки профиля"}
              {activeTab === "appearance" && "Оформление"}
              {activeTab === "security" && "Безопасность"}
            </h2>

            <div className="flex-1 min-w-0">
              {activeTab === "profile" && (
                <ProfileSection
                  user={localUser}
                  fullNameDraft={fullNameDraft}
                  emailDraft={emailDraft}
                  isSaving={nameSaving}
                  isSaved={nameSaved}
                  error={nameError}
                  onFullNameChange={(val) => {
                    setFullNameDraft(val)
                    setNameError(null)
                    setNameSaved(false)
                  }}
                  onEmailChange={(val) => {
                    setEmailDraft(val)
                    setNameError(null)
                    setNameSaved(false)
                  }}
                  onSubmit={handleSaveProfile}
                  canSubmit={
                    fullNameDraft.trim() !== (localUser.full_name || "").trim() ||
                    emailDraft.trim() !== (localUser.email || "").trim()
                  }
                  oidcEnabled={oidcEnabled}
                  userSettingsUrl={userSettingsUrl}
                />
              )}

              {activeTab === "appearance" && (
                <AppearanceSection
                  localeDraft={localeDraft}
                  themeDraft={themeDraft}
                  isSaving={prefsSaving}
                  isSaved={prefsSaved}
                  error={prefsError}
                  onLocaleChange={(val) => {
                    setLocaleDraft(val)
                    setPrefsError(null)
                    setPrefsSaved(false)
                  }}
                  onThemeChange={handleThemeChange}
                  onSubmit={handleSavePrefs}
                  canSubmit={
                    localeDraft !== (localUser.locale || "ru") ||
                    themeDraft !== (localUser.theme || "system")
                  }
                  profileSot={localUser.profile_sot ?? null}
                />
              )}

              {activeTab === "security" && (
                <SecuritySection
                  oidcEnabled={oidcEnabled}
                  userSettingsUrl={userSettingsUrl}
                  sessions={sessions}
                  isLoading={sessionsLoading}
                  error={sessionsError}
                  revokingId={revokingId}
                  revokingOthers={revokingOthers}
                  onRevoke={handleRevokeSession}
                  onRevokeOthers={handleRevokeOthers}
                />
              )}
            </div>
          </main>
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
