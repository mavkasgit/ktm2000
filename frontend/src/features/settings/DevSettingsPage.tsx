import { HardDrive, Database, Trash2, Download, Check, X, Loader2, UserCog, Wrench, ArrowLeft } from "lucide-react"
import { useNavigate } from "react-router-dom"
import { useState } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Button } from "@/shared/ui/Button"
import { Checkbox } from "@/shared/ui/Checkbox"
import { Input } from "@/shared/ui/Input"
import { AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogTitle, AlertDialogDescription, AlertDialogFooter, AlertDialogAction, AlertDialogCancel } from "@/shared/ui"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/shared/ui/Dialog"
import { toast } from "@/shared/ui"
import { resetAllPlans } from "@/shared/api/productionPlans"
import { seedRoutes, listRoutes, listRouteRuleProfiles, listRouteSelectionRules, reseedSystemUser, seedPreview, seedDemoProduction, clearDemoProduction, getCleanupStats, executeCleanup } from "@/shared/api/routes"
import { listImportTemplates } from "@/shared/api/importTemplates"
import { listSections } from "@/shared/api/sections"
import { queryKeys } from "@/shared/api/queryKeys"
import { usePermission } from "@/features/auth/hooks/usePermission"

function useCurrentData() {
  const routes = useQuery({ queryKey: queryKeys.routes.all(), queryFn: () => listRoutes() })
  const profiles = useQuery({ queryKey: queryKeys.routes.ruleProfiles(), queryFn: () => listRouteRuleProfiles() })
  const selectionRules = useQuery({ queryKey: queryKeys.routes.selectionRules(), queryFn: () => listRouteSelectionRules() })
  const templates = useQuery({ queryKey: queryKeys.importTemplates.all(), queryFn: () => listImportTemplates() })
  const sections = useQuery({ queryKey: queryKeys.sections.all(), queryFn: () => listSections() })
  return { routes, profiles, selectionRules, templates, sections }
}

function SeedDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const { routes, profiles, selectionRules, templates, sections } = useCurrentData()
  const preview = useQuery({ queryKey: queryKeys.routes.seedPreview(), queryFn: () => seedPreview() })
  const [seeding, setSeeding] = useState(false)
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

  const hasData = currentRoutes > 0 || currentProfiles > 0 || currentRules > 0 || currentTemplates > 0 || currentSections > 0

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
          <Button onClick={handleSeed} disabled={seeding || loading}>
            {seeding ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : <Download className="h-4 w-4 mr-1" />}
            {seeding ? "Загрузка..." : "Загрузить"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}


type TableDefinition = {
  id: string;
  name: string;
  description: string;
  group: "reference" | "operational";
};

const TABLES_LIST: TableDefinition[] = [
  // Справочники
  { id: "sections", name: "Производственные участки", description: "Список цехов, участков и складов", group: "reference" },
  { id: "section_operations", name: "Операции участков", description: "Технологические операции на участках", group: "reference" },
  { id: "production_routes", name: "Технологические маршруты", description: "Справочник маршрутов производства", group: "reference" },
  { id: "route_stages", name: "Этапы маршрутов", description: "Последовательность этапов в маршрутах", group: "reference" },
  { id: "route_operations", name: "Операции этапов", description: "Специфические операции внутри каждого этапа", group: "reference" },
  { id: "route_matching_rules", name: "Правила сопоставления", description: "Правила автоматической привязки маршрутов", group: "reference" },
  { id: "route_rule_conditions", name: "Условия сопоставления", description: "Критерии выбора технологического маршрута", group: "reference" },
  { id: "route_rule_profiles", name: "Профили правил", description: "Группировки правил выбора маршрутов", group: "reference" },
  { id: "route_selection_rules", name: "Правила выбора маршрута", description: "Логика автоматического назначения маршрутов", group: "reference" },
  { id: "import_templates", name: "Шаблоны импорта", description: "Настройки разбора Excel-файлов для планов", group: "reference" },

  // Оперативные данные
  { id: "production_plans", name: "Производственные планы", description: "Заголовки планов производства продукции", group: "operational" },
  { id: "plan_positions", name: "Позиции планов", description: "Конкретные номенклатуры и количества в планах", group: "operational" },
  { id: "plan_change_sets", name: "Пакеты изменений", description: "Пакеты корректировок производственных планов", group: "operational" },
  { id: "plan_change_items", name: "Детали изменений", description: "Построчные корректировки позиций планов", group: "operational" },
  { id: "internal_plans", name: "Внутрицеховые планы", description: "Планы работы конкретных участков", group: "operational" },
  { id: "section_plan_lines", name: "Строки планов участков", description: "Позиции внутрицеховых планов по сменам", group: "operational" },
  { id: "work_tasks", name: "Рабочие задачи", description: "Задачи исполнителей на участках по выпуску продукции", group: "operational" },
  { id: "rework_tasks", name: "Задачи на доработку", description: "Задачи на исправление брака на участках", group: "operational" },
  { id: "movements", name: "Перемещения деталей", description: "Движение деталей по технологическим операциям", group: "operational" },
  { id: "transfers", name: "Накладные перемещений", description: "Передачи партий между участками/складами", group: "operational" },
  { id: "transfer_discrepancies", name: "Расхождения передач", description: "Акты несоответствия количества при приемке", group: "operational" },
  { id: "release_batches", name: "Партии выпуска", description: "Сформированные партии готовой продукции", group: "operational" },
  { id: "release_batch_positions", name: "Позиции партий выпуска", description: "Детали партий выпуска готовой продукции", group: "operational" },
  { id: "defects", name: "Регистрация брака", description: "Зарегистрированные случаи брака на производстве", group: "operational" },
  { id: "defect_items", name: "Позиции брака", description: "Детализация брака по деталям и количествам", group: "operational" },
  { id: "defect_decisions", name: "Решения по браку", description: "Принятые решения: утилизация, доработка и др.", group: "operational" },
  { id: "transfer_discrepancy_defect_items", name: "Брак при передаче", description: "Связи брака с расхождениями передач", group: "operational" },
  { id: "spg_remainders", name: "Остатки ГХП", description: "Остатки готовой и полуготовой продукции на складах", group: "operational" },
  { id: "import_batches", name: "Партии импорта", description: "Журнал импорта планов из внешних файлов", group: "operational" },
  { id: "import_files", name: "Файлы импорта", description: "Архив загруженных Excel-файлов", group: "operational" },
];

const TABLE_DEPENDENCIES: Record<string, string[]> = {
  sections: [
    "section_operations",
    "route_stages",
    "internal_plans",
    "section_plan_lines",
    "work_tasks",
    "movements",
    "transfers",
    "spg_remainders",
    "defects",
  ],
  production_routes: [
    "route_stages",
    "route_operations",
    "route_matching_rules",
    "route_rule_conditions",
    "work_tasks",
  ],
  route_stages: ["route_operations", "work_tasks"],
  route_matching_rules: ["route_rule_conditions"],
  route_rule_profiles: ["route_selection_rules"],
  production_plans: [
    "plan_positions",
    "plan_change_sets",
    "plan_change_items",
    "internal_plans",
    "section_plan_lines",
    "work_tasks",
    "release_batch_positions",
  ],
  plan_positions: [
    "plan_change_items",
    "section_plan_lines",
    "work_tasks",
    "release_batch_positions",
  ],
  plan_change_sets: ["plan_change_items"],
  internal_plans: ["section_plan_lines", "work_tasks"],
  section_plan_lines: ["work_tasks"],
  work_tasks: ["rework_tasks", "movements", "defects"],
  defects: [
    "defect_items",
    "defect_decisions",
    "transfer_discrepancy_defect_items",
    "rework_tasks",
  ],
  transfers: ["transfer_discrepancies", "transfer_discrepancy_defect_items"],
  transfer_discrepancies: ["transfer_discrepancy_defect_items"],
  release_batches: ["release_batch_positions", "transfers"],
  spg_remainders: ["defects"],
  import_files: ["import_batches"],
};

function getTransitiveDependencies(tableId: string, visited = new Set<string>()): Set<string> {
  if (visited.has(tableId)) return visited;
  visited.add(tableId);
  const deps = TABLE_DEPENDENCIES[tableId] || [];
  for (const dep of deps) {
    getTransitiveDependencies(dep, visited);
  }
  return visited;
}

function getChildDependencies(tableId: string): Set<string> {
  const visited = new Set<string>();
  const deps = TABLE_DEPENDENCIES[tableId] || [];
  for (const dep of deps) {
    getTransitiveDependencies(dep, visited);
  }
  return visited;
}

function CleanupDatabaseDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const queryClient = useQueryClient();
  const { data: statsData, isLoading, refetch } = useQuery({
    queryKey: ["cleanup-stats"],
    queryFn: getCleanupStats,
    enabled: open,
    refetchOnWindowFocus: false,
  });

  const [userSelected, setUserSelected] = useState<Set<string>>(new Set());
  const [confirmText, setConfirmText] = useState("");
  const [isCleaning, setIsCleaning] = useState(false);

  // Вычисляем итоговые выбранные (с учетом каскадных зависимостей)
  const effectiveSelected = new Set<string>();
  const disabledSelected = new Set<string>();

  for (const tableId of userSelected) {
    effectiveSelected.add(tableId);
    const childDeps = getChildDependencies(tableId);
    for (const dep of childDeps) {
      effectiveSelected.add(dep);
      disabledSelected.add(dep);
    }
  }

  const handleToggle = (tableId: string) => {
    const next = new Set(userSelected);
    if (next.has(tableId)) {
      next.delete(tableId);
    } else {
      next.add(tableId);
    }
    setUserSelected(next);
  };

  const handleSelectAll = (group?: "reference" | "operational") => {
    const next = new Set(userSelected);
    const filtered = TABLES_LIST.filter(t => !group || t.group === group);
    
    // Если все элементы группы уже в userSelected, убираем их. Иначе добавляем все.
    const allSelected = filtered.every(t => next.has(t.id));
    if (allSelected) {
      filtered.forEach(t => next.delete(t.id));
    } else {
      filtered.forEach(t => next.add(t.id));
    }
    setUserSelected(next);
  };

  const handleClearSelection = () => {
    setUserSelected(new Set());
  };

  const handleCleanup = async () => {
    if (confirmText !== "ОЧИСТИТЬ" || effectiveSelected.size === 0) return;
    setIsCleaning(true);
    try {
      await executeCleanup(Array.from(effectiveSelected));
      toast({
        title: "Данные очищены",
        description: `Успешно удалены записи из ${effectiveSelected.size} таблиц.`,
        variant: "success",
      });
      queryClient.invalidateQueries();
      onOpenChange(false);
      setConfirmText("");
      setUserSelected(new Set());
    } catch (e) {
      toast({
        title: "Ошибка очистки",
        description: e instanceof Error ? e.message : "Не удалось очистить выбранные данные",
        variant: "destructive",
      });
    } finally {
      setIsCleaning(false);
    }
  };

  const stats = statsData?.stats || {};
  const maxCount = Math.max(...Object.values(stats), 1);
  
  // Подсчет количества записей к удалению
  const totalRecordsToDelete = Array.from(effectiveSelected).reduce((sum, tableId) => {
    return sum + (stats[tableId] || 0);
  }, 0);

  const referenceTables = TABLES_LIST.filter(t => t.group === "reference");
  const operationalTables = TABLES_LIST.filter(t => t.group === "operational");

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl max-h-[90vh] flex flex-col p-6">
        <DialogHeader className="pb-2 border-b">
          <DialogTitle className="text-xl flex items-center gap-2 text-destructive">
            <Trash2 className="h-5 w-5" />
            Выборочная очистка базы данных
          </DialogTitle>
          <DialogDescription>
            Выберите конкретные таблицы для очистки. В скобках указано текущее количество записей. 
            Красным цветом и замочком выделены таблицы, которые будут удалены автоматически из-за связей (Foreign Keys).
          </DialogDescription>
        </DialogHeader>

        {isLoading ? (
          <div className="flex flex-col items-center justify-center py-20 flex-grow">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground mb-2" />
            <span className="text-sm text-muted-foreground">Загрузка счетчиков таблиц...</span>
          </div>
        ) : (
          <div className="flex-grow overflow-y-auto py-4 space-y-6 pr-2">
            {/* Панель быстрого выбора */}
            <div className="flex gap-2 justify-end text-xs">
              <Button variant="outline" size="sm" onClick={() => handleSelectAll("operational")} className="h-8">
                Выбрать всё производство
              </Button>
              <Button variant="outline" size="sm" onClick={() => handleSelectAll("reference")} className="h-8">
                Выбрать все справочники
              </Button>
              <Button variant="ghost" size="sm" onClick={handleClearSelection} className="h-8 text-muted-foreground">
                Сбросить выбор
              </Button>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {/* Группа: Оперативные данные */}
              <div className="space-y-3">
                <div className="flex justify-between items-center border-b pb-2">
                  <h3 className="font-semibold text-sm text-foreground flex items-center gap-2">
                    <Database className="h-4 w-4 text-blue-500" />
                    Оперативные данные (Производство)
                  </h3>
                  <span className="text-xs text-muted-foreground bg-blue-500/10 text-blue-600 px-2 py-0.5 rounded-full">
                    Не общие
                  </span>
                </div>
                <div className="space-y-1 max-h-[55vh] overflow-y-auto pr-1">
                  {operationalTables.map(table => {
                    const isSelected = effectiveSelected.has(table.id);
                    const isDisabled = disabledSelected.has(table.id);
                    const rowCount = stats[table.id] ?? 0;
                    const ratio = rowCount > 0 ? rowCount / maxCount : 0;

                    // Градиентная подсветка для таблиц, где есть данные
                    const itemStyle = rowCount > 0 && !isDisabled
                      ? {
                          background: `linear-gradient(90deg, transparent 40%, rgba(59, 130, 246, ${0.05 + ratio * 0.2}) 100%)`
                        }
                      : undefined;

                    return (
                      <div
                        key={table.id}
                        className={`flex items-center gap-2 px-2 py-1 rounded-md transition-all border text-left text-xs ${
                          isDisabled
                            ? "bg-red-500/5 border-red-200/30"
                            : isSelected
                            ? "border-primary/40"
                            : "hover:bg-accent/40 border-transparent"
                        }`}
                        style={itemStyle}
                        title={table.description}
                      >
                        <Checkbox
                          id={table.id}
                          checked={isSelected}
                          disabled={isDisabled}
                          onCheckedChange={() => handleToggle(table.id)}
                          className="h-3.5 w-3.5 shrink-0"
                        />
                        <div className="flex items-center justify-between flex-1 min-w-0 gap-1.5">
                          <label
                            htmlFor={table.id}
                            className={`cursor-pointer flex items-center gap-1.5 leading-none select-none truncate ${
                              isDisabled ? "text-red-600 font-semibold" : "text-foreground font-medium"
                            }`}
                          >
                            <span className="truncate">{table.name}</span>
                            <span className="text-[9px] text-muted-foreground font-mono shrink-0">
                              ({table.id})
                            </span>
                          </label>
                          <div className="flex items-center gap-1 shrink-0">
                            <span className={`px-1.5 py-0.5 rounded font-mono border transition-all ${
                              rowCount > 0
                                ? "text-blue-700 bg-blue-100 border-blue-300 font-extrabold text-sm shadow-sm"
                                : "text-muted-foreground bg-muted border-transparent text-[10px]"
                            }`}>
                              {rowCount}
                            </span>
                            {isDisabled && (
                              <span className="text-[9px] bg-red-100 text-red-700 px-1 rounded font-normal whitespace-nowrap">
                                Зависит
                              </span>
                            )}
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Группа: Системные справочники */}
              <div className="space-y-3">
                <div className="flex justify-between items-center border-b pb-2">
                  <h3 className="font-semibold text-sm text-foreground flex items-center gap-2">
                    <HardDrive className="h-4 w-4 text-emerald-500" />
                    Системные справочники (Настройки)
                  </h3>
                  <span className="text-xs text-muted-foreground bg-emerald-500/10 text-emerald-600 px-2 py-0.5 rounded-full">
                    Общие
                  </span>
                </div>
                <div className="space-y-1 max-h-[55vh] overflow-y-auto pr-1">
                  {referenceTables.map(table => {
                    const isSelected = effectiveSelected.has(table.id);
                    const isDisabled = disabledSelected.has(table.id);
                    const rowCount = stats[table.id] ?? 0;
                    const ratio = rowCount > 0 ? rowCount / maxCount : 0;

                    // Градиентная подсветка для таблиц, где есть данные
                    const itemStyle = rowCount > 0 && !isDisabled
                      ? {
                          background: `linear-gradient(90deg, transparent 40%, rgba(16, 185, 129, ${0.05 + ratio * 0.2}) 100%)`
                        }
                      : undefined;

                    return (
                      <div
                        key={table.id}
                        className={`flex items-center gap-2 px-2 py-1 rounded-md transition-all border text-left text-xs ${
                          isDisabled
                            ? "bg-red-500/5 border-red-200/30"
                            : isSelected
                            ? "border-primary/40"
                            : "hover:bg-accent/40 border-transparent"
                        }`}
                        style={itemStyle}
                        title={table.description}
                      >
                        <Checkbox
                          id={table.id}
                          checked={isSelected}
                          disabled={isDisabled}
                          onCheckedChange={() => handleToggle(table.id)}
                          className="h-3.5 w-3.5 shrink-0"
                        />
                        <div className="flex items-center justify-between flex-1 min-w-0 gap-1.5">
                          <label
                            htmlFor={table.id}
                            className={`cursor-pointer flex items-center gap-1.5 leading-none select-none truncate ${
                              isDisabled ? "text-red-600 font-semibold" : "text-foreground font-medium"
                            }`}
                          >
                            <span className="truncate">{table.name}</span>
                            <span className="text-[9px] text-muted-foreground font-mono shrink-0">
                              ({table.id})
                            </span>
                          </label>
                          <div className="flex items-center gap-1 shrink-0">
                            <span className={`px-1.5 py-0.5 rounded font-mono border transition-all ${
                              rowCount > 0
                                ? "text-emerald-700 bg-emerald-100 border-emerald-300 font-extrabold text-sm shadow-sm"
                                : "text-muted-foreground bg-muted border-transparent text-[10px]"
                            }`}>
                              {rowCount}
                            </span>
                            {isDisabled && (
                              <span className="text-[9px] bg-red-100 text-red-700 px-1 rounded font-normal whitespace-nowrap">
                                Зависит
                              </span>
                            )}
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Панель подтверждения и футер */}
        <div className="pt-4 border-t space-y-4">
          <div className="rounded-lg bg-amber-500/10 border border-amber-500/20 p-3.5 flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-sm">
            <div className="space-y-1">
              <p className="font-semibold text-amber-800">
                Итого выбрано таблиц для очистки: {effectiveSelected.size} из {TABLES_LIST.length}
              </p>
              <p className="text-amber-700 text-xs">
                Всего будет безвозвратно удалено записей: <span className="font-bold text-sm">{totalRecordsToDelete}</span>
              </p>
            </div>
            {effectiveSelected.size > 0 && (
              <div className="flex items-center gap-2">
                <span className="text-xs text-amber-800 whitespace-nowrap">Для подтверждения введите:</span>
                <Input
                  placeholder="ОЧИСТИТЬ"
                  value={confirmText}
                  onChange={e => setConfirmText(e.target.value)}
                  className="w-32 h-8 text-xs font-bold tracking-wider placeholder:font-normal placeholder:tracking-normal bg-white"
                />
              </div>
            )}
          </div>

          <DialogFooter className="flex-col-reverse sm:flex-row gap-2">
            <Button variant="outline" onClick={() => onOpenChange(false)}>
              Отмена
            </Button>
            <Button
              variant="destructive"
              onClick={handleCleanup}
              disabled={isCleaning || isLoading || effectiveSelected.size === 0 || confirmText !== "ОЧИСТИТЬ"}
            >
              {isCleaning ? (
                <>
                  <Loader2 className="h-4 w-4 mr-1 animate-spin" />
                  Удаление...
                </>
              ) : (
                <>
                  <Trash2 className="h-4 w-4 mr-1" />
                  Очистить выбранные данные ({totalRecordsToDelete})
                </>
              )}
            </Button>
          </DialogFooter>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export function DevSettingsPage() {
  const { canEditSettings } = usePermission()
  const isReadOnly = !canEditSettings
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [cleanupOpen, setCleanupOpen] = useState(false)
  const [seedOpen, setSeedOpen] = useState(false)
  const [reseedingUser, setReseedingUser] = useState(false)
  
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

  const handleReseedUser = async () => {
    setReseedingUser(true)
    try {
      const result = await reseedSystemUser()
      queryClient.invalidateQueries()
      toast({ title: "Системный пользователь восстановлен", description: `ID: ${result.user_id}, Email: ${result.email}`, variant: "success" })
    } catch (e) {
      toast({ title: "Ошибка", description: e instanceof Error ? e.message : "Не удалось восстановить пользователя", variant: "destructive" })
    } finally {
      setReseedingUser(false)
    }
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

        <div className="rounded-lg border bg-card p-6 space-y-4">
          <div className="flex items-center gap-3">
            <div className="rounded-lg bg-violet-500/10 p-2">
              <UserCog className="h-5 w-5 text-violet-500" />
            </div>
            <div>
              <h3 className="font-medium">Системный пользователь</h3>
              <p className="text-sm text-muted-foreground">Восстановить ID=1 для dev-режима</p>
            </div>
          </div>
          <Button onClick={handleReseedUser} disabled={reseedingUser} className="w-full">
            {reseedingUser ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : <UserCog className="h-4 w-4 mr-1" />}
            {reseedingUser ? "Восстановление..." : "Восстановить"}
          </Button>
        </div>

        <div className="rounded-lg border bg-card p-6 space-y-4">
          <div className="flex items-center gap-3">
            <div className="rounded-lg bg-red-500/10 p-2">
              <Trash2 className="h-5 w-5 text-red-500" />
            </div>
            <div>
              <h3 className="font-medium">Очистка данных</h3>
              <p className="text-sm text-muted-foreground">Удаление планов и справочников</p>
            </div>
          </div>
          <Button variant="destructive" onClick={() => setCleanupOpen(true)} className="w-full">
            Очистить
          </Button>
        </div>
      </div>

      <SeedDialog open={seedOpen} onOpenChange={setSeedOpen} />

      <CleanupDatabaseDialog open={cleanupOpen} onOpenChange={setCleanupOpen} />

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
