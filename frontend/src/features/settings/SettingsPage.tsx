import { HardDrive, Database, Trash2, Download, Check, X, Loader2 } from "lucide-react"
import { useNavigate } from "react-router-dom"
import { useState } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Button } from "@/shared/ui/Button"
import { AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogTitle, AlertDialogDescription, AlertDialogFooter, AlertDialogAction, AlertDialogCancel } from "@/shared/ui"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/shared/ui/Dialog"
import { toast } from "@/shared/ui"
import { resetAllPlans } from "@/shared/api/productionPlans"
import { seedRoutes, listRoutes, listRouteRuleProfiles, listRouteSelectionRules } from "@/shared/api/routes"
import { listImportTemplates } from "@/shared/api/importTemplates"

function useCurrentData() {
  const routes = useQuery({ queryKey: ["routes"], queryFn: () => listRoutes() })
  const profiles = useQuery({ queryKey: ["route-rule-profiles"], queryFn: () => listRouteRuleProfiles() })
  const selectionRules = useQuery({ queryKey: ["route-selection-rules"], queryFn: () => listRouteSelectionRules() })
  const templates = useQuery({ queryKey: ["import-templates"], queryFn: () => listImportTemplates() })
  return { routes, profiles, selectionRules, templates }
}

const SEED_DATA = {
  import_templates: 1,
  route_rule_profiles: 1,
  routes: 12,
  selection_rules: 9,
}

function SeedDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const { routes, profiles, selectionRules, templates } = useCurrentData()
  const [seeding, setSeeding] = useState(false)
  const queryClient = useQueryClient()

  const loading = routes.isLoading || profiles.isLoading || selectionRules.isLoading || templates.isLoading

  const currentRoutes = routes.data?.length ?? 0
  const currentProfiles = profiles.data?.length ?? 0
  const currentRules = selectionRules.data?.length ?? 0
  const currentTemplates = templates.data?.length ?? 0

  const handleSeed = async () => {
    setSeeding(true)
    try {
      const summary = await seedRoutes()
      queryClient.invalidateQueries()
      toast({
        title: "Справочники загружены",
        description:
          `Шаблонов: ${summary.import_templates}, ` +
          `Профилей: ${summary.route_rule_profiles}, ` +
          `Маршрутов: ${summary.routes}, ` +
          `Правил: ${summary.selection_rules}`,
        variant: "success",
      })
      onOpenChange(false)
    } catch (e) {
      toast({ variant: "destructive", title: "Ошибка", description: e instanceof Error ? e.message : "Не удалось загрузить справочники" })
    } finally {
      setSeeding(false)
    }
  }

  const hasData = currentRoutes > 0 || currentProfiles > 0 || currentRules > 0 || currentTemplates > 0

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Загрузка справочников</DialogTitle>
          <DialogDescription>
            Сравнение текущих данных с типовыми. Сеed обновит или создаст недостающие записи.
          </DialogDescription>
        </DialogHeader>

        {loading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            <span className="ml-2 text-sm text-muted-foreground">Загрузка данных...</span>
          </div>
        ) : (
          <div className="space-y-4">
            {/* Table header */}
            <div className="grid grid-cols-3 gap-4 text-sm font-medium text-muted-foreground border-b pb-2">
              <div>Раздел</div>
              <div className="text-center">В базе</div>
              <div className="text-center">После загрузки</div>
            </div>

            {/* Rows */}
            {[
              { label: "Шаблоны импорта", current: currentTemplates, seed: SEED_DATA.import_templates },
              { label: "Профили правил", current: currentProfiles, seed: SEED_DATA.route_rule_profiles },
              { label: "Маршруты", current: currentRoutes, seed: SEED_DATA.routes },
              { label: "Правила выбора", current: currentRules, seed: SEED_DATA.selection_rules },
            ].map((row) => {
              const isMatch = row.current >= row.seed
              return (
                <div key={row.label} className="grid grid-cols-3 gap-4 text-sm items-center">
                  <div className="font-medium">{row.label}</div>
                  <div className="flex items-center justify-center gap-1">
                    <span className={isMatch ? "text-green-600" : "text-amber-600"}>
                      {row.current}
                    </span>
                    {isMatch ? <Check className="h-3.5 w-3.5 text-green-600" /> : <X className="h-3.5 w-3.5 text-amber-600" />}
                  </div>
                  <div className="text-center font-medium">{row.seed}</div>
                </div>
              )
            })}

            {!hasData && (
              <div className="rounded-md bg-amber-50 border border-amber-200 p-3 text-sm text-amber-800">
                Данные отсутствуют. Загрузка создаст все справочники.
              </div>
            )}
          </div>
        )}

        <DialogFooter className="flex-col-reverse sm:flex-row gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>Закрыть</Button>
          <Button onClick={handleSeed} disabled={seeding || loading}>
            {seeding ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : <Download className="h-4 w-4 mr-1" />}
            {seeding ? "Загрузка..." : "Загрузить"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export function SettingsPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [resetting, setResetting] = useState(false)
  const [seedOpen, setSeedOpen] = useState(false)

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
          <p className="page-subtitle">Управление бэкапами, справочниками и системными параметрами.</p>
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
            <div className="rounded-lg bg-blue-500/10 p-2">
              <Download className="h-5 w-5 text-blue-500" />
            </div>
            <div>
              <h3 className="font-medium">Справочники</h3>
              <p className="text-sm text-muted-foreground">Шаблоны, маршруты и правила маршрутизации</p>
            </div>
          </div>
          <Button onClick={() => setSeedOpen(true)} className="w-full">
            <Download className="h-4 w-4 mr-1" />
            Загрузить справочники
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

      <SeedDialog open={seedOpen} onOpenChange={setSeedOpen} />

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
