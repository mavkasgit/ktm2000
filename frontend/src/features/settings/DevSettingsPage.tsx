import { Database, Trash2, Download, Check, X, Loader2, Wrench, ArrowLeft } from "lucide-react"
import { useNavigate } from "react-router-dom"
import { useState } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Button } from "@/shared/ui/button"
import { AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogTitle, AlertDialogDescription, AlertDialogFooter, AlertDialogAction, AlertDialogCancel } from "@/shared/ui"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/shared/ui/dialog"
import { toast } from "@/shared/ui"
import { seedRoutes, listRoutes, listRouteRuleProfiles, listRouteSelectionRules, seedPreview, seedDemoProduction, clearDemoProduction } from "@/shared/api/routes"
import { listAllImportTemplates } from "@/shared/api/importTemplates"
import { listSections } from "@/shared/api/sections"
import { queryKeys } from "@/shared/api/queryKeys"
import { usePermission } from "@/features/auth/hooks/usePermission"

function useCurrentData() {
  const routes = useQuery({ queryKey: queryKeys.routes.all(), queryFn: () => listRoutes() })
  const profiles = useQuery({ queryKey: queryKeys.routes.ruleProfiles(), queryFn: () => listRouteRuleProfiles() })
  const selectionRules = useQuery({ queryKey: queryKeys.routes.selectionRules(), queryFn: () => listRouteSelectionRules() })
  const templates = useQuery({ queryKey: queryKeys.importTemplates.all(), queryFn: () => listAllImportTemplates() })
  const sections = useQuery({ queryKey: queryKeys.sections.all(), queryFn: () => listSections() })
  return { routes, profiles, selectionRules, templates, sections }
}

function SeedDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const { routes, profiles, selectionRules, templates, sections } = useCurrentData()
  const preview = useQuery({ queryKey: queryKeys.routes.seedPreview(), queryFn: () => seedPreview() })
  const [seeding, setSeeding] = useState(false)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const queryClient = useQueryClient()

  const loading = routes.isLoading || profiles.isLoading || selectionRules.isLoading || templates.isLoading || sections.isLoading || preview.isLoading

  const currentRoutes = routes.data?.length ?? 0
  const currentProfiles = profiles.data?.length ?? 0
  const currentRules = selectionRules.data?.length ?? 0
  const currentTemplates = templates.data?.length ?? 0
  const currentSections = sections.data?.length ?? 0

  const seed = preview.data

  const handleSeed = async () => {
    setSeeding(true)
    try {
      const summary = await seedRoutes(true)
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
      setConfirmOpen(false)
    }
  }

  const onLoadClick = () => {
    setConfirmOpen(true)
  }

  const onConfirm = () => {
    void handleSeed()
  }

  const hasData = currentRoutes > 0 || currentProfiles > 0 || currentRules > 0 || currentTemplates > 0 || currentSections > 0

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Загрузка справочников</DialogTitle>
          <DialogDescription>
            Сравнение текущих данных с типовыми. Загрузка <b>перезапишет</b> все справочники и <b>удалит</b> сгенерированные производственные данные.
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
              { label: "Участки", current: currentSections, seed: seed?.sections ?? 0 },
              { label: "Шаблоны импорта", current: currentTemplates, seed: seed?.import_templates ?? 0 },
              { label: "Профили правил", current: currentProfiles, seed: seed?.route_rule_profiles ?? 0 },
              { label: "Маршруты", current: currentRoutes, seed: seed?.routes ?? 0 },
              { label: "Правила выбора", current: currentRules, seed: seed?.selection_rules ?? 0 },
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
          <Button onClick={onLoadClick} disabled={seeding || loading}>
            {seeding ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : <Download className="h-4 w-4 mr-1" />}
            {seeding ? "Загрузка..." : "Загрузить"}
          </Button>
        </DialogFooter>
      </DialogContent>

      <AlertDialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle className="text-red-600">Перезаписать справочники?</AlertDialogTitle>
            <AlertDialogDescription className="space-y-2">
              <p>
                Будут <b>удалены</b> все сгенерированные производственные данные: задачи, передачи, движения,
                остатки ГХП, внутренние планы, батчи запуска, импорты, дефекты, брак.
              </p>
              <p>
                Затем <b>перезаписаны</b> справочники: участки, операции, ГХП, маршруты, профили правил, правила выбора.
              </p>
              <p>Действие необратимо.</p>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={seeding}>Отмена</AlertDialogCancel>
            <AlertDialogAction
              onClick={onConfirm}
              disabled={seeding}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {seeding ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : null}
              Перезаписать
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Dialog>
  )
}




export function DevSettingsPage() {
  const { canEditSettings } = usePermission()
  const isReadOnly = !canEditSettings
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [seedOpen, setSeedOpen] = useState(false)
  const [seedingDemo, setSeedingDemo] = useState(false)
  const [clearingDemo, setClearingDemo] = useState(false)
  const [confirmDemoClearOpen, setConfirmDemoClearOpen] = useState(false)

  // Если нет прав на редактирование настроек, то показываем сообщение об ошибке
  if (isReadOnly) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-center">
        <h2 className="text-xl font-semibold text-destructive mb-2">Доступ ограничен</h2>
        <p className="text-muted-foreground mb-4">У вас нет прав для просмотра панели разработчика.</p>
        <Button onClick={() => navigate("/settings")}>Назад к настройкам</Button>
      </div>
    )
  }

  const handleSeedDemo = async () => {
    setSeedingDemo(true)
    try {
      const summary = await seedDemoProduction()
      queryClient.invalidateQueries()
      toast({
        title: "Демо-данные загружены",
        description: `Продуктов: ${summary.products}, Остатков: ${summary.remainders}, Дефектов: ${summary.defects}`,
        variant: "success",
      })
    } catch (e) {
      toast({
        variant: "destructive",
        title: "Ошибка",
        description: e instanceof Error ? e.message : "Не удалось загрузить демо-данные",
      })
    } finally {
      setSeedingDemo(false)
    }
  }

  const handleClearDemo = async () => {
    setConfirmDemoClearOpen(false)
    setClearingDemo(true)
    try {
      const summary = await clearDemoProduction()
      queryClient.invalidateQueries()
      const clearedCount = Object.values(summary.cleanup).reduce((a: number, b: any) => a + (typeof b === "number" ? b : 0), 0)
      toast({
        title: "Демо-данные очищены",
        description: `Удалено записей: ${clearedCount}`,
        variant: "success",
      })
    } catch (e) {
      toast({
        variant: "destructive",
        title: "Ошибка",
        description: e instanceof Error ? e.message : "Не удалось очистить демо-данные",
      })
    } finally {
      setClearingDemo(false)
    }
  }

  return (
    <>
      <header className="page-header flex items-center justify-between">
        <div>
          <h1 className="page-title flex items-center gap-2">
            <Wrench className="h-6 w-6 text-violet-500" />
            Панель разработчика
          </h1>
          <p className="page-subtitle">Инструменты для отладки, заполнения базы демо-данными и сброса состояния.</p>
        </div>
        <Button variant="outline" onClick={() => navigate("/settings")} className="flex items-center gap-2">
          <ArrowLeft className="h-4 w-4" />
          Назад к настройкам
        </Button>
      </header>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
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
            <div className="rounded-lg bg-emerald-500/10 p-2">
              <Database className="h-5 w-5 text-emerald-500" />
            </div>
            <div>
              <h3 className="font-medium">Демо-производство</h3>
              <p className="text-sm text-muted-foreground">Остатки ГХП, этапы маршрута и брак</p>
            </div>
          </div>
          <div className="flex gap-2">
            <Button onClick={handleSeedDemo} disabled={seedingDemo} className="flex-1">
              {seedingDemo ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : <Download className="h-4 w-4 mr-1" />}
              {seedingDemo ? "Загрузка..." : "Загрузить демо"}
            </Button>
            <Button variant="outline" onClick={() => setConfirmDemoClearOpen(true)} disabled={clearingDemo} className="text-destructive hover:bg-destructive/10">
              {clearingDemo ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : <Trash2 className="h-4 w-4" />}
              {clearingDemo ? "Очистить" : "Очистить"}
            </Button>
          </div>
        </div>

      </div>

      <SeedDialog open={seedOpen} onOpenChange={setSeedOpen} />


      <AlertDialog open={confirmDemoClearOpen} onOpenChange={setConfirmDemoClearOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Очистить демонстрационные данные?</AlertDialogTitle>
            <AlertDialogDescription>
              Это действие удалит все зарегистрированные остатки ГХП, брак, принятые решения, а также связанные задачи (work_tasks / rework_tasks).
              Справочники и профили правил останутся без изменений.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Отмена</AlertDialogCancel>
            <AlertDialogAction onClick={handleClearDemo} className="bg-destructive text-destructive-foreground hover:bg-destructive/90">
              Очистить
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
