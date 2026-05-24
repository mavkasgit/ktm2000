import { useState } from "react";
import { ArrowRight, Check } from "lucide-react";
import { Button, Input } from "@/shared/ui";
import type { SectionBoardTask } from "@/shared/api/shopfloor";

function fmtQty(value: string): string {
  const n = parseFloat(value);
  if (!Number.isFinite(n)) return "0";
  return String(Math.round(n));
}

function toInteger(value: string | number): number {
  const n = typeof value === "number" ? value : parseFloat(value);
  return Number.isFinite(n) ? Math.round(n) : 0;
}

type RowStep = "issue" | "complete" | "send";

type BulkOpEntry = {
  task: SectionBoardTask;
  issueQty: string;
  completeQty: string;
  defectQty: string;
  sendQty: string;
  confirmedSteps: Set<RowStep>;
};

interface BulkOperationsPanelProps {
  tasks: SectionBoardTask[];
  onExecuteAll: (data: {
    issueEntries: { taskId: number; quantity: string }[];
    completeEntries: { taskId: number; goodQty: string; defectQty: string }[];
    sendEntries: { taskId: number; quantity: string }[];
  }) => void;
  pending: boolean;
}

export function BulkOperationsPanel({
  tasks,
  onExecuteAll,
  pending,
}: BulkOperationsPanelProps) {
  const [entries, setEntries] = useState<Record<number, BulkOpEntry>>(() => {
    const map: Record<number, BulkOpEntry> = {};
    return map;
  });

  const [activatedArrows, setActivatedArrows] = useState<Record<number, Set<"issue" | "complete">>>(() => {
    const map: Record<number, Set<"issue" | "complete">> = {};
    return map;
  });

  const [bulkArrows, setBulkArrows] = useState<Set<"issue" | "complete">>(new Set());
  const [bulkConfirmActive, setBulkConfirmActive] = useState(false);

  const initEntry = (task: SectionBoardTask): BulkOpEntry => {
    const issueMax = toInteger(task.cache.available_quantity);
    const inWork = toInteger(task.cache.in_work_quantity);
    const completedQty = toInteger(task.cache.completed_quantity);
    const transferredQty = toInteger(task.cache.transferred_quantity);
    const sendMax = Math.max(0, completedQty - transferredQty);
    // completeQty = in_work, but user can change defectQty which reduces available for complete
    return {
      task,
      issueQty: issueMax > 0 ? String(issueMax) : "",
      completeQty: inWork > 0 ? String(inWork) : "",
      defectQty: "0",
      sendQty: sendMax > 0 ? String(sendMax) : "",
      confirmedSteps: new Set<RowStep>(),
    };
  };

  const getEntry = (task: SectionBoardTask): BulkOpEntry => {
    if (!entries[task.id]) {
      const init = initEntry(task);
      setEntries((prev) => ({ ...prev, [task.id]: init }));
      return init;
    }
    return entries[task.id];
  };

  const updateQty = (taskId: number, field: keyof BulkOpEntry, value: string) => {
    const digits = value.replace(/[^\d]/g, "");
    setEntries((prev) => ({
      ...prev,
      [taskId]: { ...prev[taskId], [field]: digits },
    }));
  };

  const toggleStep = (taskId: number, step: RowStep) => {
    setEntries((prev) => {
      const e = prev[taskId];
      if (!e) return prev;
      const next = new Set(e.confirmedSteps);
      if (next.has(step)) next.delete(step);
      else next.add(step);
      return { ...prev, [taskId]: { ...e, confirmedSteps: next } };
    });
  };

  const transferQty = (taskId: number, field: keyof BulkOpEntry, maxVal: number, arrowType: "issue" | "complete") => {
    if (maxVal > 0) {
      updateQty(taskId, field, String(maxVal));
      setActivatedArrows((prev) => {
        const taskArrows = prev[taskId] || new Set<"issue" | "complete">();
        const next = new Set(taskArrows);
        next.add(arrowType);
        return { ...prev, [taskId]: next };
      });
    }
  };

  const undoCascade = (taskId: number, arrowType: "issue" | "complete") => {
    const e = entries[taskId];
    if (!e) return;

    if (arrowType === "issue") {
      // Отменяем передачу issue→complete и всё что за ней (complete→send)
      const issueMax = toInteger(e.task.cache.available_quantity);
      const inWork = toInteger(e.task.cache.in_work_quantity);
      setEntries((prev) => ({
        ...prev,
        [taskId]: {
          ...prev[taskId],
          issueQty: issueMax > 0 ? String(issueMax) : "",
          completeQty: inWork > 0 ? String(inWork) : "",
          sendQty: "0",
        },
      }));
      setActivatedArrows((prev) => {
        const taskArrows = prev[taskId] || new Set<"issue" | "complete">();
        const next = new Set(taskArrows);
        next.delete("issue");
        next.delete("complete");
        return { ...prev, [taskId]: next };
      });
    } else if (arrowType === "complete") {
      // Отменяем только передачу complete→send
      setEntries((prev) => ({
        ...prev,
        [taskId]: {
          ...prev[taskId],
          sendQty: "0",
        },
      }));
      setActivatedArrows((prev) => {
        const taskArrows = prev[taskId] || new Set<"issue" | "complete">();
        const next = new Set(taskArrows);
        next.delete("complete");
        return { ...prev, [taskId]: next };
      });
    }
  };

  const toggleArrow = (taskId: number, arrowType: "issue" | "complete") => {
    const taskArrows = activatedArrows[taskId] || new Set<"issue" | "complete">();
    
    if (taskArrows.has(arrowType)) {
      // Если уже активирована - отменяем каскад
      undoCascade(taskId, arrowType);
    } else {
      // Иначе активируем
      setActivatedArrows((prev) => {
        const next = new Set(prev[taskId] || new Set<"issue" | "complete">());
        next.add(arrowType);
        return { ...prev, [taskId]: next };
      });
    }
  };

  const confirmAll = (task: SectionBoardTask) => {
    const e = entries[task.id];
    if (!e) return;
    const allSteps: RowStep[] = [];
    if (toInteger(e.issueQty) > 0) allSteps.push("issue");
    if (toInteger(e.completeQty) > 0) allSteps.push("complete");
    if (toInteger(e.sendQty) > 0) allSteps.push("send");
    if (allSteps.length === 0) return;

    setEntries((prev) => ({
      ...prev,
      [task.id]: { ...prev[task.id], confirmedSteps: new Set(allSteps) },
    }));
  };

  const doConfirm = async () => {
    const currentEntries = { ...entries };
    const issueEntries: { taskId: number; quantity: string }[] = [];
    const completeEntries: { taskId: number; goodQty: string; defectQty: string }[] = [];
    const sendEntries: { taskId: number; quantity: string }[] = [];

    for (const task of tasks) {
      const e = currentEntries[task.id];
      if (!e) continue;
      if (e.confirmedSteps.has("issue") && toInteger(e.issueQty) > 0) {
        issueEntries.push({ taskId: task.id, quantity: e.issueQty });
      }
      if (e.confirmedSteps.has("complete") && toInteger(e.completeQty) > 0) {
        const defect = e.defectQty && e.defectQty !== "" ? e.defectQty : "0";
        const completeVal = toInteger(e.completeQty);
        const defectVal = toInteger(defect);
        const goodVal = Math.max(0, completeVal - defectVal);
        completeEntries.push({ taskId: task.id, goodQty: String(goodVal), defectQty: defect });
      }
      if (e.confirmedSteps.has("send") && toInteger(e.sendQty) > 0) {
        sendEntries.push({ taskId: task.id, quantity: e.sendQty });
      }
    }

    if (issueEntries.length > 0 || completeEntries.length > 0 || sendEntries.length > 0) {
      onExecuteAll({ issueEntries, completeEntries, sendEntries });
    }
  };

  // Bulk actions — apply to all rows
  const transferAllIssueToComplete = () => {
    for (const task of tasks) {
      const e = entries[task.id];
      if (!e) continue;
      const issueMax = toInteger(task.cache.available_quantity);
      const issueVal = toInteger(e.issueQty);
      if (issueVal > 0) {
        updateQty(task.id, "completeQty", String(issueVal));
        // Activate individual arrow for this task
        setActivatedArrows((prev) => {
          const taskArrows = prev[task.id] || new Set<"issue" | "complete">();
          const next = new Set(taskArrows);
          next.add("issue");
          return { ...prev, [task.id]: next };
        });
      }
    }
    setBulkArrows((prev) => {
      const next = new Set(prev);
      next.add("issue");
      return next;
    });
  };

  const undoBulkIssueCascade = () => {
    for (const task of tasks) {
      const e = entries[task.id];
      if (!e) continue;
      const issueMax = toInteger(task.cache.available_quantity);
      const inWork = toInteger(task.cache.in_work_quantity);
      setEntries((prev) => ({
        ...prev,
        [task.id]: {
          ...prev[task.id],
          issueQty: issueMax > 0 ? String(issueMax) : "",
          completeQty: inWork > 0 ? String(inWork) : "",
          sendQty: "0",
        },
      }));
    }
    // Clear all individual arrow activations for all tasks
    setActivatedArrows({});
    setBulkArrows((prev) => {
      const next = new Set(prev);
      next.delete("issue");
      next.delete("complete");
      return next;
    });
  };

  const transferAllCompleteToSend = () => {
    for (const task of tasks) {
      const e = entries[task.id];
      if (!e) continue;
      const completeVal = toInteger(e.completeQty);
      const defectVal = toInteger(e.defectQty || "0");
      const sendVal = Math.max(0, completeVal - defectVal);
      if (sendVal > 0) {
        updateQty(task.id, "sendQty", String(sendVal));
        // Activate individual arrow for this task
        setActivatedArrows((prev) => {
          const taskArrows = prev[task.id] || new Set<"issue" | "complete">();
          const next = new Set(taskArrows);
          next.add("complete");
          return { ...prev, [task.id]: next };
        });
      }
    }
    setBulkArrows((prev) => {
      const next = new Set(prev);
      next.add("complete");
      return next;
    });
  };

  const undoBulkCompleteCascade = () => {
    for (const task of tasks) {
      setEntries((prev) => ({
        ...prev,
        [task.id]: {
          ...prev[task.id],
          sendQty: "0",
        },
      }));
    }
    // Clear only complete arrows for all tasks, keep issue arrows
    setActivatedArrows((prev) => {
      const next: Record<number, Set<"issue" | "complete">> = {};
      for (const [taskId, arrows] of Object.entries(prev)) {
        const filtered = new Set(arrows);
        filtered.delete("complete");
        if (filtered.size > 0) {
          next[Number(taskId)] = filtered;
        }
      }
      return next;
    });
    setBulkArrows((prev) => {
      const next = new Set(prev);
      next.delete("complete");
      return next;
    });
  };

  const toggleBulkArrow = (arrowType: "issue" | "complete") => {
    if (bulkArrows.has(arrowType)) {
      // Отменяем каскад
      if (arrowType === "issue") {
        undoBulkIssueCascade();
      } else {
        undoBulkCompleteCascade();
      }
    } else {
      // Активируем
      if (arrowType === "issue") {
        transferAllIssueToComplete();
      } else {
        transferAllCompleteToSend();
      }
    }
  };

  const confirmAllTasks = () => {
    for (const task of tasks) {
      const e = entries[task.id];
      if (!e) continue;
      const allSteps: RowStep[] = [];
      if (toInteger(e.issueQty) > 0) allSteps.push("issue");
      if (toInteger(e.completeQty) > 0) allSteps.push("complete");
      if (toInteger(e.sendQty) > 0) allSteps.push("send");
      if (allSteps.length > 0) {
        setEntries((prev) => ({
          ...prev,
          [task.id]: { ...prev[task.id], confirmedSteps: new Set(allSteps) },
        }));
      }
    }
    setBulkConfirmActive(true);
  };

  const undoBulkConfirm = () => {
    for (const task of tasks) {
      setEntries((prev) => ({
        ...prev,
        [task.id]: { ...prev[task.id], confirmedSteps: new Set<RowStep>() },
      }));
    }
    setBulkConfirmActive(false);
  };

  const toggleBulkConfirm = () => {
    if (bulkConfirmActive) {
      undoBulkConfirm();
    } else {
      confirmAllTasks();
    }
  };

  return (
    <div className="rounded-lg border bg-card inline-block">
      <div className="overflow-auto">
        <table className="text-sm">
          <thead className="sticky top-0 bg-background border-b">
            <tr>
              <th className="text-left p-2 text-xs font-medium text-muted-foreground whitespace-nowrap">Этап</th>
              <th className="text-left p-2 text-xs font-medium text-muted-foreground whitespace-nowrap">Артикул</th>
              <th className="text-left p-2 text-xs font-medium text-muted-foreground whitespace-nowrap">Доступно</th>
              <th className="text-left p-2 text-xs font-medium text-muted-foreground whitespace-nowrap">Выдача</th>
              <th className="w-8"></th>
              <th className="text-left p-2 text-xs font-medium text-muted-foreground whitespace-nowrap">Завершение</th>
              <th className="text-left p-2 text-xs font-medium text-muted-foreground whitespace-nowrap">Брак</th>
              <th className="w-8"></th>
              <th className="text-left p-2 text-xs font-medium text-muted-foreground whitespace-nowrap">Передача</th>
              <th className="w-8"></th>
            </tr>
          </thead>
          <tbody>
            {tasks.map((task) => {
              const e = getEntry(task);
              const issueMax = toInteger(task.cache.available_quantity);
              const completeMax = toInteger(task.cache.in_work_quantity);
              const sendMax = Math.max(0, toInteger(task.cache.completed_quantity) - toInteger(task.cache.transferred_quantity));
              return (
                <tr key={task.id} className="border-b">
                  <td className="p-2 whitespace-nowrap">#{task.sequence}</td>
                  <td className="p-2 font-medium whitespace-nowrap">{task.product_sku}</td>
                  <td className="p-2 whitespace-nowrap">{fmtQty(String(issueMax))}</td>
                  <td className="p-2">
                    <Input
                      type="number"
                      min="0"
                      max={issueMax}
                      value={e.issueQty}
                      onChange={(ev) => updateQty(task.id, "issueQty", ev.target.value)}
                      className="h-7 w-20 text-xs"
                      disabled={pending}
                    />
                  </td>
                  <td className="p-1 text-center">
                    <button
                      type="button"
                      className={`inline-flex items-center justify-center h-6 w-6 rounded transition-colors disabled:opacity-30 disabled:cursor-not-allowed ${
                        activatedArrows[task.id]?.has("issue")
                          ? "bg-blue-100 text-blue-700 hover:bg-red-100 hover:text-red-700 hover:line-through"
                          : "hover:bg-accent text-muted-foreground hover:text-foreground"
                      }`}
                      disabled={pending || toInteger(e.issueQty) <= 0}
                      onClick={() => {
                        if (activatedArrows[task.id]?.has("issue")) {
                          toggleArrow(task.id, "issue");
                        } else {
                          transferQty(task.id, "completeQty", toInteger(e.issueQty), "issue");
                        }
                      }}
                      title={activatedArrows[task.id]?.has("issue") ? "Отменить передачу" : "Выдача → Завершение"}
                    >
                      <ArrowRight size={14} />
                    </button>
                  </td>
                  <td className="p-2">
                    <Input
                      type="number"
                      min="0"
                      max={completeMax}
                      value={e.completeQty}
                      onChange={(ev) => updateQty(task.id, "completeQty", ev.target.value)}
                      className="h-7 w-20 text-xs"
                      disabled={pending}
                    />
                  </td>
                  <td className="p-2">
                    <Input
                      type="number"
                      min="0"
                      value={e.defectQty}
                      onChange={(ev) => updateQty(task.id, "defectQty", ev.target.value)}
                      className="h-7 w-16 text-xs"
                      disabled={pending}
                    />
                  </td>
                  <td className="p-1 text-center">
                    <button
                      type="button"
                      className={`inline-flex items-center justify-center h-6 w-6 rounded transition-colors disabled:opacity-30 disabled:cursor-not-allowed ${
                        activatedArrows[task.id]?.has("complete")
                          ? "bg-blue-100 text-blue-700 hover:bg-red-100 hover:text-red-700 hover:line-through"
                          : "hover:bg-accent text-muted-foreground hover:text-foreground"
                      }`}
                      disabled={pending || toInteger(e.completeQty) - toInteger(e.defectQty || "0") <= 0}
                      onClick={() => {
                        if (activatedArrows[task.id]?.has("complete")) {
                          toggleArrow(task.id, "complete");
                        } else {
                          transferQty(task.id, "sendQty", Math.max(0, toInteger(e.completeQty) - toInteger(e.defectQty || "0")), "complete");
                        }
                      }}
                      title={activatedArrows[task.id]?.has("complete") ? "Отменить передачу" : "Завершение - Брак → Передача"}
                    >
                      <ArrowRight size={14} />
                    </button>
                  </td>
                  <td className="p-2">
                    <Input
                      type="number"
                      min="0"
                      max={sendMax}
                      value={e.sendQty}
                      onChange={(ev) => updateQty(task.id, "sendQty", ev.target.value)}
                      className="h-7 w-20 text-xs"
                      disabled={pending}
                    />
                  </td>
                  <td className="p-1 text-center">
                    <button
                      type="button"
                      className={`inline-flex items-center justify-center h-6 w-6 rounded transition-colors disabled:opacity-30 disabled:cursor-not-allowed ${
                        e.confirmedSteps.size > 0
                          ? "bg-emerald-100 text-emerald-700 hover:bg-red-100 hover:text-red-700 hover:line-through"
                          : "hover:bg-emerald-100 text-muted-foreground hover:text-emerald-700"
                      }`}
                      disabled={pending}
                      onClick={() => confirmAll(task)}
                      title={e.confirmedSteps.size > 0 ? "Отменить подтверждение" : "Отметить все шаги для выполнения"}
                    >
                      <Check size={14} />
                    </button>
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
            className={`inline-flex items-center justify-center h-7 w-7 rounded border transition-colors disabled:opacity-30 disabled:cursor-not-allowed ${
              bulkArrows.has("issue")
                ? "bg-blue-100 border-blue-400 hover:bg-red-100 hover:border-red-400 hover:text-red-700 hover:line-through"
                : "bg-background hover:bg-accent text-muted-foreground hover:text-foreground"
            }`}
            disabled={pending}
            onClick={() => toggleBulkArrow("issue")}
            title={bulkArrows.has("issue") ? "Отменить передачу для всех" : "Выдача → Завершение для всех"}
          >
            <ArrowRight size={14} />
          </button>
          <button
            type="button"
            className={`inline-flex items-center justify-center h-7 w-7 rounded border transition-colors disabled:opacity-30 disabled:cursor-not-allowed ${
              bulkArrows.has("complete")
                ? "bg-blue-100 border-blue-400 hover:bg-red-100 hover:border-red-400 hover:text-red-700 hover:line-through"
                : "bg-background hover:bg-accent text-muted-foreground hover:text-foreground"
            }`}
            disabled={pending}
            onClick={() => toggleBulkArrow("complete")}
            title={bulkArrows.has("complete") ? "Отменить передачу для всех" : "Завершение - Брак → Передача для всех"}
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
            title={bulkConfirmActive ? "Отменить подтверждение для всех" : "Отметить все шаги для всех задач"}
          >
            <Check size={14} />
          </button>
          <span className="text-sm text-muted-foreground ml-4">
            {(() => {
              let count = 0;
              for (const e of Object.values(entries)) count += e.confirmedSteps.size;
              return count > 0 ? `Отмечено: ${count}` : "Нажмите ✓ для отметки";
            })()}
          </span>
        </div>
        <Button
          size="sm"
          onClick={doConfirm}
          disabled={pending || Object.values(entries).every(e => e.confirmedSteps.size === 0)}
        >
          Подтвердить
        </Button>
      </div>
    </div>
  );
}
