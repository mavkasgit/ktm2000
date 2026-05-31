import { useMemo, useState } from "react"
import { AlertTriangle, Route } from "lucide-react"
import { useQuery } from "@tanstack/react-query"
import { Button, AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogTitle, AlertDialogDescription, AlertDialogFooter, AlertDialogAction, AlertDialogCancel, Combobox } from "@/shared/ui"
import { cn } from "@/shared/utils/cn"
import { PlanPositionOut } from "@/shared/api/productionPlans"
import { ProductionRoute } from "@/shared/api/routes"
import { routeCheck } from "@/shared/api/productionPlans"
import { PLAN_POSITIONS_GRID } from "../lib/gridTemplates"
import {
  translateLabel,
  routeMetaLabel,
  routeErrorLabels,
  errorLabels,
  warningLabels,
  isRiskyForApprove,
  DuplicateConflict,
} from "../lib/plan-labels"

export function PositionRow({ pos, onApprove, onDelete, selected, routes, onAssignRoute, onOpenDetail, duplicateConflict, onJumpToPosition, onSelect }: {
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
  const noErrors = !hasErrors && !duplicateConflict
  const noWarnings = !hasWarnings
  const routeColSpan = noErrors && noWarnings ? 3 : noWarnings ? 2 : 1
  const qty = Number(pos.quantity || 0)
  const qtyStr = Number.isInteger(qty) ? String(qty) : qty.toFixed(3).replace(/\.?0+$/, '')
  const originalQtyRaw = (pos.payload?.original_quantity as string | number | null | undefined) ?? null
  const originalQtyNum = originalQtyRaw != null ? Number(originalQtyRaw) : null
  const originalQtyDisplay = originalQtyNum != null && Number.isFinite(originalQtyNum)
    ? (Number.isInteger(originalQtyNum) ? String(originalQtyNum) : String(originalQtyNum))
    : null
  const qtyAdjusted = originalQtyDisplay != null && originalQtyDisplay !== qtyStr
  const quantityPerHanger = (pos.payload?.quantity_per_hanger as number | null | undefined) ?? null
  const hangerCount = quantityPerHanger && quantityPerHanger > 0
    ? qty / quantityPerHanger
    : null
  const hangerDisplay = hangerCount != null
    ? (Number.isInteger(hangerCount) ? String(hangerCount) : hangerCount.toFixed(1))
    : null
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
        items: routeIssues.map((issue: string) => translateLabel(issue, routeErrorLabels)),
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
        items: routeIssues.map((issue: string) => translateLabel(issue, routeErrorLabels)),
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
    <div
      id={`plan-position-${pos.id}`}
      className={`grid items-start border-b ${hasErrors || hasDuplicateConflict ? "bg-red-50" : hasWarnings ? "bg-amber-50" : ""} ${selected ? "bg-blue-100 ring-1 ring-blue-300" : ""} cursor-pointer hover:bg-accent hover:ring-1 hover:ring-ring/20 transition-colors`}
      style={{ gridTemplateColumns: PLAN_POSITIONS_GRID }}
      onClick={(e) => {
        if (onSelect) {
          e.stopPropagation()
          onSelect(pos.id)
        } else {
          onOpenDetail?.()
        }
      }}
    >
      <div className="p-2 text-sm">
        <span className="text-muted-foreground">#{pos.id}</span>
      </div>
      <div className="p-2 text-sm font-medium">{rowNum}</div>
      <div className="p-2 text-sm">{pos.source_sku}</div>
      <div className="p-2 text-sm whitespace-nowrap">
        {qtyAdjusted ? (
          <span>
            <span className="text-muted-foreground">{originalQtyDisplay}</span>
            <span className="mx-1 text-muted-foreground">→</span>
            <span className="font-medium text-amber-600">
              {qtyStr}{hangerDisplay ? ` (${hangerDisplay}П)` : ''}
            </span>
          </span>
        ) : (
          <span>
            {qtyStr}{hangerDisplay ? ` (${hangerDisplay}П)` : ''}
          </span>
        )}
      </div>
      <div className="p-2 text-sm truncate whitespace-nowrap" title={pos.source_name ?? undefined}>{pos.source_name ?? "—"}</div>
      <div className="p-2 text-sm truncate overflow-hidden">
        {routes && onAssignRoute ? (
          <div onClick={(e) => e.stopPropagation()} className="truncate">
          <Combobox
            options={[{ label: "— Снять маршрут —", value: "__clear__" }, ...routes.map(r => ({ label: r.name, value: String(r.id) }))]}
            value={pos.route_id ? String(pos.route_id) : undefined}
            onValueChange={(v) => onAssignRoute(pos.id, v === "__clear__" ? null : Number(v))}
            placeholder={routeError || "Не назначен"}
            emptyText="Маршрут не найден"
            className={cn(
              "rounded-md border border-dashed border-input px-2 py-1.5 hover:bg-accent/50 hover:border-primary/50 transition-colors cursor-pointer group w-full",
              pos.route_id ? "border-solid border-blue-200 bg-blue-50/50" : "bg-muted/20",
            )}
            triggerContent={
              <span className="inline-flex items-center gap-1.5 w-full min-w-0">
                <Route className={cn("h-3.5 w-3.5 shrink-0", pos.route_id ? "text-blue-600" : "text-muted-foreground group-hover:text-primary")} />
                {pos.route_name ? (
                  <span className="text-blue-700 truncate" title={`${pos.route_name}${routeSourceLabel ? ` (${routeSourceLabel})` : ''}`}>
                    {pos.route_name}
                    {routeSourceLabel && <span className="text-xs text-muted-foreground ml-1">({routeSourceLabel})</span>}
                  </span>
                ) : (
                  <span className={cn("text-xs truncate", routeError ? "text-red-600" : "text-muted-foreground group-hover:text-foreground")} title={routeError || undefined}>
                    {routeError || "Нажмите для выбора"}
                  </span>
                )}
              </span>
            }
          />
          </div>
        ) : pos.route_name ? (
          <span className="inline-flex items-center gap-1 text-blue-700 truncate" title={`Маршрут #${pos.route_id} ${routeSourceLabel}`}>
            <Route className="h-3 w-3 shrink-0" />
            {pos.route_name}
            {routeSourceLabel && <span className="text-xs text-muted-foreground">({routeSourceLabel})</span>}
          </span>
        ) : (
          <span className={routeError ? "text-red-600 text-xs truncate" : "text-muted-foreground text-xs truncate"} title={routeError || undefined}>
            {routeError || "Не назначен"}
          </span>
        )}
      </div>
      <div className="p-2 text-xs">
        {noErrors ? null : (
        <div className="space-y-1 text-red-600">
          {hasDuplicateConflict && (
            <div>
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
        )}
      </div>
      <div className="p-2 text-xs">
        {noWarnings ? null : (
        <span className="truncate block text-amber-600" title={translatedWarnings.join("\n")}>
          {translatedWarnings.join(", ")}
        </span>
        )}
      </div>
      <div className="p-2">
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
      </div>
    </div>

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
