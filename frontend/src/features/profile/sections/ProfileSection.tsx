import React from "react"
import { Copy, CheckCircle2, Loader2 } from "lucide-react"
import type { User } from "@/features/auth/api"
import { ROLE_LABELS } from "../lib/roleLabels"
import { Button } from "@/shared/ui/Button"
import { Input } from "@/shared/ui/Input"

export type ProfileSectionProps = {
  user: User
  fullNameDraft: string
  emailDraft: string
  isSaving: boolean
  isSaved: boolean
  error: string | null
  onFullNameChange: (val: string) => void
  onEmailChange: (val: string) => void
  onSubmit: (e: React.FormEvent) => void
  canSubmit: boolean
  oidcEnabled: boolean
  userSettingsUrl: string | null
}

export function ProfileSection({
  user,
  fullNameDraft,
  emailDraft,
  isSaving,
  isSaved,
  error,
  onFullNameChange,
  onEmailChange,
  onSubmit,
  canSubmit,
  oidcEnabled,
  userSettingsUrl,
}: ProfileSectionProps) {
  const [copied, setCopied] = React.useState(false)

  const handleCopyUsername = () => {
    if (!user.username) return
    navigator.clipboard.writeText(user.username)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const isAuthentikLinked = user.profile_sot === "authentik" || !!user.authentik_linked

  return (
    <div className="space-y-6">
      {/* Системная информация */}
      <div className="space-y-4 rounded-xl border border-border bg-muted/20 p-4">
        <h4 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
          Системная информация
        </h4>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-muted-foreground" htmlFor="profile-username">
              Логин (Username)
            </label>
            <div className="flex gap-2">
              <Input
                id="profile-username"
                value={user.username || ""}
                readOnly
                className="bg-muted/50 cursor-default"
              />
              <Button
                type="button"
                variant="outline"
                size="icon"
                onClick={handleCopyUsername}
                title={copied ? "Скопировано!" : "Копировать логин"}
                className="shrink-0"
              >
                {copied ? (
                  <CheckCircle2 className="h-4 w-4 text-green-500" />
                ) : (
                  <Copy className="h-4 w-4" />
                )}
              </Button>
            </div>
          </div>
          <div className="space-y-1.5 flex flex-col justify-center">
            <span className="text-xs font-semibold text-muted-foreground">Роль MES (локальная)</span>
            <div className="text-sm font-medium mt-1">
              {ROLE_LABELS[user.role] || user.role}
            </div>
          </div>
        </div>

        {oidcEnabled && userSettingsUrl && (
          <div className="pt-2 border-t border-border/50">
            <a
              href={userSettingsUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-primary hover:underline inline-flex items-center gap-1 font-medium"
            >
              Настройки входа в IdP ↗
            </a>
          </div>
        )}
      </div>

      {/* Форма изменения имени и почты */}
      <form onSubmit={onSubmit} className="space-y-4">
        <div className="space-y-1.5">
          <label className="text-xs font-semibold text-muted-foreground" htmlFor="profile-fullname">
            Полное имя
          </label>
          <Input
            id="profile-fullname"
            value={fullNameDraft}
            onChange={(e) => onFullNameChange(e.target.value)}
            placeholder="Введите ваше имя"
            maxLength={255}
            disabled={isSaving}
          />
        </div>

        <div className="space-y-1.5">
          <label className="text-xs font-semibold text-muted-foreground" htmlFor="profile-email">
            Email
          </label>
          <Input
            id="profile-email"
            type="email"
            value={emailDraft}
            onChange={(e) => onEmailChange(e.target.value)}
            placeholder="example@domain.com"
            disabled={isSaving}
          />
        </div>

        <div className="flex items-center gap-3 pt-2">
          <Button
            type="submit"
            disabled={isSaving || !canSubmit}
            className="min-w-[140px]"
          >
            {isSaving ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Сохранение...
              </>
            ) : (
              "Сохранить профиль"
            )}
          </Button>

          {isSaved && (
            <span className="flex items-center gap-1 text-sm text-green-500 font-medium">
              <CheckCircle2 className="h-4 w-4" />
              Сохранено
            </span>
          )}
        </div>

        {error && (
          <p className="text-xs text-destructive mt-1 font-medium">{error}</p>
        )}
      </form>

      {/* Подсказка в самом низу (hint) */}
      <div className="text-xs text-muted-foreground pt-4 border-t border-border/50">
        {isAuthentikLinked ? (
          <em>Единый профиль: имя, email и аватар синхронизируются через IdP (KTM и HRMS).</em>
        ) : (
          <em>Локальный профиль KTM.</em>
        )}
      </div>
    </div>
  )
}
