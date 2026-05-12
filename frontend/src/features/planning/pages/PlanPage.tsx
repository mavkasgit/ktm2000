import { useEffect, useMemo, useState } from "react"
import { Beaker, Download, Eye, FileSpreadsheet, Plus, Upload, Route, Trash2 } from "lucide-react"
import { ImportWizard } from "../ImportWizard"
import { Button, Badge, Checkbox, Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, Combobox, Select, SelectContent, SelectItem, SelectTrigger, SelectValue, AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogTitle, AlertDialogDescription, AlertDialogFooter, AlertDialogAction, AlertDialogCancel } from "@/shared/ui"
import { cn } from "@/shared/utils/cn"
import { toast } from "@/shared/ui"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { planFiles, allPositions, allPlanFiles, allPlanPositions, PlanFileInfo, PlanPositionOut, listPlans, PlanSummary, batchAssignRouteGlobal, deleteImportBatch } from "@/shared/api/productionPlans"
import { listRoutes, ProductionRoute } from "@/shared/api/routes"
import { getImportFileDownloadUrl } from "@/shared/api/imports"
import { apiClient } from "@/shared/api/client"

const statusLabels: Record<string, string> = {
  parsed: "Распознан",
  failed: "Ошибка",
  applied: "Применён",
  cancelled: "Отменён",
  draft: "Черновик",
  valid: "Валиден",
  invalid: "Ошибка",
  approved: "Утверждён",
  released: "Запущен",
}

const statusVariant: Record<string, string> = {
  parsed: "secondary",
  failed: "destructive",
  applied: "default",
  cancelled: "destructive",
  draft: "secondary",
  valid: "default",
  invalid: "destructive",
  approved: "default",
  released: "default",
}

const routeErrorLabels: Record<string, string> = {
  route_signature_incomplete: "Сигнатура маршрута неполная",
  route_not_found: "Маршрут не найден",
  active_route_not_found: "Активный маршрут не найден",
  active_route_has_no_steps: "Маршрут без этапов",
  route_sequence_invalid: "Неверная последовательность маршрута",
  route_contains_inactive_section: "Маршрут содержит неактивный участок",
  route_not_matching_import_signature: "Маршрут не совпадает с импортом",
  route_missing_required_step: "Отсутствует обязательный этап",
  route_missing_pack_additional_operation: "Отсутствует доп. упаковочная операция",
  route_primary_operation_mismatch: "Основная операция маршрута не совпадает",
  manual_route_not_found: "Ручной маршрут не найден",
  manual_route_inactive: "Ручной маршрут неактивен",
  auto_fallback: "Маршрут выбран автоматически — проверьте",
}

const errorLabels: Record<string, string> = {
  product_not_found: "Изделие не найдено",
  product_inactive: "Изделие неактивно",
  active_techcard_not_found: "Нет активной техкарты",
  active_techcard_has_no_lines: "Техкарта пустая",
  active_route_not_found: "Нет активного маршрута",
  active_route_has_no_steps: "Маршрут без этапов",
  route_sequence_invalid: "Неверная последовательность маршрута",
  route_contains_inactive_section: "Неактивный участок в маршруте",
  duplicate_sku_due_date: "Дубликат: такой артикул со сроком уже есть",
  route_primary_operation_mismatch: "Основная операция маршрута не совпадает",
  route_not_matching_import_signature: "Маршрут не совпадает с ожидаемым",
  route_missing_required_step: "Отсутствует обязательный этап в маршруте",
  route_missing_pack_additional_operation: "Отсутствует доп. упаковочная операция",
  quantity_must_be_positive: "Количество должно быть > 0",
  route_signature_incomplete: "Сигнатура маршрута неполная",
  route_not_found: "Маршрут не найден по сигнатуре",
}

const warningLabels: Record<string, string> = {
  paired_profile_product_unmapped: "Парный профиль не сопоставлен",
  techcard_pair_not_resolved: "Не выбран парный профиль техкарты",
  product_name_missing: "Отсутствует наименование",
  period_not_detected: "Период не определён",
  route_auto_fallback: "Маршрут выбран автоматически — проверьте корректность",
}

function translateLabel(code: string, labels: Record<string, string>): string {
  const [base] = String(code).split(":")
  return labels[base] ?? code
}

function FileRow({ file, activePlan, onDelete }: { file: PlanFileInfo; activePlan: PlanSummary; onDelete: (batchId: number) => void }) {
  const [previewOpen, setPreviewOpen] = useState(false)
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const downloadUrl = getImportFileDownloadUrl(file.file_id)

  const { data: previewData } = useQuery({
    queryKey: ["batch-preview", file.batch_id],
    queryFn: () =>
      apiClient.get(`/production-plans/${activePlan!.id}/batches/${file.batch_id}/preview`).then(r => r.data),
    enabled: previewOpen && !!activePlan,
  })

  const previewItems = ((previewData as any)?.items as Record<string, any>[] | undefined) ?? []

  return (
    <>
      <tr className="border-b">
        <td className="p-3">
          <div className="flex items-center gap-2">
            <FileSpreadsheet className="h-4 w-4 text-muted-foreground" />
            <span className="font-medium text-sm">{file.filename}</span>
          </div>
        </td>
        <td className="p-3 text-sm text-muted-foreground">
          {new Date(file.created_at).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" })}
        </td>
        <td className="p-3 text-sm text-muted-foreground">{file.sheet_name}</td>
        <td className="p-3 text-sm">{file.total_rows}</td>
        <td className="p-3 text-sm">
          {(file.size_bytes / 1024).toFixed(1)} KB
        </td>
        <td className="p-3">
          <Badge variant={statusVariant[file.status] as any || "secondary"}>
            {statusLabels[file.status] || file.status}
          </Badge>
        </td>
        <td className="p-3">
          <div className="flex gap-1">
            <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={() => setPreviewOpen(true)}>
              <Eye className="h-3 w-3 mr-1" /> Просмотр
            </Button>
            <Button variant="ghost" size="sm" className="h-7 text-xs" asChild>
              <a href={downloadUrl} download={file.filename}>
                <Download className="h-3 w-3 mr-1" /> Скачать
              </a>
            </Button>
            <Button variant="ghost" size="sm" className="h-7 text-xs text-red-600 hover:text-red-700" onClick={() => setDeleteDialogOpen(true)}>
              <Trash2 className="h-3 w-3 mr-1" /> Удалить
            </Button>
          </div>
        </td>
      </tr>

      <Dialog open={previewOpen} onOpenChange={setPreviewOpen}>
        <DialogContent className="max-w-[90vw] max-h-[80vh] overflow-hidden flex flex-col">
          <DialogHeader>
            <DialogTitle>Файл: {file.filename}</DialogTitle>
            <DialogDescription>Предпросмотр содержимого загруженного файла</DialogDescription>
          </DialogHeader>
          {previewItems.length === 0 && (
            <p className="text-sm text-muted-foreground">Предпросмотр недоступен</p>
          )}
          {previewItems.length > 0 && (
            <div className="flex-1 overflow-auto border rounded-lg">
              <table className="w-full text-sm">
                <thead className="border-b bg-muted/50">
                  <tr>
                    <th className="text-left p-2">Артикул</th>
                    <th className="text-left p-2">Наименование</th>
                    <th className="text-left p-2">Кол-во</th>
                    <th className="text-left p-2">Статус</th>
                  </tr>
                </thead>
                <tbody>
                  {previewItems.slice(0, 100).map((row, i) => (
                    <tr key={i} className="border-b">
                      <td className="p-2">{row.source_sku ?? row.sku ?? "—"}</td>
                      <td className="p-2">{row.source_name ?? row.product_name ?? "—"}</td>
                      <td className="p-2">{row.quantity ?? "—"}</td>
                      <td className="p-2">{row.status ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {previewItems.length > 100 && (
                <p className="text-xs text-muted-foreground p-2">Показано 100 из {previewItems.length} строк</p>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>

      <AlertDialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Удалить импорт?</AlertDialogTitle>
            <AlertDialogDescription>
              Файл «{file.filename}» и все связанные позиции будут удалены. Это действие нельзя отменить.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Отмена</AlertDialogCancel>
            <AlertDialogAction onClick={() => onDelete(file.batch_id)}>Удалить</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}

function PositionRow({ pos, onApprove, onDelete, selected, onToggle, routes, onAssignRoute }: {
  pos: PlanPositionOut;
  onApprove: (id: number, planId?: number) => void;
  onDelete: (id: number, planId?: number) => void;
  selected?: boolean;
  onToggle?: (id: number) => void;
  routes?: ProductionRoute[];
  onAssignRoute?: (positionId: number, routeId: number | null) => void;
}) {
  const hasErrors = pos.errors && pos.errors.length > 0
  const hasWarnings = pos.warnings && pos.warnings.length > 0
  const qty = Number(pos.quantity || 0)
  const qtyStr = Number.isInteger(qty) ? String(qty) : qty.toFixed(3).replace(/\.?0+$/, '')
  const isDraft = pos.status === 'draft'
  const translatedErrors = hasErrors ? pos.errors.map((e) => translateLabel(e, errorLabels)) : []
  const translatedWarnings = hasWarnings ? pos.warnings.map((w) => translateLabel(w, warningLabels)) : []
  const reason = pos.validation_status === 'invalid'
    ? (translatedErrors.length > 0 ? translatedErrors.join(', ') : 'Ошибка валидации')
    : isDraft
      ? 'Ожидает утверждения'
      : ''
  const rowNum = pos.source_row_number ?? "—"
  const routeSourceLabel = pos.route_source === "manual" ? "(вручную)" : pos.route_source === "auto" ? "(авто)" : ""
  const routeError = pos.route_error ? translateLabel(pos.route_error, routeErrorLabels) : null
  const [routeCellOpen, setRouteCellOpen] = useState(false)

  return (
    <tr className={`border-b ${hasErrors ? "bg-red-50" : hasWarnings ? "bg-amber-50" : ""} ${selected ? "bg-blue-50" : ""}`}>
      <td className="p-2">
        {onToggle && (
          <Checkbox checked={selected || false} onCheckedChange={() => onToggle(pos.id)} />
        )}
      </td>
      <td className="p-2 text-sm">
        <span className="text-muted-foreground">#{pos.id}</span>
      </td>
      <td className="p-2 text-sm font-medium">{rowNum}</td>
      <td className="p-2 text-sm">{pos.source_sku}</td>
      <td className="p-2 text-sm">{pos.source_name ?? "—"}</td>
      <td className="p-2 text-sm">{qtyStr}</td>
      <td className="p-2 text-sm min-w-[200px]">
        {routes && onAssignRoute ? (
          <Combobox
            options={[{ label: "— Снять маршрут —", value: "__clear__" }, ...routes.map(r => ({ label: r.name, value: String(r.id) }))]}
            value={pos.route_id ? String(pos.route_id) : undefined}
            onValueChange={(v) => onAssignRoute(pos.id, v === "__clear__" ? null : Number(v))}
            placeholder={routeError || "Не назначен"}
            emptyText="Маршрут не найден"
            className={cn(
              "rounded-md border border-dashed border-input px-2 py-1.5 hover:bg-accent/50 hover:border-primary/50 transition-colors cursor-pointer group",
              pos.route_id ? "border-solid border-blue-200 bg-blue-50/50" : "bg-muted/20",
            )}
            triggerContent={
              <span className="inline-flex items-center gap-1.5 w-full">
                <Route className={cn("h-3.5 w-3.5 shrink-0", pos.route_id ? "text-blue-600" : "text-muted-foreground group-hover:text-primary")} />
                {pos.route_name ? (
                  <span className="text-blue-700">
                    {pos.route_name}
                    <span className="text-xs text-muted-foreground ml-1">{routeSourceLabel}</span>
                  </span>
                ) : (
                  <span className={cn("text-xs", routeError ? "text-red-600" : "text-muted-foreground group-hover:text-foreground")}>
                    {routeError || "Нажмите для выбора"}
                  </span>
                )}
              </span>
            }
          />
        ) : pos.route_name ? (
          <span className="inline-flex items-center gap-1 text-blue-700" title={`Маршрут #${pos.route_id} ${routeSourceLabel}`}>
            <Route className="h-3 w-3" />
            {pos.route_name}
            <span className="text-xs text-muted-foreground">{routeSourceLabel}</span>
          </span>
        ) : (
          <span className={routeError ? "text-red-600 text-xs" : "text-muted-foreground text-xs"} title={routeError || undefined}>
            {routeError || "Не назначен"}
          </span>
        )}
      </td>
      <td className="p-2">
        <Badge variant={statusVariant[pos.status] as any || "secondary"}>
          {statusLabels[pos.status] || pos.status}
        </Badge>
      </td>
      <td className="p-2 text-xs text-red-600 max-w-[200px]">
        {hasErrors ? (
          <span className="truncate block" title={translatedErrors.join("\n")}>
            {translatedErrors.join(", ")}
          </span>
        ) : "—"}
      </td>
      <td className="p-2 text-xs text-amber-600 max-w-[150px]">
        {hasWarnings ? (
          <span className="truncate block" title={translatedWarnings.join("\n")}>
            {translatedWarnings.join(", ")}
          </span>
        ) : "—"}
      </td>
      <td className="p-2">
        <div className="flex gap-1">
          {pos.status === 'valid' && (
            <>
              <Button variant="ghost" size="sm" className="h-6 text-xs text-green-700 hover:text-green-800" onClick={() => onApprove(pos.id, pos.production_plan_id)}>
                Утвердить
              </Button>
              <Button variant="ghost" size="sm" className="h-6 text-xs text-red-600 hover:text-red-700" onClick={() => onDelete(pos.id, pos.production_plan_id)}>
                Удалить
              </Button>
            </>
          )}
          {pos.status === 'draft' && (
            <Button variant="ghost" size="sm" className="h-6 text-xs text-red-600 hover:text-red-700" onClick={() => onDelete(pos.id, pos.production_plan_id)}>
              Удалить
            </Button>
          )}
          {pos.status === 'invalid' && (
            <Button variant="ghost" size="sm" className="h-6 text-xs text-red-600 hover:text-red-700" onClick={() => onDelete(pos.id, pos.production_plan_id)}>
              Удалить
            </Button>
          )}
        </div>
        {pos.validation_status === 'invalid' && (
          <p className="text-xs text-red-600 mt-1 max-w-[250px]" title={reason}>{reason.slice(0, 50)}{reason.length > 50 ? '…' : ''}</p>
        )}
      </td>
    </tr>
  )
}

export function PlanPage() {
  const [importOpen, setImportOpen] = useState(false)
  const [testImportOpen, setTestImportOpen] = useState(false)
  const queryClient = useQueryClient()
  const [showAllFiles, setShowAllFiles] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [selectedRouteId, setSelectedRouteId] = useState<string>("")
  const [assigningRoute, setAssigningRoute] = useState(false)

  const { data: plans } = useQuery({ queryKey: ["plans"], queryFn: listPlans })
  const activePlan = plans && plans.length > 0 ? plans[0] : null

  const { data: routes } = useQuery({ queryKey: ["routes"], queryFn: () => listRoutes() })
  const activeRoutes = routes?.filter(r => r.is_active) ?? []

  const [filterStatus, setFilterStatus] = useState<"all" | "draft" | "valid" | "invalid">("all")

  const handleSuccess = () => {
    queryClient.invalidateQueries({ queryKey: ["plans"] })
    queryClient.invalidateQueries({ queryKey: ["all-plan-files"] })
    queryClient.invalidateQueries({ queryKey: ["all-plan-positions"] })
  }

  const handleApprove = async (positionId: number, planId?: number) => {
    const targetPlanId = planId || activePlan?.id
    if (!targetPlanId) return
    try {
      await apiClient.post(`/production-plans/${targetPlanId}/positions/${positionId}/approve`)
      queryClient.invalidateQueries({ queryKey: ["all-plan-positions"] })
      toast({ title: "Позиция утверждена", variant: "success" })
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Не удалось утвердить"
      toast({
        title: "Ошибка валидации",
        description: msg,
        variant: "destructive",
      })
    }
  }

  const handleDelete = async (positionId: number, planId?: number) => {
    const targetPlanId = planId || activePlan?.id
    if (!targetPlanId) return
    try {
      await apiClient.delete(`/production-plans/${targetPlanId}/positions/${positionId}`)
      queryClient.invalidateQueries({ queryKey: ["all-plan-positions"] })
      toast({ title: "Позиция удалена", variant: "success" })
    } catch (e) {
      toast({ title: "Ошибка", description: e instanceof Error ? e.message : "Не удалось удалить", variant: "destructive" })
    }
  }

  const handleDeleteFile = async (batchId: number) => {
    if (!activePlan) return
    try {
      await deleteImportBatch(activePlan.id, batchId)
      queryClient.invalidateQueries({ queryKey: ["all-plan-files"] })
      queryClient.invalidateQueries({ queryKey: ["all-plan-positions"] })
      toast({ title: "Импорт удалён", variant: "success" })
    } catch (e) {
      toast({ title: "Ошибка", description: e instanceof Error ? e.message : "Не удалось удалить импорт", variant: "destructive" })
    }
  }

  const toggleSelect = (id: number) => {
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const selectAll = () => {
    if (!filteredPositions) return
    if (selectedIds.size === filteredPositions.length) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(filteredPositions.map(p => p.id)))
    }
  }

  const clearSelection = () => setSelectedIds(new Set())

  const handleAssignRouteSingle = async (positionId: number, routeId: number | null) => {
    try {
      const rid = (routeId === null || Number.isNaN(routeId)) ? null : routeId
      await batchAssignRouteGlobal([positionId], rid)
      queryClient.invalidateQueries({ queryKey: ["all-plan-positions"] })
    } catch (e) {
      toast({
        title: "Ошибка",
        description: e instanceof Error ? e.message : "Не удалось назначить маршрут",
        variant: "destructive",
      })
    }
  }

  const handleAssignRoute = async () => {
    if (selectedIds.size === 0) return
    const routeId = selectedRouteId ? Number(selectedRouteId) : null
    setAssigningRoute(true)
    try {
      const result = await batchAssignRouteGlobal(Array.from(selectedIds), routeId)
      queryClient.invalidateQueries({ queryKey: ["all-plan-positions"] })
      toast({
        title: routeId ? "Маршрут назначен" : "Маршрут снят",
        description: `Обновлено позиций: ${result.updated_count}`,
        variant: "success",
      })
      setSelectedIds(new Set())
      setSelectedRouteId("")
    } catch (e) {
      toast({
        title: "Ошибка",
        description: e instanceof Error ? e.message : "Не удалось назначить маршрут",
        variant: "destructive",
      })
    } finally {
      setAssigningRoute(false)
    }
  }

  const { data: files, isLoading: filesLoading } = useQuery({
    queryKey: ["all-plan-files"],
    queryFn: () => allPlanFiles(),
  })

  const { data: positions, isLoading: posLoading } = useQuery({
    queryKey: ["all-plan-positions"],
    queryFn: () => allPlanPositions(),
  })

  const filteredPositions = useMemo(() => {
    if (!positions) return []
    if (filterStatus === "all") return positions
    if (filterStatus === "invalid") return positions.filter(p => p.validation_status === "invalid")
    return positions.filter(p => p.status === filterStatus)
  }, [positions, filterStatus])

  const totalQty = positions?.reduce((sum, p) => sum + Number(p.quantity || 0), 0) ?? 0
  const totalQtyStr = Number.isInteger(totalQty) ? String(totalQty) : totalQty.toFixed(3).replace(/\.?0+$/, '')
  const errorCount = positions?.filter(p => p.errors?.length > 0).length ?? 0
  const warningCount = positions?.filter(p => p.warnings?.length > 0).length ?? 0

  // Use file stats when positions are not yet created (change set not applied)
  const fileParsedRows = files?.reduce((sum, f) => sum + f.parsed_rows, 0) ?? 0
  const displayPositions = positions && positions.length > 0 ? positions.length : fileParsedRows
  const displayTotalQty = totalQty > 0 ? totalQtyStr : (fileParsedRows > 0 ? String(fileParsedRows) : "0")

  return (
    <>
      <header className="page-header">
        <div>
          <h1 className="page-title">План</h1>
          <p className="page-subtitle">Импорт производственного плана из Excel и запуск в производство.</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => setTestImportOpen(true)}>
            <Beaker className="h-4 w-4 mr-2" />
            Тестовый импорт
          </Button>
          <Button onClick={() => setImportOpen(true)}>
            <Plus className="h-4 w-4 mr-2" />
            Добавить файл
          </Button>
        </div>
      </header>

      {!activePlan && (
        <div className="rounded-lg border border-dashed p-12 text-center">
          <Upload className="h-12 w-12 mx-auto text-muted-foreground mb-3" />
          <h3 className="text-lg font-medium mb-1">Нет активного плана</h3>
          <p className="text-sm text-muted-foreground mb-4">
            Загрузите Excel-файл чтобы создать производственный план
          </p>
          <Button onClick={() => setImportOpen(true)}>
            <Upload className="h-4 w-4 mr-2" />
            Загрузить файл
          </Button>
        </div>
      )}

      {activePlan && (
        <div className="space-y-6">
          {/* Unified plan card: two columns */}
          <div className="rounded-lg border bg-card flex flex-col md:flex-row">
            {/* Left column: stats */}
            <div className="p-4 md:w-72 border-b md:border-b-0 md:border-r shrink-0">
              <h2 className="text-lg font-semibold mb-4">Общий план</h2>
              <div className="space-y-3 text-sm">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Файлов</span>
                  <strong>{files?.length ?? 0}</strong>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Позиций</span>
                  <strong>{displayPositions}</strong>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Общее кол-во</span>
                  <strong>{displayTotalQty}</strong>
                </div>
                {errorCount > 0 && (
                  <div className="flex justify-between text-red-600">
                    <span>Ошибок</span>
                    <strong>{errorCount}</strong>
                  </div>
                )}
                {warningCount > 0 && (
                  <div className="flex justify-between text-amber-600">
                    <span>Предупр.</span>
                    <strong>{warningCount}</strong>
                  </div>
                )}
              </div>
            </div>

            {/* Right column: files table */}
            <div className="flex-1 min-w-0">
              {filesLoading && <p className="p-4 text-sm text-muted-foreground">Загрузка...</p>}
              {files && files.length === 0 && (
                <div className="p-6 text-center text-sm text-muted-foreground">
                  Файлов пока нет. Нажмите «Добавить файл» чтобы загрузить Excel.
                </div>
              )}
              {files && files.length > 0 && (
                <div className="overflow-auto">
                  <table className="w-full">
                    <thead className="border-b bg-muted/50">
                      <tr>
                        <th className="text-left p-3 text-xs font-medium text-muted-foreground">Файл</th>
                        <th className="text-left p-3 text-xs font-medium text-muted-foreground">Дата загрузки</th>
                        <th className="text-left p-3 text-xs font-medium text-muted-foreground">Лист</th>
                        <th className="text-left p-3 text-xs font-medium text-muted-foreground">Строк</th>
                        <th className="text-left p-3 text-xs font-medium text-muted-foreground">Размер</th>
                        <th className="text-left p-3 text-xs font-medium text-muted-foreground">Статус</th>
                        <th className="text-left p-3 text-xs font-medium text-muted-foreground">Действия</th>
                      </tr>
                    </thead>
                    <tbody>
                      {files.slice(0, showAllFiles ? undefined : 5).map(f => <FileRow key={f.batch_id} file={f} activePlan={activePlan} onDelete={handleDeleteFile} />)}
                    </tbody>
                  </table>
                  {files.length > 5 && (
                    <button
                      onClick={() => setShowAllFiles(!showAllFiles)}
                      className="w-full text-center py-2 text-sm text-blue-600 hover:bg-muted/50 border-t"
                    >
                      {showAllFiles ? `Скрыть (показать 5)` : `Показать ещё ${files.length - 5} файл(ов)`}
                    </button>
                  )}
                </div>
              )}
            </div>
          </div>

          {/* Aggregated positions */}
          <section>
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-base font-semibold">Сводная таблица позиций</h3>
              <div className="flex gap-1">
                {(["all", "draft", "valid", "invalid"] as const).map((f) => (
                  <button
                    key={f}
                    onClick={() => setFilterStatus(f)}
                    className={`px-2.5 py-1 text-xs rounded-md border transition-colors ${
                      filterStatus === f
                        ? "bg-primary text-primary-foreground border-primary"
                        : "bg-background hover:bg-accent border-input"
                    }`}
                  >
                    {f === "all" ? "Все" : f === "draft" ? "Черновики" : f === "valid" ? "Валидные" : "Ошибки"}
                  </button>
                ))}
              </div>
            </div>

            {/* Route assignment toolbar */}
            {selectedIds.size > 0 && (
              <div className="flex items-center gap-3 mb-3 p-3 bg-blue-50 border border-blue-200 rounded-lg">
                <span className="text-sm font-medium text-blue-800">Выбрано: {selectedIds.size}</span>
                <Select value={selectedRouteId} onValueChange={setSelectedRouteId}>
                  <SelectTrigger className="w-56 h-8 text-sm">
                    <SelectValue placeholder="Выберите маршрут..." />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__clear__">— Снять маршрут —</SelectItem>
                    {activeRoutes.map(r => (
                      <SelectItem key={r.id} value={String(r.id)}>{r.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Button size="sm" className="h-8 text-sm" onClick={handleAssignRoute} disabled={assigningRoute || !selectedRouteId}>
                  {assigningRoute ? "Применение..." : "Применить маршрут"}
                </Button>
                <Button variant="ghost" size="sm" className="h-8 text-sm" onClick={clearSelection}>Сбросить</Button>
              </div>
            )}

            {posLoading && <p className="text-sm text-muted-foreground">Загрузка...</p>}
            {positions && positions.length > 0 && (
              <>
              <div className="rounded-lg border overflow-auto">
                <table className="w-full">
                  <thead className="border-b bg-muted/50">
                    <tr>
                      <th className="text-left p-2 text-xs font-medium text-muted-foreground w-10">
                        <Checkbox
                          checked={filteredPositions.length > 0 && selectedIds.size === filteredPositions.length}
                          onCheckedChange={selectAll}
                        />
                      </th>
                      <th className="text-left p-2 text-xs font-medium text-muted-foreground">Id</th>
                      <th className="text-left p-2 text-xs font-medium text-muted-foreground">Строка</th>
                      <th className="text-left p-2 text-xs font-medium text-muted-foreground">Артикул</th>
                      <th className="text-left p-2 text-xs font-medium text-muted-foreground">Наименование</th>
                      <th className="text-left p-2 text-xs font-medium text-muted-foreground">Кол-во</th>
                      <th className="text-left p-2 text-xs font-medium text-muted-foreground">Маршрут</th>
                      <th className="text-left p-2 text-xs font-medium text-muted-foreground">Статус</th>
                      <th className="text-left p-2 text-xs font-medium text-muted-foreground">Ошибки</th>
                      <th className="text-left p-2 text-xs font-medium text-muted-foreground">Предупр.</th>
                      <th className="text-left p-2 text-xs font-medium text-muted-foreground">Действия</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredPositions.map(p => <PositionRow key={p.id} pos={p} onApprove={handleApprove} onDelete={handleDelete} selected={selectedIds.has(p.id)} onToggle={toggleSelect} routes={activeRoutes} onAssignRoute={handleAssignRouteSingle} />)}
                  </tbody>
                </table>
              </div>
              {filteredPositions.length === 0 && (
                <p className="text-sm text-muted-foreground p-4 text-center">Нет позиций с таким фильтром</p>
              )}
              </>
            )}
          </section>
        </div>
      )}

      <ImportWizard open={importOpen} onClose={() => setImportOpen(false)} onSuccess={handleSuccess} productionPlanId={activePlan?.id} />
      <ImportWizard open={testImportOpen} onClose={() => setTestImportOpen(false)} onSuccess={handleSuccess} mode="test" productionPlanId={activePlan?.id} />
    </>
  )
}
