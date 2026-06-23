import { HardDrive, Database, Users, Wrench } from "lucide-react"
import { useNavigate } from "react-router-dom"
import { Button } from "@/shared/ui/Button"
import { usePermission } from "@/features/auth/hooks/usePermission"

export function SettingsPage() {
  const { canEditSettings } = usePermission()
  const navigate = useNavigate()

  return (
    <>
      <header className="page-header flex items-center justify-between">
        <div>
          <h1 className="page-title flex items-center gap-2">
            <HardDrive className="h-6 w-6" />
            Настройки
          </h1>
          <p className="page-subtitle">Управление бэкапами, пользователями и системными параметрами.</p>
        </div>
        {canEditSettings && (
          <Button variant="outline" onClick={() => navigate("/settings/dev")} className="flex items-center gap-2">
            <Wrench className="h-4 w-4" />
            Панель разработчика
          </Button>
        )}
      </header>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <div className="rounded-lg border bg-card p-6 space-y-4">
          <div className="flex items-center gap-3">
            <div className="rounded-lg bg-primary/10 p-2">
              <Database className="h-5 w-5 text-primary" />
            </div>
            <div>
              <h3 className="font-medium">Бэкапы</h3>
              <p className="text-sm text-muted-foreground">Резервное копирование и восстановление</p>
            </div>
          </div>
          <Button onClick={() => navigate("/settings/backups")} className="w-full">
            Открыть
          </Button>
        </div>

        {canEditSettings && (
          <div className="rounded-lg border bg-card p-6 space-y-4">
            <div className="flex items-center gap-3">
              <div className="rounded-lg bg-indigo-500/10 p-2">
                <Users className="h-5 w-5 text-indigo-500" />
              </div>
              <div>
                <h3 className="font-medium">Пользователи</h3>
                <p className="text-sm text-muted-foreground">Управление учетными записями и ролями</p>
              </div>
            </div>
            <Button onClick={() => navigate("/settings/users")} className="w-full">
              Открыть
            </Button>
          </div>
        )}
      </div>
    </>
  )
}
