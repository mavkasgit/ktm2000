/**
 * components/TaskGroupRow.tsx
 * ============================
 * Строка одной группы задач на доске участка.
 *
 * ВИЗУАЛЬНАЯ ЛОГИКА:
 *   - display_sku с трансформацией (→)
 *   - operation_code бейджи
 *   - Прогресс qty_done / qty_plan
 *   - Раскрывающийся список задач
 */

import React, { useState } from "react";
import type { SectionBoardTask, TaskGroup, RouteHistoryOp } from "@/shared/api/shopfloor";
import { isTransformingTask, taskProgress, groupProgress } from "@/shared/api/shopfloor";
import type { GroupingProfile } from "../lib/groupingProfiles";
import { groupStatus } from "../lib/groupTasksByProfile";


function renderIcon(icon: string, className: string) {
  // Lucide icons are rendered as SVG paths
  // For simplicity, show first letter as fallback
  return <span className={className}>{icon[0]?.toUpperCase()}</span>;
}


// ---------------------------------------------------------------------------
// Типы
// ---------------------------------------------------------------------------

interface TaskGroupRowProps {
  group: TaskGroup;
  profile: GroupingProfile;
  defaultExpanded?: boolean;
}

interface TaskRowProps {
  task: SectionBoardTask;
}


// ---------------------------------------------------------------------------
// TaskGroupRow
// ---------------------------------------------------------------------------

export function TaskGroupRow({
  group,
  profile,
  defaultExpanded = true,
}: TaskGroupRowProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);

  const firstTask = group.tasks[0];
  const isTransforming = isTransformingTask(firstTask);
  const status = groupStatus(group);
  const progress = groupProgress(group);

  // Build icon lookup for combined operations
  const iconByOpCode = new Map<string, { icon?: string | null; iconColor?: string | null }>();
  if (firstTask.combined_operation_codes) {
    // Icons come from the task's own fields and route_history_after
    const allOps = firstTask.route_history_after ?? [];
    for (const op of allOps) {
      if (op.operation_code) {
        iconByOpCode.set(op.operation_code, { icon: op.icon, iconColor: op.icon_color });
      }
    }
    // Also use the task's own icon
    if (firstTask.operation_code) {
      iconByOpCode.set(firstTask.operation_code, { icon: firstTask.icon, iconColor: firstTask.icon_color });
    }
  }

  return (
    <div
      className={`rounded-lg border ${statusBorderClass(status)}`}
      data-group-key={group.key}
    >
      {/* Заголовок группы */}
      <button
        className="w-full flex items-center justify-between p-3 hover:bg-gray-50 transition-colors"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        type="button"
      >
        <div className="flex items-center gap-2 flex-wrap">
          {/* Иконка раскрытия */}
          <span className="text-xs text-muted-foreground">
            {expanded ? "▼" : "▶"}
          </span>

          {/* Артикул */}
          <div className="font-medium">
            {isTransforming ? (
              <>
                <span className="text-muted-foreground">{firstTask.input_sku}</span>
                <span className="mx-1 text-blue-500">→</span>
                <span className="font-semibold">{firstTask.output_sku}</span>
              </>
            ) : (
              <span>{firstTask.output_sku}</span>
            )}
          </div>

          {/* Код операции */}
          {profile.criteria.includes("operationCode") && firstTask.operation_code && (
            <span className="inline-flex items-center rounded-md bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-700">
              {firstTask.operation_code}
            </span>
          )}

          {/* Комбинированные операции */}
          {firstTask.is_combined_primary && firstTask.combined_operation_names?.length > 0 && (
            <div className="flex items-center gap-1">
              {firstTask.combined_operation_names.map((opName: string, i: number) => {
                const opCode = firstTask.combined_operation_codes?.[i];
                const iconInfo = opCode ? iconByOpCode.get(opCode) : null;
                return (
                  <React.Fragment key={i}>
                    {i > 0 && <span className="text-muted-foreground text-xs">→</span>}
                    <span
                      className="inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium"
                      style={{
                        backgroundColor: iconInfo?.iconColor ? iconInfo.iconColor + "18" : undefined,
                        color: iconInfo?.iconColor || undefined,
                      }}
                      title={opName}
                    >
                      {iconInfo?.icon && renderIcon(iconInfo.icon, "h-3 w-3")}
                      {opName}
                    </span>
                  </React.Fragment>
                );
              })}
            </div>
          )}

          {/* Ссылка на заказ */}
          {profile.criteria.includes("sourceRef") && firstTask.source_ref && (
            <span className="inline-flex items-center rounded-md bg-purple-50 px-2 py-0.5 text-xs font-medium text-purple-700">
              {firstTask.source_ref}
            </span>
          )}
        </div>

        <div className="flex items-center gap-3 shrink-0">
          {/* Прогресс */}
          <div className="flex items-center gap-2">
            <div className="w-24 h-1.5 bg-gray-200 rounded-full overflow-hidden">
              <div
                className="h-full rounded-full transition-all"
                style={{
                  width: `${progress}%`,
                  backgroundColor: progressColor(progress),
                }}
              />
            </div>
            <span className="text-sm text-muted-foreground whitespace-nowrap">
              {group.totalQtyDone.toFixed(0)} / {group.totalQtyPlan.toFixed(0)}
            </span>
          </div>

          {/* Статус */}
          <StatusBadge status={status} />

          {/* Кол-во задач */}
          <span className="inline-flex items-center justify-center w-6 h-6 rounded-full bg-gray-100 text-xs font-medium text-gray-600" title="Количество заказов">
            {group.tasks.length}
          </span>
        </div>
      </button>

      {/* Список задач */}
      {expanded && (
        <div className="border-t px-3 py-2 space-y-1 bg-gray-50/50">
          {group.tasks.map((task) => (
            <TaskRow key={task.id} task={task} />
          ))}
        </div>
      )}
    </div>
  );
}


// ---------------------------------------------------------------------------
// TaskRow
// ---------------------------------------------------------------------------

function TaskRow({ task }: TaskRowProps) {
  const progress = taskProgress(task);

  return (
    <div className={`flex items-center justify-between gap-3 px-3 py-1.5 rounded text-sm ${taskRowBgClass(task.status)}`}>
      <span className="text-muted-foreground">
        {task.source_ref ?? `#${task.id}`}
      </span>

      <span className="text-sm">
        {parseFloat(task.cache.completed_quantity).toFixed(0)}{" "}
        <span className="text-muted-foreground">/</span>{" "}
        {parseFloat(task.planned_quantity).toFixed(0)}
      </span>

      <div className="w-16 h-1.5 bg-gray-200 rounded-full overflow-hidden">
        <div
          className="h-full bg-blue-500 rounded-full"
          style={{ width: `${progress}%` }}
        />
      </div>

      <StatusBadge status={task.status} compact />
    </div>
  );
}


// ---------------------------------------------------------------------------
// StatusBadge
// ---------------------------------------------------------------------------

type StatusValue = "pending" | "in_work" | "done" | "partially" | "blocked" | string;

interface StatusBadgeProps {
  status: StatusValue;
  compact?: boolean;
}

const STATUS_META: Record<string, { label: string; short: string; color: string }> = {
  pending:   { label: "Ожидает",   short: "○", color: "bg-gray-100 text-gray-600" },
  in_work:   { label: "В работе",  short: "▶", color: "bg-amber-100 text-amber-700" },
  done:      { label: "Готово",    short: "✓", color: "bg-emerald-100 text-emerald-700" },
  partially: { label: "Частично",  short: "◑", color: "bg-orange-100 text-orange-700" },
  blocked:   { label: "Блокировка", short: "✕", color: "bg-red-100 text-red-600" },
};

function StatusBadge({ status, compact = false }: StatusBadgeProps) {
  const meta = STATUS_META[status] ?? { label: status, short: "?", color: "bg-gray-100 text-gray-600" };
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${meta.color} ${compact ? "px-1.5" : ""}`}
      title={meta.label}
    >
      {compact ? meta.short : meta.label}
    </span>
  );
}


// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function statusBorderClass(status: string): string {
  switch (status) {
    case "done":      return "border-emerald-300";
    case "in_work":   return "border-amber-300";
    case "blocked":   return "border-red-300";
    case "partially": return "border-orange-300";
    default:          return "border-gray-200";
  }
}

function progressColor(progress: number): string {
  if (progress >= 100) return "#10b981";
  if (progress >= 50) return "#f59e0b";
  if (progress > 0) return "#3b82f6";
  return "#d1d5db";
}

function taskRowBgClass(status: string): string {
  switch (status) {
    case "done":      return "bg-emerald-50/50";
    case "in_work":   return "bg-amber-50/50";
    case "blocked":   return "bg-red-50/50";
    default:          return "";
  }
}
