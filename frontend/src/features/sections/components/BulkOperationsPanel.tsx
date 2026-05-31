import { useState, useMemo, useCallback } from "react";
import { ArrowRight, Check } from "lucide-react";
import { Button, Input, toast } from "@/shared/ui";
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

type RowStep = "issue" | "complete" | "send";

type BulkOpGroup = {
  key: string;
  tasks: SectionBoardTask[];
  label: string;
  operationName: string;
  // Aggregated totals
  totalPlan: number;
  totalIssued: number;
  totalInWork: number;
  totalCompleted: number;
  totalTransferred: number;
  totalRejected: number;
  totalRemaining: number;
  // Group-level inputs
  issueQty: string;
  completeQty: string;
  defectQty: string;
  sendQty: string;
  confirmedSteps: Set<RowStep>;
  lastConfirmedSteps: Set<RowStep>; // Track which steps were confirmed (for highlighting)
  // Per-task distribution (hidden, used for submit)
  taskIssueQty: Record<number, number>;
  taskCompleteQty: Record<number, number>;
  taskDefectQty: Record<number, number>;
  taskSendQty: Record<number, number>;
  // Cascade activation per group
  issueArrowActive: boolean;
  completeArrowActive: boolean;
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

function distributeQty(
  tasks: SectionBoardTask[],
  totalQty: number,
  getMax: (task: SectionBoardTask) => number,
): Record<number, number> {
  const result: Record<number, number> = {};
  let remaining = totalQty;

  for (const task of tasks) {
    if (remaining <= 0) {
      result[task.id] = 0;
      continue;
    }
    const max = getMax(task);
    const allocated = Math.min(remaining, max);
    result[task.id] = allocated;
    remaining -= allocated;
  }

  return result;
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

  // Default issueQty = actual issued quantity (user can increase to issue more)
  const defaultIssueQty = totalIssued > 0 ? String(totalIssued) : "0";
  // Default complete/defect/send = actual values from cache
  const defaultCompleteQty = totalCompleted > 0 ? String(totalCompleted) : "0";
  const defaultDefectQty = totalRejected > 0 ? String(totalRejected) : "0";
  const defaultSendQty = totalTransferred > 0 ? String(totalTransferred) : "0";

  // Pre-distribute default values
  const taskIssueQty = distributeQty(
    tasks,
    toInteger(defaultIssueQty || "0"),
    (t) => toInteger(t.cache.issued_quantity),
  );
  const taskCompleteQty = distributeQty(
    tasks,
    toInteger(defaultCompleteQty || "0"),
    (t) => toInteger(t.cache.in_work_quantity),
  );
  const taskSendQty: Record<number, number> = {};
  for (const task of tasks) {
    taskSendQty[task.id] = 0;
  }

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
    issueQty: defaultIssueQty,
    completeQty: defaultCompleteQty,
    defectQty: defaultDefectQty,
    sendQty: defaultSendQty,
    confirmedSteps: new Set<RowStep>(),
    lastConfirmedSteps: new Set<RowStep>(),
    taskIssueQty,
    taskCompleteQty,
    taskDefectQty: {},
    taskSendQty,
    issueArrowActive: false,
    completeArrowActive: false,
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

interface BulkOperationsPanelProps {
  tasks: SectionBoardTask[];
  onExecuteAll: (data: {
    issueEntries: { taskId: number; quantity: string }[];
    completeEntries: { taskId: number; goodQty: string; defectQty: string }[];
    sendEntries: { taskId: number; quantity: string }[];
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

  // Re-initialize groups when tasks change (e.g., after selection changes)
  const taskIdsStr = useMemo(() => tasks.map((t) => `${t.id}:${t.cache.issued_quantity}:${t.cache.completed_quantity}:${t.cache.transferred_quantity}`).sort().join(","), [tasks]);

  // When the tasks prop changes significantly, re-group
  const [prevTaskIds, setPrevTaskIds] = useState(taskIdsStr);
  if (prevTaskIds !== taskIdsStr) {
    setPrevTaskIds(taskIdsStr);
    setGroups(groupTasks(tasks));
  }

  const updateGroupQty = (groupKey: string, field: keyof BulkOpGroup, value: string) => {
    const digits = value.replace(/[^\d]/g, "");
    setGroups((prev) =>
      prev.map((g) => {
        if (g.key !== groupKey) return g;

        const updated = { ...g, [field]: digits };

        // Re-distribute when qty fields change
        if (field === "issueQty") {
          const qty = toInteger(digits || "0");
          updated.taskIssueQty = distributeQty(
            g.tasks,
            qty,
            (t) => toInteger(t.cache.issued_quantity),
          );
          // Reset cascade if issue changes
          if (g.issueArrowActive) {
            updated.issueArrowActive = false;
            updated.completeArrowActive = false;
            updated.taskCompleteQty = distributeQty(
              g.tasks,
              qty,
              (t) => toInteger(t.cache.in_work_quantity),
            );
            updated.taskSendQty = {};
            for (const task of g.tasks) {
              updated.taskSendQty[task.id] = 0;
            }
            if (updated.confirmedSteps.has("complete")) {
              updated.confirmedSteps = new Set([...updated.confirmedSteps].filter((s) => s !== "complete" && s !== "send"));
            }
            if (updated.confirmedSteps.has("send")) {
              updated.confirmedSteps = new Set([...updated.confirmedSteps].filter((s) => s !== "send"));
            }
          }
        } else if (field === "completeQty" || field === "defectQty") {
          const completeVal = toInteger(field === "completeQty" ? digits : g.completeQty);
          const defectVal = toInteger(field === "defectQty" ? digits : g.defectQty);
          const goodVal = Math.max(0, completeVal - defectVal);
          // Distribute proportionally by in_work_quantity
          const totalInWork = g.totalInWork;
          for (const task of g.tasks) {
            const taskInWork = toInteger(task.cache.in_work_quantity);
            const ratio = totalInWork > 0 ? taskInWork / totalInWork : 1 / g.tasks.length;
            updated.taskCompleteQty[task.id] = Math.round(completeVal * ratio);
            updated.taskDefectQty[task.id] = Math.round(defectVal * ratio);
          }
          // Reset send cascade if complete changes
          if (g.completeArrowActive) {
            updated.completeArrowActive = false;
            updated.taskSendQty = {};
            for (const task of g.tasks) {
              updated.taskSendQty[task.id] = 0;
            }
            if (updated.confirmedSteps.has("send")) {
              updated.confirmedSteps = new Set([...updated.confirmedSteps].filter((s) => s !== "send"));
            }
          }
        } else if (field === "sendQty") {
          const qty = toInteger(digits || "0");
          const sendablePerTask = g.tasks.map((t) =>
            Math.max(0, toInteger(t.cache.completed_quantity) - toInteger(t.cache.transferred_quantity)),
          );
          let remaining = qty;
          updated.taskSendQty = {};
          for (let i = 0; i < g.tasks.length; i++) {
            const alloc = Math.min(remaining, sendablePerTask[i]);
            updated.taskSendQty[g.tasks[i].id] = alloc;
            remaining -= alloc;
          }
        }

        return updated;
      }),
    );
  };

  const toggleGroupStep = (groupKey: string, step: RowStep) => {
    setGroups((prev) =>
      prev.map((g) => {
        if (g.key !== groupKey) return g;
        const next = new Set(g.confirmedSteps);
        if (next.has(step)) next.delete(step);
        else next.add(step);
        return { ...g, confirmedSteps: next };
      }),
    );
  };

  const activateGroupIssueArrow = (groupKey: string) => {
    setGroups((prev) =>
      prev.map((g) => {
        if (g.key !== groupKey) return g;
        const issueVal = toInteger(g.issueQty);
        // Transfer issueQty to completeQty
        const newCompleteQty = issueVal;
        const newCompleteQtyStr = issueVal > 0 ? String(issueVal) : "";
        const taskCompleteQty = distributeQty(
          g.tasks,
          issueVal,
          (t) => toInteger(t.cache.in_work_quantity),
        );
        return {
          ...g,
          completeQty: newCompleteQtyStr,
          taskCompleteQty,
          issueArrowActive: true,
        };
      }),
    );
  };

  const deactivateGroupIssueArrow = (groupKey: string) => {
    setGroups((prev) =>
      prev.map((g) => {
        if (g.key !== groupKey) return g;
        // Reset complete and send
        const defaultCompleteQty = g.totalInWork > 0 ? String(g.totalInWork) : "";
        return {
          ...g,
          completeQty: defaultCompleteQty,
          sendQty: String(g.totalTransferred),
          taskCompleteQty: distributeQty(
            g.tasks,
            g.totalInWork,
            (t) => toInteger(t.cache.in_work_quantity),
          ),
          taskSendQty: Object.fromEntries(g.tasks.map((t) => [t.id, 0])),
          issueArrowActive: false,
          completeArrowActive: false,
          confirmedSteps: new Set([...g.confirmedSteps].filter((s) => s !== "complete" && s !== "send")),
        };
      }),
    );
  };

  const toggleGroupIssueArrow = (groupKey: string) => {
    setGroups((prev) => {
      const g = prev.find((x) => x.key === groupKey);
      if (!g) return prev;
      if (g.issueArrowActive) {
        // Can't use setGroups callback here easily, so we call the specific functions
        // We need a different approach
        const result = [...prev];
        const idx = result.findIndex((x) => x.key === groupKey);
        if (idx < 0) return prev;

        const defaultCompleteQty = result[idx].totalInWork > 0 ? String(result[idx].totalInWork) : "";
        result[idx] = {
          ...result[idx],
          completeQty: defaultCompleteQty,
          sendQty: String(result[idx].totalTransferred),
          taskCompleteQty: distributeQty(
            result[idx].tasks,
            result[idx].totalInWork,
            (t) => toInteger(t.cache.in_work_quantity),
          ),
          taskSendQty: Object.fromEntries(result[idx].tasks.map((t) => [t.id, 0])),
          issueArrowActive: false,
          completeArrowActive: false,
          confirmedSteps: new Set([...result[idx].confirmedSteps].filter((s) => s !== "complete" && s !== "send")),
        };
        return result;
      } else {
        const result = [...prev];
        const idx = result.findIndex((x) => x.key === groupKey);
        if (idx < 0) return prev;

        // Distribute sequentially: already issued - completed - defect + new input
        const inputVal = toInteger(result[idx].issueQty);
        const taskCompleteQty: Record<number, number> = {};
        let remainingInput = inputVal;
        for (const task of result[idx].tasks) {
          const taskIssued = toInteger(task.cache.issued_quantity);
          const taskCompleted = toInteger(task.cache.completed_quantity);
          const taskDefect = toInteger(task.cache.rejected_quantity);
          const alreadyInWork = Math.max(0, taskIssued - taskCompleted - taskDefect);
          const taskPlan = toInteger(task.planned_quantity);
          const canAdd = Math.max(0, taskPlan - taskIssued);
          const addFromInput = Math.min(remainingInput, canAdd);

          taskCompleteQty[task.id] = alreadyInWork + addFromInput;
          remainingInput -= addFromInput;
        }
        const totalComplete = Object.values(taskCompleteQty).reduce((s, v) => s + v, 0);
        result[idx] = {
          ...result[idx],
          completeQty: totalComplete > 0 ? String(totalComplete) : "",
          taskCompleteQty,
          issueArrowActive: true,
        };
        return result;
      }
    });
  };

  const toggleGroupCompleteArrow = (groupKey: string) => {
    setGroups((prev) => {
      const g = prev.find((x) => x.key === groupKey);
      if (!g) return prev;
      if (g.completeArrowActive) {
        const result = [...prev];
        const idx = result.findIndex((x) => x.key === groupKey);
        if (idx < 0) return prev;
        result[idx] = {
          ...result[idx],
          sendQty: String(result[idx].totalTransferred),
          taskSendQty: Object.fromEntries(result[idx].tasks.map((t) => [t.id, 0])),
          completeArrowActive: false,
          confirmedSteps: new Set([...result[idx].confirmedSteps].filter((s) => s !== "send")),
        };
        return result;
      } else {
        const result = [...prev];
        const idx = result.findIndex((x) => x.key === groupKey);
        if (idx < 0) return prev;

        const inputCompleteVal = toInteger(result[idx].completeQty);
        const inputDefectVal = toInteger(result[idx].defectQty);
        // Transfer: completeQty - defectQty → sendQty, distributed sequentially
        const toTransfer = Math.max(0, inputCompleteVal - inputDefectVal);
        let remaining = toTransfer;
        const taskSendQty: Record<number, number> = {};

        for (const task of result[idx].tasks) {
          const taskCompleted = toInteger(task.cache.completed_quantity);
          const taskTransferred = toInteger(task.cache.transferred_quantity);
          const taskDefect = toInteger(task.cache.rejected_quantity);
          const alreadyReady = Math.max(0, taskCompleted - taskTransferred - taskDefect);
          const canTake = Math.min(remaining, alreadyReady);

          taskSendQty[task.id] = canTake;
          remaining -= canTake;
          if (remaining <= 0) break;
        }

        const totalSend = toTransfer;
        result[idx] = {
          ...result[idx],
          sendQty: String(totalSend),
          taskSendQty,
          completeArrowActive: true,
        };
        return result;
      }
    });
  };

  const confirmGroupAll = (groupKey: string) => {
    setGroups((prev) =>
      prev.map((g) => {
        if (g.key !== groupKey) return g;
        const allSteps: RowStep[] = [];
        if (toInteger(g.issueQty) > 0) allSteps.push("issue");
        if (toInteger(g.completeQty) > 0) allSteps.push("complete");
        if (toInteger(g.sendQty) > 0) allSteps.push("send");
        if (allSteps.length === 0) return g;
        return { ...g, confirmedSteps: new Set(allSteps) };
      }),
    );
  };

  const doConfirm = () => {
    const issueEntries: { taskId: number; quantity: string }[] = [];
    const completeEntries: { taskId: number; goodQty: string; defectQty: string }[] = [];
    const sendEntries: { taskId: number; quantity: string }[] = [];

    for (const group of groups) {
      // Issue: confirm if field has value
      const totalIssue = toInteger(group.issueQty);
      if (totalIssue > 0) {
        const hasTaskData = Object.values(group.taskIssueQty).some((v) => v > 0);
        if (hasTaskData) {
          for (const task of group.tasks) {
            const qty = group.taskIssueQty[task.id] || 0;
            if (qty > 0) {
              issueEntries.push({ taskId: task.id, quantity: String(qty) });
            }
          }
        } else {
          const perTask = Math.floor(totalIssue / group.tasks.length);
          let remaining = totalIssue;
          for (let i = 0; i < group.tasks.length; i++) {
            const qty = i === group.tasks.length - 1 ? remaining : perTask;
            remaining -= qty;
            if (qty > 0) {
              issueEntries.push({ taskId: group.tasks[i].id, quantity: String(qty) });
            }
          }
        }
      }
      // Complete: confirm if field has value
      const totalComplete = toInteger(group.completeQty);
      const totalDefect = toInteger(group.defectQty);
      if (totalComplete > 0) {
        const hasTaskData = Object.values(group.taskCompleteQty).some((v) => v > 0);
        if (hasTaskData) {
          for (const task of group.tasks) {
            const completeQty = group.taskCompleteQty[task.id] || 0;
            const defectQty = group.taskDefectQty[task.id] || 0;
            const goodQty = Math.max(0, completeQty - defectQty);
            if (completeQty > 0) {
              completeEntries.push({ taskId: task.id, goodQty: String(goodQty), defectQty: String(defectQty) });
            }
          }
        } else {
          const perTaskComplete = Math.floor(totalComplete / group.tasks.length);
          const perTaskDefect = Math.floor(totalDefect / group.tasks.length);
          let remComplete = totalComplete;
          let remDefect = totalDefect;
          for (let i = 0; i < group.tasks.length; i++) {
            const isLast = i === group.tasks.length - 1;
            const completeQty = isLast ? remComplete : perTaskComplete;
            const defectQty = isLast ? remDefect : perTaskDefect;
            remComplete -= completeQty;
            remDefect -= defectQty;
            const goodQty = Math.max(0, completeQty - defectQty);
            if (completeQty > 0) {
              completeEntries.push({ taskId: group.tasks[i].id, goodQty: String(goodQty), defectQty: String(defectQty) });
            }
          }
        }
      }
      // Send: confirm if field has value
      const totalSend = toInteger(group.sendQty);
      if (totalSend > 0) {
        // Use taskSendQty if populated, otherwise distribute evenly
        const hasTaskData = Object.values(group.taskSendQty).some((v) => v > 0);
        if (hasTaskData) {
          for (const task of group.tasks) {
            const qty = group.taskSendQty[task.id] || 0;
            if (qty > 0) {
              sendEntries.push({ taskId: task.id, quantity: String(qty) });
            }
          }
        } else {
          // Distribute evenly across tasks
          const perTask = Math.floor(totalSend / group.tasks.length);
          let remaining = totalSend;
          for (let i = 0; i < group.tasks.length; i++) {
            const qty = i === group.tasks.length - 1 ? remaining : perTask;
            remaining -= qty;
            if (qty > 0) {
              sendEntries.push({ taskId: group.tasks[i].id, quantity: String(qty) });
            }
          }
        }
      }
    }

    if (issueEntries.length > 0 || completeEntries.length > 0 || sendEntries.length > 0) {
      const now = new Date();
      const timeStr = now.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
      const log: typeof actionLog = [];

      if (issueEntries.length > 0) {
        log.push({ type: "Выдача", time: timeStr, status: "success", message: `${issueEntries.length} задач` });
      }
      if (completeEntries.length > 0) {
        log.push({ type: "Факт", time: timeStr, status: "success", message: `${completeEntries.length} задач` });
      }
      if (sendEntries.length > 0) {
        log.push({ type: "Передача", time: timeStr, status: "success", message: `${sendEntries.length} задач` });
      }

      // Save lastConfirmedSteps per group for highlighting
      setGroups((prev) =>
        prev.map((g) => {
          const stepsForGroup: RowStep[] = [];
          if (toInteger(g.issueQty) > 0) stepsForGroup.push("issue");
          if (toInteger(g.completeQty) > 0) stepsForGroup.push("complete");
          if (toInteger(g.sendQty) > 0) stepsForGroup.push("send");
          return { ...g, lastConfirmedSteps: new Set(stepsForGroup), confirmedSteps: new Set<RowStep>() };
        }),
      );

      setActionLog(log);
      toast({
        title: "Массовая операция выполнена",
        description: log.map((e) => `${e.type}: ${e.message}`).join(", "),
        variant: "success",
      });
      onExecuteAll({ issueEntries, completeEntries, sendEntries });
    }
  };

  // Bulk actions — apply to all groups
  const bulkIssueActive = groups.some((g) => g.issueArrowActive);
  const bulkCompleteActive = groups.some((g) => g.completeArrowActive);
  const bulkConfirmActive = groups.some((g) => g.confirmedSteps.size > 0);

  const toggleBulkIssue = () => {
    if (bulkIssueActive) {
      // Deactivate all
      setGroups((prev) =>
        prev.map((g) => {
          const defaultCompleteQty = g.totalInWork > 0 ? String(g.totalInWork) : "";
          return {
            ...g,
            completeQty: defaultCompleteQty,
            sendQty: String(g.totalTransferred),
            taskCompleteQty: distributeQty(g.tasks, g.totalInWork, (t) => toInteger(t.cache.in_work_quantity)),
            taskSendQty: Object.fromEntries(g.tasks.map((t) => [t.id, 0])),
            issueArrowActive: false,
            completeArrowActive: false,
            confirmedSteps: new Set([...g.confirmedSteps].filter((s) => s !== "complete" && s !== "send")),
          };
        }),
      );
    } else {
      // Activate all - sequential distribution
      setGroups((prev) =>
        prev.map((g) => {
          const inputVal = toInteger(g.issueQty);
          // Distribute sequentially: already issued - completed - defect + new input
          const taskCompleteQty: Record<number, number> = {};
          let remainingInput = inputVal;
          for (const task of g.tasks) {
            const taskIssued = toInteger(task.cache.issued_quantity);
            const taskCompleted = toInteger(task.cache.completed_quantity);
            const taskDefect = toInteger(task.cache.rejected_quantity);
            // What's already in work but not yet completed
            const alreadyInWork = Math.max(0, taskIssued - taskCompleted - taskDefect);
            // Plus new from input field
            const taskPlan = toInteger(task.planned_quantity);
            const canAdd = Math.max(0, taskPlan - taskIssued);
            const addFromInput = Math.min(remainingInput, canAdd);

            taskCompleteQty[task.id] = alreadyInWork + addFromInput;
            remainingInput -= addFromInput;
          }
          const totalComplete = Object.values(taskCompleteQty).reduce((s, v) => s + v, 0);
          return {
            ...g,
            completeQty: totalComplete > 0 ? String(totalComplete) : "",
            taskCompleteQty,
            issueArrowActive: true,
          };
        }),
      );
    }
  };

  const toggleBulkComplete = () => {
    if (bulkCompleteActive) {
      setGroups((prev) =>
        prev.map((g) => ({
          ...g,
          sendQty: String(g.totalTransferred),
          taskSendQty: Object.fromEntries(g.tasks.map((t) => [t.id, 0])),
          completeArrowActive: false,
          confirmedSteps: new Set([...g.confirmedSteps].filter((s) => s !== "send")),
        })),
      );
    } else {
      setGroups((prev) =>
        prev.map((g) => {
          const inputCompleteVal = toInteger(g.completeQty);
          const inputDefectVal = toInteger(g.defectQty);
          // Transfer: completeQty - defectQty → sendQty, distributed sequentially
          const toTransfer = Math.max(0, inputCompleteVal - inputDefectVal);
          let remaining = toTransfer;
          const taskSendQty: Record<number, number> = {};
          for (const task of g.tasks) {
            const taskCompleted = toInteger(task.cache.completed_quantity);
            const taskTransferred = toInteger(task.cache.transferred_quantity);
            const taskDefect = toInteger(task.cache.rejected_quantity);
            const alreadyReady = Math.max(0, taskCompleted - taskTransferred - taskDefect);
            const canTake = Math.min(remaining, alreadyReady);
            taskSendQty[task.id] = canTake;
            remaining -= canTake;
            if (remaining <= 0) break;
          }
          return {
            ...g,
            sendQty: String(toTransfer),
            taskSendQty,
            completeArrowActive: true,
          };
        }),
      );
    }
  };

  const toggleBulkConfirm = () => {
    if (bulkConfirmActive) {
      setGroups((prev) => prev.map((g) => ({ ...g, confirmedSteps: new Set<RowStep>() })));
    } else {
      setGroups((prev) =>
        prev.map((g) => {
          const allSteps: RowStep[] = [];
          if (toInteger(g.issueQty) > 0) allSteps.push("issue");
          if (toInteger(g.completeQty) > 0) allSteps.push("complete");
          if (toInteger(g.sendQty) > 0) allSteps.push("send");
          if (allSteps.length === 0) return g;
          return { ...g, confirmedSteps: new Set(allSteps) };
        }),
      );
    }
  };

  // Count confirmed steps across all groups
  const totalConfirmedSteps = groups.reduce((sum, g) => sum + g.confirmedSteps.size, 0);
  const totalTasksWithSteps = groups.filter((g) => g.confirmedSteps.size > 0).length;

  const getTaskProgress = (group: BulkOpGroup): string => {
    return group.tasks.map((task) => {
      const completed = toInteger(task.cache.completed_quantity);
      const planned = toInteger(task.planned_quantity);
      return `${completed}/${planned}`;
    }).join(", ");
  };

  return (
    <div className="rounded-lg border bg-card inline-block">
      <div className="overflow-auto">
        <table className="text-sm">
          <thead className="sticky top-0 bg-background border-b">
            <tr>
              <th className="text-left p-2 text-xs font-medium text-muted-foreground whitespace-nowrap">Этап</th>
              <th className="text-left p-2 text-xs font-medium text-muted-foreground whitespace-nowrap">Артикул</th>
              <th className="text-left p-2 text-xs font-medium text-muted-foreground whitespace-nowrap">Операция</th>
              <th className="text-left p-2 text-xs font-medium text-muted-foreground whitespace-nowrap">План</th>
              <th className="text-left p-2 text-xs font-medium text-muted-foreground whitespace-nowrap">Выдано</th>
              <th className="w-8"></th>
              <th className="text-left p-2 text-xs font-medium text-muted-foreground whitespace-nowrap">Завершение</th>
              <th className="text-left p-2 text-xs font-medium text-muted-foreground whitespace-nowrap">Брак</th>
              <th className="w-8"></th>
              <th className="text-left p-2 text-xs font-medium text-muted-foreground whitespace-nowrap">Передача</th>
              <th className="w-8"></th>
              <th className="text-left p-2 text-xs font-medium text-muted-foreground whitespace-nowrap">Прогресс</th>
            </tr>
          </thead>
          <tbody>
            {groups.map((group) => {
              const planQty = group.totalPlan;
              const sendMax = Math.max(0, group.totalCompleted - group.totalTransferred);
              const progress = getTaskProgress(group);

              return (
                <tr key={group.key} className={`border-b ${group.lastConfirmedSteps.size > 0 ? "bg-emerald-50/50" : ""}`}>
                  <td className="p-2 whitespace-nowrap">#{group.tasks[0].sequence}</td>
                  <td className="p-2 font-medium whitespace-nowrap">{group.label}</td>
                  <td className="p-2 text-xs whitespace-nowrap">
                    <span className="flex items-center gap-1">
                      {group.operationName}
                      {group.tasks.length > 1 && (
                        <span className="px-1 py-0.5 text-[10px] font-semibold rounded-full bg-blue-100 text-blue-700">
                          ×{group.tasks.length}
                        </span>
                      )}
                    </span>
                  </td>
                  <td className="p-2 whitespace-nowrap">
                    <button
                      type="button"
                      className="cursor-pointer hover:text-blue-600 transition-colors"
                      onClick={() => updateGroupQty(group.key, "issueQty", String(planQty))}
                      title="Кликнуть = выдать весь план"
                    >
                      {fmtQty(planQty)}
                    </button>
                  </td>
                  <td className="p-2">
                    <QtyInput
                      min="0"
                      value={group.issueQty}
                      onChange={(ev) => updateGroupQty(group.key, "issueQty", ev.target.value)}
                      className="w-20"
                      disabled={pending}
                    />
                  </td>
                  <td className="p-1 text-center">
                    <button
                      type="button"
                      className={`inline-flex items-center justify-center h-6 w-6 rounded transition-colors disabled:opacity-30 disabled:cursor-not-allowed ${
                        group.issueArrowActive
                          ? "bg-blue-100 text-blue-700 hover:bg-red-100 hover:text-red-700 hover:line-through"
                          : "hover:bg-accent text-muted-foreground hover:text-foreground"
                      }`}
                      disabled={pending}
                      onClick={() => toggleGroupIssueArrow(group.key)}
                      title={group.issueArrowActive ? "Отменить передачу" : "Выдача → Завершение"}
                    >
                      <ArrowRight size={14} />
                    </button>
                  </td>
                  <td className="p-2">
                    <QtyInput
                      min="0"
                      value={group.completeQty}
                      onChange={(ev) => updateGroupQty(group.key, "completeQty", ev.target.value)}
                      className="w-20"
                      disabled={pending}
                    />
                  </td>
                  <td className="p-2">
                    <QtyInput
                      min="0"
                      value={group.defectQty}
                      onChange={(ev) => updateGroupQty(group.key, "defectQty", ev.target.value)}
                      className="w-16"
                      disabled={pending}
                    />
                  </td>
                  <td className="p-1 text-center">
                    <button
                      type="button"
                      className={`inline-flex items-center justify-center h-6 w-6 rounded transition-colors disabled:opacity-30 disabled:cursor-not-allowed ${
                        group.completeArrowActive
                          ? "bg-blue-100 text-blue-700 hover:bg-red-100 hover:text-red-700 hover:line-through"
                          : "hover:bg-accent text-muted-foreground hover:text-foreground"
                      }`}
                      disabled={pending || toInteger(group.completeQty) - toInteger(group.defectQty) <= 0}
                      onClick={() => toggleGroupCompleteArrow(group.key)}
                      title={group.completeArrowActive ? "Отменить передачу" : "Завершение - Брак → Передача"}
                    >
                      <ArrowRight size={14} />
                    </button>
                  </td>
                  <td className="p-2">
                    <QtyInput
                      min="0"
                      value={group.sendQty}
                      onChange={(ev) => updateGroupQty(group.key, "sendQty", ev.target.value)}
                      className="w-20"
                      disabled={pending}
                    />
                  </td>
                  <td className="p-1 text-center">
                    <button
                      type="button"
                      className={`inline-flex items-center justify-center h-6 w-6 rounded transition-colors disabled:opacity-30 disabled:cursor-not-allowed ${
                        group.confirmedSteps.size > 0
                          ? "bg-emerald-100 text-emerald-700 hover:bg-red-100 hover:text-red-700 hover:line-through"
                          : "hover:bg-emerald-100 text-muted-foreground hover:text-emerald-700"
                      }`}
                      disabled={pending}
                      onClick={() => confirmGroupAll(group.key)}
                      title={group.confirmedSteps.size > 0 ? "Отменить подтверждение" : "Отметить все шаги для группы"}
                    >
                      <Check size={14} />
                    </button>
                  </td>
                  <td className="p-2 text-xs text-muted-foreground whitespace-nowrap font-mono">
                    {progress}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between p-3 border-t">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-muted-foreground whitespace-nowrap">Применить ко всем:</span>
          <button
            type="button"
            className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-blue-50 hover:border-blue-400 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
            disabled={pending}
            onClick={() => {
              setGroups((prev) =>
                prev.map((g) => {
                  const remaining = Math.max(0, g.totalPlan - g.totalIssued);
                  const currentIssue = toInteger(g.issueQty);
                  const newIssue = currentIssue + remaining;
                  return {
                    ...g,
                    issueQty: String(newIssue),
                    taskIssueQty: distributeQty(g.tasks, newIssue, (t) => {
                      const taskIssued = toInteger(t.cache.issued_quantity);
                      const taskPlan = toInteger(t.planned_quantity);
                      return Math.max(0, taskPlan - taskIssued);
                    }),
                  };
                }),
              );
            }}
            title="Выдать остаток плана (план - уже выданное)"
          >
            Выдать план
          </button>
          <button
            type="button"
            className={`inline-flex items-center justify-center h-7 w-7 rounded border transition-colors disabled:opacity-30 disabled:cursor-not-allowed ${
              bulkIssueActive
                ? "bg-blue-100 border-blue-400 hover:bg-red-100 hover:border-red-400 hover:text-red-700 hover:line-through"
                : "bg-background hover:bg-accent text-muted-foreground hover:text-foreground"
            }`}
            disabled={pending}
            onClick={toggleBulkIssue}
            title={bulkIssueActive ? "Отменить передачу для всех" : "Выдача → Завершение для всех"}
          >
            <ArrowRight size={14} />
          </button>
          <button
            type="button"
            className={`inline-flex items-center justify-center h-7 w-7 rounded border transition-colors disabled:opacity-30 disabled:cursor-not-allowed ${
              bulkCompleteActive
                ? "bg-blue-100 border-blue-400 hover:bg-red-100 hover:border-red-400 hover:text-red-700 hover:line-through"
                : "bg-background hover:bg-accent text-muted-foreground hover:text-foreground"
            }`}
            disabled={pending}
            onClick={toggleBulkComplete}
            title={bulkCompleteActive ? "Отменить передачу для всех" : "Завершение - Брак → Передача для всех"}
          >
            <ArrowRight size={14} />
          </button>
          <button
            type="button"
            className={`inline-flex items-center justify-center h-7 w-7 rounded border transition-colors disabled:opacity-30 disabled:cursor-not-allowed ${
              bulkConfirmActive
                ? "bg-emerald-100 border-emerald-400 hover:bg-red-100 hover:border-red-400 hover:text-red-700 hover:line-through"
                : "bg-background hover:bg-emerald-100 text-muted-foreground hover:text-emerald-700"
            }`}
            disabled={pending}
            onClick={toggleBulkConfirm}
            title={bulkConfirmActive ? "Отменить подтверждение для всех" : "Отметить все шаги для всех групп"}
          >
            <Check size={14} />
          </button>
          <span className="text-sm text-muted-foreground ml-4">
            {totalConfirmedSteps > 0
              ? `Групп отмечено: ${totalTasksWithSteps}`
              : "Нажмите ✓ для отметки"}
          </span>
        </div>
        <div className="flex flex-col items-end gap-2">
          <Button
            size="sm"
            onClick={doConfirm}
            disabled={pending}
          >
            Подтвердить
          </Button>
          {actionLog.length > 0 && (
            <div className="flex flex-col gap-1 text-xs">
              <span className="font-medium text-muted-foreground">Журнал действий (сессия)</span>
              {actionLog.map((entry, i) => (
                <div key={i} className="flex items-center gap-2">
                  <span className={entry.status === "success" ? "text-emerald-600" : "text-red-600"}>
                    {entry.status === "success" ? "✓" : "✗"}
                  </span>
                  <span className="font-medium">{entry.type}</span>
                  <span className="text-muted-foreground">{entry.time}</span>
                  <span className="text-muted-foreground">{entry.message}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
