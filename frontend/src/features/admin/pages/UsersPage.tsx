import { useEffect, useState } from "react"
import { ExternalLink, Users } from "lucide-react"
import { Card, Button } from "@/shared/ui"
import { fetchOidcConfig } from "@/features/auth/api/oidcAuth"

export function UsersPage() {
  const [adminUrl, setAdminUrl] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchOidcConfig()
      .then((config) => {
        if (config.enabled && config.issuer) {
          try {
            const url = new URL(config.issuer)
            setAdminUrl(`${url.origin}/if/admin/#/identity/users`)
          } catch {
            setAdminUrl(null)
          }
        } else {
          setAdminUrl(null)
        }
      })
      .catch(() => setAdminUrl(null))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="max-w-xl mx-auto mt-16">
      <Card className="p-8 text-center space-y-5">
        <div className="mx-auto w-12 h-12 rounded-full bg-violet-500/10 flex items-center justify-center">
          <Users className="h-6 w-6 text-violet-600" />
        </div>
        <h1 className="text-xl font-bold">Управление пользователями</h1>
        
        {loading ? (
          <p className="text-sm text-muted-foreground">Загрузка...</p>
        ) : adminUrl ? (
          <>
            <p className="text-sm text-muted-foreground">
              Создание, редактирование, блокировка учётных записей и назначение ролей
              выполняется через панель администратора <strong>Authentik</strong>.
            </p>
            <Button asChild>
              <a href={adminUrl} target="_blank" rel="noopener noreferrer">
                <ExternalLink className="h-4 w-4 mr-2" />
                Открыть Authentik
              </a>
            </Button>
          </>
        ) : (
          <p className="text-sm text-amber-600 bg-amber-500/10 rounded-lg p-3">
            Authentik не настроен. Обратитесь к администратору для настройки единого входа.
          </p>
        )}
      </Card>
    </div>
  )
}
