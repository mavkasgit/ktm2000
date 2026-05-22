import { ProductionPlanningRow } from "@/shared/api/productionPlans";
import { Badge, Button } from "@/shared/ui";
import { ArrowRight, History, RotateCcw, Trash2, XCircle } from "lucide-react";
import { positionStatusLabels, positionStatusColor, routeMetaLabel, fmtQty, planPreviewUrl, getLaunchBlockReason } from "./execution-utils";
import { StepIndicator } from "../components/StepIndicator";
import type { ExecutionColumnId, ExecutionTableColumn } from "./execution-table-columns";

function StatusBadge({ status, isCompleted }: { status: string; isCompleted?: boolean }) {
  const displayStatus = isCompleted ? "completed" : status;
  return (
    <span className={`inline-flex max-w-full items-center truncate whitespace-nowrap rounded-full px-2 py-0.5 text-xs ${positionStatusColor[displayStatus] || "bg-gray-100 text-gray-700"}`}>
      {positionStatusLabels[displayStatus] || displayStatus}
    </span>
  );
}

function RowRouteCell({ row }: { row: ProductionPlanningRow }) {
  if (row.route_name) {
    const meta = routeMetaLabel(row);
    return (
      <span className="block truncate text-xs text-blue-700" title={`${row.route_name} (${meta})`}>
        <span className="truncate">{row.route_name}</span>
        <span className="text-muted-foreground max-[1099px]:hidden"> ({meta})</span>
      </span>
    );
  }
  return (
    <span className="block truncate text-xs text-red-600" title={row.route_error || "Не назначен"}>
      {row.route_error || "Не назначен"}
    </span>
  );
}

interface ExecutionRowProps {
  row: ProductionPlanningRow;
  bulkMode: boolean;
  isSelected: boolean;
  columns: ExecutionTableColumn[];
  sectionMetaById: Map<number, { icon: string | null; icon_color: string | null }>;
  onToggleSelect: (id: number) => void;
  onOpenDetail: (id: number) => void;
  onSingleLaunch: (row: ProductionPlanningRow) => void;
  onManualPass: (row: ProductionPlanningRow) => void;
  onCancel: (row: ProductionPlanningRow) => void;
  onRestore: (row: ProductionPlanningRow) => void;
  onSoftDelete: (row: ProductionPlanningRow) => void;
  onOpenHistory: (row: ProductionPlanningRow) => void;
}

export function ExecutionRow({
  row,
  bulkMode,
  isSelected,
  columns,
  sectionMetaById,
  onToggleSelect,
  onOpenDetail,
  onSingleLaunch,
  onManualPass,
  onCancel,
  onRestore,
  onSoftDelete,
  onOpenHistory,
}: ExecutionRowProps) {
  const canLaunch = row.position_status === "approved" && !row.has_tasks && !row.is_released && !!row.route_id;
  const canManualPass = !!row.route_id && ["approved", "released"].includes(row.position_status) && !row.is_completed;
  const blockReason = getLaunchBlockReason(row);

  const cellBaseClass = "p-2 align-middle min-w-0 overflow-hidden text-ellipsis whitespace-nowrap text-sm";

  const renderCell = (columnId: ExecutionColumnId) => {
    switch (columnId) {
      case "id":
        return `#${row.plan_position_id}`;
      case "row":
        return `#${row.source_row_number ?? "—"}`;
      case "plan":
        return (
          <a
            href={planPreviewUrl(row.production_plan_id)}
            target="_blank"
            rel="noreferrer"
            className="text-blue-700 hover:underline"
            onClick={(e) => e.stopPropagation()}
          >
            {row.production_plan_id}
          </a>
        );
      case "sku":
        return (
          <span className="block truncate" title={row.source_sku}>
            {row.source_sku}
          </span>
        );
      case "name":
        return (
          <span className="block truncate" title={row.source_name || undefined}>
            {row.source_name || "—"}
          </span>
        );
      case "qty":
        return fmtQty(row.quantity);
      case "route":
        return <RowRouteCell row={row} />;
      case "status":
        return (
          <div className="flex min-w-0 items-center gap-1 overflow-hidden">
            <StatusBadge status={row.position_status} isCompleted={row.is_completed} />
            {row.current_stage_sequence !== null && (
              <span
                className="hidden shrink-0 rounded bg-muted px-1 text-[10px] text-muted-foreground max-[699px]:inline"
                title={row.current_stage_section_name || undefined}
              >
                Э{row.current_stage_sequence}
              </span>
            )}
          </div>
        );
      case "stage":
        return row.route_steps && row.route_steps.length > 0 ? (
          <div className="min-w-0 overflow-hidden">
            <StepIndicator
              steps={row.route_steps}
              currentStageSequence={row.current_stage_sequence}
              currentStageTaskStatus={row.current_stage_task_status}
              sectionMetaById={sectionMetaById}
            />
          </div>
        ) : row.has_tasks ? (
          <Badge variant="secondary" className="max-w-full truncate">Задачи созданы</Badge>
        ) : (
          <Badge variant="secondary">Нет</Badge>
        );
      case "actions":
        return (
          <div className="flex min-w-0 items-center justify-end gap-1 overflow-hidden" onClick={(e) => e.stopPropagation()}>
            {canLaunch ? (
              <Button
                size="sm"
                variant="outline"
                className="h-8 min-w-0 shrink px-2"
                onClick={() => onSingleLaunch(row)}
                title="Взять в работу"
              >
                <span className="truncate">Взять в работу</span>
              </Button>
            ) : (
              <span
                className="min-w-0 truncate text-xs text-muted-foreground max-[959px]:max-w-6"
                title={blockReason || ""}
              >
                {blockReason || "—"}
              </span>
            )}
            {canManualPass && (
              <Button
                size="sm"
                variant="outline"
                className="h-8 w-8 shrink-0 px-0"
                onClick={() => onManualPass(row)}
                title="Сквозной проход"
              >
                <ArrowRight className="h-4 w-4" />
              </Button>
            )}
            {row.position_status === "approved" && (
              <Button
                size="sm"
                variant="ghost"
                className="h-8 min-w-0 shrink px-2 text-red-600 hover:text-red-700 max-[959px]:w-8 max-[959px]:shrink-0 max-[959px]:px-0"
                onClick={() => onCancel(row)}
                title="Отменить"
              >
                <XCircle className="h-4 w-4 shrink-0" />
                <span className="ml-1.5 truncate max-[959px]:hidden">Отменить</span>
              </Button>
            )}
            {row.position_status === "released" && (
              <Button
                size="sm"
                variant="ghost"
                className="h-8 min-w-0 shrink px-2 text-red-600 hover:text-red-700 max-[959px]:w-8 max-[959px]:shrink-0 max-[959px]:px-0"
                onClick={() => onCancel(row)}
                title="Остановить"
              >
                <XCircle className="h-4 w-4 shrink-0" />
                <span className="ml-1.5 truncate max-[959px]:hidden">Остановить</span>
              </Button>
            )}
            {row.position_status === "cancelled" && (
              <>
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-8 min-w-0 shrink px-2 text-green-600 hover:text-green-700 max-[959px]:w-8 max-[959px]:shrink-0 max-[959px]:px-0"
                  onClick={() => onRestore(row)}
                  title="Восстановить"
                >
                  <RotateCcw className="h-4 w-4 shrink-0" />
                  <span className="ml-1.5 truncate max-[959px]:hidden">Восстановить</span>
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-8 min-w-0 shrink px-2 text-red-600 hover:text-red-700 max-[959px]:w-8 max-[959px]:shrink-0 max-[959px]:px-0"
                  onClick={() => onSoftDelete(row)}
                  title="Удалить из списка"
                >
                  <Trash2 className="h-4 w-4 shrink-0" />
                  <span className="ml-1.5 truncate max-[959px]:hidden">Удалить</span>
                </Button>
              </>
            )}
            <Button
              size="sm"
              variant="ghost"
              className="h-8 w-8 shrink-0 px-0 text-gray-500 hover:text-gray-700"
              onClick={() => onOpenHistory(row)}
              title="История"
            >
              <History className="h-4 w-4" />
            </Button>
          </div>
        );
      default:
        return null;
    }
  };

  return (
    <tr
      className={`border-b hover:bg-accent hover:ring-1 hover:ring-ring/20 cursor-pointer transition-colors overflow-hidden ${isSelected ? "bg-blue-100 ring-1 ring-blue-300" : ""}`}
      onClick={() => {
        if (bulkMode) {
          onToggleSelect(row.plan_position_id);
        } else {
          onOpenDetail(row.plan_position_id);
        }
      }}
    >
      {columns.map((column) => (
        <td
          key={column.id}
          className={`${cellBaseClass} ${column.cellClassName ?? ""}`}
        >
          {renderCell(column.id)}
        </td>
      ))}
    </tr>
  );
}
