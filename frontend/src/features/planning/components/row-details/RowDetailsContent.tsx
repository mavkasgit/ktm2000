import { Badge } from "@/shared/ui"
import { renderIcon } from "@/shared/ui/EntityDialog"
import { type RowDetailsData } from "./types"
import { useMemo, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { listSections } from "@/shared/api/sections"

const statusLabels: Record<string, string> = {
  draft: "Черновик",
  invalid: "Ошибка",
  valid: "Валиден",
  approved: "Утверждён",
  released: "Запущен",
  cancelled: "Отменён",
  parsed: "Распознан",
  failed: "Ошибка",
  applied: "Применён",
  warning: "Предупреждение",
  pending: "Ожидает",
}

const statusVariant: Record<string, string> = {
  draft: "secondary",
  invalid: "destructive",
  valid: "default",
  approved: "default",
  released: "default",
  cancelled: "destructive",
  parsed: "secondary",
  failed: "destructive",
  applied: "default",
  warning: "secondary",
  pending: "secondary",
}

const taskStatusLabels: Record<string, string> = {
  waiting_previous: "Ожидает этап",
  ready: "Готов",
  in_progress: "В работе",
  partially_completed: "Частично выполнен",
  completed: "Выполнен",
  cancelled: "Отменён",
  not_started: "Не начат",
}

function fmtQty(value: number | string): string {
  const num = typeof value === "string" ? Number(value) : value
  if (!Number.isFinite(num)) return String(value)
  if (Number.isInteger(num)) return String(num)
  return num.toFixed(3).replace(/\.?0+$/, "")
}

function fmtEventAt(value: string | null | undefined): string {
  if (!value) return "—"
  const dt = new Date(value)
  if (Number.isNaN(dt.getTime())) return "—"
  return dt.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  })
}

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
}

export function RowDetailsContent({
  data,
  showPlanLink = true,
}: RowDetailsContentProps) {
  const [expandedStages, setExpandedStages] = useState<Record<number, boolean>>({})
  const hasErrors = data.errors.length > 0
  const hasWarnings = data.warnings.length > 0
  const hasRouteCheckIssues = (data.routeCheckIssues?.length ?? 0) > 0
  const hasStages = (data.stages?.length ?? 0) > 0
  const hasRawData = (data.rawExcelRows?.length ?? 0) > 0
  const hasIssues = hasErrors || hasWarnings || hasRouteCheckIssues
  const hasCurrentStage = Boolean(data.currentStageSectionName && data.currentStageSequence)

  const { data: sectionsData } = useQuery({
    queryKey: ["sections"],
    queryFn: listSections,
    enabled: hasCurrentStage || hasStages,
  })

  const sectionMetaById = useMemo(() => {
    const map = new Map<number, { icon: string | null; icon_color: string | null }>()
    ;(sectionsData || []).forEach((s) => map.set(s.id, { icon: s.icon, icon_color: s.icon_color }))
    return map
  }, [sectionsData])

  const currentSectionId = data.currentStageSectionId
  const currentSectionMeta = currentSectionId ? sectionMetaById.get(currentSectionId) : null
  const currentIconColor = currentSectionMeta?.icon_color || "#2563EB"
  const routeText = data.routeName || data.routeError || "Не назначен"
  const currentStageLabel = hasCurrentStage
    ? `#${data.currentStageSequence} ${data.currentStageSectionName}`
    : "Не начат"
  const positionIdText = typeof data.id === "number" || typeof data.id === "string" ? String(data.id) : "—"

  return (
    <div className="space-y-4">
      <div className="rounded-lg border p-3">
        <div className="grid grid-cols-1 gap-2 text-sm">
          <div className="flex items-center gap-2 min-w-0 flex-nowrap overflow-hidden">
            {hasCurrentStage && currentSectionMeta?.icon && (
              <span
                className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded"
                style={{ backgroundColor: `${currentIconColor}20`, color: currentIconColor }}
              >
                {renderIcon(currentSectionMeta.icon, "h-3 w-3")}
              </span>
            )}
            <span className="text-muted-foreground">Текущий этап:</span>
            <span className="font-medium truncate">{currentStageLabel}</span>
            {data.currentStageTaskStatus && (
              <>
                <span className="text-muted-foreground">·</span>
                <span className="font-medium shrink-0">
                  {data.currentStageTaskStatus === "in_progress"
                    ? "В работе"
                    : data.currentStageTaskStatus === "ready"
                      ? "Готов"
                      : data.currentStageTaskStatus}
                </span>
              </>
            )}
            <span className="text-muted-foreground shrink-0">·</span>
            <span className="text-muted-foreground shrink-0">Статус:</span>
            <span className="font-medium shrink-0">{statusLabels[data.status] || data.status}</span>
            <span className="text-muted-foreground shrink-0">·</span>
            <span className="text-muted-foreground shrink-0">Маршрут:</span>
            <span className={`min-w-0 truncate ${data.routeError ? "font-medium text-red-700" : "font-medium"}`}>
              {routeText}
              {data.routeName && data.routeMeta ? ` (${data.routeMeta})` : ""}
            </span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            <div className="md:col-span-2">
              <span className="text-muted-foreground">ID {positionIdText}</span>
              <span className="text-muted-foreground"> · </span>
              <span className="text-muted-foreground">Строка #{data.sourceRowNumber ?? "—"}</span>
              {data.productionPlanId > 0 && (
                <>
                  <span className="text-muted-foreground"> · </span>
                  <span className="text-muted-foreground">План {data.productionPlanId}</span>
                  {showPlanLink && (
                    <>
                      {" "}
                      <a
                        href={planPreviewUrl(data.productionPlanId)}
                        target="_blank"
                        rel="noreferrer"
                        className="text-blue-700 hover:underline"
                      >
                        План
                      </a>
                    </>
                  )}
                </>
              )}
            </div>
            <div className="md:col-span-2 min-w-0">
              <span className="text-muted-foreground">SKU </span>
              <span className="font-mono font-medium">{data.sku}</span>
              <span className="text-muted-foreground"> · Кол-во </span>
              <span className="font-medium">{fmtQty(data.quantity)} шт.</span>
              <span className="text-muted-foreground"> · Наименование </span>
              <span className="font-medium">{data.name || "—"}</span>
            </div>
          </div>

          {hasRawData && (
            <div className="space-y-2">
              <div className="text-sm font-medium">Исходная строка импорта</div>
              {data.rawExcelRows!.map((r, i) => (
                <div key={i} className="text-xs">
                  <div className="rounded-md bg-muted/50 px-3 py-2 font-mono whitespace-pre-wrap break-words">
                    {r.text}
                  </div>
                </div>
              ))}
            </div>
          )}

        </div>
      </div>

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

      {hasStages && (
        <div className="rounded-lg border overflow-auto">
          <table className="w-full text-sm">
            <thead className="border-b bg-muted/50">
              <tr>
                <th className="text-left p-2">Этап</th>
                <th className="text-left p-2">Участок</th>
                <th className="text-left p-2">Статус этапа</th>
                <th className="text-left p-2">План</th>
                <th className="text-left p-2">Выдано</th>
                <th className="text-left p-2" title="Годные">Годные</th>
                <th className="text-left p-2" title="Брак">Брак</th>
                <th className="text-left p-2" title="Итог = Годные + Брак">Итог</th>
                <th className="text-left p-2">Передано</th>
                <th className="text-left p-2">Принято след. этапом</th>
                <th className="text-left p-2">Остаток</th>
                <th className="text-left p-2">% выполнения</th>
              </tr>
            </thead>
            <tbody>
              {data.stages!.map((stage, idx) => {
                const pct = stage.planned_quantity > 0
                  ? ((stage.completed_quantity / stage.planned_quantity) * 100).toFixed(1)
                  : "0.0"
                const sectionMeta = sectionMetaById.get(stage.section_id)
                const stageIcon = stage.section_icon || sectionMeta?.icon || null
                const iconColor = stage.section_icon_color || sectionMeta?.icon_color || "#2563EB"
                const isFinalStage = idx === data.stages!.length - 1
                const isCurrentStage = Boolean(data.currentStageSectionId && stage.section_id === data.currentStageSectionId)
                const isExpanded = Boolean(expandedStages[stage.route_step_id])
                const stageStatusBaseText = taskStatusLabels[stage.task_status] || stage.task_status
                const stageStatusText = isFinalStage ? `${stageStatusBaseText} (финальный этап)` : stageStatusBaseText
                const remainingQty = Math.max(stage.planned_quantity - stage.accounted_total_qty, 0)
                return (
                  [
                    <tr
                      key={`stage-row-${stage.route_step_id}`}
                      className={`border-b cursor-pointer hover:bg-muted/30${isCurrentStage ? " bg-blue-50 border-l-4 border-l-blue-500" : ""}`}
                      role="button"
                      tabIndex={0}
                      aria-expanded={isExpanded}
                      onClick={() =>
                        setExpandedStages((prev) => ({
                          ...prev,
                          [stage.route_step_id]: !prev[stage.route_step_id],
                        }))
                      }
                      onKeyDown={(event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault()
                          setExpandedStages((prev) => ({
                            ...prev,
                            [stage.route_step_id]: !prev[stage.route_step_id],
                          }))
                        }
                      }}
                    >
                      <td className="p-2 align-top">
                        <div className="flex flex-col items-start gap-1">
                          <div className="flex items-center gap-2">
                            <span>#{stage.sequence}</span>
                            {isCurrentStage && (
                              <Badge variant="default" className="text-[10px] px-1.5 py-0">
                                Текущий
                              </Badge>
                            )}
                          </div>
                          <span className="text-lg leading-none text-muted-foreground">{isExpanded ? "▾" : "▸"}</span>
                        </div>
                      </td>
                      <td className="p-2">
                        <div className="flex items-start gap-2">
                          {stageIcon && (
                            <span
                              className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded mt-0.5"
                              style={{ backgroundColor: `${iconColor}20`, color: iconColor }}
                            >
                              {renderIcon(stageIcon, "h-4 w-4")}
                            </span>
                          )}
                          <div className="min-w-0">
                            <div className={`font-medium${isCurrentStage ? " text-blue-900" : ""}`}>
                              {stage.section_name}
                            </div>
                          </div>
                        </div>
                      </td>
                      <td className="p-2 align-top">
                        <span className="text-xs">{stageStatusText}</span>
                      </td>
                      <td className="p-2 align-top">{fmtQty(stage.planned_quantity)}</td>
                      <td className="p-2 align-top">{fmtQty(stage.issued_qty)}</td>
                      <td className="p-2 align-top">{fmtQty(stage.accounted_good_qty)}</td>
                      <td className="p-2 align-top">{fmtQty(stage.accounted_reject_qty)}</td>
                      <td className="p-2 align-top">{fmtQty(stage.accounted_total_qty)}</td>
                      <td className="p-2 align-top">{fmtQty(stage.sent_qty)}</td>
                      <td className="p-2 align-top">
                        {isFinalStage ? (
                          <span className="text-muted-foreground">Не требуется</span>
                        ) : (
                          fmtQty(stage.accepted_by_next_qty)
                        )}
                      </td>
                      <td className="p-2 align-top">{fmtQty(remainingQty)}</td>
                      <td className="p-2 align-top">{pct}%</td>
                    </tr>,
                    isExpanded ? (
                      <tr key={`stage-events-${stage.route_step_id}`} className="border-b bg-muted/20">
                        <td colSpan={12} className="p-2">
                          <div className="space-y-1 text-xs">
                            {stage.flow_events.length === 0 ? (
                              <div className="text-muted-foreground">Операции по этапу отсутствуют</div>
                            ) : (
                              stage.flow_events.map((event, idx) => (
                                <div key={`${stage.route_step_id}-${idx}`} className="flex flex-wrap items-center gap-2">
                                  <span className="font-medium">{event.label}</span>
                                  {event.manual_route_pass && (
                                    <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
                                      ручной пропуск
                                    </Badge>
                                  )}
                                  <span>{fmtQty(event.quantity)} шт.</span>
                                  <span className="text-muted-foreground">{fmtEventAt(event.event_at)}</span>
                                  {event.task_id && <span className="text-muted-foreground">task #{event.task_id}</span>}
                                  {event.transfer_id && <span className="text-muted-foreground">transfer #{event.transfer_id}</span>}
                                </div>
                              ))
                            )}
                          </div>
                        </td>
                      </tr>
                    ) : null,
                  ]
                )
              })}
            </tbody>
          </table>
          {data.stages!.length === 0 && (
            <p className="p-4 text-sm text-muted-foreground text-center">Маршрутные этапы отсутствуют</p>
          )}
        </div>
      )}

    </div>
  )
}
