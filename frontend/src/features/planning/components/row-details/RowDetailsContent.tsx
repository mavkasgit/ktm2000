import { Badge } from "@/shared/ui"
import { cn } from "@/shared/utils/cn"
import { type RowDetailsData } from "./types"

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

function fmtQty(value: number | string): string {
  const num = typeof value === "string" ? Number(value) : value
  if (!Number.isFinite(num)) return String(value)
  if (Number.isInteger(num)) return String(num)
  return num.toFixed(3).replace(/\.?0+$/, "")
}

function planPreviewUrl(planId: number): string {
  return `/plans/${planId}/preview`
}

interface RowDetailsContentProps {
  data: RowDetailsData
  showPlanLink?: boolean
}

export function RowDetailsContent({ data, showPlanLink = true }: RowDetailsContentProps) {
  const hasErrors = data.errors.length > 0
  const hasWarnings = data.warnings.length > 0
  const hasRouteCheckIssues = (data.routeCheckIssues?.length ?? 0) > 0
  const hasStages = (data.stages?.length ?? 0) > 0
  const hasRawData = !!data.rawExcelRow

  return (
    <div className="space-y-4">
      {/* Raw Excel data */}
      {hasRawData && (
        <div className="rounded-lg border p-4">
          <pre className="text-xs bg-muted/50 rounded-md p-3 overflow-auto whitespace-pre-wrap break-words font-mono">
            {data.rawExcelRow}
          </pre>
        </div>
      )}

      {/* Basic info */}
      <div className="rounded-lg border p-4">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
          <div>
            <div className="text-muted-foreground">Строка импорта</div>
            <div className="font-medium">#{data.sourceRowNumber ?? "—"}</div>
          </div>
          <div>
            <div className="text-muted-foreground">SKU</div>
            <div className="font-mono font-medium">{data.sku}</div>
          </div>
          {data.name && (
            <div className="md:col-span-2">
              <div className="text-muted-foreground">Наименование</div>
              <div className="font-medium">{data.name}</div>
            </div>
          )}
          <div>
            <div className="text-muted-foreground">Количество</div>
            <div className="font-medium">{fmtQty(data.quantity)}</div>
          </div>
          <div>
            <div className="text-muted-foreground">Статус</div>
            <div className="pt-1">
              <Badge variant={(statusVariant[data.status] as any) || "secondary"}>
                {statusLabels[data.status] || data.status}
              </Badge>
            </div>
          </div>
          {data.productionPlanId > 0 && showPlanLink && (
            <div>
              <div className="text-muted-foreground">План</div>
              <div className="font-medium">
                {data.productionPlanId}{" "}
                <a
                  href={planPreviewUrl(data.productionPlanId)}
                  target="_blank"
                  rel="noreferrer"
                  className="text-blue-700 hover:underline inline-block max-w-[240px] truncate align-bottom"
                >
                  План
                </a>
              </div>
            </div>
          )}
          <div className={cn("md:col-span-2", !hasStages && "md:col-span-2")}>
            <div className="text-muted-foreground">Маршрут</div>
            <div className="font-medium">
              {data.routeName || data.routeError || "Не назначен"}
              {data.routeName && data.routeMeta && (
                <span className="text-muted-foreground"> ({data.routeMeta})</span>
              )}
            </div>
            {data.routeError && (
              <div className="text-xs text-red-600 mt-1">{data.routeError}</div>
            )}
          </div>
        </div>
      </div>

      {/* Errors */}
      {hasErrors && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4">
          <p className="text-sm font-medium text-red-800 mb-2">Ошибки</p>
          <ul className="text-sm text-red-700 space-y-1">
            {data.errors.map((err, i) => (
              <li key={i} className="flex items-start gap-2">
                <span className="mt-1.5 h-1.5 w-1.5 rounded-full bg-red-500 shrink-0" />
                {err}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Warnings */}
      {hasWarnings && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-4">
          <p className="text-sm font-medium text-amber-800 mb-2">Предупреждения</p>
          <ul className="text-sm text-amber-700 space-y-1">
            {data.warnings.map((w, i) => (
              <li key={i} className="flex items-start gap-2">
                <span className="mt-1.5 h-1.5 w-1.5 rounded-full bg-amber-500 shrink-0" />
                {w}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Route check issues */}
      {hasRouteCheckIssues && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-4">
          <p className="text-sm font-medium text-amber-800 mb-2">Несовпадения маршрута</p>
          <ul className="text-sm text-amber-700 space-y-1">
            {data.routeCheckIssues!.map((issue, i) => (
              <li key={i} className="flex items-start gap-2">
                <span className="mt-1.5 h-1.5 w-1.5 rounded-full bg-amber-500 shrink-0" />
                {issue}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Stages table */}
      {hasStages && (
        <div className="rounded-lg border overflow-auto">
          <table className="w-full text-sm">
            <thead className="border-b bg-muted/50">
              <tr>
                <th className="text-left p-2">Этап</th>
                <th className="text-left p-2">Участок</th>
                <th className="text-left p-2">План</th>
                <th className="text-left p-2">Факт</th>
                <th className="text-left p-2">Брак</th>
                <th className="text-left p-2">% выполнения</th>
              </tr>
            </thead>
            <tbody>
              {data.stages!.map((stage) => {
                const pct = stage.planned_quantity > 0
                  ? ((stage.completed_quantity / stage.planned_quantity) * 100).toFixed(1)
                  : "0.0"
                return (
                  <tr key={stage.route_step_id} className="border-b">
                    <td className="p-2">#{stage.sequence}</td>
                    <td className="p-2">
                      <div>
                        <div className="font-medium">{stage.section_name}</div>
                        <div className="text-xs text-muted-foreground">
                          {stage.section_code} · {stage.operation_name}
                        </div>
                      </div>
                    </td>
                    <td className="p-2">{fmtQty(stage.planned_quantity)}</td>
                    <td className="p-2">{fmtQty(stage.completed_quantity)}</td>
                    <td className="p-2">{fmtQty(stage.rejected_quantity)}</td>
                    <td className="p-2">{pct}%</td>
                  </tr>
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
