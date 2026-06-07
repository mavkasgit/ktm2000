import { useState, useMemo, useCallback, useEffect } from "react";
import { Check } from "lucide-react";
import { Button, Input, toast, Checkbox, DatePicker } from "@/shared/ui";
import { cn } from "@/shared/utils/cn";
import type { SectionBoardTask } from "@/shared/api/shopfloor";

const QTY_INPUT_CLASSES = "h-7 text-xs [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none";

function QtyInput({
  value,
  onChange,
  className = "",
  ...props
}: React.ComponentProps<typeof Input>) {
  return (
    <Input
      type="number"
      value={value}
      onChange={onChange}
      className={`${QTY_INPUT_CLASSES} ${className}`}
      {...props}
    />
  );
}

function fmtQty(value: string | number): string {
  const n = typeof value === "number" ? value : parseFloat(value);
  if (!Number.isFinite(n)) return "0";
  return String(Math.round(n));
}

function toInteger(value: string | number): number {
  const n = typeof value === "number" ? value : parseFloat(value);
  return Number.isFinite(n) ? Math.round(n) : 0;
}

function nowLocalDateTime(): string {
  const d = new Date();
  const p = (v: number) => String(v).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}

function nowLocalDateTimeParts(): { date: string; time: string } {
  const d = new Date();
  const p = (v: number) => String(v).padStart(2, "0");
  return {
    date: `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`,
    time: `${p(d.getHours())}:${p(d.getMinutes())}`,
  };
}

type BulkOpGroup = {
  key: string;
  tasks: SectionBoardTask[];
  label: string;
  operationName: string;
  totalPlan: number;
  totalIssued: number;
  totalInWork: number;
  totalCompleted: number;
  totalTransferred: number;
  totalRejected: number;
  totalRemaining: number;
  // Группа-уровень inputs
  addQty: string;
  defectQty: string;
  // Per-task распределение
  taskAddQty: Record<number, number>;
  taskDefectQty: Record<number, number>;
};

function buildGroupKey(task: SectionBoardTask): string {
  return `${task.product_sku}__${task.operation_code || task.operation_name || "—"}`;
}

function buildGroupLabel(task: SectionBoardTask): string {
  return task.product_sku;
}

function getOperationName(task: SectionBoardTask): string {
  return task.operation_name || "—";
}

function distributeQtyProportional(
  tasks: SectionBoardTask[],
  totalQty: number,
): Record<number, number> {
  const result: Record<number, number> = {};
  if (tasks.length === 0 || totalQty <= 0) {
    for (const task of tasks) result[task.id] = 0;
    return result;
  }

  // Берём ёмкость каждой задачи из её плана (planned_quantity).
  const capacities = tasks.map((t) => Math.max(0, toInteger(t.planned_quantity)));
  const totalCapacity = capacities.reduce((s, c) => s + c, 0);

  if (totalCapacity === 0) {
    for (const task of tasks) result[task.id] = 0;
    return result;
  }

  // Распределяем пропорционально ёмкости. Остаток от округления кладём
  // в последнюю задачу, чтобы сумма точно совпала с totalQty.
  let remaining = totalQty;
  for (let i = 0; i < tasks.length - 1; i++) {
    const share = Math.round((totalQty * capacities[i]) / totalCapacity);
    result[tasks[i].id] = share;
    remaining -= share;
  }
  result[tasks[tasks.length - 1].id] = Math.max(0, remaining);
  return result;
}

function distributeQtyUncapped(
  tasks: SectionBoardTask[],
  totalQty: number,
): Record<number, number> {
  return distributeQtyProportional(tasks, totalQty);
}

function sumTasks(
  tasks: SectionBoardTask[],
  getVal: (task: SectionBoardTask) => number,
): number {
  return tasks.reduce((s, t) => s + getVal(t), 0);
}

function initGroup(tasks: SectionBoardTask[]): BulkOpGroup {
  const key = buildGroupKey(tasks[0]);
  const label = buildGroupLabel(tasks[0]);
  const operationName = getOperationName(tasks[0]);

  const totalPlan = sumTasks(tasks, (t) => toInteger(t.planned_quantity));
  const totalIssued = sumTasks(tasks, (t) => toInteger(t.cache.issued_quantity));
  const totalInWork = sumTasks(tasks, (t) => toInteger(t.cache.in_work_quantity));
  const totalCompleted = sumTasks(tasks, (t) => toInteger(t.cache.completed_quantity));
  const totalTransferred = sumTasks(tasks, (t) => toInteger(t.cache.transferred_quantity));
  const totalRejected = sumTasks(tasks, (t) => toInteger(t.cache.rejected_quantity));
  const totalRemaining = sumTasks(tasks, (t) => toInteger(t.cache.remaining_quantity));

  // Дефолт «+ Добавить» = 0 (пользователь сам вводит любое число)
  const taskAddQty: Record<number, number> = {};
  for (const task of tasks) taskAddQty[task.id] = 0;
  const taskDefectQty: Record<number, number> = {};
  for (const task of tasks) taskDefectQty[task.id] = 0;

  return {
    key,
    tasks,
    label,
    operationName,
    totalPlan,
    totalIssued,
    totalInWork,
    totalCompleted,
    totalTransferred,
    totalRejected,
    totalRemaining,
    addQty: "0",
    defectQty: "0",
    taskAddQty,
    taskDefectQty,
  };
}

function groupTasks(tasks: SectionBoardTask[]): BulkOpGroup[] {
  const map = new Map<string, SectionBoardTask[]>();

  for (const task of tasks) {
    const key = buildGroupKey(task);
    if (!map.has(key)) map.set(key, []);
    map.get(key)!.push(task);
  }

  return Array.from(map.values()).map((groupTasks) => initGroup(groupTasks));
}

function StatusDot({ status }: { status: string }) {
  let colorClass = "bg-slate-300";
  if (["in_progress", "in_work"].includes(status)) {
    colorClass = "bg-amber-500 animate-pulse";
  } else if (["ready", "partially_completed", "partially"].includes(status)) {
    colorClass = "bg-blue-500";
  } else if (["completed", "done"].includes(status)) {
    colorClass = "bg-emerald-500";
  } else if (status === "blocked") {
    colorClass = "bg-red-500";
  } else if (["waiting_previous", "pending"].includes(status)) {
    colorClass = "bg-yellow-400";
  }
  return (
    <span className={`inline-block h-2.5 w-2.5 rounded-full ${colorClass}`} title={status} />
  );
}

interface BulkOperationsPanelProps {
  tasks: SectionBoardTask[];
  onExecuteAll: (data: {
    completeEntries: { taskId: number; goodQty: string; defectQty: string }[];
    performedAt?: string;
    accountedAt?: string;
  }) => void;
  pending: boolean;
  onDone?: () => void;
}

export function BulkOperationsPanel({
  tasks,
  onExecuteAll,
  pending,
  onDone,
}: BulkOperationsPanelProps) {
  const [groups, setGroups] = useState<BulkOpGroup[]>(() => groupTasks(tasks));
  const [actionLog, setActionLog] = useState<{ type: string; time: string; status: "success" | "error"; message: string }[]>([]);

  // Date/Time States
  const now = nowLocalDateTimeParts();
  const [performedDate, setPerformedDate] = useState(now.date);
  const [performedShift, setPerformedShift] = useState<"1" | "2">("1");

  const toIsoDateTime = (dateStr: string, timeStr: string): string => {
    if (!timeStr) return nowLocalDateTime();
    if (!dateStr) {
      const d = new Date();
      const p = (v: number) => String(v).padStart(2, "0");
      const today = `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
      return `${today}T${timeStr}`;
    }
    if (/^\d{4}-\d{2}-\d{2}$/.test(dateStr)) {
      return `${dateStr}T${timeStr}`;
    }
    const [dd, mm, yyyy] = dateStr.split(".");
    const [hh, min] = timeStr.split(":");
    if (!dd || !mm || !yyyy || !hh || !min) return nowLocalDateTime();
    return `${yyyy}-${mm}-${dd}T${hh}:${min}`;
  };

  // Re-initialize groups when tasks change (e.g., after selection changes)
  const taskIdsStr = useMemo(() => tasks.map((t) => `${t.id}:${t.cache.completed_quantity}:${t.cache.issued_quantity}`).sort().join(","), [tasks]);

  // When the tasks prop changes significantly, re-group
  const [prevTaskIds, setPrevTaskIds] = useState(taskIdsStr);
  if (prevTaskIds !== taskIdsStr) {
    setPrevTaskIds(taskIdsStr);
    setGroups(groupTasks(tasks));
  }

  const updateGroupQty = (groupKey: string, field: "addQty" | "defectQty", value: string) => {
    const digits = value.replace(/[^\d]/g, "");
    setGroups((prev) =>
      prev.map((g) => {
        if (g.key !== groupKey) return g;
        const updated = { ...g, [field]: digits };
        // Пересчитать per-task распределение
        const addVal = toInteger(updated.addQty);
        const defectVal = toInteger(updated.defectQty);
        updated.taskAddQty = distributeQtyUncapped(g.tasks, addVal);
        updated.taskDefectQty = distributeQtyUncapped(g.tasks, defectVal);
        return updated;
      }),
    );
  };

  const fillPlannedQuantities = () => {
    setGroups((prev) =>
      prev.map((g) => {
        const plannedVal = String(g.totalPlan);
        const addVal = toInteger(plannedVal);
        const defectVal = toInteger(g.defectQty);
        return {
          ...g,
          addQty: plannedVal,
          taskAddQty: distributeQtyUncapped(g.tasks, addVal),
          taskDefectQty: distributeQtyUncapped(g.tasks, defectVal),
        };
      })
    );
  };

  const clearInputs = () => {
    setGroups((prev) =>
      prev.map((g) => {
        const taskAddQty: Record<number, number> = {};
        for (const task of g.tasks) taskAddQty[task.id] = 0;
        const taskDefectQty: Record<number, number> = {};
        for (const task of g.tasks) taskDefectQty[task.id] = 0;

        return {
          ...g,
          addQty: "0",
          defectQty: "0",
          taskAddQty,
          taskDefectQty,
        };
      })
    );
  };


  const doConfirm = () => {
    const completeEntries: { taskId: number; goodQty: string; defectQty: string }[] = [];

    for (const group of groups) {
      const totalAdd = toInteger(group.addQty);
      const totalDefect = toInteger(group.defectQty);
      if (totalAdd <= 0 && totalDefect <= 0) continue;

      for (const task of group.tasks) {
        const addQty = group.taskAddQty[task.id] || 0;
        const defectQty = group.taskDefectQty[task.id] || 0;
        if (addQty <= 0 && defectQty <= 0) continue;

        completeEntries.push({ taskId: task.id, goodQty: String(addQty), defectQty: String(defectQty) });
      }
    }

    if (completeEntries.length > 0) {
      const now = new Date();
      const timeStr = now.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
      setActionLog([{ type: "Завершение", time: timeStr, status: "success", message: `${completeEntries.length} задач` }]);
      toast({
        title: "Массовая операция выполнена",
        description: `Завершение: ${completeEntries.length} задач`,
        variant: "success",
      });

      const effectivePerformedAt = `${performedDate}T${performedShift === "1" ? "08:00" : "20:00"}`;
      const effectiveAccountedAt = nowLocalDateTime();

      onExecuteAll({
        completeEntries,
        performedAt: effectivePerformedAt,
        accountedAt: effectiveAccountedAt,
      });
    }
  };

  const getTaskProgress = (group: BulkOpGroup): string => {
    return group.tasks.map((task) => {
      const completed = toInteger(task.cache.completed_quantity);
      const planned = toInteger(task.planned_quantity);
      return `${completed}/${planned}`;
    }).join(", ");
  };

  const getPlanBreakdown = (group: BulkOpGroup): string => {
    if (group.tasks.length <= 1) return fmtQty(group.totalPlan);
    return group.tasks
      .map((t) => fmtQty(toInteger(t.planned_quantity)))
      .join("+");
  };

  return (
    <div className="rounded-lg border bg-card inline-block">
      <div className="overflow-auto">
        <table className="text-sm">
          <thead className="sticky top-0 bg-background border-b z-20">
            <tr className="border-b">
              <th rowSpan={2} className="text-center p-2 text-xs font-medium text-muted-foreground whitespace-nowrap border-r">Статус</th>
              <th rowSpan={2} className="text-center p-2 text-xs font-medium text-muted-foreground whitespace-nowrap border-r">Артикул</th>
              <th rowSpan={2} className="text-center p-2 text-xs font-medium text-muted-foreground whitespace-nowrap border-r">Операция</th>
              <th rowSpan={2} className="text-center p-1 text-xs font-medium whitespace-nowrap border-r">
                <button
                  type="button"
                  onClick={fillPlannedQuantities}
                  disabled={pending}
                  title="Заполнить столбец «+ Добавить» планом"
                  className={cn(
                    "inline-flex items-center justify-center px-2 py-1 rounded-md w-full",
                    "border border-blue-300 bg-white text-blue-700 font-medium",
                    "transition-all duration-150",
                    "hover:bg-blue-50 hover:border-blue-500 hover:shadow-sm hover:-translate-y-px",
                    "focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-1",
                    "active:translate-y-0 active:shadow-none",
                    "disabled:opacity-50 disabled:pointer-events-none disabled:hover:translate-y-0 disabled:hover:shadow-none",
                  )}
                >
                  План
                </button>
              </th>
              <th rowSpan={2} className="text-center p-2 text-xs font-medium text-muted-foreground whitespace-nowrap leading-tight border-r">
                <div>Завершено</div>
                <div className="text-[10px] font-normal mt-0.5">Годные/Брак</div>
              </th>
              <th colSpan={2} className="text-center p-1.5 text-xs font-medium text-muted-foreground whitespace-nowrap border-r border-b">
                Добавить
              </th>
              <th rowSpan={2} className="text-center p-2 text-xs font-medium text-muted-foreground whitespace-nowrap border-r">Прогресс</th>
            </tr>
            <tr>
              <th className="text-center p-1 text-[10px] font-medium text-muted-foreground whitespace-nowrap border-r">Годные</th>
              <th className="text-center p-1 text-[10px] font-medium text-muted-foreground whitespace-nowrap border-r">Брак</th>
            </tr>
          </thead>
          <tbody>
            {groups.map((group) => {
              const progress = getTaskProgress(group);
 
              return (
                <tr key={group.key} className="border-b">
                  <td className="p-2 text-center whitespace-nowrap border-r">
                    <div className="flex items-center justify-center gap-1.5 flex-wrap max-w-[60px] mx-auto">
                      {(() => {
                        const uniqueStatuses = Array.from(new Set(group.tasks.map((t) => t.status)));
                        if (uniqueStatuses.length === 1) {
                          return <StatusDot status={uniqueStatuses[0]} />;
                        }
                        return group.tasks.map((task) => (
                          <StatusDot key={task.id} status={task.status} />
                        ));
                      })()}
                    </div>
                  </td>
                  <td className="p-2 text-center font-medium whitespace-nowrap border-r">{group.label}</td>
                  <td className="p-2 text-center text-xs whitespace-nowrap border-r">
                    <span className="inline-flex items-center gap-1">
                      {group.operationName}
                      {group.tasks.length > 1 && (
                        <span className="px-1 py-0.5 text-[10px] font-semibold rounded-full bg-blue-100 text-blue-700">
                          ×{group.tasks.length}
                        </span>
                      )}
                    </span>
                  </td>
                  <td className="p-2 text-center whitespace-nowrap font-mono text-xs border-r">
                    <button
                      type="button"
                      onClick={() => updateGroupQty(group.key, "addQty", String(group.totalPlan))}
                      title={
                        group.tasks.length > 1
                          ? `Заполнит ${group.tasks.length} заданий: ${getPlanBreakdown(group)} = ${fmtQty(group.totalPlan)}`
                          : "Скопировать план в '+ Добавить'"
                      }
                      className={cn(
                        "inline-flex flex-col items-center justify-center min-w-[3rem] px-2 py-1 rounded-md",
                        "border border-blue-300 bg-white text-blue-700 font-mono leading-tight",
                        "transition-all duration-150",
                        "hover:bg-blue-50 hover:border-blue-500 hover:shadow-sm hover:-translate-y-px",
                        "focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-1",
                        "active:translate-y-0 active:shadow-none",
                        "disabled:opacity-50 disabled:pointer-events-none",
                      )}
                    >
                      <span className="font-semibold">{fmtQty(group.totalPlan)}</span>
                    </button>
                  </td>
                  <td className="p-2 text-center whitespace-nowrap font-mono text-xs border-r">
                    {fmtQty(group.totalCompleted)}/{fmtQty(group.totalRejected)}
                  </td>
                  <td className="p-2 text-center border-r">
                    <QtyInput
                      min="0"
                      value={group.addQty}
                      onChange={(ev) => updateGroupQty(group.key, "addQty", ev.target.value)}
                      className="w-20 mx-auto"
                      disabled={pending}
                    />
                  </td>
                  <td className="p-2 text-center border-r">
                    <QtyInput
                      min="0"
                      value={group.defectQty}
                      onChange={(ev) => updateGroupQty(group.key, "defectQty", ev.target.value)}
                      className="w-20 mx-auto"
                      disabled={pending}
                    />
                  </td>
                  <td className="p-2 text-center text-xs text-muted-foreground whitespace-nowrap font-mono border-r">
                    {progress}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="p-4 border-t bg-muted/10 flex flex-row items-end justify-between gap-6 flex-wrap md:flex-nowrap">
        {/* Date / Shift controls */}
        <div className="flex flex-row gap-4 items-end">
          <DatePicker
            value={performedDate}
            onChange={setPerformedDate}
            label="Дата"
          />
          <div className="flex flex-col gap-1.5">
            <span className="text-sm font-medium">Смена</span>
            <div className="flex gap-1 bg-muted p-0.5 rounded-md h-8 items-center">
              <button
                type="button"
                onClick={() => setPerformedShift("1")}
                className={cn(
                  "px-3 h-7 text-sm font-medium rounded transition-all flex items-center justify-center",
                  performedShift === "1"
                    ? "bg-background text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground"
                )}
              >
                1-я
              </button>
              <button
                type="button"
                onClick={() => setPerformedShift("2")}
                className={cn(
                  "px-3 h-7 text-sm font-medium rounded transition-all flex items-center justify-center",
                  performedShift === "2"
                    ? "bg-background text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground"
                )}
              >
                2-я
              </button>
            </div>
          </div>
        </div>

        {/* Action buttons */}
        <div className="flex flex-col items-end gap-2 self-stretch justify-end">
          {actionLog.length > 0 && (
            <div className="text-xs text-muted-foreground font-medium flex items-center gap-2 mb-1">
              <span className="text-emerald-600">✓</span>
              <span>{actionLog[0].type}: {actionLog[0].message} ({actionLog[0].time})</span>
            </div>
          )}
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={clearInputs}
              disabled={pending}
            >
              Очистить
            </Button>
            <Button
              size="sm"
              onClick={doConfirm}
              disabled={pending || !groups.some((g) => toInteger(g.addQty) > 0 || toInteger(g.defectQty) > 0)}
            >
              Подтвердить
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
