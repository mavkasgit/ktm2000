import React from "react"
import { CheckCircle2, Loader2 } from "lucide-react"
import type { ProfileLocale, ProfileTheme } from "@user/ui"
import { Button } from "@/shared/ui/Button"

export type AppearanceSectionProps = {
  localeDraft: ProfileLocale
  themeDraft: ProfileTheme
  isSaving: boolean
  isSaved: boolean
  error: string | null
  onLocaleChange: (val: ProfileLocale) => void
  onThemeChange: (val: ProfileTheme) => void
  onSubmit: (e: React.FormEvent) => void
  canSubmit: boolean
  profileSot: string | null
}

export function AppearanceSection({
  localeDraft,
  themeDraft,
  isSaving,
  isSaved,
  error,
  onLocaleChange,
  onThemeChange,
  onSubmit,
  canSubmit,
  profileSot,
}: AppearanceSectionProps) {
  return (
    <div className="space-y-6">
      <form onSubmit={onSubmit} className="space-y-6">
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-muted-foreground" htmlFor="appearance-locale">
              Язык
            </label>
            <select
              id="appearance-locale"
              value={localeDraft}
              onChange={(e) => onLocaleChange(e.target.value as ProfileLocale)}
              disabled={isSaving}
              className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-50"
            >
              <option value="ru">Русский</option>
              <option value="en">English</option>
            </select>
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-muted-foreground" htmlFor="appearance-theme">
              Тема
            </label>
            <select
              id="appearance-theme"
              value={themeDraft}
              onChange={(e) => onThemeChange(e.target.value as ProfileTheme)}
              disabled={isSaving}
              className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-50"
            >
              <option value="system">Системная</option>
              <option value="light">Светлая</option>
              <option value="dark">Тёмная</option>
            </select>
          </div>
        </div>

        <div className="flex items-center gap-3 pt-2">
          <Button
            type="submit"
            disabled={isSaving || !canSubmit}
            className="min-w-[170px]"
          >
            {isSaving ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Сохранение...
              </>
            ) : (
              "Сохранить оформление"
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

      {/* Подсказка (hint) */}
      <div className="text-xs text-muted-foreground pt-4 border-t border-border/50">
        {profileSot === "authentik" ? (
          <em>Общие настройки оформления сохраняются в IdP.</em>
        ) : (
          <em>Общие настройки оформления сохраняются локально для KTM.</em>
        )}
      </div>
    </div>
  )
}
