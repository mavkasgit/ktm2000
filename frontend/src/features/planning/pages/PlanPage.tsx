import { useEffect, useMemo, useRef, useState } from "react"
import { FileSpreadsheet, Plus, Upload, ListChecks } from "lucide-react"
import { ImportWizard } from "../ImportWizard"
import { Button, Select, SelectContent, SelectItem, SelectTrigger, SelectValue, AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogTitle, AlertDialogDescription, AlertDialogFooter, AlertDialogAction, AlertDialogCancel, SortableFilterHeader, VirtualizedTableBody, FiltersPanel, type FiltersPanelField, Badge } from "@/shared/ui"
import { buildActiveFilterSummary } from "@/shared/ui/buildActiveFilterSummary"
import { useTableQueryEngine, SortConfig, ColumnSortDef } from "@/shared/hooks/useTableQueryEngine"
import { nextMultiSortConfigs } from "@/shared/lib/multiSort"
import { toast } from "@/shared/ui"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { allPlanFiles, allPlanPositions, PlanPositionOut, listPlans, batchAssignRouteGlobal, deleteImportBatch, approveProductionPlanPosition, getPlanDuplicates } from "@/shared/api/productionPlans"
import { listRoutes } from "@/shared/api/routes"
import { listImportTemplates } from "@/shared/api/importTemplates"
import { apiClient, getErrorMessage } from "@/shared/api/client"
import { RowDetailsSidePanel, adaptPlanPositionOut } from "../components/row-details"
import {
  BulkResultsDialog,
  summarizeBulkResults,
  useBulkSelection,
  type BulkActionResultItem,
  type BulkActionSummary,
  type BulkRunnerProgress,
} from "@/shared/bulk"
import { FileRow } from "../components/PlanFileRow"
import { PositionRow } from "../components/PlanPositionRow"
import {
  DuplicateConflict,
  PlanSortField,
  PlanFiltersState,
} from "../lib/plan-labels"

export function PlanPage() {
  const [importOpen, setImportOpen] = useState(false)
  const queryClient = useQueryClient()
  const [showAllFiles, setShowAllFiles] = useState(false)
  const bulkSelection = useBulkSelection<number>()
  const [bulkMode, setBulkMode] = useState(false)
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
  const [columnFilters, setColumnFilters] = useState<
    Partial<Record<PlanSortField, Set<string>>>
  >({})
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
    bulkSelection.selectOne(id)
  }

  const selectAll = () => {
    if (bulkSelection.isAllSelected(filteredPositionIds)) {
      bulkSelection.clear()
    } else {
      bulkSelection.selectAllFiltered(filteredPositionIds)
    }
  }

  const resetAllFilters = () => {
    setSearchQuery("")
    setSortConfigs([])
    setColumnFilters({})
    setFilters({
      status: "all",
      validation_status: "all",
      has_route: "all",
      has_errors: "all",
      has_warnings: "all",
      has_duplicates: "all",
    })
    bulkSelection.clear()
    setBulkMode(false)
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
    setBulkMode(false)
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
    setBulkMode(false)
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
  const getPlanCellValue = (row: PlanPositionOut, field: PlanSortField): string => {
    switch (field) {
      case "id": return String(row.id)
      case "rowNum": {
        const numbers = Array.isArray(row.source_row_numbers)
          ? row.source_row_numbers.filter((v): v is number => typeof v === "number")
          : []
        return String(numbers.length > 0 ? Math.min(...numbers) : (row.source_row_number ?? 0))
      }
      case "sku": return row.source_sku
      case "name": return row.source_name ?? ""
      case "qty": return String(Number(row.quantity || 0))
      case "route": return row.route_name ?? "Не назначен"
      case "errors": return String(row.errors?.length ?? 0)
      case "warnings": return String(row.warnings?.length ?? 0)
      default: return ""
    }
  }

  const filterPredicate = useMemo(() => {
    const hasColumnFilters = Object.values(columnFilters).some(s => s && s.size > 0)
    const hasTopFilters =
      filters.status !== "all" ||
      filters.validation_status !== "all" ||
      filters.has_route !== "all" ||
      filters.has_errors !== "all" ||
      filters.has_warnings !== "all" ||
      filters.has_duplicates !== "all" ||
      searchQuery.trim() !== ""

    if (!hasColumnFilters && !hasTopFilters) return null

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
      // Column filters (AND across columns, OR within column)
      for (const [field, selected] of Object.entries(columnFilters)) {
        if (selected && selected.size > 0) {
          const cellValue = getPlanCellValue(row, field as PlanSortField)
          if (!selected.has(cellValue)) return false
        }
      }
      return true
    }
  }, [filters, duplicateConflictsByPosition, columnFilters, searchQuery])

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

  const handleColumnFilterChange = (field: PlanSortField, selected: Set<string>) => {
    setColumnFilters((prev) => ({ ...prev, [field]: selected }))
  }

  const uniqueValuesByField = useMemo(() => {
    const allRows = positions ?? []
    return {
      id: [...new Set(allRows.map((p) => String(p.id)))],
      rowNum: [...new Set(allRows.map((p) => {
        const numbers = Array.isArray(p.source_row_numbers)
          ? p.source_row_numbers.filter((v): v is number => typeof v === "number")
          : []
        return String(numbers.length > 0 ? Math.min(...numbers) : (p.source_row_number ?? 0))
      }))],
      sku: [...new Set(allRows.map((p) => p.source_sku))],
      name: [...new Set(allRows.map((p) => p.source_name ?? "").filter(Boolean))],
      qty: [...new Set(allRows.map((p) => String(Number(p.quantity || 0))))],
      route: [...new Set(allRows.map((p) => p.route_name ?? "Не назначен"))],
      errors: [...new Set(allRows.map((p) => String(p.errors?.length ?? 0)))],
      warnings: [...new Set(allRows.map((p) => String(p.warnings?.length ?? 0)))],
    }
  }, [positions])
  const filterFields = useMemo<FiltersPanelField[]>(
    () => [
      {
        kind: "search",
        key: "search",
        value: searchQuery,
        onChange: setSearchQuery,
        placeholder: "Поиск",
        layoutSpan: "min-w-[250px]",
      },
      {
        kind: "bulk",
        key: "bulk-mode",
        enabled: bulkMode,
        onChange: (enabled: boolean) => {
          if (enabled) {
            setBulkMode(true);
          } else {
            exitBulkMode();
          }
        },
      },
    ],
    [searchQuery, bulkMode, exitBulkMode],
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
              compact
              fields={filterFields}
              onReset={resetAllFilters}
              hasActiveFilters={activeFilterSummary.count > 0}
              activeSummary={activeFilterSummary}
              actions={
                <>
                  {bulkMode && bulkSelection.selectedCount > 0 && (
                    <>
                      <span className="text-sm font-medium whitespace-nowrap">Выбрано: {bulkSelection.selectedCount}</span>
                      <Button
                        size="sm"
                        variant="success"
                        onClick={handleBulkApprove}
                        disabled={bulkApproving || bulkDeleting}
                      >
                        {bulkApproving ? "Выполнение..." : "Утвердить"}
                      </Button>
                      <Button
                        size="sm"
                        variant="destructive"
                        onClick={requestBulkDelete}
                        disabled={bulkApproving || bulkDeleting}
                      >
                        {bulkDeleting ? "Удаление..." : "Удалить"}
                      </Button>
                      {bulkProgress?.running && (
                        <span className="text-xs text-muted-foreground">
                          {bulkProgress.completed}/{bulkProgress.total}
                        </span>
                      )}
                      {bulkSummary && bulkSummary.total > 0 && !bulkProgress?.running && (
                        <Badge variant={bulkSummary.failed > 0 ? "destructive" : "secondary"}>
                          {bulkSummary.success} ok / {bulkSummary.skipped} пропущено / {bulkSummary.failed} ошибок
                        </Badge>
                      )}
                    </>
                  )}
                </>
              }
              onSelectAll={() => {
                setBulkMode(true);
                selectAll();
              }}
              totalRowCount={processedRows.length}
            />


            <div className="flex-1 min-h-0">
            {posLoading && <p className="text-sm text-muted-foreground">Загрузка...</p>}
            {positions && positions.length > 0 && (
              <>
              <div
                ref={tableScrollRef}
                className="rounded-lg border overflow-auto"
                style={{ maxHeight: bulkMode ? undefined : '70vh' }}
              >
                <table className="w-full border-separate border-spacing-0">
                  <thead className="[&_th]:sticky [&_th]:top-0 [&_th]:z-20 [&_th]:bg-background [&_th]:border-b">
                    <tr>
                      <th className="text-left p-2">
                        <SortableFilterHeader
                          field="id"
                          label="Id"
                          currentSorts={sortConfigs}
                          onSortChange={handleSortChange}
                          values={uniqueValuesByField.id}
                          selectedValues={columnFilters.id ?? new Set()}
                          onFilterChange={handleColumnFilterChange}
                        />
                      </th>
                      <th className="text-left p-2">
                        <SortableFilterHeader
                          field="rowNum"
                          label="Строка"
                          currentSorts={sortConfigs}
                          onSortChange={handleSortChange}
                          values={uniqueValuesByField.rowNum}
                          selectedValues={columnFilters.rowNum ?? new Set()}
                          onFilterChange={handleColumnFilterChange}
                        />
                      </th>
                      <th className="text-left p-2">
                        <SortableFilterHeader
                          field="sku"
                          label="Артикул"
                          currentSorts={sortConfigs}
                          onSortChange={handleSortChange}
                          values={uniqueValuesByField.sku}
                          selectedValues={columnFilters.sku ?? new Set()}
                          onFilterChange={handleColumnFilterChange}
                        />
                      </th>
                      <th className="text-left p-2">
                        <SortableFilterHeader
                          field="qty"
                          label="Кол-во"
                          currentSorts={sortConfigs}
                          onSortChange={handleSortChange}
                          values={uniqueValuesByField.qty}
                          selectedValues={columnFilters.qty ?? new Set()}
                          onFilterChange={handleColumnFilterChange}
                          valueLabel={(v) => v}
                        />
                      </th>
                      <th className="text-left p-2">
                        <SortableFilterHeader
                          field="name"
                          label="Наименование"
                          currentSorts={sortConfigs}
                          onSortChange={handleSortChange}
                          values={uniqueValuesByField.name}
                          selectedValues={columnFilters.name ?? new Set()}
                          onFilterChange={handleColumnFilterChange}
                        />
                      </th>
                      <th className="text-left p-2 min-w-[200px]">
                        <SortableFilterHeader
                          field="route"
                          label="Маршрут"
                          currentSorts={sortConfigs}
                          onSortChange={handleSortChange}
                          values={uniqueValuesByField.route}
                          selectedValues={columnFilters.route ?? new Set()}
                          onFilterChange={handleColumnFilterChange}
                        />
                      </th>
                      <th className="text-left p-2">
                        <SortableFilterHeader
                          field="errors"
                          label="Ошибки"
                          currentSorts={sortConfigs}
                          onSortChange={handleSortChange}
                          values={uniqueValuesByField.errors}
                          selectedValues={columnFilters.errors ?? new Set()}
                          onFilterChange={handleColumnFilterChange}
                        />
                      </th>
                      <th className="text-left p-2">
                        <SortableFilterHeader
                          field="warnings"
                          label="Предупр."
                          currentSorts={sortConfigs}
                          onSortChange={handleSortChange}
                          values={uniqueValuesByField.warnings}
                          selectedValues={columnFilters.warnings ?? new Set()}
                          onFilterChange={handleColumnFilterChange}
                        />
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
        onSaved={() => {
          queryClient.invalidateQueries({ queryKey: ["all-plan-positions"] })
        }}
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
