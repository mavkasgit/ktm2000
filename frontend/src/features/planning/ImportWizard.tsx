import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { Check, ExternalLink } from "lucide-react"
import { useNavigate } from "react-router-dom"
import { uploadExcel, applyChangeSet, discardImport } from "./api"
import { getExcelSheetNames, previewExcelSheet, type SheetPreviewResponse } from "shared/api/imports"
import { Button, Input, AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogTitle, AlertDialogDescription, AlertDialogFooter, AlertDialogAction, AlertDialogCancel, FiltersPanel, Select, SelectContent, SelectItem, SelectTrigger, SelectValue, type FiltersPanelField } from "shared/ui"
import { useImportRowExpansion, ImportRawRows, ImportUpload, ImportPreview, getImportDialogContentClass } from "@/shared/ui/import-utils"
import { PlanImportPreviewTable, PLAN_IMPORT_ERROR_LABELS } from "./components/PlanImportPreviewTable"
import { buildActiveFilterSummary } from "shared/ui/buildActiveFilterSummary"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { listAllImportTemplates, type ImportTemplate } from "@/shared/api/importTemplates"
import { getErrorMessage } from "@/shared/api/client"
import { queryKeys } from "@/shared/api/queryKeys"
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "shared/ui"

type SortConfig = { key: string; dir: "asc" | "desc" } | null


type SheetPreviewCache = Record<string, SheetPreviewResponse>

function buildPreviewCacheKey(sheetIdx: number, templateId: number | null, rowSelection: string, normalizeHanger: boolean): string {
  const selection = rowSelection.trim();
  const templatePart = templateId == null ? "none" : String(templateId);
  return `${sheetIdx}:${templatePart}:${selection}:${normalizeHanger ? "h" : "n"}`;
}

export function ImportWizard(props: {
  open: boolean
  onClose: () => void
  onSuccess: (planId: string, changeSetId: string) => void
  productionPlanId?: number
  templateId?: number
}) {
  const queryClient = useQueryClient()
  const [step, setStep] = useState<"upload" | "preview" | "result">("upload")
  const [file, setFile] = useState<File | null>(null)
  const [sheets, setSheets] = useState<string[]>([])
  const [selectedSheet, setSelectedSheet] = useState(0)
  const [sheetPreviews, setSheetPreviews] = useState<SheetPreviewCache>({})
  const [previewLoading, setPreviewLoading] = useState<Record<string, boolean>>({})
  const [sortConfig, setSortConfig] = useState<SortConfig>(null)
  const [filterStatus, setFilterStatus] = useState<"all" | "invalid" | "warning">("all")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<Record<string, unknown> | null>(null)
  const [searchQuery, setSearchQuery] = useState("")
  const [rowSelection, setRowSelection] = useState("")
  const [pendingChangeSet, setPendingChangeSet] = useState<{ planId: string; changeSetId: string } | null>(null)
  const [showApplyConfirm, setShowApplyConfirm] = useState(false)
  const [showCloseConfirm, setShowCloseConfirm] = useState(false)
  const expansion = useImportRowExpansion()
  const [activeTemplateId, setActiveTemplateId] = useState<number | null>(props.templateId ?? null)
  const [normalizeHangerQuantity, setNormalizeHangerQuantity] = useState(true)
  const [loadingStartTime, setLoadingStartTime] = useState<number | null>(null)
  const [loadingElapsed, setLoadingElapsed] = useState(0)

  const fileInputRef = useRef<HTMLInputElement>(null)
  const navigate = useNavigate()
  const { data: templates } = useQuery<ImportTemplate[]>({
    queryKey: queryKeys.importTemplates.modal(),
    queryFn: listAllImportTemplates,
    enabled: props.open,
  })

  useEffect(() => {
    if (!props.open) return
    setActiveTemplateId(props.templateId ?? null)
  }, [props.open, props.templateId])

  const activeTemplates = useMemo(
    () => (templates ?? []).filter((template) => template.is_active).sort((a, b) => a.sort_order - b.sort_order || a.id - b.id),
    [templates],
  )
  const selectedTemplate = useMemo(
    () => activeTemplates.find((template) => template.id === activeTemplateId) ?? null,
    [activeTemplates, activeTemplateId],
  )
  const templateLocked = props.templateId != null

  useEffect(() => {
    if (step !== "preview" || !file) return
    setSheetPreviews({})
    setPreviewLoading({})
    setPendingChangeSet(null)
    loadSheetPreview(file, selectedSheet, rowSelection)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTemplateId, rowSelection])

  // Preview for the currently selected sheet
  const currentPreviewKey = useMemo(
    () => buildPreviewCacheKey(selectedSheet, activeTemplateId, rowSelection, normalizeHangerQuantity),
    [selectedSheet, activeTemplateId, rowSelection, normalizeHangerQuantity],
  )
  const currentPreview = sheetPreviews[currentPreviewKey] ?? null

  // Timer for loading progress
  useEffect(() => {
    if (previewLoading[currentPreviewKey] && !loadingStartTime) {
      setLoadingStartTime(Date.now())
    } else if (!previewLoading[currentPreviewKey] && loadingStartTime) {
      setLoadingStartTime(null)
      setLoadingElapsed(0)
    }
  }, [previewLoading, currentPreviewKey, loadingStartTime])

  useEffect(() => {
    if (!loadingStartTime) return
    const interval = setInterval(() => {
      setLoadingElapsed(Math.floor((Date.now() - loadingStartTime) / 1000))
    }, 1000)
    return () => clearInterval(interval)
  }, [loadingStartTime])

  const allRows = useMemo(() => {
    const base = (currentPreview?.items as Record<string, unknown>[]) ?? []
    // Compute predicted DB IDs: for rows without persisted plan_position_id,
    // assign sequential IDs starting from max visible DB id.
    let maxId = 0
    for (const r of base) {
      const pid = r.plan_position_id as number | undefined
      if (pid != null && pid > maxId) maxId = pid
      const dupId = (r.after_data as Record<string, unknown> | undefined)?.duplicate_existing_id
      if (typeof dupId === "number" && dupId > maxId) maxId = dupId
    }
    let nextId = maxId + 1
    return base.map((r) => {
      const pid = r.plan_position_id as number | undefined
      if (pid == null) {
        return { ...r, _predicted_id: nextId++ }
      }
      return r
    })
  }, [currentPreview])

  const filteredRows = useMemo(() => {
    let rows = allRows
    // Client-side row number filter
    if (rowSelection.trim() && rows.length > 0) {
      try {
        const allowed = new Set<number>()
        for (const token of rowSelection.split(",")) {
          const part = token.trim()
          if (!part) continue
          if (part.includes("-")) {
            const bounds = part.split("-").map((s) => s.trim())
            const s = Number(bounds[0])
            const e = Number(bounds[1])
            if (Number.isFinite(s) && Number.isFinite(e) && s > 0 && e > 0) {
              for (let i = Math.min(s, e); i <= Math.max(s, e); i++) allowed.add(i)
            }
          } else if (/^\d+$/.test(part)) {
            const n = Number(part)
            if (Number.isFinite(n) && n > 0) allowed.add(n)
          }
        }
        if (allowed.size > 0) {
          rows = rows.filter((r) => {
            const rowNum = r.source_row_number ?? (r.after_data as any)?.source_row_numbers?.[0]
            return rowNum != null && allowed.has(Number(rowNum))
          })
        }
      } catch {
        // ignore invalid rowSelection
      }
    }
    if (filterStatus !== "all") {
      rows = rows.filter((r) => r.status === filterStatus)
    }
    if (searchQuery.trim()) {
      const q = searchQuery.trim().toLowerCase()
      rows = rows.filter((r) => {
        const rowNum = String(r.source_row_number ?? (r.after_data as any)?.source_row_numbers?.[0] ?? "")
        const planPosId = String(r.plan_position_id ?? "")
        const after = (r.after_data as Record<string, unknown>) || {}
        const sku = String(after.source_sku ?? r.source_sku ?? "")
        const name = String(after.source_name ?? r.source_name ?? "")
        return rowNum.includes(q) || planPosId.includes(q) || sku.toLowerCase().includes(q) || name.toLowerCase().includes(q)
      })
    }
    if (!sortConfig) return rows
    return [...rows].sort((a, b) => {
      let aVal: string
      let bVal: string
      if (sortConfig.key === "change_action" || sortConfig.key === "status") {
        aVal = String(a[sortConfig.key] ?? "")
        bVal = String(b[sortConfig.key] ?? "")
      } else {
        const aAfter = (a.after_data as Record<string, unknown>) || {}
        const bAfter = (b.after_data as Record<string, unknown>) || {}
        aVal = String(aAfter[sortConfig.key] ?? a[sortConfig.key] ?? "")
        bVal = String(bAfter[sortConfig.key] ?? b[sortConfig.key] ?? "")
      }
      if (aVal < bVal) return sortConfig.dir === "asc" ? -1 : 1
      if (aVal > bVal) return sortConfig.dir === "asc" ? 1 : -1
      return 0
    })
  }, [allRows, filterStatus, sortConfig, rowSelection, searchQuery])

  const summary = useMemo(() => {
    const total = allRows.length
    const invalid = allRows.filter((r) => r.status === "invalid").length
    const warning = allRows.filter((r) => r.status === "warning").length
    return { total, invalid, warning }
  }, [allRows])
  const previewActiveFilterSummary = useMemo(
    () =>
      buildActiveFilterSummary(
        { status: filterStatus },
        searchQuery,
        sortConfig ? 1 : 0,
      ),
    [filterStatus, searchQuery, sortConfig],
  )
  const resetPreviewFilters = useCallback(() => {
    setSearchQuery("")
    setFilterStatus("all")
    setSortConfig(null)
  }, [])
  const previewFilterFields = useMemo<FiltersPanelField[]>(
    () => [
      {
        kind: "search" as const,
        key: "search",
        value: searchQuery,
        onChange: setSearchQuery,
        placeholder: "Поиск: строка, ID, артикул...",
      },
      {
        kind: "select" as const,
        key: "status",
        value: filterStatus,
        onChange: (value: string) => setFilterStatus(value as "all" | "invalid" | "warning"),
        placeholder: "Статус строк",
        options: [
          { value: "all", label: "Все" },
          { value: "invalid", label: "Ошибки" },
          { value: "warning", label: "Предупр." },
        ],
      },
    ],
    [filterStatus, searchQuery],
  )

  const applyStats = useMemo(() => {
    const total = summary.total
    const invalid = summary.invalid
    const warning = summary.warning
    return {
      total,
      invalid,
      warning,
      normal: Math.max(total - invalid - warning, 0),
      uploadAll: total,
      uploadSkipInvalid: Math.max(total - invalid, 0),
    }
  }, [summary])

  const errorBreakdown = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const row of allRows) {
      const errs = row.errors as string[] | undefined
      if (Array.isArray(errs)) {
        for (const e of errs) {
          counts[e] = (counts[e] || 0) + 1
        }
      }
    }
    return counts
  }, [allRows])

  const errorBreakdownEntries = useMemo(() => {
    return Object.entries(errorBreakdown).sort((a, b) => b[1] - a[1])
  }, [errorBreakdown])

  async function handleFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0]
    if (!f) return
    setFile(f)
    setLoading(true)
    setError(null)
    try {
      const sheetNames = await getExcelSheetNames(f)
      setSheets(sheetNames)
      setSelectedSheet(0)
      setSheetPreviews({})
      setPreviewLoading({})
      setPendingChangeSet(null)
      setStep("preview")
      // Auto-load preview for first sheet
      loadSheetPreview(f, 0, rowSelection)
    } catch (e) {
      setError(getErrorMessage(e))
    } finally {
      setLoading(false)
    }
  }

  // Refetch preview when hanger quantity toggle changes
  useEffect(() => {
    if (!file) return
    // Invalidate old cache entries that had different normalizeHangerQuantity value
    setSheetPreviews((prev) => {
      const next: Record<string, SheetPreviewResponse> = {}
      for (const [key, value] of Object.entries(prev)) {
        // Keep entries that match current normalizeHangerQuantity
        if (key.endsWith(normalizeHangerQuantity ? ":h" : ":n")) {
          next[key] = value
        }
      }
      return next
    })
    loadSheetPreview(file, selectedSheet)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [normalizeHangerQuantity])

  async function loadSheetPreview(f: File, sheetIdx: number, selection: string = rowSelection) {
    const cacheKey = buildPreviewCacheKey(sheetIdx, activeTemplateId, selection, normalizeHangerQuantity)
    if (previewLoading[cacheKey] || sheetPreviews[cacheKey]) return
    setPreviewLoading((prev) => ({ ...prev, [cacheKey]: true }))
    try {
      const data = await previewExcelSheet(f, {
        sheet_index: sheetIdx,
        row_selection: selection.trim() || undefined,
        template_id: activeTemplateId ?? undefined,
        mode: props.productionPlanId ? "append_to_plan" : "create_plan",
        production_plan_id: props.productionPlanId,
        normalize_hanger_quantity: normalizeHangerQuantity,
      })
      setSheetPreviews((prev) => ({ ...prev, [cacheKey]: data }))
    } catch {
      // ignore — user will see empty table
    } finally {
      setPreviewLoading((prev) => ({ ...prev, [cacheKey]: false }))
    }
  }

  async function handleApplyConfirmed(skipInvalid: boolean) {
    if (!file) return
    if (!activeTemplateId) {
      setError("Выберите шаблон импорта перед применением")
      return
    }

    setShowApplyConfirm(false)
    setLoading(true)
    setError(null)
    let changeSet = pendingChangeSet
    let createdNow = false
    try {
      if (!changeSet) {
        const uploaded = await uploadExcel(file, {
          templateId: activeTemplateId,
          productionPlanId: props.productionPlanId,
          rowSelection: rowSelection || undefined,
          sheetIndex: selectedSheet,
          normalizeHangerQuantity: normalizeHangerQuantity,
        })
        const planId = String(uploaded.planId ?? uploaded.production_plan_id ?? "")
        const changeSetId = String(uploaded.changeSetId ?? uploaded.change_set_id ?? "")
        if (!planId || !changeSetId) {
          throw new Error("Не найден planId или changeSetId")
        }
        changeSet = { planId, changeSetId }
        createdNow = true
        setPendingChangeSet(changeSet)
      }

      const data = await applyChangeSet(changeSet.planId, changeSet.changeSetId, { skipInvalid })
      setResult(data)
      setPendingChangeSet(null)
      setStep("result")
      // Инвалидируем все домены, которые зависят от плана
      void queryClient.invalidateQueries({ queryKey: queryKeys.plan.allPositions() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.plan.preview(changeSet.planId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.shopfloor.boardAll() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.sections.all() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.spg.snapshotAll() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.plan.batchPreview(changeSet.changeSetId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.importTemplates.all() });
      props.onSuccess(changeSet.planId, changeSet.changeSetId)
    } catch (e) {
      // If apply failed right after creating a change set, cleanup immediately.
      if (createdNow && changeSet) {
        discardImport(changeSet.planId, changeSet.changeSetId).catch(() => {})
        setPendingChangeSet(null)
      }
      setError(getErrorMessage(e))
    } finally {
      setLoading(false)
    }
  }

  function handleApply() {
    if (!file) return
    if (!activeTemplateId) {
      setError("Выберите шаблон импорта перед применением")
      return
    }
    setShowApplyConfirm(true)
  }

  function toggleSort(key: string) {
    setSortConfig((prev) => {
      if (!prev || prev.key !== key) return { key, dir: "asc" }
      if (prev.dir === "asc") return { key, dir: "desc" }
      return null
    })
  }

  function reset() {
    // Discard any pending change set on reset
    if (pendingChangeSet) {
      discardImport(pendingChangeSet.planId, pendingChangeSet.changeSetId).catch(() => {})
      void queryClient.invalidateQueries({ queryKey: queryKeys.plan.allPositions() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.plan.preview(pendingChangeSet.planId) });
    }
    setStep("upload")
    setFile(null)
    setSheets([])
    setSelectedSheet(0)
    setSheetPreviews({})
    setPreviewLoading({})
    setResult(null)
    setError(null)
    setSortConfig(null)
    setFilterStatus("all")
    setSearchQuery("")
    setRowSelection("")
    setPendingChangeSet(null)
    expansion.resetExpansion()
    if (fileInputRef.current) {
      fileInputRef.current.value = ""
    }
  }

  function handleClose() {
    if (pendingChangeSet && step !== "result") {
      setShowCloseConfirm(true)
      return
    }
    reset()
    props.onClose()
  }

  function handleForceClose() {
    setShowCloseConfirm(false)
    reset()
    props.onClose()
  }

  return (
    <>
      <Dialog open={props.open} onOpenChange={(open) => { if (!open) handleClose() }}>
      <DialogContent className={getImportDialogContentClass(step)}>
        <DialogHeader>
          <DialogTitle>Импорт производственного плана</DialogTitle>
        </DialogHeader>

        {error ? <ImportPreview.Error message={error} /> : null}

        {step === "upload" && (
          <div className="space-y-4 py-1">
            <ImportUpload.Intro>
              <p>
                {props.productionPlanId
                  ? "Добавление позиций в текущий производственный план."
                  : "Создание нового производственного плана из Excel-файла."}
              </p>
              <p>
                {templateLocked && selectedTemplate ? (
                  <>
                    Шаблон импорта:{" "}
                    <span className="font-medium text-foreground">
                      {selectedTemplate.button_label || selectedTemplate.name}
                    </span>{" "}
                    — сопоставление колонок Excel задано этим шаблоном.
                  </>
                ) : (
                  <>
                    Выберите шаблон импорта — он определяет сопоставление колонок Excel с полями системы.
                    {selectedTemplate ? (
                      <>
                        {" "}
                        Текущий шаблон:{" "}
                        <span className="font-medium text-foreground">
                          {selectedTemplate.button_label || selectedTemplate.name}
                        </span>
                        .
                      </>
                    ) : null}
                  </>
                )}
              </p>
              <p>После загрузки файла откроется предпросмотр с проверкой маршрутов и ошибок.</p>
            </ImportUpload.Intro>

            {activeTemplates.length > 0 && !templateLocked ? (
              <ImportUpload.SettingsCard title="Настройки импорта">
                <div className="space-y-1.5">
                  <label className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">
                    Шаблон импорта
                  </label>
                  <Select
                    value={activeTemplateId != null ? String(activeTemplateId) : "none"}
                    onValueChange={(v) => setActiveTemplateId(v === "none" ? null : Number(v))}
                  >
                    <SelectTrigger className="h-10 w-full">
                      <SelectValue placeholder="Без шаблона (только глобальные правила)" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="none">Без шаблона (только глобальные правила)</SelectItem>
                      {activeTemplates.map((template) => (
                        <SelectItem key={template.id} value={String(template.id)}>
                          {template.button_label || template.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  {!activeTemplateId ? (
                    <p className="text-[10px] text-amber-700 dark:text-amber-400 leading-snug">
                      Шаблон обязателен для применения импорта.
                    </p>
                  ) : null}
                </div>
              </ImportUpload.SettingsCard>
            ) : null}

            <ImportUpload.Dropzone
              inputRef={fileInputRef}
              accept=".xlsx,.xls,.xlsm,.xlsb,.ods"
              onFileChange={handleFileSelect}
              disabled={loading}
              title={loading ? "Загрузка…" : "Выберите файл .xlsx / .xls"}
              subtitle="Нажмите или перетащите заполненный файл Excel"
              fileName={file && !loading ? file.name : null}
            />

            <ImportUpload.FooterHint>
              Поддерживаются .xlsx, .xls, .xlsm, .xlsb, .ods. Лист и диапазон строк настраиваются на шаге
              предпросмотра.
            </ImportUpload.FooterHint>
          </div>
        )}

        {step === "preview" && file && sheets.length > 0 && (
          <div className="flex-1 overflow-hidden flex flex-col space-y-3">
            {/* Loading state: spinner + progress bar */}
            {previewLoading[currentPreviewKey] && (
              <div className="flex-1 flex flex-col items-center justify-center p-8">
                <div className="w-full max-w-md space-y-6">
                  {/* Spinner */}
                  <div className="flex justify-center">
                    <div className="relative">
                      <div className="w-12 h-12 border-4 border-muted rounded-full" />
                      <div className="absolute inset-0 w-12 h-12 border-4 border-primary rounded-full border-t-transparent animate-spin" />
                    </div>
                  </div>

                  {/* Progress bar with time */}
                  <div className="space-y-2">
                    <div className="h-2 bg-muted rounded-full overflow-hidden">
                      <div
                        className="h-full bg-primary rounded-full transition-all duration-1000 ease-linear"
                        style={{ width: `${Math.min(95, 10 + (loadingElapsed / 6) * 85)}%` }}
                      />
                    </div>
                    <div className="text-center text-xs text-muted-foreground">
                      Загружено {loadingElapsed}с...
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* Compact horizontal controls */}
            {currentPreview && (
              <>
                {/* Row 1: Sheet tabs / File / Rows / Template / References */}
                <div className="flex flex-wrap items-center gap-3 shrink-0">
                  <ImportPreview.SheetTabs
                    sheets={sheets}
                    selectedIndex={selectedSheet}
                    onSelect={(idx) => {
                      setSelectedSheet(idx)
                      loadSheetPreview(file, idx, rowSelection)
                    }}
                    size="md"
                  />

                  <span className="text-xs text-muted-foreground">
                    {currentPreview.total_rows} строк
                  </span>

                  <span className="text-xs text-muted-foreground font-medium">Строки:</span>
                  <Input
                    value={rowSelection}
                    onChange={(e) => setRowSelection(e.target.value)}
                    placeholder="5,7,12-15"
                    className="h-7 w-32 text-xs"
                  />

                  <label className="flex items-center gap-1.5 text-xs cursor-pointer shrink-0">
                    <input
                      type="checkbox"
                      checked={normalizeHangerQuantity}
                      onChange={(e) => setNormalizeHangerQuantity(e.target.checked)}
                      className="h-3.5 w-3.5 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                    />
                    <span className="text-muted-foreground font-medium">Округлять до кратности подвеса</span>
                  </label>

                  {templateLocked && selectedTemplate ? (
                    <span className="text-xs text-muted-foreground">
                      <span className="font-medium">Шаблон:</span>{" "}
                      {selectedTemplate.button_label || selectedTemplate.name}
                    </span>
                  ) : activeTemplates.length > 0 ? (
                    <>
                      <span className="text-xs text-muted-foreground font-medium">Шаблон:</span>
                      <div className="w-[300px] flex-shrink-0">
                        <Select value={activeTemplateId != null ? String(activeTemplateId) : "none"} onValueChange={(v) => setActiveTemplateId(v === "none" ? null : Number(v))}>
                          <SelectTrigger className="h-7 text-xs">
                            <SelectValue placeholder="Без шаблона" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="none">Без шаблона</SelectItem>
                            {activeTemplates.map((template) => (
                              <SelectItem key={template.id} value={String(template.id)}>
                                {template.button_label || template.name}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                    </>
                  ) : null}
                </div>

                {/* Row 2: Summary + Error chips */}
                <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm shrink-0">
                  <span><strong>Всего:</strong> {summary.total}</span>
                  {(() => {
                    const qtyTotalRaw = (currentPreview.summary as Record<string, unknown>)?.quantity_total as string | undefined;
                    const qtyAdjustedTotalRaw = (currentPreview.summary as Record<string, unknown>)?.quantity_adjusted_total as string | undefined;
                    const normalizeQty = (qty: string) => {
                      const n = Number(qty);
                      return Number.isFinite(n) ? (n % 1 === 0 ? String(Math.trunc(n)) : String(n)) : qty;
                    };
                    const qtyTotal = qtyTotalRaw ? normalizeQty(qtyTotalRaw) : undefined;
                    const qtyAdjustedTotal = qtyAdjustedTotalRaw ? normalizeQty(qtyAdjustedTotalRaw) : undefined;
                    if (qtyTotal && qtyAdjustedTotal && qtyTotal !== qtyAdjustedTotal) {
                      return (
                        <span>
                          <strong>Кол-во:</strong>{" "}
                          <span className="text-muted-foreground">{qtyTotal}</span>
                          <span className="mx-1 text-muted-foreground">→</span>
                          <span className="font-medium text-amber-600">{qtyAdjustedTotal}</span>
                        </span>
                      );
                    }
                    if (qtyTotal) {
                      return <span><strong>Кол-во:</strong> {qtyTotal}</span>;
                    }
                    return null;
                  })()}
                  {summary.invalid > 0 && <span className="text-red-600"><strong>Ошибок:</strong> {summary.invalid}</span>}
                  {summary.warning > 0 && <span className="text-amber-600"><strong>Предупр.:</strong> {summary.warning}</span>}
                  {summary.invalid === 0 && summary.warning === 0 && <span className="text-green-600 text-xs">Без ошибок</span>}
                  {errorBreakdown["product_not_found"] > 0 && (
                    <Button
                      variant="outline"
                      size="sm"
                      className="h-7 text-xs gap-1 shrink-0"
                      onClick={() => window.open("/references/raw-materials", "_blank")}
                    >
                      <ExternalLink className="h-3 w-3" />
                      Открыть справочники
                    </Button>
                  )}
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-7 text-xs gap-1 shrink-0"
                    onClick={() => window.open("/planning", "_blank")}
                  >
                    <ExternalLink className="h-3 w-3" />
                    Открыть план
                  </Button>
                </div>

                {Object.keys(errorBreakdown).length > 0 && (
                  <div className="flex flex-wrap items-center gap-2 text-xs shrink-0">
                    {Object.entries(errorBreakdown).map(([code, count]) => (
                      <span key={code} className="bg-red-50 text-red-700 px-2 py-0.5 rounded border border-red-100">
                        {PLAN_IMPORT_ERROR_LABELS[code] ?? code}: {count}
                      </span>
                    ))}
                  </div>
                )}

                {/* Row 3: Filters */}
                <FiltersPanel
                  compact
                  fields={previewFilterFields}
                  activeSummary={previewActiveFilterSummary}
                  className="p-3"
                  actions={(
                    <ImportRawRows.Toggle
                      active={expansion.expandAllRaw}
                      onToggle={() => expansion.setExpandAllRaw(!expansion.expandAllRaw)}
                    />
                  )}
                />

                <ImportPreview.TableFrame
                  loading={previewLoading[currentPreviewKey]}
                  loadingVariant="custom"
                  loadingContent={
                    <div className="p-4 space-y-3">
                      {Array.from({ length: 8 }).map((_, i) => (
                        <div key={i} className="flex items-center gap-3 animate-pulse">
                          <div className="w-6 h-4 bg-muted rounded" />
                          <div className="w-12 h-4 bg-muted rounded" />
                          <div className="w-8 h-4 bg-muted rounded" />
                          <div className="w-20 h-4 bg-muted rounded" />
                          <div className="w-10 h-4 bg-muted rounded" />
                          <div className="flex-1 h-4 bg-muted rounded" style={{ maxWidth: "300px" }} />
                          <div className="flex-1 h-4 bg-muted rounded" style={{ maxWidth: "250px" }} />
                          <div className="flex-1 h-4 bg-muted rounded" style={{ maxWidth: "120px" }} />
                          <div className="flex-1 h-4 bg-muted rounded" style={{ maxWidth: "180px" }} />
                        </div>
                      ))}
                    </div>
                  }
                  isEmpty={allRows.length === 0}
                  emptyContent={
                    <span className="text-sm text-muted-foreground">Нет данных для отображения</span>
                  }
                  className="rounded-lg"
                >
                  <PlanImportPreviewTable
                    rows={filteredRows}
                    sortConfig={sortConfig}
                    onSort={toggleSort}
                    expansion={expansion}
                    hasActiveFilters={previewActiveFilterSummary.count > 0}
                    onReset={resetPreviewFilters}
                  />
                </ImportPreview.TableFrame>
              </>
            )}
          </div>
        )}

        {step === "result" && result && (
          <div className="text-center py-6">
                <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-green-100 mb-4">
                  <Check className="h-8 w-8 text-green-600" />
                </div>
                <h3 className="text-lg font-medium mb-4">Изменения применены</h3>
                <div className="flex justify-center gap-6 text-sm">
                  <div>
                    <div className="font-semibold">{(result as any).created_positions ?? 0}</div>
                    <div className="text-muted-foreground">Создано</div>
                  </div>
                  <div>
                    <div className="font-semibold">{(result as any).updated_positions ?? 0}</div>
                    <div className="text-muted-foreground">Обновлено</div>
                  </div>
                </div>
          </div>
        )}

        <DialogFooter className="shrink-0">
          {step === "preview" && (
            <>
              <Button variant="outline" onClick={reset} disabled={loading}>
                Назад
              </Button>
              <Button onClick={handleApply} disabled={loading || !currentPreview}>
                {loading ? "Проверка…" : "Применить изменения"}
              </Button>
            </>
          )}
          {step === "result" && (
            <Button onClick={handleClose}>Закрыть</Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <AlertDialog open={showCloseConfirm} onOpenChange={setShowCloseConfirm}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Выйти без применения?</AlertDialogTitle>
          <AlertDialogDescription>
            Загруженные изменения будут отменены и удалены. Вы уверены?
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel onClick={() => setShowCloseConfirm(false)}>Отмена</AlertDialogCancel>
          <AlertDialogAction onClick={handleForceClose}>Выйти</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>

    <AlertDialog open={showApplyConfirm} onOpenChange={setShowApplyConfirm}>
      <AlertDialogContent className="max-w-2xl">
        <AlertDialogHeader>
          <AlertDialogTitle>Подтвердите применение</AlertDialogTitle>
          <div className="mt-2 space-y-3 text-sm">
            <div className="grid grid-cols-2 gap-2">
              <div className="rounded border p-2">
                <div className="text-muted-foreground">Всего строк</div>
                <div className="font-semibold">{applyStats.total}</div>
              </div>
              <div className="rounded border p-2">
                <div className="text-muted-foreground">Новые</div>
                <div className="font-semibold text-green-700">{applyStats.normal}</div>
              </div>
              <div className="rounded border p-2">
                <div className="text-muted-foreground">С предупреждениями</div>
                <div className="font-semibold text-amber-700">{applyStats.warning}</div>
              </div>
              <div className="rounded border p-2">
                <div className="text-muted-foreground">С ошибками</div>
                <div className="font-semibold text-red-700">{applyStats.invalid}</div>
              </div>
            </div>
            <div className="rounded border p-2">
              <div className="text-muted-foreground">Файл</div>
              <div className="font-medium break-all">{file?.name || "—"}</div>
              <div className="mt-1 text-xs text-muted-foreground">
                Лист: {sheets[selectedSheet] ?? currentPreview?.sheet_name ?? "—"}; Строки: {rowSelection.trim() || "все"}
              </div>
            </div>
            {applyStats.invalid > 0 && (
              <div className="rounded border border-red-200 bg-red-50 p-3">
                <div className="font-medium text-red-900 mb-2">
                  Ошибки в {applyStats.invalid} строках:
                </div>
                <div className="space-y-1 max-h-40 overflow-y-auto text-xs">
                  {errorBreakdownEntries.map(([error, count]) => (
                    <div key={error} className="flex items-start gap-2 text-red-800">
                      <span className="text-red-600 mt-0.5">•</span>
                      <span className="font-medium">{error}</span>
                      <span className="text-red-600 ml-auto">{count} строк</span>
                    </div>
                  ))}
                </div>
                <div className="mt-2 pt-2 border-t border-red-200">
                  <AlertDialogDescription className="text-red-700">
                    Режим "Пропустить ошибки" загрузит только строки без ошибок.
                  </AlertDialogDescription>
                </div>
              </div>
            )}
          </div>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel onClick={() => setShowApplyConfirm(false)}>Отмена</AlertDialogCancel>
          <AlertDialogAction onClick={() => void handleApplyConfirmed(false)} disabled={loading}>
            {applyStats.invalid > 0
              ? `Загрузить с ошибками (${applyStats.uploadAll} строк)`
              : `Загрузить (${applyStats.uploadAll} строк)`}
          </AlertDialogAction>
          {applyStats.invalid > 0 && (
            <Button onClick={() => void handleApplyConfirmed(true)} disabled={loading}>
              Загрузить ({applyStats.uploadSkipInvalid} строк)
            </Button>
          )}
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
    </>
  )
}
