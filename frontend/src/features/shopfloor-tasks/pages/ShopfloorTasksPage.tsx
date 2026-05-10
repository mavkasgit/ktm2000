import { useCallback, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Clock, Send } from "lucide-react";

import { apiClient, getErrorMessage } from "@/shared/api/client";
import { listSections } from "@/shared/api/sections";
import {
  completeTask,
  createTransfer,
  getSectionBoard,
  getSectionDailyStats,
  issueTask,
  type DailyStatsRow,
  type SectionBoardTask,
} from "@/shared/api/shopfloor";
import {
  Badge,
  Button,
  Checkbox,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/shared/ui";
import { toast } from "@/shared/ui/use-toast";

type TaskActionDialogType = "issue" | "complete" | "send";

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

function todayISO(): string {
  return new Date().toISOString().split("T")[0];
}

function nowLocalDateTime(): string {
  const d = new Date();
  const p = (v: number) => String(v).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}

function makeIdempotencyKey(prefix: string): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `${prefix}-${crypto.randomUUID()}`;
  }
  return `${prefix}-${Date.now()}-${Math.floor(Math.random() * 1_000_000)}`;
}

function actionTitle(type: TaskActionDialogType): string {
  if (type === "issue") return "Выдать в работу";
  if (type === "send") return "Передать на следующий этап";
  return "Внести факт";
}

export function ShopfloorTasksPage() {
  const queryClient = useQueryClient();
  const [sectionId, setSectionId] = useState<number | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [dateFrom, setDateFrom] = useState(todayISO());
  const [dateTo, setDateTo] = useState(todayISO());

  const [actionDialog, setActionDialog] = useState<{ open: boolean; type: TaskActionDialogType; task: SectionBoardTask | null }>({
    open: false,
    type: "complete",
    task: null,
  });

  const [actionQty, setActionQty] = useState("");
  const [defectQty, setDefectQty] = useState("");
  const [timesMatch, setTimesMatch] = useState(true);
  const [performedAt, setPerformedAt] = useState("");
  const [accountedAt, setAccountedAt] = useState("");
  const [actionComment, setActionComment] = useState("");

  const { data: me } = useQuery({
    queryKey: ["auth-me"],
    queryFn: async () => (await apiClient.get<{ id: number }>("/auth/me")).data,
    retry: false,
  });

  const { data: sections } = useQuery({
    queryKey: ["sections"],
    queryFn: listSections,
  });

  const boardParams = useMemo(
    () => ({
      date_from: dateFrom ? `${dateFrom}T00:00:00` : undefined,
      date_to: dateTo ? `${dateTo}T23:59:59` : undefined,
      status: statusFilter !== "all" ? statusFilter : undefined,
    }),
    [dateFrom, dateTo, statusFilter]
  );

  const { data: board, isLoading: boardLoading } = useQuery({
    queryKey: ["shopfloor-board", sectionId, boardParams],
    queryFn: () => getSectionBoard(sectionId as number, boardParams),
    enabled: sectionId !== null,
  });

  const { data: stats } = useQuery({
    queryKey: ["shopfloor-stats", sectionId, dateFrom, dateTo],
    queryFn: () =>
      getSectionDailyStats(sectionId as number, {
        date_from: `${dateFrom}T00:00:00`,
        date_to: `${dateTo}T23:59:59`,
      }),
    enabled: sectionId !== null,
  });

  const invalidateShopfloor = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["shopfloor-board"] });
    queryClient.invalidateQueries({ queryKey: ["shopfloor-stats"] });
  }, [queryClient]);

  const issueMutation = useMutation({
    mutationFn: ({ taskId, payload }: { taskId: number; payload: Parameters<typeof issueTask>[1] }) => issueTask(taskId, payload),
    onSuccess: () => {
      toast({ title: "Выдача записана", variant: "success" });
      invalidateShopfloor();
      setActionDialog({ open: false, type: "issue", task: null });
    },
    onError: (err) => toast({ title: "Ошибка", description: getErrorMessage(err), variant: "destructive" }),
  });

  const completeMutation = useMutation({
    mutationFn: ({ taskId, payload }: { taskId: number; payload: Parameters<typeof completeTask>[1] }) => completeTask(taskId, payload),
    onSuccess: () => {
      toast({ title: "Факт сохранен", variant: "success" });
      invalidateShopfloor();
      setActionDialog({ open: false, type: "complete", task: null });
    },
    onError: (err) => toast({ title: "Ошибка", description: getErrorMessage(err), variant: "destructive" }),
  });

  const sendMutation = useMutation({
    mutationFn: createTransfer,
    onSuccess: () => {
      toast({ title: "Передача отправлена", variant: "success" });
      invalidateShopfloor();
      setActionDialog({ open: false, type: "send", task: null });
    },
    onError: (err) => toast({ title: "Ошибка", description: getErrorMessage(err), variant: "destructive" }),
  });

  const selectedSection = useMemo(
    () => (sections || []).find((s) => s.id === sectionId),
    [sections, sectionId]
  );

  const openActionDialog = useCallback((type: TaskActionDialogType, task: SectionBoardTask) => {
    const now = nowLocalDateTime();
    setActionDialog({ open: true, type, task });
    setTimesMatch(true);
    setPerformedAt(now);
    setAccountedAt(now);
    setActionComment("");
    if (type === "complete") {
      setActionQty("");
      setDefectQty("");
    } else if (type === "issue") {
      setActionQty(fmtQty(task.cache.remaining_quantity));
      setDefectQty("");
    } else {
      const transferable = Math.max(0, parseFloat(task.cache.completed_quantity) - parseFloat(task.cache.transferred_quantity));
      setActionQty(Number.isFinite(transferable) ? String(transferable) : "");
      setDefectQty("");
    }
  }, []);

  const handleTimesMatchChange = useCallback(
    (checked: boolean) => {
      setTimesMatch(checked);
      if (checked) {
        setAccountedAt(performedAt);
      }
    },
    [performedAt]
  );

  const handlePerformedAtChange = useCallback(
    (value: string) => {
      setPerformedAt(value);
      if (timesMatch) {
        setAccountedAt(value);
      }
    },
    [timesMatch]
  );

  const submitAction = useCallback(() => {
    const task = actionDialog.task;
    if (!task) return;

    const qty = parseFloat(actionQty || "0");
    const effectivePerformedAt = performedAt || nowLocalDateTime();
    const effectiveAccountedAt = accountedAt || effectivePerformedAt;
    const executorUserId = me?.id;

    if (!(qty > 0)) {
      toast({ title: "Ошибка", description: "Количество должно быть больше 0", variant: "destructive" });
      return;
    }

    if (actionDialog.type === "issue") {
      issueMutation.mutate({
        taskId: task.id,
        payload: {
          quantity: String(qty),
          comment: actionComment || undefined,
          idempotency_key: makeIdempotencyKey("issue"),
          executor_user_id: executorUserId,
          performed_at: effectivePerformedAt,
          accounted_at: effectiveAccountedAt,
        },
      });
      return;
    }

    if (actionDialog.type === "complete") {
      const parsedDefect = parseFloat(defectQty || "0");
      const good = qty;
      const defect = Number.isFinite(parsedDefect) ? parsedDefect : 0;
      if (good + defect <= 0) {
        toast({ title: "Ошибка", description: "Укажите факт или брак", variant: "destructive" });
        return;
      }
      completeMutation.mutate({
        taskId: task.id,
        payload: {
          good_quantity: String(good),
          defect_quantity: String(defect),
          comment: actionComment || undefined,
          idempotency_key: makeIdempotencyKey("complete"),
          executor_user_id: executorUserId,
          performed_at: effectivePerformedAt,
          accounted_at: effectiveAccountedAt,
        },
      });
      return;
    }

    if (!task.next_task_id) {
      toast({ title: "Ошибка", description: "Не найдено задание следующего этапа", variant: "destructive" });
      return;
    }
    sendMutation.mutate({
      from_task_id: task.id,
      to_task_id: task.next_task_id,
      quantity: String(qty),
      comment: actionComment || undefined,
      idempotency_key: makeIdempotencyKey("send"),
      executor_user_id: executorUserId,
      performed_at: effectivePerformedAt,
      accounted_at: effectiveAccountedAt,
    });
  }, [
    actionDialog,
    actionQty,
    performedAt,
    accountedAt,
    me?.id,
    issueMutation,
    completeMutation,
    sendMutation,
    actionComment,
    defectQty,
  ]);

  const pendingMutation = issueMutation.isPending || completeMutation.isPending || sendMutation.isPending;

  const tasks = board?.tasks || [];
  const activeTasks = useMemo(() => tasks.filter((t) => ["ready", "in_progress", "partially_completed"].includes(t.status)), [tasks]);
  const waitingTasks = useMemo(() => tasks.filter((t) => t.status === "waiting_previous"), [tasks]);

  return (
    <>
      <header className="page-header">
        <div>
          <h1 className="page-title">Цеховые задания</h1>
          <p className="page-subtitle">Операционная доска цеха: выдача, факт, передача и статистика.</p>
        </div>
      </header>

      <section className="space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-2">
          <Select value={sectionId ? String(sectionId) : ""} onValueChange={(v) => setSectionId(v ? Number(v) : null)}>
            <SelectTrigger>
              <SelectValue placeholder="Выберите цех" />
            </SelectTrigger>
            <SelectContent>
              {sections?.filter((s) => s.kind === "production").map((s) => (
                <SelectItem key={s.id} value={String(s.id)}>
                  {s.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
          <Input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger>
              <SelectValue placeholder="Статус" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Все статусы</SelectItem>
              <SelectItem value="ready">Готов</SelectItem>
              <SelectItem value="in_progress">В работе</SelectItem>
              <SelectItem value="partially_completed">Частично</SelectItem>
              <SelectItem value="completed">Завершен</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {sectionId && (
          <>
            <div>
              <h2 className="text-lg font-semibold mb-2">Активные задачи</h2>
              {boardLoading && <p className="text-sm text-muted-foreground p-4">Загрузка...</p>}
              {!boardLoading && activeTasks.length === 0 && (
                <div className="rounded-lg border p-4 text-sm text-muted-foreground text-center">Нет активных задач</div>
              )}
              {!boardLoading && activeTasks.length > 0 && (
                <div className="rounded-lg border overflow-auto">
                  <table className="w-full text-sm">
                    <thead className="border-b bg-muted/50">
                      <tr>
                        <th className="text-left p-2">Этап</th>
                        <th className="text-left p-2">Операция</th>
                        <th className="text-left p-2">План</th>
                        <th className="text-left p-2">В работе</th>
                        <th className="text-left p-2">Факт</th>
                        <th className="text-left p-2">Брак</th>
                        <th className="text-left p-2">Остаток</th>
                        <th className="text-left p-2">Статус</th>
                        <th className="text-left p-2">Пред. этап</th>
                        <th className="text-left p-2">Действия</th>
                      </tr>
                    </thead>
                    <tbody>
                      {activeTasks.map((task) => (
                        <tr key={task.id} className="border-b hover:bg-accent/30">
                          <td className="p-2">#{task.sequence}</td>
                          <td className="p-2">
                            <div className="font-medium">{task.operation_name || "—"}</div>
                            <div className="text-xs text-muted-foreground">{task.operation_code}</div>
                          </td>
                          <td className="p-2">{fmtQty(task.planned_quantity)}</td>
                          <td className="p-2">{fmtQty(task.cache.in_work_quantity)}</td>
                          <td className="p-2">{fmtQty(task.cache.completed_quantity)}</td>
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
                              <Button size="sm" variant="outline" onClick={() => openActionDialog("issue", task)}>
                                Выдать
                              </Button>
                              <Button size="sm" variant="outline" onClick={() => openActionDialog("complete", task)}>
                                <Clock size={14} />
                                <span className="ml-1">Факт</span>
                              </Button>
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() => openActionDialog("send", task)}
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
              )}
            </div>

            <div>
              <h2 className="text-lg font-semibold mb-2">Назначенные (ожидают предыдущий этап)</h2>
              {!boardLoading && waitingTasks.length === 0 && (
                <div className="rounded-lg border p-4 text-sm text-muted-foreground text-center">Нет ожидающих задач</div>
              )}
              {!boardLoading && waitingTasks.length > 0 && (
                <div className="rounded-lg border overflow-auto">
                  <table className="w-full text-sm">
                    <thead className="border-b bg-muted/50">
                      <tr>
                        <th className="text-left p-2">Этап</th>
                        <th className="text-left p-2">Операция</th>
                        <th className="text-left p-2">План</th>
                        <th className="text-left p-2">В работе</th>
                        <th className="text-left p-2">Факт</th>
                        <th className="text-left p-2">Брак</th>
                        <th className="text-left p-2">Остаток</th>
                        <th className="text-left p-2">Статус</th>
                        <th className="text-left p-2">Пред. этап</th>
                        <th className="text-left p-2">Действия</th>
                      </tr>
                    </thead>
                    <tbody>
                      {waitingTasks.map((task) => (
                        <tr key={task.id} className="border-b hover:bg-accent/30">
                          <td className="p-2">#{task.sequence}</td>
                          <td className="p-2">
                            <div className="font-medium">{task.operation_name || "—"}</div>
                            <div className="text-xs text-muted-foreground">{task.operation_code}</div>
                          </td>
                          <td className="p-2">{fmtQty(task.planned_quantity)}</td>
                          <td className="p-2">{fmtQty(task.cache.in_work_quantity)}</td>
                          <td className="p-2">{fmtQty(task.cache.completed_quantity)}</td>
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
                              <Button size="sm" variant="outline" onClick={() => openActionDialog("issue", task)}>
                                Выдать
                              </Button>
                              <Button size="sm" variant="outline" onClick={() => openActionDialog("complete", task)}>
                                <Clock size={14} />
                                <span className="ml-1">Факт</span>
                              </Button>
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() => openActionDialog("send", task)}
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
              )}
            </div>

            {stats && (
              <div className="rounded-lg border p-4">
                <h3 className="text-sm font-semibold mb-3">Статистика по дням</h3>
                <div className="overflow-auto">
                  <table className="w-full text-sm">
                    <thead className="border-b bg-muted/50">
                      <tr>
                        <th className="text-left p-2">Дата</th>
                        <th className="text-left p-2">Факт</th>
                        <th className="text-left p-2">Брак</th>
                        <th className="text-left p-2">Операций</th>
                        <th className="text-left p-2">Ср. задержка учета</th>
                      </tr>
                    </thead>
                    <tbody>
                      {stats.daily_stats.map((row: DailyStatsRow) => (
                        <tr key={row.date} className="border-b">
                          <td className="p-2">{row.date}</td>
                          <td className="p-2">{fmtQty(row.good_quantity)}</td>
                          <td className="p-2">{parseFloat(row.rejected_quantity) > 0 ? <span className="text-red-600 font-medium">{fmtQty(row.rejected_quantity)}</span> : fmtQty(row.rejected_quantity)}</td>
                          <td className="p-2">{row.op_count}</td>
                          <td className="p-2">
                            {(() => {
                              const delaySec = parseFloat(row.avg_accounting_delay_seconds);
                              if (!Number.isFinite(delaySec) || delaySec === 0) return "—";
                              const min = Math.floor(delaySec / 60);
                              const sec = Math.round(delaySec % 60);
                              return `${min}м ${sec}с`;
                            })()}
                          </td>
                        </tr>
                      ))}
                      {stats.daily_stats.length === 0 && (
                        <tr>
                          <td colSpan={5} className="p-4 text-center text-muted-foreground">Нет данных за период</td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </>
        )}
      </section>

      <Dialog
        open={actionDialog.open}
        onOpenChange={(open) => {
          if (!open) {
            setActionDialog({ open: false, type: "complete", task: null });
          }
        }}
      >
        <DialogContent className="sm:max-w-[560px]">
          <DialogHeader>
            <DialogTitle>{actionTitle(actionDialog.type)}</DialogTitle>
            <DialogDescription>
              {actionDialog.task?.operation_name} — Этап #{actionDialog.task?.sequence}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div>
              <label className="text-sm font-medium">
                {actionDialog.type === "complete" ? "Факт (годные)" : "Количество"}
              </label>
              <Input type="number" step="0.001" value={actionQty} onChange={(e) => setActionQty(e.target.value)} />
            </div>

            {actionDialog.type === "complete" && (
              <div>
                <label className="text-sm font-medium">Брак</label>
                <Input type="number" step="0.001" value={defectQty} onChange={(e) => setDefectQty(e.target.value)} />
              </div>
            )}

            {actionDialog.type === "send" && (
              <div className="text-xs text-muted-foreground">
                Следующий этап: {actionDialog.task?.next_operation_name || "—"}
              </div>
            )}

            <div>
              <label className="text-sm font-medium">Время сдачи</label>
              <Input type="datetime-local" value={performedAt} onChange={(e) => handlePerformedAtChange(e.target.value)} />
            </div>

            <div className="flex items-center gap-2">
              <Checkbox checked={timesMatch} onCheckedChange={(c) => handleTimesMatchChange(!!c)} id="times-match-action" />
              <label htmlFor="times-match-action" className="text-sm">Время сдачи = Время учета</label>
            </div>

            <div>
              <label className="text-sm font-medium">Время учета</label>
              <Input type="datetime-local" value={accountedAt} onChange={(e) => setAccountedAt(e.target.value)} disabled={timesMatch} />
            </div>

            <div>
              <label className="text-sm font-medium">Комментарий</label>
              <Input value={actionComment} onChange={(e) => setActionComment(e.target.value)} placeholder="Опционально" />
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <Button variant="outline" onClick={() => setActionDialog({ open: false, type: "complete", task: null })}>
                Отмена
              </Button>
              <Button onClick={submitAction} disabled={pendingMutation}>
                {pendingMutation ? "Сохранение..." : "Сохранить"}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
