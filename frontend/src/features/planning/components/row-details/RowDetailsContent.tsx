import { fmtQty } from "@/shared/utils/fmtQty"
import { Input, Button } from "@/shared/ui"
import { type RowDetailsContentMode, type RowDetailsData } from "./types"
import { useEffect, useMemo, useState } from "react"
import { useQueryClient, useMutation } from "@tanstack/react-query"
import { updatePositionQuantity } from "@/shared/api/productionPlans"
import { toast } from "@/shared/ui"
import { getErrorMessage } from "@/shared/api/client"
import { queryKeys } from "@/shared/api/queryKeys"
import { statusLabels } from "@/shared/lib/generated-labels"
import { ExecutionStagesTable } from "./ExecutionStagesTable"
import { ExecutionEventsTable } from "./ExecutionEventsTable"

function planPreviewUrl(planId: number): string {
  return `/plans/${planId}/preview`
}

function jumpToPlanPosition(positionId: number): void {
  const row = document.getElementById(`plan-position-${positionId}`)
  if (!row) return
  row.scrollIntoView({ behavior: "smooth", block: "center" })
  row.classList.add("ring-2", "ring-red-300")
  setTimeout(() => row.classList.remove("ring-2", "ring-red-300"), 1800)
}

interface RowDetailsContentProps {
  data: RowDetailsData
  showPlanLink?: boolean
  onSaved?: () => void
  contentMode?: RowDetailsContentMode
}

export function RowDetailsContent({
  data,
  showPlanLink = true,
  onSaved,
  contentMode = "stages",
}: RowDetailsContentProps) {
  const queryClient = useQueryClient()

  const [currentQuantity, setCurrentQuantity] = useState(data.quantity)
  const [editQuantity, setEditQuantity] = useState(fmtQty(data.quantity))
  const [editQuantityPerHanger, setEditQuantityPerHanger] = useState(
    data.quantityPerHanger ? String(data.quantityPerHanger) : ""
  )

  useEffect(() => {
    setCurrentQuantity(data.quantity)
    setEditQuantity(fmtQty(data.quantity))
    setEditQuantityPerHanger(data.quantityPerHanger ? String(data.quantityPerHanger) : "")
  }, [data.id, data.quantity, data.quantityPerHanger])

  const updateMutation = useMutation({
    mutationFn: (payload: { quantity: number | string; quantity_per_hanger: number | null }) => {
      if (!data.productionPlanId || typeof data.id !== "number") {
        throw new Error("Нет данных для сохранения")
      }
      return updatePositionQuantity(data.productionPlanId, data.id, {
        quantity: payload.quantity,
        quantity_per_hanger: payload.quantity_per_hanger,
      })
    },
    onSuccess: (updatedPosition) => {
      const newQty = Number(updatedPosition.quantity)
      if (!Number.isNaN(newQty)) {
        setCurrentQuantity(newQty)
      }
      void queryClient.invalidateQueries({ queryKey: queryKeys.plan.allPositions() })
      void queryClient.invalidateQueries({ queryKey: queryKeys.plan.positionDetail(Number(data.id)) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.sections.all() })
      void queryClient.invalidateQueries({ queryKey: queryKeys.shopfloor.boardAll() })
      void queryClient.invalidateQueries({ queryKey: queryKeys.shopfloor.statsAll() })
      void queryClient.invalidateQueries({ queryKey: queryKeys.shopfloor.summary() })
      void queryClient.invalidateQueries({ queryKey: queryKeys.transfers.readyAll() })
      void queryClient.invalidateQueries({ queryKey: queryKeys.transfers.historyAll() })
      void queryClient.invalidateQueries({ queryKey: queryKeys.plan.previewAll() })
      toast({ title: "Количество обновлено", variant: "success" })
      onSaved?.()
    },
    onError: (e) => {
      toast({ title: "Ошибка", description: getErrorMessage(e), variant: "destructive" })
    },
  })

  const hangerCount = useMemo(() => {
    const qty = Number(editQuantity) || 0
    const perHanger = Number(editQuantityPerHanger) || 0
    if (perHanger > 0) {
      const val = qty / perHanger
      return Number.isInteger(val) ? String(val) : val.toFixed(1)
    }
    return null
  }, [editQuantity, editQuantityPerHanger])

  const handleSave = () => {
    const qty = Number(editQuantity)
    if (!qty || qty <= 0) {
      toast({ title: "Ошибка", description: "Количество должно быть > 0", variant: "destructive" })
      return
    }
    updateMutation.mutate({
      quantity: qty,
      quantity_per_hanger: editQuantityPerHanger ? Number(editQuantityPerHanger) : null,
    })
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      e.preventDefault()
      handleSave()
    }
  }

  const canEdit = typeof data.id === "number" && data.productionPlanId > 0 &&
    (data.status === "draft" || data.status === "invalid" || data.status === "valid")
  const hasErrors = data.errors.length > 0
  const hasWarnings = data.warnings.length > 0
  const hasRouteCheckIssues = (data.routeCheckIssues?.length ?? 0) > 0
  const hasStages = (data.stages?.length ?? 0) > 0
  const hasRawData = (data.rawExcelRows?.length ?? 0) > 0
  const hasIssues = hasErrors || hasWarnings || hasRouteCheckIssues

  const routeText = data.routeName || data.routeError || "Не назначен"
  const positionIdText = typeof data.id === "number" || typeof data.id === "string" ? String(data.id) : "—"
  const statusLabel = statusLabels[data.status] || data.status

  return (
    <div className="space-y-4">
      <div className="text-sm min-w-0 space-y-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="text-muted-foreground">Статус:</span>
          <span className="font-medium">{statusLabel}</span>
          <span className="text-muted-foreground">·</span>
          <span className="text-muted-foreground">Маршрут:</span>
          <span className={`min-w-0 truncate font-medium ${data.routeError ? "text-red-700" : ""}`}>
            {routeText}
            {data.routeName && data.routeMeta ? ` (${data.routeMeta})` : ""}
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-muted-foreground">
          <span>ID {positionIdText}</span>
          <span>·</span>
          <span>Строка #{data.sourceRowNumber ?? "—"}</span>
          {data.productionPlanId > 0 && (
            <>
              <span>·</span>
              <span>План {data.productionPlanId}</span>
              {showPlanLink && (
                <>
                  <span>·</span>
                  <a
                    href={planPreviewUrl(data.productionPlanId)}
                    target="_blank"
                    rel="noreferrer"
                    className="text-blue-700 hover:underline"
                  >
                    Открыть план
                  </a>
                </>
              )}
            </>
          )}
          <span>·</span>
          <span>
            Артикул <span className="font-mono font-medium text-foreground">{data.sku}</span>
          </span>
          <span>·</span>
          <span>
            Кол-во{" "}
            {data.originalQuantity && fmtQty(data.originalQuantity) !== fmtQty(currentQuantity) ? (
              <>
                <span>{fmtQty(data.originalQuantity)}</span>
                <span className="mx-1">→</span>
                <span className="font-medium text-amber-600">{fmtQty(currentQuantity)} шт.</span>
              </>
            ) : (
              <span className="font-medium text-foreground">{fmtQty(currentQuantity)} шт.</span>
            )}
          </span>
        </div>
        <div className="font-medium">{data.name || "—"}</div>
      </div>

      {hasRawData && (
        <div className="space-y-1">
          {data.rawExcelRows!.map((r, i) => (
            <div key={i} className="rounded-md border bg-muted/30 px-3 py-2 font-mono text-xs whitespace-pre-wrap break-words">
              {r.text}
            </div>
          ))}
        </div>
      )}

      {canEdit && (
        <div className="rounded-lg border p-3">
          <div className="text-sm font-medium">Редактирование количества <span className="text-sm font-medium">{data.sku}</span></div>
          <div className="space-y-3">
            <div className="flex items-end gap-3 flex-wrap">
              <div>
                <label className="text-xs text-muted-foreground">Количество</label>
                <Input
                  type="number"
                  value={editQuantity}
                  onChange={(e) => setEditQuantity(e.target.value)}
                  onKeyDown={handleKeyDown}
                  min="1"
                  step="1"
                  className="mt-1 w-[200px]"
                />
              </div>
              <div>
                <label className="text-xs text-muted-foreground">
                  Кол-во на подвес{data.quantityPerHanger ? ` (из справочника: ${data.quantityPerHanger})` : ""}
                </label>
                <Input
                  type="number"
                  value={editQuantityPerHanger}
                  onChange={(e) => setEditQuantityPerHanger(e.target.value)}
                  onKeyDown={handleKeyDown}
                  min="1"
                  step="1"
                  placeholder={data.quantityPerHanger ? String(data.quantityPerHanger) : "—"}
                  className="mt-1 w-[200px]"
                />
              </div>
              {hangerCount !== null && (
                <div className="text-sm text-muted-foreground whitespace-nowrap pb-2">
                  = <strong>{hangerCount}П</strong>
                </div>
              )}
            </div>
            <Button onClick={handleSave} disabled={updateMutation.isPending} size="sm">
              {updateMutation.isPending ? "Сохранение..." : "Сохранить"}
            </Button>
          </div>
        </div>
      )}

      {hasIssues && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3">
          <div className="text-sm font-medium text-amber-900 mb-2">Проблемы и предупреждения</div>
          <div className="space-y-3 text-sm">
            {hasErrors && (
              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-red-800 mb-1">Ошибки</div>
                {(data.duplicateConflictIds?.length ?? 0) > 0 && (
                  <div className="mb-2 flex flex-wrap gap-2">
                    {data.duplicateConflictIds!.map((id) => (
                      <button
                        key={id}
                        type="button"
                        className="text-xs underline text-red-700 hover:no-underline"
                        onClick={() => jumpToPlanPosition(id)}
                      >
                        Конфликт #{id}
                      </button>
                    ))}
                  </div>
                )}
                <ul className="space-y-1 text-red-700">
                  {data.errors.map((err, i) => (
                    <li key={i} className="flex items-start gap-2">
                      <span className="mt-1.5 h-1.5 w-1.5 rounded-full bg-red-500 shrink-0" />
                      {err}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {hasWarnings && (
              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-amber-800 mb-1">Предупреждения</div>
                <ul className="space-y-1 text-amber-700">
                  {data.warnings.map((w, i) => (
                    <li key={i} className="flex items-start gap-2">
                      <span className="mt-1.5 h-1.5 w-1.5 rounded-full bg-amber-500 shrink-0" />
                      {w}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {hasRouteCheckIssues && (
              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-amber-800 mb-1">Несовпадения маршрута</div>
                <ul className="space-y-1 text-amber-700">
                  {data.routeCheckIssues!.map((issue, i) => (
                    <li key={i} className="flex items-start gap-2">
                      <span className="mt-1.5 h-1.5 w-1.5 rounded-full bg-amber-500 shrink-0" />
                      {issue}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </div>
      )}

      {hasStages && contentMode === "stages" && (
        <ExecutionStagesTable
          stages={data.stages!}
          currentStageSectionId={data.currentStageSectionId}
          currentStageSequence={data.currentStageSequence}
        />
      )}

      {hasStages && contentMode === "events" && (
        <ExecutionEventsTable
          stages={data.stages!}
          statusHistory={data.statusHistory ?? []}
        />
      )}
    </div>
  )
}