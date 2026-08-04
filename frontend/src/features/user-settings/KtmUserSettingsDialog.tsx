import { useMemo } from "react"
import { applyTheme, storeLocale } from "@user/ui"
import { toast } from "@/shared/ui"
import {
  UserSettingsDialog,
  type UserSettingsCallbacks,
  type UserProfile,
} from "@/modules/user-settings"
import { ktmUserSettingsApi } from "./ktmUserSettingsApi"

type KtmUserSettingsDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Колбэк хоста: профиль обновился → перечитать currentUser. */
  onProfileUpdated?: () => void
  /** Колбэк хоста: текущая сессия отозвана → разлогинить. */
  onLogoutRequest?: () => void
}

/**
 * KTM-обвязка переносимого модуля user-settings:
 * axios-адаптер + тосты + применение темы/языка + logout.
 */
export function KtmUserSettingsDialog({
  open,
  onOpenChange,
  onProfileUpdated,
  onLogoutRequest,
}: KtmUserSettingsDialogProps) {
  const callbacks = useMemo<UserSettingsCallbacks>(
    () => ({
      onProfileUpdated: (_profile: UserProfile) => onProfileUpdated?.(),
      onThemeChange: applyTheme,
      onLocaleChange: storeLocale,
      onLogoutRequest,
      notify: (t) =>
        toast({
          variant: t.variant ?? "default",
          title: t.title,
          description: t.description,
        }),
    }),
    [onProfileUpdated, onLogoutRequest],
  )

  return (
    <UserSettingsDialog
      open={open}
      onOpenChange={onOpenChange}
      api={ktmUserSettingsApi}
      callbacks={callbacks}
    />
  )
}
