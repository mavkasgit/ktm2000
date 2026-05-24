import { HardDrive, Database, Trash2 } from "lucide-react"
import { useNavigate } from "react-router-dom"
import { useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { Button } from "@/shared/ui/Button"
import { AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogTitle, AlertDialogDescription, AlertDialogFooter, AlertDialogAction, AlertDialogCancel } from "@/shared/ui"
import { toast } from "@/shared/ui"
import { resetAllPlans } from "@/shared/api/productionPlans"

export function SettingsPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [resetting, setResetting] = useState(false)

  const handleReset = async () => {
    setConfirmOpen(false)
    setResetting(true)
    try {
      await resetAllPlans()
      queryClient.invalidateQueries()
      toast({ title: "Планы очищены", variant: "success" })
      navigate("/planning")
    } catch (e) {
      toast({ title: "Ошибка", description: e instanceof Error ? e.message : "Не удалось очистить планы", variant: "destructive" })
    } finally {
      setResetting(false)
    }
  }

  return (
    <>
      <header className="page-header">
        <div>
          <h1 className="page-title flex items-center gap-2">
            <HardDrive className="h-6 w-6" />
            Настройки
          </h1>
          <p className="page-subtitle">Управление бэкапами и системными параметрами.</p>
        </div>
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

        <div className="rounded-lg border bg-card p-6 space-y-4">
          <div className="flex items-center gap-3">
            <div className="rounded-lg bg-red-500/10 p-2">
              <Trash2 className="h-5 w-5 text-red-500" />
            </div>
            <div>
              <h3 className="font-medium">Планы</h3>
              <p className="text-sm text-muted-foreground">Очистка всех производственных планов</p>
            </div>
          </div>
          <Button variant="destructive" onClick={() => setConfirmOpen(true)} disabled={resetting} className="w-full">
            {resetting ? "Очистка..." : "Очистить все планы"}
          </Button>
        </div>
      </div>

      <AlertDialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Очистить все планы?</AlertDialogTitle>
            <AlertDialogDescription>
              Все производственные планы, импорты, позиции, задачи и связанные данные будут удалены.
              Справочники (продукты, маршруты, участки) останутся без изменений.
              Это действие нельзя отменить.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Отмена</AlertDialogCancel>
            <AlertDialogAction onClick={handleReset}>Очистить</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
