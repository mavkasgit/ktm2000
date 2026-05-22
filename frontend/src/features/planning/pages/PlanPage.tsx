import { useEffect, useMemo, useRef, useState } from "react"
import { Download, Eye, FileSpreadsheet, Plus, Upload, Route, Trash2, AlertTriangle, ListChecks } from "lucide-react"
import { ImportWizard } from "../ImportWizard"
import { Button, Badge, Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, Combobox, Select, SelectContent, SelectItem, SelectTrigger, SelectValue, AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogTitle, AlertDialogDescription, AlertDialogFooter, AlertDialogAction, AlertDialogCancel, SortableHeader, VirtualizedTableBody, FiltersPanel, type FiltersPanelField } from "@/shared/ui"
import { buildActiveFilterSummary } from "@/shared/ui/buildActiveFilterSummary"
import { useTableQueryEngine, SortConfig, ColumnSortDef } from "@/shared/hooks/useTableQueryEngine"
import { nextMultiSortConfigs } from "@/shared/lib/multiSort"
import { cn } from "@/shared/utils/cn"
import { toast } from "@/shared/ui"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { planFiles, allPositions, allPlanFiles, allPlanPositions, PlanFileInfo, PlanPositionOut, listPlans, PlanSummary, batchAssignRouteGlobal, deleteImportBatch, routeCheck, approveProductionPlanPosition, getPlanDuplicates } from "@/shared/api/productionPlans"
import { listRoutes, ProductionRoute } from "@/shared/api/routes"
import { listImportTemplates, ImportTemplate } from "@/shared/api/importTemplates"
import { getImportFileDownloadUrl } from "@/shared/api/imports"
import { apiClient, getErrorMessage } from "@/shared/api/client"
import { RowDetailsSidePanel, adaptPlanPositionOut } from "../components/row-details"
import {
  BulkResultsDialog,
  summarizeBulkResults,
  useBulkSelection,
  type BulkActionResultItem,
  type BulkActionSummary,
  type BulkRunnerProgress,
  BulkSelectionTable,
  type BulkSelectionRow,
  type BulkSelectionAction,
} from "@/shared/bulk"

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
  no_route_candidate: "Нет маршрута под правила выбора",
  route_rule_conflict: "Конфликт правил выбора маршрута",
  route_contains_excluded_step: "Маршрут содержит исключённый участок",
  selection_rules: "Маршрут выбран правилами",
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
  auto_fallback: "Маршрут скорректирован автоматически — проверьте",
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
  duplicate_sku_due_date: "Дубликат строки Excel: такая же строка уже есть",
  route_primary_operation_mismatch: "Основная операция маршрута не совпадает",
  route_not_matching_import_signature: "Маршрут не совпадает с ожидаемым",
  route_missing_required_step: "Отсутствует обязательный этап в маршруте",
  route_missing_pack_additional_operation: "Отсутствует доп. упаковочная операция",
  quantity_must_be_positive: "Количество должно быть > 0",
  route_signature_incomplete: "Сигнатура маршрута неполная",
  route_not_found: "Маршрут не найден",
  no_route_candidate: "Нет маршрута под правила выбора",
  route_rule_conflict: "Конфликт правил выбора маршрута",
  route_contains_excluded_step: "Маршрут содержит исключённый участок",
  selection_rules: "Маршрут выбран правилами",
}

const warningLabels: Record<string, string> = {
  paired_profile_product_unmapped: "Парный профиль не сопоставлен",
  techcard_pair_not_resolved: "Не выбран парный профиль техкарты",
  product_name_missing: "Отсутствует наименование",
  period_not_detected: "не определен",
  route_auto_fallback: "Маршрут скорректирован автоматически — проверьте корректность",
}

type PlanSortField = "id" | "rowNum" | "sku" | "name" | "qty" | "route" | "status" | "validation" | "errors" | "warnings"

interface PlanFiltersState {
  status: "all" | "draft" | "valid" | "invalid"
  validation_status: "all" | "valid" | "invalid"
  has_route: "all" | "yes" | "no"
  has_errors: "all" | "yes" | "no"
  has_warnings: "all" | "yes" | "no"
  has_duplicates: "all" | "yes" | "no"
}

function translateLabel(code: string, labels: Record<string, string>): string {
  const [base] = String(code).split(":")
  return labels[base] ?? code
}

function formatRouteAssignedAt(value: string | null | undefined): string {
  if (!value) return "дата неизвестна"
  const dt = new Date(value)
  if (Number.isNaN(dt.getTime())) return "дата неизвестна"
  return dt.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
}

function routeMetaLabel(pos: PlanPositionOut): string {
  const assignedAt = formatRouteAssignedAt(pos.route_assigned_at)
  if (pos.route_origin === "manual_confirmed" || pos.route_source === "manual") {
    return `вручную • ${assignedAt}`
  }
  if (pos.route_origin === "auto" || pos.route_source === "auto") {
    const quality = pos.route_match_quality === "exact" ? "полное" : "скорректирован"
    return `автомаппинг (${quality}) • ${assignedAt}`
  }
  if (pos.route_origin === "legacy" || pos.route_source === "legacy") {
    return "legacy • дата неизвестна"
  }
  return ""
}

type DuplicateConflict = {
  fingerprint: string
  conflictIds: number[]
}

function isRiskyForApprove(pos: PlanPositionOut, duplicateConflict?: DuplicateConflict): boolean {
  const hasRouteProblems =
    pos.route_match_quality === "corrected" ||
    pos.route_origin === "legacy" ||
    pos.route_error !== null ||
    pos.route_match_reason !== null ||
    (pos.warnings && pos.warnings.length > 0) ||
    (pos.errors && pos.errors.length > 0)
  return hasRouteProblems || Boolean(duplicateConflict && duplicateConflict.conflictIds.length > 0)
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

function PositionRow({ pos, onApprove, onDelete, selected, routes, onAssignRoute, onOpenDetail, duplicateConflict, onJumpToPosition, onSelect }: {
  pos: PlanPositionOut;
  onApprove: (id: number, planId?: number, force?: boolean) => Promise<void>;
  onDelete: (id: number, planId?: number) => void;
  selected?: boolean;
  routes?: ProductionRoute[];
  onAssignRoute?: (positionId: number, routeId: number | null) => void;
  onOpenDetail?: () => void;
  duplicateConflict?: DuplicateConflict;
  onJumpToPosition?: (id: number) => void;
  onSelect?: (id: number) => void;
}) {
  const hasErrors = pos.errors && pos.errors.length > 0
  const hasWarnings = pos.warnings && pos.warnings.length > 0
  const qty = Number(pos.quantity || 0)
  const qtyStr = Number.isInteger(qty) ? String(qty) : qty.toFixed(3).replace(/\.?0+$/, '')
  const translatedErrors = hasErrors ? pos.errors.map((e) => translateLabel(e, errorLabels)) : []
  const translatedWarnings = hasWarnings ? pos.warnings.map((w) => translateLabel(w, warningLabels)) : []
  const rowNum = (() => {
    const numbers = Array.isArray(pos.source_row_numbers)
      ? pos.source_row_numbers.filter((v): v is number => typeof v === "number")
      : []
    if (numbers.length > 0) return numbers.join(",")
    return pos.source_row_number ?? "—"
  })()
  const routeSourceLabel = routeMetaLabel(pos)
  const routeError = pos.route_error ? translateLabel(pos.route_error, routeErrorLabels) : null
  const hasDuplicateConflict = Boolean(duplicateConflict && duplicateConflict.conflictIds.length > 0)
  const canApprove =
    (pos.status === 'draft' || pos.status === 'valid') &&
    pos.validation_status === 'valid' &&
    pos.route_id !== null

  const [approveDialogOpen, setApproveDialogOpen] = useState(false)
  const [approving, setApproving] = useState(false)

  // Route-check runs eagerly for all positions with an assigned route
  const { data: routeCheckData, isLoading: routeCheckLoading, error: routeCheckError } = useQuery({
    queryKey: ["route-check", pos.production_plan_id, pos.id],
    queryFn: () => routeCheck(pos.production_plan_id!, pos.id),
    enabled: pos.route_id !== null && pos.validation_status === "valid",
    staleTime: 60_000,
  })

  const routeCheckRisky = routeCheckData !== undefined && (
    !routeCheckData.match || (routeCheckData.issues && routeCheckData.issues.length > 0)
  )

  const handleApproveClick = (e: React.MouseEvent) => {
    e.stopPropagation()
    if (isRiskyForApprove(pos, duplicateConflict) || routeCheckRisky) {
      setApproveDialogOpen(true)
    } else {
      onApprove(pos.id, pos.production_plan_id)
    }
  }

  const handleConfirmApprove = async () => {
    setApproving(true)
    try {
      await onApprove(pos.id, pos.production_plan_id, true)
    } finally {
      setApproving(false)
      setApproveDialogOpen(false)
    }
  }

  const handleDeleteClick = (e: React.MouseEvent) => {
    e.stopPropagation()
    onDelete(pos.id, pos.production_plan_id)
  }

  const detailedReasons = useMemo(() => {
    const sections: { title: string; items: string[] }[] = []

    // Section 1: Route mismatch issues from route-check
    const routeIssues = routeCheckData?.issues ?? []
    if (routeIssues.length > 0) {
      sections.push({
        title: "Несовпадения маршрута",
        items: routeIssues.map((issue) => translateLabel(issue, routeErrorLabels)),
      })
    }

    // Section 2: Position warnings and errors
    const positionMessages: string[] = []
    if (translatedWarnings.length > 0) positionMessages.push(...translatedWarnings)
    if (translatedErrors.length > 0) positionMessages.push(...translatedErrors)
    if (positionMessages.length > 0) {
      sections.push({
        title: "Предупреждения позиции",
        items: positionMessages,
      })
    }

    // Section 3: Route-check issues (when route-check found problems not reflected in position errors)
    if (routeCheckData && !routeCheckData.match && routeIssues.length > 0) {
      sections.push({
        title: "Проверка маршрута",
        items: routeIssues.map((issue) => translateLabel(issue, routeErrorLabels)),
      })
    }

    // Section 4: Route risk factors
    const riskFactors: string[] = []
    if (pos.route_match_quality === "corrected") {
      const qualityDetail = pos.route_match_reason ? translateLabel(pos.route_match_reason, routeErrorLabels) : null
      const parts = ["Маршрут скорректирован"]
      if (pos.route_name) parts.push(`маршрут: ${pos.route_name}`)
      if (qualityDetail) parts.push(`причина: ${qualityDetail}`)
      if (pos.route_origin === "manual_confirmed") parts.push("подтверждён вручную")
      riskFactors.push(parts.join(" • "))
    } else if (pos.route_match_reason) {
      const reasonDetail = translateLabel(pos.route_match_reason, routeErrorLabels)
      riskFactors.push(`Причина сопоставления: ${reasonDetail}`)
    }
    if (pos.route_origin === "legacy") {
      const parts = ["Использован legacy-маршрут"]
      if (pos.route_name) parts.push(`маршрут: ${pos.route_name}`)
      riskFactors.push(parts.join(" • "))
    }
    if (pos.route_error) {
      riskFactors.push(translateLabel(pos.route_error, routeErrorLabels))
    }
    if (riskFactors.length > 0) {
      sections.push({
        title: "Факторы риска подтверждения",
        items: riskFactors,
      })
    }

    return sections
  }, [routeCheckData, translatedWarnings, translatedErrors, pos])

  return (
    <>
    <tr
      id={`plan-position-${pos.id}`}
      className={`border-b ${hasErrors || hasDuplicateConflict ? "bg-red-50" : hasWarnings ? "bg-amber-50" : ""} ${selected ? "bg-blue-100 ring-1 ring-blue-300" : ""} cursor-pointer hover:bg-accent hover:ring-1 hover:ring-ring/20 transition-colors`}
      onClick={(e) => {
        if (onSelect) {
          e.stopPropagation()
          onSelect(pos.id)
        } else {
          onOpenDetail?.()
        }
      }}
    >
      <td className="p-2 text-sm">
        <span className="text-muted-foreground">#{pos.id}</span>
      </td>
      <td className="p-2 text-sm font-medium">{rowNum}</td>
      <td className="p-2 text-sm">{pos.source_sku}</td>
      <td className="p-2 text-sm">{pos.source_name ?? "—"}</td>
      <td className="p-2 text-sm">{qtyStr}</td>
      <td className="p-2 text-sm min-w-[200px]">
        {routes && onAssignRoute ? (
          <div onClick={(e) => e.stopPropagation()}>
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
                    {routeSourceLabel && <span className="text-xs text-muted-foreground ml-1">({routeSourceLabel})</span>}
                  </span>
                ) : (
                  <span className={cn("text-xs", routeError ? "text-red-600" : "text-muted-foreground group-hover:text-foreground")}>
                    {routeError || "Нажмите для выбора"}
                  </span>
                )}
              </span>
            }
          />
          </div>
        ) : pos.route_name ? (
          <span className="inline-flex items-center gap-1 text-blue-700" title={`Маршрут #${pos.route_id} ${routeSourceLabel}`}>
            <Route className="h-3 w-3" />
            {pos.route_name}
            {routeSourceLabel && <span className="text-xs text-muted-foreground">({routeSourceLabel})</span>}
          </span>
        ) : (
          <span className={routeError ? "text-red-600 text-xs" : "text-muted-foreground text-xs"} title={routeError || undefined}>
            {routeError || "Не назначен"}
          </span>
        )}
      </td>
      <td className="p-2 text-xs text-red-600 max-w-[200px]">
        {hasErrors || hasDuplicateConflict ? (
          <div className="space-y-1">
            {hasDuplicateConflict && (
              <div className="text-red-700">
                <span className="block">Дубликат Excel-строки</span>
                <div className="flex flex-wrap gap-1 mt-1">
                  {duplicateConflict?.conflictIds.map((id) => (
                    <button
                      key={id}
                      type="button"
                      className="underline hover:no-underline"
                      onClick={(e) => {
                        e.stopPropagation()
                        onJumpToPosition?.(id)
                      }}
                    >
                      #{id}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {hasErrors && (
              <span className="truncate block" title={translatedErrors.join("\n")}>
                {translatedErrors.join(", ")}
              </span>
            )}
          </div>
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
          {canApprove && (
            <>
              <Button variant="ghost" size="sm" className="h-6 text-xs text-green-700 hover:text-green-800" onClick={handleApproveClick} disabled={approving}>
                Утвердить
              </Button>
              <Button variant="ghost" size="sm" className="h-6 text-xs text-red-600 hover:text-red-700" onClick={handleDeleteClick} disabled={approving}>
                Удалить
              </Button>
            </>
          )}
          {!canApprove && (
            <Button variant="ghost" size="sm" className="h-6 text-xs text-red-600 hover:text-red-700" onClick={handleDeleteClick}>
              Удалить
            </Button>
          )}
        </div>
      </td>
    </tr>

    <AlertDialog open={approveDialogOpen} onOpenChange={setApproveDialogOpen}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle className="flex items-center gap-2">
            <AlertTriangle className="h-5 w-5 text-amber-500" />
            Позиция требует внимания
          </AlertDialogTitle>
          <AlertDialogDescription className="text-left">
            Эта позиция может содержать некорректные данные. Утверждение потребует последующей проверки.
          </AlertDialogDescription>
        </AlertDialogHeader>

        {routeCheckLoading && (
          <div className="text-sm text-muted-foreground">Загрузка диагностики...</div>
        )}

        {routeCheckError && !routeCheckLoading && (
          <div className="rounded-md border bg-amber-50 p-3 mb-3">
            <p className="text-sm font-medium mb-1">Диагностика недоступна</p>
            <p className="text-xs text-muted-foreground">Не удалось получить детали проверки маршрута, но вы можете продолжить утверждение.</p>
          </div>
        )}

        {!routeCheckLoading && detailedReasons.length > 0 && (
          <div className="space-y-3">
            {detailedReasons.map((section, idx) => (
              <div key={idx} className="rounded-md border bg-amber-50 p-3">
                <p className="text-sm font-medium mb-2">{section.title}</p>
                <ul className="text-sm text-muted-foreground space-y-1">
                  {section.items.map((item, i) => (
                    <li key={i} className="flex items-start gap-2">
                      <span className="mt-1 h-1.5 w-1.5 rounded-full bg-amber-500 shrink-0" />
                      {item}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        )}

        {hasDuplicateConflict && (
          <div className="rounded-md border bg-red-50 p-3">
            <p className="text-sm font-medium mb-2">
              Дубликат Excel-строки
            </p>
            <div className="flex flex-wrap gap-2">
              {duplicateConflict?.conflictIds.map((id) => (
                <button
                  key={id}
                  type="button"
                  className="text-sm underline text-red-700 hover:no-underline"
                  onClick={() => onJumpToPosition?.(id)}
                >
                  Перейти к позиции #{id}
                </button>
              ))}
            </div>
          </div>
        )}

        <AlertDialogFooter>
          <AlertDialogCancel disabled={approving}>Отмена</AlertDialogCancel>
          <AlertDialogAction onClick={handleConfirmApprove} disabled={approving}>
            {approving ? "Утверждение..." : "Утвердить всё равно"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
    </>
  )
}

export function PlanPage() {
  const [importOpen, setImportOpen] = useState(false)
  const queryClient = useQueryClient()
  const [showAllFiles, setShowAllFiles] = useState(false)
  const bulkSelection = useBulkSelection<number>()
  const [bulkMode, setBulkMode] = useState(false)
  const [selectionOrder, setSelectionOrder] = useState<number[]>([])
  const [bulkApproving, setBulkApproving] = useState(false)
  const [bulkDeleting, setBulkDeleting] = useState(false)
  const [bulkDeleteConfirmOpen, setBulkDeleteConfirmOpen] = useState(false)
  const [bulkProgress, setBulkProgress] = useState<BulkRunnerProgress | null>(null)
  const [bulkResults, setBulkResults] = useState<BulkActionResultItem<number>[]>([])
  const [bulkSummary, setBulkSummary] = useState<BulkActionSummary | null>(null)
  const [bulkResultsOpen, setBulkResultsOpen] = useState(false)
  const [detailPosition, setDetailPosition] = useState<PlanPositionOut | null>(null)
  const [detailOpen, setDetailOpen] = useState(false)
  const tableScrollRef = useRef<HTMLDivElement>(null)

  const openDetail = (pos: PlanPositionOut) => {
    setDetailPosition(pos)
    setDetailOpen(true)
  }

  const { data: plans } = useQuery({ queryKey: ["plans"], queryFn: listPlans })
  const activePlan = plans && plans.length > 0 ? plans[0] : null

  const { data: routes } = useQuery({ queryKey: ["routes"], queryFn: () => listRoutes() })
  const activeRoutes = routes?.filter(r => r.is_active) ?? []

  const { data: templates } = useQuery({ queryKey: ["import-templates"], queryFn: listImportTemplates })
  const activeTemplates = (templates ?? []).filter(t => t.is_active).sort((a, b) => a.sort_order - b.sort_order)

  const [filters, setFilters] = useState<PlanFiltersState>({
    status: "all",
    validation_status: "all",
    has_route: "all",
    has_errors: "all",
    has_warnings: "all",
    has_duplicates: "all",
  })
  const [searchQuery, setSearchQuery] = useState("")
  const [sortConfigs, setSortConfigs] = useState<SortConfig<PlanSortField>[]>([])
  const [templateImportOpen, setTemplateImportOpen] = useState<number | null>(null)

  const { data: duplicateGroupsByPlan } = useQuery({
    queryKey: ["plan-duplicates-all", plans?.map((p) => p.id).join(",")],
    queryFn: async () => {
      const planIds = (plans ?? []).map((p) => p.id)
      const entries = await Promise.all(
        planIds.map(async (planId) => [planId, await getPlanDuplicates(planId)] as const),
      )
      return Object.fromEntries(entries) as Record<number, Awaited<ReturnType<typeof getPlanDuplicates>>>
    },
    enabled: (plans?.length ?? 0) > 0,
    staleTime: 30_000,
  })

  const handleSuccess = () => {
    queryClient.invalidateQueries({ queryKey: ["plans"] })
    queryClient.invalidateQueries({ queryKey: ["all-plan-files"] })
    queryClient.invalidateQueries({ queryKey: ["all-plan-positions"] })
    queryClient.invalidateQueries({ queryKey: ["plan-duplicates-all"] })
  }

  const handleApprove = async (positionId: number, planId?: number, force = false) => {
    const targetPlanId = planId || activePlan?.id
    if (!targetPlanId) return
    try {
      await approveProductionPlanPosition(targetPlanId, positionId, { force })
      queryClient.invalidateQueries({ queryKey: ["all-plan-positions"] })
      queryClient.invalidateQueries({ queryKey: ["plan-duplicates-all"] })
      queryClient.invalidateQueries({ queryKey: ["production-planning-rows"] })
      toast({ title: "Позиция утверждена", variant: "success" })
    } catch (e) {
      const msg = getErrorMessage(e)
      const duplicateConflict = duplicateConflictsByPosition.get(positionId)
      const duplicateLinksPrefix =
        duplicateConflict && duplicateConflict.conflictIds.length > 0
          ? `Конфликтующие позиции: ${duplicateConflict.conflictIds.map((id) => `#${id}`).join(", ")}. `
          : ""
      toast({
        title: "Ошибка валидации",
        description: `${duplicateLinksPrefix}${msg}`,
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
      queryClient.invalidateQueries({ queryKey: ["plan-duplicates-all"] })
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
    const wasSelected = bulkSelection.isSelected(id)
    bulkSelection.selectOne(id)
    if (!wasSelected) {
      setSelectionOrder(prev => [id, ...prev])
    } else {
      setSelectionOrder(prev => prev.filter(x => x !== id))
    }
  }

  const selectAll = () => {
    if (bulkSelection.isAllSelected(filteredPositionIds)) {
      bulkSelection.clear()
      setSelectionOrder([])
    } else {
      bulkSelection.selectAllFiltered(filteredPositionIds)
      setSelectionOrder([...filteredPositionIds])
    }
  }

  const resetAllFilters = () => {
    setSearchQuery("")
    setSortConfigs([])
    setFilters({
      status: "all",
      validation_status: "all",
      has_route: "all",
      has_errors: "all",
      has_warnings: "all",
      has_duplicates: "all",
    })
  }

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

  const exitBulkMode = () => {
    bulkSelection.clear()
    setSelectionOrder([])
    setBulkMode(false)
  }

  useEffect(() => {
    if (!bulkMode) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") exitBulkMode()
    }
    window.addEventListener("keydown", handler)
    return () => window.removeEventListener("keydown", handler)
  }, [bulkMode])

  const canApprovePosition = (pos: PlanPositionOut) =>
    (pos.status === 'draft' || pos.status === 'valid') &&
    pos.validation_status === 'valid' &&
    pos.route_id !== null

  const getApproveIneligibleReason = (pos: PlanPositionOut): string | null => {
    if (pos.status === 'approved' || pos.status === 'released') return "Уже утверждена"
    if (pos.validation_status !== 'valid') return "Валидация не пройдена"
    if (!pos.route_id) return "Нет маршрута"
    return null
  }

  const handleBulkApprove = async () => {
    if (bulkSelection.selectedCount === 0) return
    const selectedIds = Array.from(bulkSelection.selectedIds)
    const selectedPositionsMap = new Map(positions?.map(p => [p.id, p]) ?? [])

    const results: BulkActionResultItem<number>[] = []
    setBulkProgress({ total: selectedIds.length, completed: 0, running: true })
    setBulkApproving(true)

    for (let i = 0; i < selectedIds.length; i++) {
      const id = selectedIds[i]
      const pos = selectedPositionsMap.get(id)
      if (!pos) {
        results.push({ id, status: "failed", reason: "Позиция не найдена" })
      } else if (!canApprovePosition(pos)) {
        results.push({ id, status: "skipped", reason: getApproveIneligibleReason(pos) ?? "Не может быть утверждена" })
      } else {
        try {
          await approveProductionPlanPosition(pos.production_plan_id, id, { force: false })
          results.push({ id, status: "success" })
        } catch (e) {
          results.push({ id, status: "failed", reason: getErrorMessage(e) })
        }
      }
      setBulkProgress({ total: selectedIds.length, completed: i + 1, running: i + 1 < selectedIds.length })
    }

    const summary = summarizeBulkResults(results)
    setBulkResults(results)
    setBulkSummary(summary)
    if (summary.failed > 0) setBulkResultsOpen(true)
    setBulkApproving(false)
    setBulkProgress(null)
    queryClient.invalidateQueries({ queryKey: ["all-plan-positions"] })
    queryClient.invalidateQueries({ queryKey: ["plan-duplicates-all"] })
    queryClient.invalidateQueries({ queryKey: ["production-planning-rows"] })
    const failedEntries = results.filter(r => r.status === "failed")
    toast({
      title: summary.failed > 0 ? "Частичный успех" : "Массовое утверждение",
      description: summary.failed > 0
        ? `${summary.success} успешно, ${summary.failed} ошибок. ${failedEntries.slice(0, 3).map(r => `#${r.id}: ${r.reason}`).join("; ")}`
        : `${summary.success} успешно, ${summary.skipped} пропущено`,
      variant: summary.failed > 0 ? "destructive" : "success",
    })
    bulkSelection.clear()
    setSelectionOrder([])
  }

  const requestBulkDelete = () => {
    if (bulkSelection.selectedCount === 0) return
    setBulkDeleteConfirmOpen(true)
  }

  const confirmBulkDelete = async () => {
    setBulkDeleteConfirmOpen(false)
    if (bulkSelection.selectedCount === 0) return
    const selectedIds = Array.from(bulkSelection.selectedIds)
    const selectedPositionsMap = new Map(positions?.map(p => [p.id, p]) ?? [])

    const results: BulkActionResultItem<number>[] = []
    setBulkProgress({ total: selectedIds.length, completed: 0, running: true })
    setBulkDeleting(true)

    for (let i = 0; i < selectedIds.length; i++) {
      const id = selectedIds[i]
      const pos = selectedPositionsMap.get(id)
      if (!pos) {
        results.push({ id, status: "failed", reason: "Позиция не найдена" })
      } else {
        try {
          await apiClient.delete(`/production-plans/${pos.production_plan_id}/positions/${id}`)
          results.push({ id, status: "success" })
        } catch (e) {
          results.push({ id, status: "failed", reason: e instanceof Error ? e.message : "Не удалось удалить" })
        }
      }
      setBulkProgress({ total: selectedIds.length, completed: i + 1, running: i + 1 < selectedIds.length })
    }

    const summary = summarizeBulkResults(results)
    setBulkResults(results)
    setBulkSummary(summary)
    if (summary.failed > 0) setBulkResultsOpen(true)
    setBulkDeleting(false)
    setBulkProgress(null)
    queryClient.invalidateQueries({ queryKey: ["all-plan-positions"] })
    queryClient.invalidateQueries({ queryKey: ["plan-duplicates-all"] })
    const failedEntries = results.filter(r => r.status === "failed")
    toast({
      title: summary.failed > 0 ? "Частичный успех" : "Массовое удаление",
      description: summary.failed > 0
        ? `${summary.success} успешно, ${summary.failed} ошибок. ${failedEntries.slice(0, 3).map(r => `#${r.id}: ${r.reason}`).join("; ")}`
        : `${summary.success} успешно`,
      variant: summary.failed > 0 ? "destructive" : "success",
    })
    bulkSelection.clear()
    setSelectionOrder([])
  }

  const { data: files, isLoading: filesLoading } = useQuery({
    queryKey: ["all-plan-files"],
    queryFn: () => allPlanFiles(),
  })

  const { data: positions, isLoading: posLoading } = useQuery({
    queryKey: ["all-plan-positions"],
    queryFn: () => allPlanPositions(),
  })

  const duplicateConflictsByPosition = useMemo(() => {
    const map = new Map<number, DuplicateConflict>()
    if (!duplicateGroupsByPlan) return map
    for (const groups of Object.values(duplicateGroupsByPlan)) {
      for (const group of groups) {
        const ids = group.positions.map((position) => position.id)
        for (const id of ids) {
          map.set(id, {
            fingerprint: group.source_fingerprint,
            conflictIds: ids.filter((otherId) => otherId !== id),
          })
        }
      }
    }
    return map
  }, [duplicateGroupsByPlan])

  // Build filter predicate from PlanFiltersState
  const filterPredicate = useMemo(() => {
    if (
      filters.status === "all" &&
      filters.validation_status === "all" &&
      filters.has_route === "all" &&
      filters.has_errors === "all" &&
      filters.has_warnings === "all" &&
      filters.has_duplicates === "all"
    ) return null

    return (row: PlanPositionOut) => {
      if (filters.status !== "all" && row.status !== filters.status) return false
      if (filters.validation_status !== "all" && row.validation_status !== filters.validation_status) return false
      if (filters.has_route === "yes" && !row.route_id) return false
      if (filters.has_route === "no" && row.route_id) return false
      if (filters.has_errors === "yes" && (!row.errors || row.errors.length === 0)) return false
      if (filters.has_errors === "no" && row.errors && row.errors.length > 0) return false
      if (filters.has_warnings === "yes" && (!row.warnings || row.warnings.length === 0)) return false
      if (filters.has_warnings === "no" && row.warnings && row.warnings.length > 0) return false
      if (filters.has_duplicates === "yes" && !duplicateConflictsByPosition.has(row.id)) return false
      if (filters.has_duplicates === "no" && duplicateConflictsByPosition.has(row.id)) return false
      return true
    }
  }, [filters, duplicateConflictsByPosition])

  // Sort definitions for PlanPage columns
  const sortDefs: ColumnSortDef<PlanPositionOut, PlanSortField>[] = useMemo(() => [
    { field: "id", getSortValue: (p) => p.id },
    {
      field: "rowNum",
      getSortValue: (p) => {
        const numbers = Array.isArray(p.source_row_numbers)
          ? p.source_row_numbers.filter((v): v is number => typeof v === "number")
          : []
        return numbers.length > 0 ? Math.min(...numbers) : (p.source_row_number ?? 0)
      },
    },
    { field: "sku", getSortValue: (p) => p.source_sku },
    { field: "name", getSortValue: (p) => p.source_name ?? "" },
    { field: "qty", getSortValue: (p) => Number(p.quantity || 0) },
    { field: "route", getSortValue: (p) => p.route_name ?? "" },
    { field: "status", getSortValue: (p) => p.status },
    { field: "validation", getSortValue: (p) => p.validation_status },
    { field: "errors", getSortValue: (p) => p.errors?.length ?? 0 },
    { field: "warnings", getSortValue: (p) => p.warnings?.length ?? 0 },
  ], [])

  const result = useTableQueryEngine<PlanPositionOut, PlanSortField>({
    rows: positions ?? [],
    getId: (p) => p.id,
    searchQuery,
    filterPredicate,
    sortConfigs,
    sortDefs,
  })
  const processedRows = result.rows
  const filteredPositionIds = useMemo(() => processedRows.map((p) => p.id), [processedRows])
  const activeFilterSummary = useMemo(
    () => buildActiveFilterSummary(filters, searchQuery, sortConfigs.length),
    [filters, searchQuery, sortConfigs.length],
  )
  const filterFields = useMemo<FiltersPanelField[]>(
    () => [
      {
        kind: "search",
        key: "search",
        value: searchQuery,
        onChange: setSearchQuery,
        placeholder: "Поиск: ID, строка, артикул, наименование...",
        layoutSpan: "md:col-span-2 xl:col-span-2",
      },
      {
        kind: "select",
        key: "status",
        value: filters.status,
        onChange: (value) => setFilters((prev) => ({ ...prev, status: value as PlanFiltersState["status"] })),
        placeholder: "Статус позиции",
        options: [
          { value: "all", label: "Статус: все" },
          { value: "draft", label: "Статус: черновик" },
          { value: "valid", label: "Статус: валиден" },
          { value: "invalid", label: "Статус: ошибка" },
        ],
      },
      {
        kind: "select",
        key: "validation_status",
        value: filters.validation_status,
        onChange: (value) => setFilters((prev) => ({ ...prev, validation_status: value as PlanFiltersState["validation_status"] })),
        placeholder: "Валидация",
        options: [
          { value: "all", label: "Валидация: все" },
          { value: "valid", label: "Валидация: пройдена" },
          { value: "invalid", label: "Валидация: ошибка" },
        ],
      },
      {
        kind: "select",
        key: "has_route",
        value: filters.has_route,
        onChange: (value) => setFilters((prev) => ({ ...prev, has_route: value as PlanFiltersState["has_route"] })),
        placeholder: "Маршрут",
        options: [
          { value: "all", label: "Маршрут: все" },
          { value: "yes", label: "Маршрут: назначен" },
          { value: "no", label: "Маршрут: не назначен" },
        ],
      },
      {
        kind: "select",
        key: "has_errors",
        value: filters.has_errors,
        onChange: (value) => setFilters((prev) => ({ ...prev, has_errors: value as PlanFiltersState["has_errors"] })),
        placeholder: "Ошибки",
        options: [
          { value: "all", label: "Ошибки: все" },
          { value: "yes", label: "Ошибки: есть" },
          { value: "no", label: "Ошибки: нет" },
        ],
      },
      {
        kind: "select",
        key: "has_warnings",
        value: filters.has_warnings,
        onChange: (value) => setFilters((prev) => ({ ...prev, has_warnings: value as PlanFiltersState["has_warnings"] })),
        placeholder: "Предупреждения",
        options: [
          { value: "all", label: "Предупр.: все" },
          { value: "yes", label: "Предупр.: есть" },
          { value: "no", label: "Предупр.: нет" },
        ],
      },
      {
        kind: "select",
        key: "has_duplicates",
        value: filters.has_duplicates,
        onChange: (value) => setFilters((prev) => ({ ...prev, has_duplicates: value as PlanFiltersState["has_duplicates"] })),
        placeholder: "Дубликаты",
        options: [
          { value: "all", label: "Дубликаты: все" },
          { value: "yes", label: "Дубликаты: есть" },
          { value: "no", label: "Дубликаты: нет" },
        ],
      },
    ],
    [filters, searchQuery],
  )

  // Sort toggle handler: click cycles none -> asc -> desc -> removed
  const handleSortChange = (field: PlanSortField) => {
    setSortConfigs((prev) => nextMultiSortConfigs(prev, field))
  }

  const getAriaSort = (field: PlanSortField): "none" | "ascending" | "descending" => {
    const active = sortConfigs.find((s) => s.field === field)
    if (!active) return "none"
    return active.order === "asc" ? "ascending" : "descending"
  }

  const jumpToPosition = (positionId: number) => {
    setFilters(prev => ({ ...prev, status: "all" }))
    const targetPosition = positions?.find((p) => p.id === positionId)
    if (targetPosition) {
      setDetailPosition(targetPosition)
      setDetailOpen(true)
    }
    setTimeout(() => {
      const row = document.getElementById(`plan-position-${positionId}`)
      if (!row) return
      row.scrollIntoView({ behavior: "smooth", block: "center" })
      row.classList.add("ring-2", "ring-red-300")
      setTimeout(() => row.classList.remove("ring-2", "ring-red-300"), 1800)
    }, 0)
  }

  const detailData = useMemo(() => {
    if (!detailPosition) return null
    const data = adaptPlanPositionOut(detailPosition)
    const duplicateConflict = duplicateConflictsByPosition.get(detailPosition.id)
    if (duplicateConflict && duplicateConflict.conflictIds.length > 0) {
      data.duplicateConflictIds = duplicateConflict.conflictIds
    }
    return data
  }, [detailPosition, duplicateConflictsByPosition])

  const bulkSelectionRows = useMemo<BulkSelectionRow[]>(() => {
    const posMap = new Map(positions?.map(p => [p.id, p]) ?? [])
    return selectionOrder.map(id => {
      const pos = posMap.get(id)
      return {
        id,
        cells: {
          id: `#${id}`,
          sku: pos?.source_sku ?? "—",
          name: pos?.source_name ?? "—",
          qty: pos ? Number(pos.quantity || 0).toString() : "0",
          route: pos?.route_name ?? "—",
        },
      }
    })
  }, [selectionOrder, positions])

  const bulkActions = useMemo<BulkSelectionAction[]>(() => [
    {
      id: "approve",
      label: "Утвердить",
      variant: "success" as const,
      onClick: handleBulkApprove,
      disabled: bulkSelection.selectedCount === 0 || bulkApproving || bulkDeleting,
      pending: bulkApproving,
    },
    {
      id: "delete",
      label: "Удалить",
      variant: "destructive" as const,
      onClick: requestBulkDelete,
      disabled: bulkSelection.selectedCount === 0 || bulkApproving || bulkDeleting,
      pending: bulkDeleting,
    },
  ], [bulkSelection.selectedCount, bulkApproving, bulkDeleting, handleBulkApprove, requestBulkDelete])

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
      {!bulkMode && (
      <header className="page-header">
        <div>
          <h1 className="page-title">План</h1>
          <p className="page-subtitle">Импорт производственного плана из Excel и запуск в производство.</p>
        </div>
        <div className="flex gap-2 flex-wrap">
          {activeTemplates.map(t => (
            <Button key={t.id} variant="secondary" onClick={() => setTemplateImportOpen(t.id)}>
              <FileSpreadsheet className="h-4 w-4 mr-2" />
              {t.button_label || t.name}
            </Button>
          ))}
          <Button onClick={() => setImportOpen(true)}>
            <Plus className="h-4 w-4 mr-2" />
            Добавить файл
          </Button>
        </div>
      </header>
      )}

      {!bulkMode && !activePlan && (
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

      {!bulkMode && activePlan && (
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
        </div>
      )}

      {activePlan && (
        <div className={bulkMode ? "fixed inset-0 z-50 bg-background flex flex-col p-4 overflow-auto" : undefined}>
          {bulkMode && (
            <div className="mb-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <ListChecks className="h-5 w-5 text-primary" />
                  <span className="text-lg font-semibold">Групповые операции</span>
                  <span className="text-sm text-muted-foreground">Выбрано: {bulkSelection.selectedCount}</span>
                </div>
                <Button variant="outline" size="sm" onClick={exitBulkMode}>
                  Выйти
                </Button>
              </div>
              <p className="text-sm text-muted-foreground mt-1">
                Выбирайте позиции кликом по строке, используйте фильтры для отбора. Примените действие — «Утвердить» или «Удалить». <kbd className="px-1 py-0.5 text-xs rounded bg-muted font-mono">Esc</kbd> — выход.
              </p>
            </div>
          )}

          {/* Aggregated positions */}
          <section className="flex-1 flex flex-col">
            {!bulkMode && (
            <div className="flex items-center gap-2 mb-2">
              <h3 className="text-base font-semibold">Сводная таблица позиций</h3>
              <span className="inline-flex items-center justify-center h-5 min-w-[20px] px-1.5 rounded-full bg-muted text-[11px] font-medium text-muted-foreground">
                {processedRows.length} строк
              </span>
            </div>
            )}

            <FiltersPanel
              className="mb-3"
              fields={filterFields}
              onReset={resetAllFilters}
              hasActiveFilters={activeFilterSummary.count > 0}
              activeSummary={activeFilterSummary}
            />

            {!bulkMode && (
            <div className="flex items-center gap-2 mb-3">
              <Button
                variant={bulkMode ? "default" : "outline"}
                size="sm"
                onClick={() => {
                  if (bulkMode) exitBulkMode()
                  else setBulkMode(true)
                }}
              >
                <ListChecks className="h-4 w-4 mr-1.5" />
                {bulkMode ? "Групповые операции: вкл" : "Групповые операции"}
              </Button>
              {bulkMode && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={selectAll}
                >
                  Выбрать все
                </Button>
              )}
            </div>
            )}

            {bulkMode && (
            <BulkSelectionTable
              selectedCount={bulkSelection.selectedCount}
              rows={bulkSelectionRows}
              columns={[
                { key: "id", label: "ID" },
                { key: "sku", label: "Артикул" },
                { key: "name", label: "Наименование" },
                { key: "qty", label: "Кол-во" },
                { key: "route", label: "Маршрут" },
              ]}
              actions={bulkActions}
              onClose={exitBulkMode}
              onRemoveRow={(id) => bulkSelection.selectOne(Number(id), false)}
              progress={bulkProgress}
              lastSummary={bulkSummary}
              className="shrink-0"
            />
            )}

            <div className="flex-1 min-h-0">
            {posLoading && <p className="text-sm text-muted-foreground">Загрузка...</p>}
            {positions && positions.length > 0 && (
              <>
              <div
                ref={tableScrollRef}
                tabIndex={-1}
                onMouseDown={() => tableScrollRef.current?.focus()}
                className="rounded-lg border overflow-auto focus:outline-none"
                style={{ maxHeight: bulkMode ? undefined : '70vh' }}
              >
                <table className="w-full border-separate border-spacing-0">
                  <thead className="[&_th]:sticky [&_th]:top-0 [&_th]:z-20 [&_th]:bg-background [&_th]:border-b">
                    <tr>
                      <th className="text-left p-2" aria-sort={getAriaSort("id")}>
                        <SortableHeader field="id" currentSorts={sortConfigs} onSortChange={handleSortChange}>Id</SortableHeader>
                      </th>
                      <th className="text-left p-2" aria-sort={getAriaSort("rowNum")}>
                        <SortableHeader field="rowNum" currentSorts={sortConfigs} onSortChange={handleSortChange}>Строка</SortableHeader>
                      </th>
                      <th className="text-left p-2" aria-sort={getAriaSort("sku")}>
                        <SortableHeader field="sku" currentSorts={sortConfigs} onSortChange={handleSortChange}>Артикул</SortableHeader>
                      </th>
                      <th className="text-left p-2" aria-sort={getAriaSort("name")}>
                        <SortableHeader field="name" currentSorts={sortConfigs} onSortChange={handleSortChange}>Наименование</SortableHeader>
                      </th>
                      <th className="text-left p-2" aria-sort={getAriaSort("qty")}>
                        <SortableHeader field="qty" currentSorts={sortConfigs} onSortChange={handleSortChange}>Кол-во</SortableHeader>
                      </th>
                      <th className="text-left p-2 min-w-[200px]">Маршрут</th>
                      <th className="text-left p-2" aria-sort={getAriaSort("errors")}>
                        <SortableHeader field="errors" currentSorts={sortConfigs} onSortChange={handleSortChange}>Ошибки</SortableHeader>
                      </th>
                      <th className="text-left p-2" aria-sort={getAriaSort("warnings")}>
                        <SortableHeader field="warnings" currentSorts={sortConfigs} onSortChange={handleSortChange}>Предупр.</SortableHeader>
                      </th>
                      <th className="text-left p-2 text-xs font-medium text-muted-foreground">Действия</th>
                    </tr>
                  </thead>
                  <VirtualizedTableBody
                    rows={processedRows}
                    rowHeight={48}
                    colSpan={9}
                    scrollContainerRef={tableScrollRef}
                    renderRow={(p) => (
                      <PositionRow
                        key={p.id}
                        pos={p}
                        onApprove={handleApprove}
                        onDelete={handleDelete}
                        selected={bulkSelection.isSelected(p.id)}
                        routes={activeRoutes}
                        onAssignRoute={handleAssignRouteSingle}
                        onOpenDetail={() => openDetail(p)}
                        duplicateConflict={duplicateConflictsByPosition.get(p.id)}
                        onJumpToPosition={jumpToPosition}
                        onSelect={bulkMode ? toggleSelect : undefined}
                      />
                    )}
                  />
                </table>
              </div>
              {processedRows.length === 0 && (
                <p className="text-sm text-muted-foreground p-4 text-center">Нет позиций, соответствующих фильтру</p>
              )}
              </>
            )}
            </div>
          </section>
        </div>
      )}

      <ImportWizard open={importOpen} onClose={() => setImportOpen(false)} onSuccess={handleSuccess} productionPlanId={activePlan?.id} />

      {activeTemplates.map(t => (
        <ImportWizard
          key={t.id}
          open={templateImportOpen === t.id}
          onClose={() => setTemplateImportOpen(null)}
          onSuccess={handleSuccess}
          productionPlanId={activePlan?.id}
          templateId={t.id}
        />
      ))}

      <RowDetailsSidePanel
        open={detailOpen}
        onOpenChange={setDetailOpen}
        data={detailData}
      />

      {bulkSummary && bulkSummary.failed > 0 && (
      <BulkResultsDialog
        open={bulkResultsOpen}
        onOpenChange={setBulkResultsOpen}
        title="Результат массового действия"
        summary={bulkSummary}
        results={bulkResults}
      />
      )}

      <AlertDialog open={bulkDeleteConfirmOpen} onOpenChange={setBulkDeleteConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle className="text-destructive">Подтвердить удаление</AlertDialogTitle>
            <AlertDialogDescription>
              Будет удалено <strong>{bulkSelection.selectedCount}</strong> позиций. Это действие нельзя отменить.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Отмена</AlertDialogCancel>
            <AlertDialogAction
              onClick={(e) => {
                e.preventDefault()
                confirmBulkDelete()
              }}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              disabled={bulkDeleting}
            >
              {bulkDeleting ? "Удаление..." : "Удалить"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
