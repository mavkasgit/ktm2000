import { useCallback, useEffect, useState } from "react"
import { CheckCircle2, Loader2, Pencil, Laptop } from "lucide-react"
import { formatDistanceToNow } from "date-fns"
import { ru } from "date-fns/locale"

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/shared/ui/Dialog"
import { Button } from "@/shared/ui/Button"
import { Input } from "@/shared/ui/Input"
import { UserAvatar } from "@/shared/ui/UserAvatar"
import { Badge } from "@/shared/ui/Badge"
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
import {
  fetchSessions,
  revokeSession,
  revokeOtherSessions,
  formatLoginMethod,
  type SessionDto,
} from "@/features/profile/api/sessionsApi"

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

  // Вкладки: Профиль или Сессии
  const [activeTab, setActiveTab] = useState<"profile" | "sessions">("profile")
  const [sessions, setSessions] = useState<SessionDto[]>([])
  const [sessionsLoading, setSessionsLoading] = useState(false)
  const [sessionsError, setSessionsError] = useState<string | null>(null)
  const [revokingId, setRevokingId] = useState<string | null>(null)
  const [revokingOthers, setRevokingOthers] = useState(false)

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

  // Сбрасываем вкладку при открытии модалки
  useEffect(() => {
    if (open) {
      setActiveTab("profile")
    }
  }, [open])

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
    if (open && activeTab === "sessions") {
      loadSessions()
    }
  }, [open, activeTab, loadSessions])

  const handleRevokeSession = useCallback(
    async (session: SessionDto) => {
      const confirmed = window.confirm(
        `Вы действительно хотите завершить сеанс на устройстве "${session.device_label || "Неизвестное устройство"}"?`
      )
      if (!confirmed) return
      setRevokingId(session.id)
      try {
        await revokeSession(session.id)
        await loadSessions()
      } catch (err) {
        console.error(err)
        alert("Не удалось завершить сеанс")
      } finally {
        setRevokingId(null)
      }
    },
    [loadSessions],
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

  const formatDateTime = (dateStr: string) => {
    try {
      const d = new Date(dateStr)
      return d.toLocaleString("ru-RU", {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      })
    } catch {
      return dateStr
    }
  }

  const formatLastSeen = (dateStr: string) => {
    try {
      return formatDistanceToNow(new Date(dateStr), {
        addSuffix: true,
        locale: ru,
      })
    } catch {
      return formatDateTime(dateStr)
    }
  }

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Настройки профиля</DialogTitle>
          </DialogHeader>

          {/* Вкладки навигации */}
          <div className="flex border-b border-border -mt-2 mb-4">
            <button
              type="button"
              className={`px-4 py-2 text-sm font-semibold border-b-2 transition-colors -mb-[1px] ${
                activeTab === "profile"
                  ? "border-primary text-primary"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
              onClick={() => setActiveTab("profile")}
            >
              Профиль
            </button>
            <button
              type="button"
              className={`px-4 py-2 text-sm font-semibold border-b-2 transition-colors -mb-[1px] ${
                activeTab === "sessions"
                  ? "border-primary text-primary"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
              onClick={() => setActiveTab("sessions")}
            >
              Сессии
            </button>
          </div>

          <div className="flex flex-col gap-6">
            {activeTab === "profile" ? (
              <>
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
              </>
            ) : (
              <div className="space-y-6">
                <div className="flex items-center justify-between gap-2 border-b border-border pb-2">
                  <div>
                    <h3 className="text-sm font-bold text-foreground">Активные сессии</h3>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      Список устройств и браузеров, с которых вы вошли в систему
                    </p>
                  </div>
                  {sessions.some((s) => !s.is_current) && (
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      disabled={revokingOthers || sessionsLoading}
                      onClick={handleRevokeOthers}
                      className="text-xs h-8 px-3"
                    >
                      {revokingOthers ? (
                        <>
                          <Loader2 className="h-3 w-3 animate-spin mr-1.5" />
                          Завершение...
                        </>
                      ) : (
                        "Завершить другие"
                      )}
                    </Button>
                  )}
                </div>

                {sessionsLoading && (
                  <div className="flex items-center gap-2 text-xs text-muted-foreground py-4 justify-center">
                    <Loader2 className="h-4 w-4 animate-spin text-primary" />
                    Загрузка сессий...
                  </div>
                )}

                {sessionsError && (
                  <p className="text-sm text-destructive py-2 text-center">{sessionsError}</p>
                )}

                {!sessionsLoading && sessions.length === 0 && !sessionsError && (
                  <p className="text-sm text-muted-foreground py-4 text-center">
                    Нет активных сессий
                  </p>
                )}

                {!sessionsLoading && sessions.length > 0 && (
                  <div className="space-y-3 max-h-[300px] overflow-y-auto pr-1">
                    {sessions.map((session) => {
                      const deviceLabel = session.device_label || "Неизвестное устройство"
                      const ipLabel = session.ip_address || "IP неизвестен"
                      return (
                        <div
                          key={session.id}
                          className="p-3.5 rounded-xl border border-border bg-card flex items-start gap-4 transition-colors hover:bg-muted/10"
                        >
                          <div
                            className={`w-9 h-9 rounded-lg flex items-center justify-center shrink-0 ${
                              session.is_current
                                ? "bg-green-500/10 text-green-500"
                                : "bg-muted text-muted-foreground"
                            }`}
                          >
                            <Laptop className="h-5 w-5" />
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 flex-wrap">
                              <h4 className="text-sm font-semibold text-foreground truncate">
                                {deviceLabel}
                              </h4>
                              {session.is_current && (
                                <Badge variant="success" className="text-[10px] py-0 px-2">
                                  Текущий сеанс
                                </Badge>
                              )}
                            </div>
                            <p className="text-xs text-muted-foreground mt-1">
                              IP: <span className="font-mono text-[11px]">{ipLabel}</span>
                              {" · "}
                              {formatLoginMethod(session.login_method)}
                            </p>
                            <p className="text-[11px] text-muted-foreground/80 mt-0.5">
                              Активность: {formatLastSeen(session.last_seen_at)}
                              {" · "}
                              Вход: {formatDateTime(session.created_at)}
                            </p>
                          </div>
                          {!session.is_current && (
                            <Button
                              type="button"
                              variant="outline"
                              size="sm"
                              disabled={revokingId === session.id}
                              onClick={() => handleRevokeSession(session)}
                              className="text-xs shrink-0 h-8 px-2.5"
                            >
                              {revokingId === session.id ? (
                                <Loader2 className="h-3 w-3 animate-spin" />
                              ) : (
                                "Завершить"
                              )}
                            </Button>
                          )}
                        </div>
                      )
                    })}
                  </div>
                )}
                <div className="text-xs text-muted-foreground bg-muted/20 p-3 rounded-lg border border-border/50">
                  Примечание: при подозрении на несанкционированный доступ завершите чужие сессии выше.
                </div>
              </div>
            )}
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
