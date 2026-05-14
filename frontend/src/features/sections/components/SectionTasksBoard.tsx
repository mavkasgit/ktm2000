import { Clock, Send } from "lucide-react";

import type { SectionBoardTask } from "@/shared/api/shopfloor";
import { Badge, Button } from "@/shared/ui";

export type TaskBoardViewMode = "active" | "waiting" | "completed";
export type TaskActionDialogType = "issue" | "complete" | "send";

const taskStatusLabels: Record<string, string> = {
  waiting_previous: "Ожидает",
  ready: "Готов",
  in_progress: "В работе",
  partially_completed: "Частично",
  completed: "Завершен",
  cancelled: "Отменен",
};

const taskStatusColor: Record<string, string> = {
  waiting_previous: "bg-gray-100 text-gray-600",
  ready: "bg-blue-100 text-blue-700",
  in_progress: "bg-amber-100 text-amber-700",
  partially_completed: "bg-orange-100 text-orange-700",
  completed: "bg-emerald-100 text-emerald-700",
  cancelled: "bg-red-100 text-red-600",
};

function fmtQty(value: string): string {
  const n = parseFloat(value);
  if (!Number.isFinite(n)) return "0";
  return Number.isInteger(n) ? String(n) : n.toFixed(3).replace(/\.?0+$/, "");
}

function isTaskVisible(task: SectionBoardTask, mode: TaskBoardViewMode): boolean {
  if (mode === "active") return ["ready", "in_progress", "partially_completed"].includes(task.status);
  if (mode === "waiting") return task.status === "waiting_previous";
  return ["completed", "cancelled"].includes(task.status);
}

type SectionTasksBoardProps = {
  tasks: SectionBoardTask[];
  isLoading: boolean;
  mode: TaskBoardViewMode;
  onModeChange: (next: TaskBoardViewMode) => void;
  onAction: (type: TaskActionDialogType, task: SectionBoardTask) => void;
};

export function SectionTasksBoard({
  tasks,
  isLoading,
  mode,
  onModeChange,
  onAction,
}: SectionTasksBoardProps) {
  const filteredTasks = tasks.filter((task) => isTaskVisible(task, mode));

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <Button variant={mode === "active" ? "default" : "outline"} onClick={() => onModeChange("active")} className="min-h-[40px]">
          Активные
        </Button>
        <Button variant={mode === "waiting" ? "default" : "outline"} onClick={() => onModeChange("waiting")} className="min-h-[40px]">
          Ожидают предыдущий
        </Button>
        <Button variant={mode === "completed" ? "default" : "outline"} onClick={() => onModeChange("completed")} className="min-h-[40px]">
          Завершенные
        </Button>
      </div>

      {isLoading && <div className="rounded-lg border p-4 text-sm text-muted-foreground">Загрузка задач...</div>}
      {!isLoading && filteredTasks.length === 0 && (
        <div className="rounded-lg border p-4 text-sm text-muted-foreground text-center">Нет задач в выбранном режиме</div>
      )}

      {!isLoading && filteredTasks.length > 0 && (
        <>
          {/* Desktop table */}
          <div className="hidden md:block rounded-lg border overflow-auto">
            <table className="w-full text-sm">
              <thead className="border-b bg-muted/50">
                <tr>
                  <th className="text-left p-2">Этап</th>
                  <th className="text-left p-2">Операция</th>
                  <th className="text-left p-2">План</th>
                  <th className="text-left p-2">В работе</th>
                  <th className="text-left p-2">Факт</th>
                  <th className="text-left p-2">Передано</th>
                  <th className="text-left p-2">Брак</th>
                  <th className="text-left p-2">Остаток</th>
                  <th className="text-left p-2">Статус</th>
                  <th className="text-left p-2">Пред. этап</th>
                  <th className="text-left p-2">Действия</th>
                </tr>
              </thead>
              <tbody>
                {filteredTasks.map((task) => (
                  <tr key={task.id} className="border-b hover:bg-accent/30">
                    <td className="p-2">#{task.sequence}</td>
                    <td className="p-2">
                      <div className="font-medium">{task.operation_name || "—"}</div>
                      <div className="text-xs text-muted-foreground">{task.operation_code || "—"}</div>
                    </td>
                    <td className="p-2">{fmtQty(task.planned_quantity)}</td>
                    <td className="p-2">{fmtQty(task.cache.in_work_quantity)}</td>
                    <td className="p-2">{fmtQty(task.cache.completed_quantity)}</td>
                    <td className="p-2">{fmtQty(task.cache.transferred_quantity)}</td>
                    <td className="p-2">{fmtQty(task.cache.rejected_quantity)}</td>
                    <td className="p-2">{fmtQty(task.cache.remaining_quantity)}</td>
                    <td className="p-2">
                      <Badge variant="secondary" className={taskStatusColor[task.status] || ""}>
                        {taskStatusLabels[task.status] || task.status}
                      </Badge>
                    </td>
                    <td className="p-2">
                      {task.previous_stage ? (
                        <div className="text-xs">
                          <div>Факт: <span className="font-medium">{fmtQty(task.previous_stage.completed_quantity)}</span></div>
                          <div>Передано: <span className="font-medium">{fmtQty(task.previous_stage.transferred_quantity)}</span></div>
                        </div>
                      ) : (
                        <span className="text-xs text-muted-foreground">—</span>
                      )}
                    </td>
                    <td className="p-2">
                      <div className="flex gap-1">
                        <Button size="sm" variant="outline" className="min-h-[32px]" onClick={() => onAction("issue", task)}>
                          Выдать
                        </Button>
                        <Button size="sm" variant="outline" className="min-h-[32px]" onClick={() => onAction("complete", task)}>
                          <Clock size={14} />
                          <span className="ml-1">Факт</span>
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          className="min-h-[32px]"
                          onClick={() => onAction("send", task)}
                          disabled={!task.next_task_id}
                          title={task.next_task_id ? `Следующий этап: ${task.next_operation_name || "—"}` : "Следующий этап не создан"}
                        >
                          <Send size={14} />
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Mobile cards */}
          <div className="md:hidden space-y-3">
            {filteredTasks.map((task) => (
              <div key={task.id} className="rounded-lg border bg-card p-4 shadow-sm space-y-3">
                <div className="flex items-center justify-between gap-2">
                  <div className="font-semibold">
                    <span className="text-muted-foreground">#{task.sequence}</span>{" "}
                    {task.operation_name || "—"}
                  </div>
                  <Badge variant="secondary" className={taskStatusColor[task.status] || ""}>
                    {taskStatusLabels[task.status] || task.status}
                  </Badge>
                </div>

                {task.operation_code && (
                  <div className="text-xs text-muted-foreground">{task.operation_code}</div>
                )}

                <div className="grid grid-cols-2 gap-2 text-sm">
                  <div><span className="text-muted-foreground">План:</span> {fmtQty(task.planned_quantity)}</div>
                  <div><span className="text-muted-foreground">В работе:</span> {fmtQty(task.cache.in_work_quantity)}</div>
                  <div><span className="text-muted-foreground">Факт:</span> {fmtQty(task.cache.completed_quantity)}</div>
                  <div><span className="text-muted-foreground">Передано:</span> {fmtQty(task.cache.transferred_quantity)}</div>
                  <div><span className="text-muted-foreground">Брак:</span> {fmtQty(task.cache.rejected_quantity)}</div>
                  <div><span className="text-muted-foreground">Остаток:</span> {fmtQty(task.cache.remaining_quantity)}</div>
                </div>

                {task.previous_stage && (
                  <div className="text-xs text-muted-foreground border-t pt-2">
                    Пред. этап: факт {fmtQty(task.previous_stage.completed_quantity)}, передано {fmtQty(task.previous_stage.transferred_quantity)}
                  </div>
                )}

                <div className="flex gap-2 pt-1">
                  <Button size="sm" variant="outline" className="flex-1 min-h-[36px]" onClick={() => onAction("issue", task)}>
                    Выдать
                  </Button>
                  <Button size="sm" variant="outline" className="flex-1 min-h-[36px]" onClick={() => onAction("complete", task)}>
                    <Clock size={14} />
                    <span className="ml-1">Факт</span>
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    className="min-h-[36px] px-3"
                    onClick={() => onAction("send", task)}
                    disabled={!task.next_task_id}
                  >
                    <Send size={14} />
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

