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

  const transferQty = (taskId: number, field: keyof BulkOpEntry, maxVal: number) => {
    if (maxVal > 0) {
      updateQty(taskId, field, String(maxVal));
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

  return (
    <div className="rounded-lg border bg-card">
      <div className="p-3 border-b">
        <h3 className="text-sm font-semibold">Групповые операции — {tasks.length} задач</h3>
      </div>

      <div className="overflow-auto">
        <table className="w-full text-sm">
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
                      className="inline-flex items-center justify-center h-6 w-6 rounded hover:bg-accent text-muted-foreground hover:text-foreground transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                      disabled={pending || toInteger(e.issueQty) <= 0}
                      onClick={() => transferQty(task.id, "completeQty", toInteger(e.issueQty))}
                      title="Выдача → Завершение"
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
                      className="inline-flex items-center justify-center h-6 w-6 rounded hover:bg-accent text-muted-foreground hover:text-foreground transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                      disabled={pending || toInteger(e.completeQty) - toInteger(e.defectQty || "0") <= 0}
                      onClick={() => transferQty(task.id, "sendQty", Math.max(0, toInteger(e.completeQty) - toInteger(e.defectQty || "0")))}
                      title="Завершение - Брак → Передача"
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
                        e.confirmedSteps.size > 0 ? "bg-emerald-100 text-emerald-700" : "hover:bg-emerald-100 text-muted-foreground hover:text-emerald-700"
                      }`}
                      disabled={pending}
                      onClick={() => confirmAll(task)}
                      title="Отметить все шаги для выполнения"
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
        <div className="text-sm text-muted-foreground">
          {(() => {
            let count = 0;
            for (const e of Object.values(entries)) count += e.confirmedSteps.size;
            return count > 0 ? `Отмечено: ${count}` : "Нажмите ✓ для отметки";
          })()}
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
