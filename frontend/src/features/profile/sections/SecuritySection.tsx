import React from "react"
import { Laptop, Loader2, X, AlertTriangle } from "lucide-react"
import { formatDistanceToNow } from "date-fns"
import { ru } from "date-fns/locale"
import type { SessionDto } from "../api/sessionsApi"
import { formatLoginMethod } from "../api/sessionsApi"
import { Button } from "@/shared/ui/Button"
import { Badge } from "@/shared/ui/Badge"

export type SecuritySectionProps = {
  oidcEnabled: boolean
  userSettingsUrl: string | null
  sessions: SessionDto[]
  isLoading: boolean
  error: string | null
  revokingId: string | null
  revokingOthers: boolean
  onRevoke: (id: string) => void
  onRevokeOthers: () => void
}

export function SecuritySection({
  oidcEnabled,
  userSettingsUrl,
  sessions,
  isLoading,
  error,
  revokingId,
  revokingOthers,
  onRevoke,
  onRevokeOthers,
}: SecuritySectionProps) {
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

  const hasOtherSessions = sessions.some((s) => !s.is_current)

  return (
    <div className="space-y-6">
      {/* Единый вход (Authentik) */}
      {oidcEnabled && (
        <div className="rounded-xl border border-border bg-muted/20 p-4 space-y-3">
          <h4 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
            Единый вход (Authentik)
          </h4>
          <p className="text-sm text-foreground">
            Telegram, MFA и способы входа — только в Authentik.
          </p>
          {userSettingsUrl && (
            <div className="pt-1">
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
      )}

      {/* Активные сессии */}
      <div className="space-y-4">
        <div className="flex items-center justify-between gap-2 border-b border-border pb-2">
          <div>
            <h3 className="text-sm font-bold text-foreground">Активные сессии</h3>
            <p className="text-xs text-muted-foreground mt-0.5">
              Список устройств и браузеров, с которых вы вошли в систему
            </p>
          </div>
          {hasOtherSessions && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={revokingOthers || isLoading}
              onClick={onRevokeOthers}
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

        {isLoading && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground py-8 justify-center">
            <Loader2 className="h-4 w-4 animate-spin text-primary" />
            Загрузка сессий...
          </div>
        )}

        {error && (
          <p className="text-sm text-destructive py-2 text-center font-medium">{error}</p>
        )}

        {!isLoading && sessions.length === 0 && !error && (
          <p className="text-sm text-muted-foreground py-4 text-center">
            Нет активных сессий
          </p>
        )}

        {!isLoading && sessions.length > 0 && (
          <div className="space-y-3 max-h-[340px] overflow-y-auto pr-1">
            {sessions.map((session) => {
              const deviceLabel = session.device_label || session.user_agent || "Неизвестное устройство"
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
                      <h4 className="text-sm font-semibold text-foreground truncate" title={deviceLabel}>
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
                      disabled={revokingId === session.id || revokingOthers}
                      onClick={() => onRevoke(session.id)}
                      className="text-xs shrink-0 h-8 px-2.5 hover:bg-destructive hover:text-destructive-foreground hover:border-destructive"
                      title="Завершить сессию"
                    >
                      {revokingId === session.id ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        <X className="h-4 w-4" />
                      )}
                    </Button>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* Подсказка (hint) внизу */}
      <div className="text-xs text-muted-foreground pt-4 border-t border-border/50 flex items-start gap-1.5">
        <AlertTriangle className="h-4 w-4 text-muted-foreground shrink-0 mt-0.5" />
        <span>При подозрении на чужой доступ завершите другие сессии или выйдите из приложения.</span>
      </div>
    </div>
  )
}
