import { Fragment, useEffect, useMemo, useState } from "react"
import { ChevronDown, ChevronUp, FileSpreadsheet, RotateCcw } from "lucide-react"
import {
  approvePositions,
  createReleaseBatch,
  previewProductionPlan,
  releaseBatch,
  rollbackChangeSet,
} from "../api"
import { ImportWizard } from "../ImportWizard"
import { listRecentImports } from "@/shared/api"
import type { RecentImport } from "@/shared/api"
import {
  routeCheck,
  sectionTotals,
  type RouteCheckResponse,
  type RouteCheckStep,
  type SectionTotalsLine,
} from "@/shared/api/productionPlans"
import { Button } from "@/shared/ui"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/shared/ui"
import { Badge } from "@/shared/ui"
import type { BackendIssue, FlowIds } from "../types"

type UnknownRecord = Record<string, unknown>

const statusLabels: Record<string, string> = {
  parsed: "Распарсен",
  applied: "Применён",
  cancelled: "Отменён",
  failed: "Ошибка",
}

const statusToneMap: Record<string, "neutral" | "success" | "warning" | "danger"> = {
  parsed: "neutral",
  applied: "success",
  cancelled: "warning",
  failed: "danger",
}

const modeLabels: Record<string, string> = {
  create_plan: "Новый план",
  append_to_plan: "Добавление",
  replace_draft_from_same_source: "Замена черновика",
}

function readId(payload: unknown, keys: string[]): string | undefined {
  if (!payload || typeof payload !== "object") return undefined
  const asRecord = payload as UnknownRecord
  for (const key of keys) {
    const value = asRecord[key]
    if (typeof value === "string" && value.trim() !== "") return value
  }
  return undefined
}

function readArray(payload: unknown, keys: string[]) {
  if (!payload || typeof payload !== "object") return []
  const asRecord = payload as UnknownRecord
  for (const key of keys) {
    const value = asRecord[key]
    if (Array.isArray(value)) return value
  }
  return []
}

function collectIssues(payload: unknown): string[] {
  const issueItems = readArray(payload, ["issues", "warnings", "errors"]) as BackendIssue[]
  const labels: Record<string, string> = {
    product_not_found: "изделие не найдено",
    paired_profile_product_unmapped: "парный профиль не сопоставлен",
    active_techcard_not_found: "нет активной техкарты",
    active_route_not_found: "нет активного маршрута",
  }
  return issueItems.map((issue) => {
    if (issue.code === "product_not_found") {
      return `${labels.product_not_found}: ${issue.productCode ?? "неизвестно"}`
    }
    if (issue.code === "paired_profile_product_unmapped") {
      return `${labels.paired_profile_product_unmapped}: ${issue.profileCode ?? "неизвестно"}`
    }
    const code = issue.code ?? "issue"
    return `${labels[String(code)] ?? code}: ${issue.message ?? "нет деталей"}`
  })
}

function formatExpectedRoute(steps: RouteCheckStep[]) {
  return steps.map(s => s.step_id.split('/').pop() ?? s.step_id).join(' → ')
}

export function PlanPage() {
  const [loading, setLoading] = useState<string | null>(null)
  const [flowIds, setFlowIds] = useState<FlowIds>({})
  const [planRows, setPlanRows] = useState<UnknownRecord[]>([])
  const [selectedPositionIds, setSelectedPositionIds] = useState<Set<string>>(new Set())
  const [routeChecks, setRouteChecks] = useState<Record<string, RouteCheckResponse>>({})
  const [sectionTotalsRows, setSectionTotalsRows] = useState<SectionTotalsLine[]>([])
  const [expandedPositions, setExpandedPositions] = useState<Set<string>>(new Set())
  const [issues, setIssues] = useState<string[]>([])
  const [importOpen, setImportOpen] = useState(false)
  const [recentImports, setRecentImports] = useState<RecentImport[]>([])
  const [expandedImports, setExpandedImports] = useState<Set<number>>(new Set())

  useEffect(() => {
    listRecentImports(5).then(setRecentImports).catch(() => setRecentImports([]))
  }, [importOpen])

  const canPreviewPlan = !!flowIds.planId && !loading
  const canApprove = !!flowIds.planId && selectedPositionIds.size > 0 && !loading
  const canCreateBatch = !!flowIds.planId && !loading
  const canRelease = !!flowIds.releaseBatchId && !loading
  const canRollback = !!flowIds.planId && !!flowIds.changeSetId && !loading

  const rowsSummary = useMemo(() => {
    return {
      plan: planRows.length,
      approved: selectedPositionIds.size,
    }
  }, [planRows.length, selectedPositionIds.size])

  async function runStep(name: string, action: () => Promise<unknown>, onSuccess: (payload: unknown) => void) {
    setLoading(name)
    try {
      const payload = await action()
      setIssues(collectIssues(payload))
      onSuccess(payload)
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unknown error"
      setIssues([message])
    } finally {
      setLoading(null)
    }
  }

  function togglePosition(positionId: string) {
    setSelectedPositionIds((prev) => {
      const next = new Set(prev)
      if (next.has(positionId)) {
        next.delete(positionId)
      } else {
        next.add(positionId)
      }
      return next
    })
  }

  function toggleImportExpand(id: number) {
    setExpandedImports((prev) => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }

  function togglePositionExpand(positionId: string) {
    setExpandedPositions((prev) => {
      const next = new Set(prev)
      if (next.has(positionId)) {
        next.delete(positionId)
      } else {
        next.add(positionId)
      }
      return next
    })
  }

  function handleImportSuccess(planId: string, changeSetId: string) {
    setFlowIds((prev) => ({
      ...prev,
      planId,
      changeSetId,
    }))
  }

  return (
    <div className="max-w-5xl mx-auto p-6 space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold tracking-tight">Импорт плана и запуск в производство</h1>
        <div className="flex items-center gap-3">
          {loading && (
            <Badge variant="secondary">Выполняется: {loading}</Badge>
          )}
          <Button
            size="sm"
            className="gap-2"
            onClick={() => setImportOpen(true)}
          >
            <FileSpreadsheet className="h-4 w-4" />
            Импорт
          </Button>
        </div>
      </div>

      {issues.length > 0 && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">
          <strong>Ошибки / предупреждения</strong>
          <ul className="mt-2 list-disc pl-4 space-y-1">
            {issues.map((line, idx) => (
              <li key={idx}>{line}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Import Section */}
      <Card>
        <CardContent className="p-6 space-y-4">
          {flowIds.planId && (
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <Badge tone="success">План загружен (ID: {flowIds.planId})</Badge>
                {canRollback && (
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={!!loading}
                    onClick={() =>
                      runStep(
                        "rollback_change_set",
                        () => rollbackChangeSet(flowIds.planId!, flowIds.changeSetId!),
                        (payload) => {
                          setFlowIds((prev) => ({
                            ...prev,
                            planId: readId(payload, ["planId"]) ?? prev.planId,
                          }))
                        }
                      )
                    }
                  >
                    <RotateCcw className="h-4 w-4 mr-1" />
                    Откатить
                  </Button>
                )}
              </div>
            </div>
          )}

          {/* Recent Imports */}
          {recentImports.length > 0 && (
            <div className="space-y-3">
              <h3 className="text-sm font-semibold text-muted-foreground">Последние импорты</h3>
          {recentImports.map((imp) => {
            const expanded = expandedImports.has(imp.id)
            const dateStr = new Date(imp.created_at).toLocaleString("ru-RU", {
              day: "2-digit",
              month: "2-digit",
              year: "numeric",
              hour: "2-digit",
              minute: "2-digit",
            })
            const canRollbackThis = imp.status === "applied" && imp.change_set_id && !loading
            return (
              <Card key={imp.id} className="overflow-hidden">
                <CardHeader className="p-4 pb-0">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <FileSpreadsheet className="h-5 w-5 text-muted-foreground" />
                      <div>
                        <CardTitle className="text-sm font-medium">
                          {imp.original_filename}
                        </CardTitle>
                        <CardDescription className="text-xs">
                          {imp.plan_name} · {dateStr}
                        </CardDescription>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <Badge tone={statusToneMap[imp.status] ?? "neutral"}>
                        {statusLabels[imp.status] ?? imp.status}
                      </Badge>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8"
                        onClick={() => toggleImportExpand(imp.id)}
                      >
                        {expanded ? (
                          <ChevronUp className="h-4 w-4" />
                        ) : (
                          <ChevronDown className="h-4 w-4" />
                        )}
                      </Button>
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="p-4 pt-3">
                  {/* Stats row */}
                  <div className="flex items-center gap-4 text-sm mb-3">
                    <div className="flex items-center gap-1.5">
                      <span className="text-muted-foreground">Строк:</span>
                      <span className="font-medium">{imp.parsed_rows} / {imp.total_rows}</span>
                    </div>
                    {imp.error_count > 0 && (
                      <div className="flex items-center gap-1.5 text-red-600">
                        <span className="font-medium">{imp.error_count} ошибок</span>
                      </div>
                    )}
                    {imp.warning_count > 0 && (
                      <div className="flex items-center gap-1.5 text-amber-600">
                        <span className="font-medium">{imp.warning_count} предупр.</span>
                      </div>
                    )}
                    {imp.error_count === 0 && imp.warning_count === 0 && (
                      <div className="text-green-600 text-xs">Без ошибок</div>
                    )}
                    {canRollbackThis && (
                      <Button
                        variant="outline"
                        size="sm"
                        className="ml-auto h-7 text-xs"
                        onClick={() =>
                          runStep(
                            "rollback_change_set",
                            () => rollbackChangeSet(String(imp.production_plan_id), String(imp.change_set_id!)),
                            () => {
                              listRecentImports(5).then(setRecentImports)
                            }
                          )
                        }
                      >
                        <RotateCcw className="h-3 w-3 mr-1" />
                        Откатить
                      </Button>
                    )}
                  </div>

                  {expanded && (
                    <div className="text-sm space-y-2 pt-3 border-t">
                      <div className="grid grid-cols-2 gap-2 text-muted-foreground">
                        <div>План: <span className="text-foreground">{imp.plan_no}</span></div>
                        <div>Режим: <span className="text-foreground">{modeLabels[imp.mode] ?? imp.mode}</span></div>
                        <div>Лист: <span className="text-foreground">{imp.sheet_name}</span></div>
                        <div>Позиций: <span className="text-foreground">{imp.parsed_rows}</span></div>
                      </div>
                      {imp.summary && typeof imp.summary === "object" && Object.keys(imp.summary).length > 0 && (
                        <div className="mt-2 text-muted-foreground">
                          <div className="font-medium text-foreground mb-1">Детали:</div>
                          <div className="grid grid-cols-2 gap-1 text-xs">
                            {Object.entries(imp.summary).map(([key, value]) => (
                              <div key={key}>
                                {key}: <span className="text-foreground">{String(value)}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </CardContent>
              </Card>
            )
          })}
        </div>
      )}
        </CardContent>
      </Card>

      {/* Plan Preview */}
      <Card>
        <CardHeader>
          <CardTitle>Производственный план</CardTitle>
          <CardDescription>
            Просмотр позиций, утверждение и подготовка к запуску
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center gap-3">
            <Button disabled={!canPreviewPlan} onClick={() => runStep("preview_plan", () => previewProductionPlan(flowIds.planId), async (payload) => {
              const rows = readArray(payload, ["positions", "rows", "plan"]) as UnknownRecord[]
              setPlanRows(rows)
              const planId = readId(payload, ["planId", "id"])
              setFlowIds((prev) => ({ ...prev, planId }))
              setSelectedPositionIds(new Set(rows.map((row) => String(row.positionId ?? row.id ?? "")).filter(Boolean)))
              setRouteChecks({})
              setExpandedPositions(new Set())
              // Load route checks for all positions
              const pid = Number(planId || flowIds.planId)
              if (pid) {
                const checks: Record<string, RouteCheckResponse> = {}
                await Promise.all(rows.map(async (row) => {
                  const posId = Number(row.id ?? row.positionId)
                  if (posId) {
                    try {
                      checks[posId] = await routeCheck(pid, posId)
                    } catch { /* ignore */ }
                  }
                }))
                setRouteChecks(checks)
                const sectionData = await sectionTotals(pid)
                setSectionTotalsRows(sectionData.totals)
              }
            })}>
              Показать план
            </Button>
            <span className="text-sm text-muted-foreground">Позиции: {rowsSummary.plan}</span>
          </div>

          {planRows.length > 0 && (
            <div className="rounded-md border max-h-96 overflow-auto">
              <table className="w-full text-sm">
                <thead className="bg-muted sticky top-0">
                  <tr>
                    <th className="text-left p-2 font-medium w-10">✓</th>
                    <th className="text-left p-2 font-medium">Артикул</th>
                    <th className="text-left p-2 font-medium">Кол-во</th>
                    <th className="text-left p-2 font-medium">Ожидаемый маршрут</th>
                    <th className="text-left p-2 font-medium">Активный маршрут</th>
                    <th className="text-left p-2 font-medium">Статус</th>
                    <th className="text-left p-2 font-medium">Доп. упаковка</th>
                  </tr>
                </thead>
                <tbody>
                  {planRows.map((row, idx) => {
                    const positionId = String(row.id ?? row.positionId ?? `row-${idx}`)
                    const check = routeChecks[Number(positionId)]
                    const validationErrors = Array.isArray(row.validation_errors) ? row.validation_errors : []
                    const canSelect = !check || (check.match && validationErrors.length === 0)
                    const isExpanded = expandedPositions.has(positionId)
                    return (
                      <Fragment key={positionId}>
                        <tr className="border-t">
                          <td className="p-2">
                            <input
                              type="checkbox"
                              disabled={!canSelect}
                              checked={selectedPositionIds.has(positionId)}
                              onChange={() => togglePosition(positionId)}
                            />
                          </td>
                          <td className="p-2 text-xs">
                            <button className="text-left" onClick={() => togglePositionExpand(positionId)}>
                              <div className="font-medium">{String(row.source_sku ?? row.sku ?? "—")}</div>
                              <div className="text-muted-foreground truncate max-w-[120px]">{String(row.source_name ?? row.name ?? "")}</div>
                            </button>
                          </td>
                          <td className="p-2 text-xs">{String(row.quantity ?? "—")}</td>
                          <td className="p-2 text-xs">
                            {check ? (
                              <div className="truncate max-w-[200px]" title={check.expected_signature.steps.map(s => s.step_id).join(" → ")}>
                                {check.expected_signature.steps.map(s => s.step_id.split("/").pop() ?? s.step_id).join(" → ")}
                              </div>
                            ) : (
                              <span className="text-muted-foreground">—</span>
                            )}
                          </td>
                          <td className="p-2 text-xs">
                            {check?.active_route_snapshot ? (
                              <span>{check.active_route_snapshot.route_name} ({check.active_route_snapshot.route_version})</span>
                            ) : (
                              <span className="text-muted-foreground">—</span>
                            )}
                          </td>
                          <td className="p-2">
                            {check ? (
                              check.match ? (
                                <Badge tone="success" className="text-xs">OK</Badge>
                              ) : (
                                <Badge tone="danger" className="text-xs">Mismatch</Badge>
                              )
                            ) : (
                              <span className="text-muted-foreground text-xs">—</span>
                            )}
                          </td>
                          <td className="p-2 text-xs">
                            {check && check.expected_signature.additional_pack_operations.length > 0 ? (
                              <span>{check.expected_signature.additional_pack_operations.join(", ")}</span>
                            ) : (
                              <span className="text-muted-foreground">—</span>
                            )}
                          </td>
                        </tr>
                        {isExpanded && check && (
                          <tr className="border-t bg-muted/30">
                            <td colSpan={7} className="p-3 text-xs">
                              <div className="grid gap-3 md:grid-cols-2">
                                <div>
                                  <div className="font-medium mb-1">Ожидаемый маршрут</div>
                                  <div>{check.expected_signature.steps.map(s => s.step_id).join(" → ")}</div>
                                </div>
                                <div>
                                  <div className="font-medium mb-1">Активный маршрут</div>
                                  {check.active_route_snapshot ? (
                                    <div>{check.active_route_snapshot.steps.map(s => `${s.sequence}:${s.section_code}/${s.operation_name}`).join(" → ")}</div>
                                  ) : (
                                    <div className="text-muted-foreground">Нет активного маршрута</div>
                                  )}
                                </div>
                              </div>
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}

          {sectionTotalsRows.length > 0 && (
            <div className="rounded-md border max-h-72 overflow-auto">
              <table className="w-full text-sm">
                <thead className="bg-muted sticky top-0">
                  <tr>
                    <th className="text-left p-2 font-medium">Участок</th>
                    <th className="text-left p-2 font-medium">Код</th>
                    <th className="text-left p-2 font-medium">Позиций</th>
                    <th className="text-left p-2 font-medium">План вход</th>
                    <th className="text-left p-2 font-medium">План выход</th>
                  </tr>
                </thead>
                <tbody>
                  {sectionTotalsRows.map((item) => (
                    <tr key={item.section_id} className="border-t">
                      <td className="p-2 text-xs">{item.section_name}</td>
                      <td className="p-2 text-xs">{item.section_code}</td>
                      <td className="p-2 text-xs">{item.positions_count}</td>
                      <td className="p-2 text-xs">{item.planned_input_quantity}</td>
                      <td className="p-2 text-xs">{item.planned_output_quantity}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div className="flex items-center gap-3 pt-2">
            <Button
              disabled={!canApprove}
              onClick={() => runStep("approve_positions", () => approvePositions(flowIds.planId!, Array.from(selectedPositionIds)), (payload) => {
                setFlowIds((prev) => ({
                  ...prev,
                  approvalId: readId(payload, ["approvalId", "jobId", "id"]),
                }))
              })}
            >
              Утвердить выбранные
            </Button>
            <span className="text-sm text-muted-foreground">Выбрано: {rowsSummary.approved}</span>
          </div>
        </CardContent>
      </Card>

      {/* Release */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Пакет запуска</CardTitle>
          </CardHeader>
          <CardContent>
            <Button
              disabled={!canCreateBatch}
              onClick={() => runStep("create_release_batch", () => createReleaseBatch(flowIds.planId!), (payload) => {
                setFlowIds((prev) => ({
                  ...prev,
                  releaseBatchId: readId(payload, ["releaseBatchId", "batchId", "id"]),
                }))
              })}
            >
              Создать пакет
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Выпуск в производство</CardTitle>
          </CardHeader>
          <CardContent>
            <Button
              disabled={!canRelease}
              onClick={() => runStep("release_batch", () => releaseBatch(flowIds.releaseBatchId!), (payload) => {
                setFlowIds((prev) => ({
                  ...prev,
                  releaseJobId: readId(payload, ["releaseJobId", "jobId", "id"]),
                }))
              })}
            >
              Выпустить
            </Button>
          </CardContent>
        </Card>
      </div>

      <ImportWizard open={importOpen} onClose={() => setImportOpen(false)} onSuccess={handleImportSuccess} />
    </div>
  )
}
