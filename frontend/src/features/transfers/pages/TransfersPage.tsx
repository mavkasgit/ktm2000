import { useState, useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Send, Inbox, RefreshCw, AlertCircle } from "lucide-react";

import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  Input,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  toast,
  SpgSelect,
  Checkbox,
} from "@/shared/ui";
import { getSpgList } from "@/shared/api/spg";
import {
  cancelTransfer,
  correctTransfer,
  createTransfer,
  listReadyToTransfer,
  listTransferHistory,
  type IncomingTransfer,
  type ReadyToTransferTask,
} from "@/shared/api/transfers";
import { getErrorMessage } from "@/shared/api/client";
import { queryKeys } from "@/shared/api/queryKeys";
import {
  useBulkSelection,
  BulkResultsDialog,
  summarizeBulkResults,
  type BulkActionResultItem,
  type BulkActionSummary,
  type BulkRunnerProgress,
} from "@/shared/bulk";

function fmtQty(value: string | number | null | undefined): string {
  if (value == null) return "0";
  const n = parseFloat(String(value));
  if (!Number.isFinite(n)) return "0";
  return String(Math.round(n));
}

function conflictHintFromTransferError(message: string): string | null {
  const n = message.toLowerCase();
  if (n.includes("превышает доступный к передаче")) {
    return "Количество больше доступного к передаче.";
  }
  if (n.includes("следующим этапом маршрута")) {
    return "Передавать можно только на следующий этап маршрута.";
  }
  if (n.includes("должна быть отправлена")) {
    return "Передача уже обработана. Обновите список входящих.";
  }
  if (n.includes("сумма принятого и отклонённого")) {
    return "Сумма принятого и отклонённого превышает отправленное количество.";
  }
  if (n.includes("превышает доступный к передаче объём исходной задачи")) {
    return "Скорректированное количество превышает доступный к передаче объём исходной задачи.";
  }
  if (n.includes("нельзя уменьшить передачу")) {
    return "Нельзя уменьшить передачу: целевая задача уже использовала материалы.";
  }
  return null;
}

function makeIdempotencyKey(prefix: string): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `${prefix}-${crypto.randomUUID()}`;
  }
  return `${prefix}-${Date.now()}-${Math.floor(Math.random() * 1_000_000)}`;
}

export function TransfersPage() {
  const queryClient = useQueryClient();
  const [spgId, setSpgId] = useState<number | null>(null);
  const [sendTask, setSendTask] = useState<ReadyToTransferTask | null>(null);
  const [editTransferRecord, setEditTransferRecord] = useState<IncomingTransfer | null>(null);

  // Bulk Operations State
  const [bulkMode, setBulkMode] = useState(false);
  const bulkSelection = useBulkSelection<number>();
  const [bulkProgress, setBulkProgress] = useState<BulkRunnerProgress | null>(null);
  const [bulkResults, setBulkResults] = useState<BulkActionResultItem<number>[]>([]);
  const [bulkSummary, setBulkSummary] = useState<BulkActionSummary | null>(null);
  const [bulkResultsOpen, setBulkResultsOpen] = useState(false);
  const [bulkSendOpen, setBulkSendOpen] = useState(false);
  const [bulkComment, setBulkComment] = useState("");

  const { data: spgs } = useQuery({
    queryKey: queryKeys.spg.list(),
    queryFn: getSpgList,
  });

  const activeSpgId = spgId ?? spgs?.find((s) => s.is_active)?.id ?? null;

  const { data: readyData, isLoading: readyLoading, refetch: refetchReady } = useQuery({
    queryKey: queryKeys.transfers.ready(activeSpgId),
    queryFn: () => listReadyToTransfer({ spg_id: activeSpgId }),
    enabled: activeSpgId != null,
  });

  const { data: historyData, isLoading: historyLoading, refetch: refetchHistory } = useQuery({
    queryKey: queryKeys.transfers.history(activeSpgId),
    queryFn: () => listTransferHistory({ spg_id: activeSpgId }),
    enabled: activeSpgId != null,
  });

  const readyItems = readyData?.items ?? [];
  const historyItems = historyData?.transfers ?? [];

  function handleRefresh() {
    void refetchReady();
    void refetchHistory();
  }

  function invalidateShopfloorCaches(fromSectionId: number | null, toSectionId: number | null) {
    const sectionIds = new Set<number>();
    if (fromSectionId != null) sectionIds.add(fromSectionId);
    if (toSectionId != null && toSectionId !== fromSectionId) sectionIds.add(toSectionId);
    sectionIds.forEach((sid) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.shopfloor.board(sid) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.shopfloor.stats(sid) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.shopfloor.incomingTransfers(sid) });
    });
    void queryClient.invalidateQueries({ queryKey: queryKeys.shopfloor.summary() });
    void queryClient.invalidateQueries({ queryKey: queryKeys.sections.all() });
  }

  function invalidateTransfersCaches() {
    void queryClient.invalidateQueries({ queryKey: queryKeys.transfers.ready(activeSpgId) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.transfers.history(activeSpgId) });
  }

  const exitBulkMode = useCallback(() => {
    bulkSelection.clear();
    setBulkMode(false);
  }, [bulkSelection]);

  const handleBulkTransferSubmit = useCallback(async (comment: string) => {
    const selectedTasks = readyItems.filter(t => bulkSelection.isSelected(t.task_id));
    if (selectedTasks.length === 0) return;

    setBulkSendOpen(false);
    setBulkProgress({ total: selectedTasks.length, completed: 0, running: true });

    const results: BulkActionResultItem<number>[] = [];
    let completedCount = 0;

    const actionResults = [];
    for (const task of selectedTasks) {
      try {
        await createTransfer({
          from_task_id: task.task_id,
          to_task_id: undefined,
          quantity: task.transferable_quantity,
          comment: comment.trim() || undefined,
          idempotency_key: makeIdempotencyKey(`transfer-send-bulk-${task.task_id}`),
        });

        completedCount++;
        setBulkProgress(prev => prev ? { ...prev, completed: completedCount } : null);

        actionResults.push({
          id: task.task_id,
          status: "success" as const,
          label: `Задание #${task.task_id} (${task.product_sku ?? "—"})`,
        });
      } catch (err) {
        completedCount++;
        setBulkProgress(prev => prev ? { ...prev, completed: completedCount } : null);

        actionResults.push({
          id: task.task_id,
          status: "failed" as const,
          reason: getErrorMessage(err),
          label: `Задание #${task.task_id} (${task.product_sku ?? "—"})`,
        });
      }
    }

    results.push(...actionResults);

    setBulkProgress(null);

    const summary = summarizeBulkResults(results);
    setBulkResults(results);
    setBulkSummary(summary);

    const sectionPairs = new Set<string>();
    selectedTasks.forEach(task => {
      sectionPairs.add(`${task.section_id}-${task.next_section_id}`);
    });

    sectionPairs.forEach(pair => {
      const [fromId, toId] = pair.split("-").map(Number);
      invalidateShopfloorCaches(fromId, toId);
    });

    invalidateTransfersCaches();

    toast({
      title: summary.failed > 0 ? "Частичный успех" : "Передача выполнена",
      description: `Успешно отправлено ${summary.success} из ${summary.total} перемещений`,
      variant: summary.failed > 0 ? "destructive" : "success",
    });

    if (summary.failed > 0 || summary.skipped > 0) {
      setBulkResultsOpen(true);
    }

    bulkSelection.clear();
    setBulkMode(false);
  }, [readyItems, bulkSelection, invalidateShopfloorCaches, invalidateTransfersCaches]);

  if (spgs !== undefined && spgs.length === 0) {
    return (
      <div className="p-6 text-center">
        <h1 className="text-xl font-semibold mb-2">Передачи между ГХП</h1>
        <p className="text-muted-foreground">В системе нет зарегистрированных групп хранения и производства (ГХП).</p>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6 max-w-screen-2xl">
      <header className="page-header">
        <div>
          <h1 className="page-title">Передачи между ГХП</h1>
          <p className="page-subtitle">
            Отдельный процесс передачи завершённых заданий на следующую ГХП по маршруту.
            В разделе «Готово к передаче» — задания текущего участка, у которых есть
            фактически выполненное количество, ожидающее отправки.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <SpgSelect
            spgs={spgs ?? []}
            value={spgId}
            onValueChange={(val) => {
              setSpgId(val);
              setSendTask(null);
              setEditTransferRecord(null);
              bulkSelection.clear();
              setBulkMode(false);
            }}
            placeholder="Выберите ГХП"
            emptyLabel="Выберите ГХП"
            className="w-[260px] bg-background h-10 border text-sm"
          />
          <Button variant="outline" size="sm" onClick={handleRefresh}>
            <RefreshCw className="h-4 w-4 mr-1" /> Обновить
          </Button>
        </div>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
            <CardTitle className="flex items-center gap-2">
              <Send className="h-4 w-4" />
              Готово к передаче
              {readyItems.length > 0 && <Badge variant="secondary">{readyItems.length}</Badge>}
            </CardTitle>
            {readyItems.length > 0 && (
              <Button
                variant={bulkMode ? "default" : "outline"}
                size="sm"
                onClick={() => {
                  if (bulkMode) {
                    exitBulkMode();
                  } else {
                    setBulkMode(true);
                  }
                }}
              >
                Групповые операции
              </Button>
            )}
          </CardHeader>
          <CardContent>
            {bulkMode && (
              <div className="mb-4 p-2 bg-muted/40 rounded-lg flex items-center justify-between border border-dashed">
                <span className="text-sm font-medium">Выбрано: {bulkSelection.selectedCount}</span>
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    disabled={bulkSelection.selectedCount === 0}
                    onClick={() => {
                      setBulkSendOpen(true);
                    }}
                  >
                    Передать выбранные
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => bulkSelection.clear()}
                  >
                    Сбросить
                  </Button>
                </div>
              </div>
            )}

            {readyLoading ? (
              <div className="text-sm text-muted-foreground py-4 text-center">Загрузка…</div>
            ) : readyItems.length === 0 ? (
              <div className="text-sm text-muted-foreground py-6 text-center">
                Нет заданий, готовых к передаче на участках выбранной ГХП. Завершите работу на этапе, чтобы появились задания
                с доступным к передаче количеством.
              </div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    {bulkMode && (
                      <TableHead className="w-[40px] p-2">
                        <Checkbox
                          checked={bulkSelection.isAllSelected(readyItems.map(t => t.task_id))}
                          onCheckedChange={(checked) => {
                            if (checked) {
                              bulkSelection.selectAll(readyItems.map(t => t.task_id));
                            } else {
                              bulkSelection.clear();
                            }
                          }}
                        />
                      </TableHead>
                    )}
                    <TableHead>Задание</TableHead>
                    <TableHead>Артикул</TableHead>
                    <TableHead>Этап</TableHead>
                    <TableHead className="text-right">К передаче</TableHead>
                    <TableHead>Следующий</TableHead>
                    {!bulkMode && <TableHead />}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {readyItems.map((t) => {
                    const isSelected = bulkSelection.isSelected(t.task_id);
                    return (
                      <TableRow
                        key={t.task_id}
                        className={bulkMode ? "cursor-pointer hover:bg-muted/50" : undefined}
                        onClick={bulkMode ? () => bulkSelection.selectOne(t.task_id) : undefined}
                      >
                        {bulkMode && (
                          <TableCell className="w-[40px] p-2" onClick={(e) => e.stopPropagation()}>
                            <Checkbox
                              checked={isSelected}
                              onCheckedChange={() => bulkSelection.selectOne(t.task_id)}
                            />
                          </TableCell>
                        )}
                        <TableCell className="font-mono text-xs">#{t.task_id}</TableCell>
                        <TableCell>{t.product_sku ?? "—"}</TableCell>
                        <TableCell>
                          <div className="text-xs">
                            <div className="font-medium">{t.operation_name ?? "—"}</div>
                            <div className="text-muted-foreground">#{t.sequence}</div>
                          </div>
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {fmtQty(t.transferable_quantity)}
                          <div className="text-[10px] text-muted-foreground">
                            из {fmtQty(t.planned_quantity)} план
                          </div>
                        </TableCell>
                        <TableCell className="text-xs">
                          {t.has_next_step ? (
                            <>
                              <div>{t.next_operation_name ?? "—"}</div>
                              <div className="text-muted-foreground">
                                {t.next_section_code ?? "—"} #{t.next_step_sequence ?? "—"}
                              </div>
                            </>
                          ) : (
                            <Badge variant="outline">Финальный</Badge>
                          )}
                        </TableCell>
                        {!bulkMode && (
                          <TableCell>
                            <Button
                              size="sm"
                              disabled={!t.has_next_step}
                              onClick={() => setSendTask(t)}
                            >
                              Передать
                            </Button>
                          </TableCell>
                        )}
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="flex items-center gap-2">
              <Inbox className="h-4 w-4" />
              Журнал передач
              {historyItems.length > 0 && <Badge variant="secondary">{historyItems.length}</Badge>}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {historyLoading ? (
              <div className="text-sm text-muted-foreground py-4 text-center">Загрузка…</div>
            ) : historyItems.length === 0 ? (
              <div className="text-sm text-muted-foreground py-6 text-center">
                Нет записей в журнале передач для выбранной ГХП.
              </div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Направление</TableHead>
                    <TableHead>№</TableHead>
                    <TableHead>Контрагент</TableHead>
                    <TableHead>Артикул</TableHead>
                    <TableHead className="text-right">Количество</TableHead>
                    <TableHead>Статус</TableHead>
                    <TableHead />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {historyItems.map((t) => {
                    const activeSpg = spgs?.find((s) => s.id === activeSpgId);
                    const sectionIdsInSpg = new Set(activeSpg?.sections.map((sec) => sec.section_id) ?? []);
                    const isIncoming = sectionIdsInSpg.has(t.to_section_id);
                    const isCancelled = t.status === "cancelled";
                    return (
                      <TableRow key={t.transfer_id} className={isCancelled ? "opacity-60" : ""}>
                        <TableCell>
                          <Badge variant={isIncoming ? "default" : "secondary"}>
                            {isIncoming ? "Входящая" : "Исходящая"}
                          </Badge>
                        </TableCell>
                        <TableCell className="font-mono text-xs">{t.transfer_no}</TableCell>
                        <TableCell>
                          <div className="text-xs">
                            <div className="font-medium">
                              {isIncoming ? t.from_section_name : t.to_section_name}
                            </div>
                            <div className="text-muted-foreground">
                              {isIncoming ? t.from_operation_name : t.to_operation_name}
                            </div>
                          </div>
                        </TableCell>
                        <TableCell className="text-xs font-medium">{t.product_sku}</TableCell>
                        <TableCell className="text-right tabular-nums font-semibold">
                          {fmtQty(t.sent_quantity)}
                        </TableCell>
                        <TableCell>
                          <div className="flex flex-col items-start gap-1">
                            <Badge variant={isCancelled ? "destructive" : "outline"}>
                              {isCancelled ? "Аннулирована" : "Принята"}
                            </Badge>
                            {t.is_post_factum && (
                              <Badge
                                variant="secondary"
                                className="bg-amber-100 text-amber-800"
                                title={
                                  t.physical_handover_at
                                    ? `Физически передано: ${new Date(t.physical_handover_at).toLocaleString("ru-RU")}`
                                    : "Постфактум-передача"
                                }
                              >
                                Постфактум
                              </Badge>
                            )}
                          </div>
                        </TableCell>
                        <TableCell>
                          {!isCancelled && (
                            <div className="flex gap-1 justify-end">
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() => setEditTransferRecord(t)}
                              >
                                Изменить
                              </Button>
                            </div>
                          )}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </div>

      {sendTask && (
        <CreateTransferDialog
          task={sendTask}
          onClose={() => setSendTask(null)}
          onSuccess={() => {
            setSendTask(null);
            invalidateShopfloorCaches(sendTask.section_id, sendTask.next_section_id);
            invalidateTransfersCaches();
          }}
        />
      )}

      {editTransferRecord && (
        <EditTransferDialog
          transfer={editTransferRecord}
          onClose={() => setEditTransferRecord(null)}
          onSuccess={() => {
            setEditTransferRecord(null);
            invalidateShopfloorCaches(editTransferRecord.from_section_id, editTransferRecord.to_section_id);
            invalidateTransfersCaches();
          }}
        />
      )}

      {bulkSendOpen && (
        <CreateBulkTransferDialog
          selectedTasks={readyItems.filter(t => bulkSelection.isSelected(t.task_id))}
          onClose={() => setBulkSendOpen(false)}
          onSubmit={handleBulkTransferSubmit}
        />
      )}

      <BulkResultsDialog
        open={bulkResultsOpen}
        onOpenChange={setBulkResultsOpen}
        title="Результаты групповой передачи"
        summary={bulkSummary}
        results={bulkResults}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Create transfer dialog
// ---------------------------------------------------------------------------

function CreateTransferDialog({
  task,
  onClose,
  onSuccess,
}: {
  task: ReadyToTransferTask;
  onClose: () => void;
  onSuccess: () => void;
}) {
  const [quantity, setQuantity] = useState(task.transferable_quantity);
  const [comment, setComment] = useState("");
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      createTransfer({
        from_task_id: task.task_id,
        to_task_id: undefined,
        quantity,
        comment: comment || undefined,
        idempotency_key: makeIdempotencyKey(`transfer-send-${task.task_id}`),
      }),
    onSuccess: () => {
      toast({ variant: "success", title: "Передача создана", description: `Задание #${task.task_id} отправлено` });
      onSuccess();
    },
    onError: (err: unknown) => {
      const message = getErrorMessage(err);
      const hint = conflictHintFromTransferError(message);
      setError(hint ?? message);
    },
  });

  const maxQty = parseFloat(task.transferable_quantity);
  const qtyNum = parseFloat(quantity || "0");
  const overLimit = qtyNum > maxQty;

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Передать на следующий этап</DialogTitle>
          <DialogDescription>
            {task.operation_name ?? "—"} — Этап #{task.sequence}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div className="rounded-lg border bg-muted/20 p-3 text-xs grid grid-cols-2 gap-2">
            <div>
              План: <span className="font-medium">{fmtQty(task.planned_quantity)}</span>
            </div>
            <div>
              К передаче: <span className="font-medium">{fmtQty(task.transferable_quantity)}</span>
            </div>
            <div className="col-span-2">
              Следующий этап:{" "}
              <span className="font-medium">
                {task.next_operation_name ?? "—"} ({task.next_section_code ?? "—"} #
                {task.next_step_sequence ?? "—"})
              </span>
            </div>
          </div>

          <div>
            <label className="text-sm font-medium">Количество</label>
            <Input
              type="number"
              step="1"
              min="0"
              value={quantity}
              onChange={(e) => {
                setQuantity(e.target.value);
                setError(null);
              }}
            />
            <div className="mt-2 flex flex-wrap gap-1">
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => setQuantity(task.transferable_quantity)}
              >
                Максимум
              </Button>
            </div>
            {overLimit && (
              <div className="mt-1 text-xs text-red-600 flex items-center gap-1">
                <AlertCircle className="h-3 w-3" /> Больше доступного к передаче
              </div>
            )}
          </div>

          <div>
            <label className="text-sm font-medium">Комментарий</label>
            <Input
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder="Опционально"
            />
          </div>

          {error && (
            <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-800">
              {error}
            </div>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={onClose}>
              Отмена
            </Button>
            <Button
              onClick={() => mutation.mutate()}
              disabled={mutation.isPending || overLimit || qtyNum <= 0}
            >
              {mutation.isPending ? "Отправка..." : "Отправить"}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Edit transfer dialog
// ---------------------------------------------------------------------------

function EditTransferDialog({
  transfer,
  onClose,
  onSuccess,
}: {
  transfer: IncomingTransfer;
  onClose: () => void;
  onSuccess: () => void;
}) {
  const [quantity, setQuantity] = useState(transfer.sent_quantity);
  const [comment, setComment] = useState(transfer.comment || "");
  const [error, setError] = useState<string | null>(null);

  const oldQty = parseFloat(transfer.sent_quantity);
  const qtyNum = parseFloat(quantity || "0");
  const hasChanged = qtyNum !== oldQty;

  const mutation = useMutation({
    mutationFn: () => {
      if (qtyNum === 0) {
        return cancelTransfer(transfer.transfer_id);
      }
      return correctTransfer(transfer.transfer_id, {
        quantity,
        comment: comment || undefined,
      });
    },
    onSuccess: () => {
      if (qtyNum === 0) {
        toast({
          variant: "success",
          title: "Передача отменена",
          description: `Передача ${transfer.transfer_no} успешно аннулирована`,
        });
      } else {
        toast({
          variant: "success",
          title: "Количество изменено",
          description: `Передача ${transfer.transfer_no} успешно скорректирована`,
        });
      }
      onSuccess();
    },
    onError: (err: unknown) => {
      const message = getErrorMessage(err);
      setError(message);
    },
  });

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Корректировка количества: {transfer.transfer_no}</DialogTitle>
          <DialogDescription>
            Изменение объема передаваемых деталей между участками.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div className="rounded-lg border bg-muted/20 p-3 text-xs grid grid-cols-2 gap-2">
            <div>
              Отправитель: <span className="font-medium">{transfer.from_section_name}</span>
            </div>
            <div>
              Получатель: <span className="font-medium">{transfer.to_section_name}</span>
            </div>
            <div className="col-span-2">
              Продукт: <span className="font-medium">{transfer.product_sku}</span>
            </div>
            <div className="col-span-2">
              Текущее количество: <span className="font-medium">{fmtQty(transfer.sent_quantity)}</span>
            </div>
          </div>

          <div>
            <label className="text-sm font-medium">Новое количество</label>
            <Input
              type="number"
              step="1"
              min="0"
              value={quantity}
              onChange={(e) => {
                setQuantity(e.target.value);
                setError(null);
              }}
            />
            {qtyNum === 0 && (
              <div className="mt-1.5 text-xs text-amber-600 flex items-center gap-1 bg-amber-50 p-2 rounded border border-amber-200">
                <AlertCircle className="h-3.5 w-3.5 flex-shrink-0" />
                <span>Установка количества в 0 приведет к отмене (аннулированию) передачи.</span>
              </div>
            )}
          </div>

          <div>
            <label className="text-sm font-medium">Причина изменения / Комментарий</label>
            <Input
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder="Укажите причину корректировки"
            />
          </div>

          {error && (
            <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-800">
              {error}
            </div>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={onClose}>
              Отмена
            </Button>
            <Button
              onClick={() => {
                if (qtyNum === 0 && !confirm(`Вы действительно хотите аннулировать передачу ${transfer.transfer_no}? Это вернет остатки в исходное состояние.`)) {
                  return;
                }
                mutation.mutate();
              }}
              disabled={mutation.isPending || qtyNum < 0 || !hasChanged}
            >
              {mutation.isPending ? "Сохранение..." : "Сохранить"}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Create bulk transfer dialog
// ---------------------------------------------------------------------------

function CreateBulkTransferDialog({
  selectedTasks,
  onClose,
  onSubmit,
}: {
  selectedTasks: ReadyToTransferTask[];
  onClose: () => void;
  onSubmit: (comment: string) => void;
}) {
  const [comment, setComment] = useState("");

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Групповая передача на следующий этап</DialogTitle>
          <DialogDescription>
            Будет отправлено {selectedTasks.length} заданий на соответствующие следующие этапы маршрутов.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="max-h-[200px] overflow-y-auto rounded-lg border p-3 bg-muted/20 text-xs space-y-2">
            {selectedTasks.map((task) => (
              <div key={task.task_id} className="flex justify-between border-b pb-1 last:border-b-0 last:pb-0">
                <div>
                  <span className="font-mono font-medium">#{task.task_id}</span> ({task.product_sku})
                  <div className="text-muted-foreground">
                    {task.operation_name} &rarr; {task.next_operation_name}
                  </div>
                </div>
                <div className="text-right font-medium">
                  {fmtQty(task.transferable_quantity)} шт.
                </div>
              </div>
            ))}
          </div>

          <div>
            <label className="text-sm font-medium">Общий комментарий</label>
            <Input
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder="Опционально (применится ко всем передачам)"
            />
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={onClose}>
              Отмена
            </Button>
            <Button
              onClick={() => onSubmit(comment)}
              disabled={selectedTasks.length === 0}
            >
              Отправить все
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
