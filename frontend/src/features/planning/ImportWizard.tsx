import { useEffect, useMemo, useRef, useState } from "react"
import { Check, ExternalLink, Upload } from "lucide-react"
import { useNavigate } from "react-router-dom"
import { uploadExcel, applyChangeSet, discardImport, runDemoFullRoute } from "./api"
import { ImportDiffTable } from "./ImportDiffTable"
import { Button, Input, AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogTitle, AlertDialogDescription, AlertDialogFooter, AlertDialogAction, AlertDialogCancel } from "shared/ui"
import { useQuery } from "@tanstack/react-query"
import { listRoutes, getRoute, type ProductionRoute, type RouteStep } from "@/shared/api/routes"
import { listTechcards, type Techcard } from "@/shared/api/techcards"
import { listProducts, type Product } from "@/shared/api/products"
import { getErrorMessage } from "@/shared/api/client"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "shared/ui"

type SortConfig = { key: string; dir: "asc" | "desc" } | null

export function ImportWizard(props: {
  open: boolean
  onClose: () => void
  onSuccess: (planId: string, changeSetId: string) => void
  mode?: "normal" | "test"
  productionPlanId?: number
}) {
  const [step, setStep] = useState<"upload" | "preview" | "result">("upload")
  const [file, setFile] = useState<File | null>(null)
  const [previewData, setPreviewData] = useState<Record<string, unknown> | null>(null)
  const [sortConfig, setSortConfig] = useState<SortConfig>(null)
  const [filterStatus, setFilterStatus] = useState<"all" | "invalid" | "warning">("all")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<Record<string, unknown> | null>(null)
  const [searchQuery, setSearchQuery] = useState("")
  const [planMonth, setPlanMonth] = useState("")
  const [planVersion, setPlanVersion] = useState("")
  const [rowSelection, setRowSelection] = useState("")
  const [testRunId, setTestRunId] = useState("")
  const [testTechcardId, setTestTechcardId] = useState("")
  const [testRouteId, setTestRouteId] = useState("")
  const [testQuantity, setTestQuantity] = useState("100")
  const [scenarioId, setScenarioId] = useState("")
  const [stagePreset, setStagePreset] = useState<"before_approve" | "after_approve" | "after_release" | "to_step_ready" | "full_route">("before_approve")
  const [targetRouteStepId, setTargetRouteStepId] = useState("")
  const [pendingChangeSet, setPendingChangeSet] = useState<{ planId: string; changeSetId: string } | null>(null)
  const [showCloseConfirm, setShowCloseConfirm] = useState(false)

  const fileInputRef = useRef<HTMLInputElement>(null)
  const navigate = useNavigate()

  const { data: techcards } = useQuery<Techcard[]>({
    queryKey: ["techcards", "test-import-modal"],
    queryFn: listTechcards,
    enabled: props.open && props.mode === "test",
  })
  const { data: routes } = useQuery<ProductionRoute[]>({
    queryKey: ["routes", "test-import-modal"],
    queryFn: () => listRoutes(),
    enabled: props.open && props.mode === "test",
  })
  const { data: products } = useQuery<Product[]>({
    queryKey: ["products", "test-import-modal"],
    queryFn: () => listProducts({ limit: 2000 }),
    enabled: props.open && props.mode === "test",
  })
  const { data: routeDetail } = useQuery({
    queryKey: ["route", testRouteId],
    queryFn: () => getRoute(Number(testRouteId)),
    enabled: props.open && props.mode === "test" && !!testRouteId && stagePreset === "to_step_ready",
  })

  useEffect(() => {
    if (props.mode !== "test") return
    if (!testTechcardId && techcards && techcards.length > 0) {
      const firstWithProduct = techcards.find((t) => t.product_id && t.is_active);
      if (firstWithProduct) setTestTechcardId(String(firstWithProduct.id));
    }
  }, [props.mode, techcards, testTechcardId])

  useEffect(() => {
    if (props.mode !== "test") return
    const activeRoutes = (routes || []).filter((r) => r.is_active);
    if (!testRouteId && activeRoutes.length > 0) {
      setTestRouteId(String(activeRoutes[0].id));
    }
  }, [props.mode, routes, testRouteId])

  const allRows = useMemo(() => {
    return (previewData?.items as Record<string, unknown>[]) ?? []
  }, [previewData])

  const filteredRows = useMemo(() => {
    let rows = allRows
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
  }, [allRows, filterStatus, sortConfig])

  const summary = useMemo(() => {
    const total = allRows.length
    const invalid = allRows.filter((r) => r.status === "invalid").length
    const warning = allRows.filter((r) => r.status === "warning").length
    return { total, invalid, warning }
  }, [allRows])

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

  async function handleFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0]
    if (!f) return
    setFile(f)
    setLoading(true)
    setError(null)
    try {
      const data = await uploadExcel(f, {
        productionPlanId: props.productionPlanId,
        planMonth: planMonth || undefined,
        planVersion: planVersion || undefined,
        rowSelection: rowSelection || undefined,
      })
      setPreviewData(data)
      const planId = String(data.planId ?? data.production_plan_id ?? "")
      const changeSetId = String(data.changeSetId ?? data.change_set_id ?? "")
      if (planId && changeSetId) {
        setPendingChangeSet({ planId, changeSetId })
      }
      setStep("preview")
    } catch (e) {
      setError(getErrorMessage(e))
    } finally {
      setLoading(false)
    }
  }

  async function handleFullRouteRun() {
    if (!testTechcardId) {
      setError("Выберите техкарту")
      return
    }
    if (!testRouteId) {
      setError("Выберите маршрут")
      return
    }
    if (stagePreset === "to_step_ready" && !targetRouteStepId) {
      setError("Выберите целевой шаг маршрута")
      return
    }
    setLoading(true)
    setError(null)
    try {
      const parsedQty = Number(testQuantity || "100")
      const data = await runDemoFullRoute({
        initial_quantity: Number.isFinite(parsedQty) && parsedQty > 0 ? parsedQty : 100,
        techcard_id: Number(testTechcardId),
        route_id: Number(testRouteId),
        run_id: testRunId || undefined,
        scenario_id: scenarioId.trim() || undefined,
        plan_month: planMonth || undefined,
        plan_version: planVersion || undefined,
        production_plan_id: props.productionPlanId,
        stage_preset: stagePreset,
        target_route_step_id: stagePreset === "to_step_ready" ? Number(targetRouteStepId) : null,
      })
      setResult({
        ...data,
        is_demo_run: true,
      })
      setPendingChangeSet(null)
      setStep("result")
      props.onSuccess(String(data.production_plan_id), "0")
    } catch (e) {
      setError(getErrorMessage(e))
    } finally {
      setLoading(false)
    }
  }

  async function handleApply() {
    if (!previewData) return
    const planId = String(previewData.planId ?? previewData.production_plan_id ?? "")
    const changeSetId = String(previewData.changeSetId ?? previewData.change_set_id ?? "")
    if (!planId || !changeSetId) {
      setError("Не найден planId или changeSetId")
      return
    }
    setLoading(true)
    setError(null)
    try {
      const data = await applyChangeSet(planId, changeSetId)
      setResult(data)
      setPendingChangeSet(null)
      setStep("result")
      props.onSuccess(planId, changeSetId)
    } catch (e) {
      setError(getErrorMessage(e))
    } finally {
      setLoading(false)
    }
  }

  function toggleSort(key: string) {
    setSortConfig((prev) => {
      if (!prev || prev.key !== key) return { key, dir: "asc" }
      if (prev.dir === "asc") return { key, dir: "desc" }
      return null
    })
  }

  function reset() {
    setStep("upload")
    setFile(null)
    setPreviewData(null)
    setResult(null)
    setError(null)
    setSortConfig(null)
    setFilterStatus("all")
    setSearchQuery("")
    setPlanMonth("")
    setPlanVersion("")
    setRowSelection("")
    setTestRunId("")
    setScenarioId("")
    setTestQuantity("100")
    setStagePreset("before_approve")
    setTargetRouteStepId("")
    setPendingChangeSet(null)
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
    if (pendingChangeSet) {
      discardImport(pendingChangeSet.planId, pendingChangeSet.changeSetId)
    }
    reset()
    props.onClose()
  }

  return (
    <>
      <Dialog open={props.open} onOpenChange={(open) => { if (!open) handleClose() }}>
      <DialogContent className={`w-full max-h-[95vh] overflow-hidden flex flex-col ${step === "preview" ? "max-w-[95vw]" : "max-w-2xl"}`}>
        <DialogHeader>
          <DialogTitle>
            {props.mode === "test" ? "Тестовый импорт плана" : "Импорт производственного плана"}
          </DialogTitle>
          <DialogDescription>
            {props.mode === "test"
              ? "Загрузка тестового плана (ЮП-2630) для проверки"
              : "Загрузите файл Excel и проверьте изменения перед применением"}
          </DialogDescription>
        </DialogHeader>

        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
            {error}
          </div>
        )}

        {step === "upload" && (
          <div className="space-y-4">
            {props.mode === "test" ? (
              <div className="space-y-4 py-1">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <div>
                    <label className="text-xs text-muted-foreground">Техкарта</label>
                    <select
                      className="h-10 w-full rounded-md border bg-background px-3 text-sm"
                      value={testTechcardId}
                      onChange={(e) => setTestTechcardId(e.target.value)}
                    >
                      <option value="">Выберите техкарту...</option>
                      {(techcards || [])
                        .filter((tc) => tc.product_id && tc.is_active)
                        .map((tc) => {
                          const product = (products || []).find((p) => p.id === tc.product_id);
                          const article = (product?.sku || "—").trim();
                          const productName = (product?.name || tc.version || "—").trim();
                          return (
                            <option key={tc.id} value={String(tc.id)}>
                              Арт: {article} · {productName} · ТК #{tc.id}
                            </option>
                          );
                        })}
                    </select>
                  </div>
                  <div>
                    <label className="text-xs text-muted-foreground">Маршрут</label>
                    <select
                      className="h-10 w-full rounded-md border bg-background px-3 text-sm"
                      value={testRouteId}
                      onChange={(e) => setTestRouteId(e.target.value)}
                    >
                      <option value="">Выберите маршрут...</option>
                      {(routes || [])
                        .filter((r) => r.is_active)
                        .map((route) => (
                          <option key={route.id} value={String(route.id)}>
                            #{route.id} · {route.name}
                          </option>
                        ))}
                    </select>
                  </div>
                  <div>
                    <label className="text-xs text-muted-foreground">Стадия остановки</label>
                    <select
                      className="h-10 w-full rounded-md border bg-background px-3 text-sm"
                      value={stagePreset}
                      onChange={(e) => setStagePreset(e.target.value as any)}
                    >
                      <option value="before_approve">До апрува</option>
                      <option value="after_approve">После апрува</option>
                      <option value="after_release">После запуска</option>
                      <option value="to_step_ready">На выбранный шаг ready</option>
                      <option value="full_route">Полный прогон</option>
                    </select>
                  </div>
                  {stagePreset === "to_step_ready" && (
                    <div>
                      <label className="text-xs text-muted-foreground">Целевой шаг маршрута</label>
                      <select
                        className="h-10 w-full rounded-md border bg-background px-3 text-sm"
                        value={targetRouteStepId}
                        onChange={(e) => setTargetRouteStepId(e.target.value)}
                      >
                        <option value="">Выберите шаг...</option>
                        {(routeDetail?.steps || []).map((step: RouteStep) => (
                          <option key={step.id} value={String(step.id)}>
                            #{step.sequence} · {step.section_code} · {step.operation_name}
                          </option>
                        ))}
                      </select>
                    </div>
                  )}
                  <div>
                    <label className="text-xs text-muted-foreground">Количество</label>
                    <Input value={testQuantity} onChange={(e) => setTestQuantity(e.target.value)} placeholder="100" />
                  </div>
                  <div>
                    <label className="text-xs text-muted-foreground">Run ID (опционально)</label>
                    <Input value={testRunId} onChange={(e) => setTestRunId(e.target.value)} placeholder="auto" />
                  </div>
                  <div>
                    <label className="text-xs text-muted-foreground">Scenario ID (опционально)</label>
                    <Input value={scenarioId} onChange={(e) => setScenarioId(e.target.value)} placeholder="none_fg / drill_fg / ..." />
                  </div>
                  {!props.productionPlanId && (
                    <>
                      <div>
                        <label className="text-xs text-muted-foreground">Месяц плана (например 2026-05)</label>
                        <Input value={planMonth} onChange={(e) => setPlanMonth(e.target.value)} placeholder="2026-05" />
                      </div>
                      <div>
                        <label className="text-xs text-muted-foreground">Версия плана (например 1)</label>
                        <Input value={planVersion} onChange={(e) => setPlanVersion(e.target.value)} placeholder="1" />
                      </div>
                    </>
                  )}
                </div>
                <div className="flex gap-2 justify-end">
                  <Button onClick={handleFullRouteRun} disabled={loading}>
                    {loading ? "Запуск…" : "Запустить тест"}
                  </Button>
                </div>
              </div>
            ) : (
              <>
              {!props.productionPlanId && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <div>
                    <label className="text-xs text-muted-foreground">Месяц плана (например 2026-05)</label>
                    <Input
                      value={planMonth}
                      onChange={(e) => setPlanMonth(e.target.value)}
                      placeholder="2026-05"
                    />
                  </div>
                  <div>
                    <label className="text-xs text-muted-foreground">Версия плана (например 1)</label>
                    <Input
                      value={planVersion}
                      onChange={(e) => setPlanVersion(e.target.value)}
                      placeholder="1"
                    />
                  </div>
                </div>
              )}
              <div className="mt-3">
                <label className="text-xs text-muted-foreground">Выбор строк Excel (опционально)</label>
                <Input
                  value={rowSelection}
                  onChange={(e) => setRowSelection(e.target.value)}
                  placeholder="5,7,12-15"
                />
              </div>
              <div
                className="border-2 border-dashed rounded-lg p-8 text-center cursor-pointer hover:bg-accent/50 transition-colors"
                onClick={() => fileInputRef.current?.click()}
              >
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".xlsx,.xls,.xlsm,.xlsb,.ods"
                  className="hidden"
                  onChange={handleFileSelect}
                />
                <Upload className="mx-auto h-12 w-12 text-muted-foreground mb-4" />
                <p className="text-sm text-muted-foreground">
                  {loading ? "Загрузка…" : "Нажмите или перетащите заполненный файл Excel"}
                </p>
                <p className="text-xs text-muted-foreground mt-2">
                  Поддерживаются .xlsx, .xls, .xlsm, .xlsb, .ods
                </p>
                {file && !loading && (
                  <p className="text-xs text-blue-600 mt-2 font-medium">{file.name}</p>
                )}
              </div>
              </>
            )}
          </div>
        )}

        {step === "preview" && previewData && (
          <div className="flex-1 overflow-hidden flex flex-col space-y-4">
            {summary.invalid > 0 && (
              <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
                <strong>{summary.invalid} строк с ошибками</strong> — будут добавлены в план с пометкой.
              </div>
            )}
            {(() => {
              const summaryData = (previewData?.summary as Record<string, unknown>) || {}
              const selection = String(summaryData.row_selection ?? "")
              const autoRows = (summaryData.auto_included_row_numbers as unknown[] | undefined) || []
              if (!selection) return null
              return (
                <div className="rounded-lg border border-blue-200 bg-blue-50 p-3 text-sm text-blue-900">
                  <div><strong>Фильтр строк:</strong> {selection}</div>
                  {autoRows.length > 0 && (
                    <div className="mt-1">
                      <strong>Автодобавлены парные строки:</strong> {autoRows.join(", ")}
                    </div>
                  )}
                </div>
              )
            })()}
            <div className="flex items-center justify-between flex-wrap gap-2">
              <div className="flex gap-4 text-sm">
                <span><strong>Всего:</strong> {summary.total}</span>
                {summary.invalid > 0 && <span className="text-red-600"><strong>Ошибок:</strong> {summary.invalid}</span>}
                {summary.warning > 0 && <span className="text-amber-600"><strong>Предупр.:</strong> {summary.warning}</span>}
                {summary.invalid === 0 && summary.warning === 0 && <span className="text-green-600 text-xs">Без ошибок</span>}
              </div>
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  placeholder="Поиск: строка, ID, артикул..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="h-7 w-48 px-2 py-1 text-xs border rounded-md bg-background"
                />
                <div className="flex gap-1">
                  {(["all", "invalid", "warning"] as const).map((f) => (
                    <button
                      key={f}
                      onClick={() => setFilterStatus(f)}
                      className={`px-2.5 py-1 text-xs rounded-md border transition-colors ${
                        filterStatus === f
                          ? "bg-primary text-primary-foreground border-primary"
                          : "bg-background hover:bg-accent border-input"
                      }`}
                    >
                      {f === "all" ? "Все" : f === "invalid" ? "Ошибки" : "Предупр."}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {Object.keys(errorBreakdown).length > 0 && (
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <span className="text-muted-foreground">Ошибки по типам:</span>
                {Object.entries(errorBreakdown).map(([code, count]) => (
                  <span key={code} className="bg-red-50 text-red-700 px-2 py-0.5 rounded border border-red-100">
                    {code}: {count}
                  </span>
                ))}
                {errorBreakdown["product_not_found"] > 0 && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="ml-auto h-7 text-xs gap-1"
                    onClick={() => { navigate("/references/raw-materials"); props.onClose() }}
                  >
                    <ExternalLink className="h-3 w-3" />
                    Открыть справочники
                  </Button>
                )}
              </div>
            )}

            <div className="flex-1 overflow-auto border rounded-lg">
              <ImportDiffTable rows={filteredRows} sortConfig={sortConfig} onSort={toggleSort} />
            </div>
          </div>
        )}

        {step === "result" && result && (
          <div className="text-center py-6">
            {(result as any).is_demo_run ? (
              <div className="space-y-4 text-left">
                <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-green-100 mb-1">
                  <Check className="h-8 w-8 text-green-600" />
                </div>
                <h3 className="text-lg font-medium">
                  {(result as any).stopped_at_stage === "completed" 
                    ? "Сквозной прогон выполнен" 
                    : `Остановлено на стадии: ${(result as any).stopped_at_stage || "—"}`}
                </h3>
                <div className="grid grid-cols-2 gap-3 text-sm">
                  <div className="rounded border p-2">
                    <div className="text-muted-foreground">Run ID</div>
                    <div className="font-medium">{String((result as any).run_id || "—")}</div>
                  </div>
                  <div className="rounded border p-2">
                    <div className="text-muted-foreground">Позиция</div>
                    <div className="font-medium">#{String((result as any).plan_position_id || "—")}</div>
                  </div>
                  <div className="rounded border p-2">
                    <div className="text-muted-foreground">Стадия</div>
                    <div className="font-medium">{String((result as any).stage_preset || "—")}</div>
                  </div>
                  <div className="rounded border p-2">
                    <div className="text-muted-foreground">Шагов выполнено</div>
                    <div className="font-medium">{(result as any).tasks_created || 0}</div>
                  </div>
                </div>
                <div className="max-h-56 overflow-auto rounded border">
                  <table className="w-full text-xs">
                    <thead className="bg-muted/50 border-b">
                      <tr>
                        <th className="text-left p-2">Участок</th>
                        <th className="text-left p-2">Вход</th>
                        <th className="text-left p-2">Брак</th>
                        <th className="text-left p-2">Годные</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(((result as any).stage_results as any[]) || []).map((s, idx) => (
                        <tr key={`${s.section_id}-${idx}`} className="border-b">
                          <td className="p-2">{s.section_code}</td>
                          <td className="p-2">{s.input_qty}</td>
                          <td className="p-2">{s.defect_qty} ({s.defect_percent}%)</td>
                          <td className="p-2">{s.good_qty}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ) : (
              <>
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
              </>
            )}
          </div>
        )}

        <DialogFooter className="shrink-0">
          {step === "preview" && (
            <>
              <Button variant="outline" onClick={reset} disabled={loading}>
                Назад
              </Button>
              <Button onClick={handleApply} disabled={loading}>
                {loading ? "Применение…" : "Применить изменения"}
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
    </>
  )
}
