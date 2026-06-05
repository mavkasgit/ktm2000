import { useState } from "react";
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
} from "@/shared/ui";
import { listSections } from "@/shared/api/sections";
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

function fmtQty(value: string | number | null | undefined): string {
  if (value == null) return "0";
  const n = parseFloat(String(value));
  if (!Number.isFinite(n)) return "0";
  return String(Math.round(n));
}

function conflictHintFromTransferError(message: string): string | null {
  const normalized = message.toLowerCase();
  if (normalized.includes("exceeds transferable")) {
    return "Количество больше доступного к передаче.";
  }
  if (normalized.includes("next route step")) {
    return "Передавать можно только на следующий этап маршрута.";
  }
  if (normalized.includes("must be sent")) {
    return "Передача уже обработана. Обновите список входящих.";
  }
  if (normalized.includes("accepted + rejected exceeds sent")) {
    return "Сумма принятого и отклонённого превышает отправленное количество.";
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
  const [sectionId, setSectionId] = useState<number | null>(null);
  const [sendTask, setSendTask] = useState<ReadyToTransferTask | null>(null);
  const [editTransferRecord, setEditTransferRecord] = useState<IncomingTransfer | null>(null);

  const { data: sections } = useQuery({
    queryKey: ["sections"],
    queryFn: listSections,
  });

  const activeSectionId = sectionId ?? sections?.find((s) => s.is_active)?.id ?? null;

  const { data: readyData, isLoading: readyLoading, refetch: refetchReady } = useQuery({
    queryKey: ["transfers-ready", activeSectionId],
    queryFn: () => listReadyToTransfer({ section_id: activeSectionId }),
    enabled: activeSectionId != null,
  });

  const { data: historyData, isLoading: historyLoading, refetch: refetchHistory } = useQuery({
    queryKey: ["transfers-history", activeSectionId],
    queryFn: () => (activeSectionId != null ? listTransferHistory(activeSectionId) : null),
    enabled: activeSectionId != null,
  });

  const readyItems = readyData?.items ?? [];
  const historyItems = historyData?.transfers ?? [];

  function handleRefresh() {
    void refetchReady();
    void refetchHistory();
  }

  const handleCancelTransfer = async (id: number, transferNo: string) => {
    if (!confirm(`Вы действительно хотите аннулировать передачу ${transferNo}? Это вернет остатки в исходное состояние.`)) {
      return;
    }
    try {
      await cancelTransfer(id);
      toast({ variant: "success", title: "Передача отменена", description: `Запись ${transferNo} успешно аннулирована` });
      void queryClient.invalidateQueries({ queryKey: ["transfers-ready"] });
      void queryClient.invalidateQueries({ queryKey: ["transfers-history"] });
    } catch (err) {
      const msg = getErrorMessage(err);
      toast({ variant: "destructive", title: "Ошибка отмены", description: msg });
    }
  };

  return (
    <div className="p-6 space-y-6 max-w-screen-2xl">
      <header className="page-header">
        <div>
          <h1 className="page-title">Передачи между SPG</h1>
          <p className="page-subtitle">
            Отдельный процесс передачи завершённых заданий на следующий SPG по маршруту.
            В разделе «Готово к передаче» — задания текущего участка, у которых есть
            фактически выполненное количество, ожидающее отправки.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={sectionId ?? ""}
            onChange={(e) => setSectionId(e.target.value ? Number(e.target.value) : null)}
            className="border rounded-md px-3 py-2 text-sm bg-background"
            aria-label="Участок"
          >
            <option value="">Текущий участок</option>
            {sections?.map((s) => (
              <option key={s.id} value={s.id}>
                {s.code} — {s.name}
              </option>
            ))}
          </select>
          <Button variant="outline" size="sm" onClick={handleRefresh}>
            <RefreshCw className="h-4 w-4 mr-1" /> Обновить
          </Button>
        </div>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="flex items-center gap-2">
              <Send className="h-4 w-4" />
              Готово к передаче
              {readyItems.length > 0 && <Badge variant="secondary">{readyItems.length}</Badge>}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {readyLoading ? (
              <div className="text-sm text-muted-foreground py-4 text-center">Загрузка…</div>
            ) : readyItems.length === 0 ? (
              <div className="text-sm text-muted-foreground py-6 text-center">
                Нет заданий, готовых к передаче. Завершите работу на участке, чтобы появились задания
                с доступным к передаче количеством.
              </div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Задание</TableHead>
                    <TableHead>Артикул</TableHead>
                    <TableHead>Этап</TableHead>
                    <TableHead className="text-right">К передаче</TableHead>
                    <TableHead>Следующий</TableHead>
                    <TableHead />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {readyItems.map((t) => (
                    <TableRow key={t.task_id}>
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
                      <TableCell>
                        <Button
                          size="sm"
                          disabled={!t.has_next_step}
                          onClick={() => setSendTask(t)}
                        >
                          Передать
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
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
                Нет записей в журнале передач для выбранного участка.
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
                    const isIncoming = t.to_section_id === activeSectionId;
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
                          <Badge variant={isCancelled ? "destructive" : "outline"}>
                            {isCancelled ? "Аннулирована" : "Принята"}
                          </Badge>
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
                              <Button
                                size="sm"
                                variant="destructive"
                                onClick={() => handleCancelTransfer(t.transfer_id, t.transfer_no)}
                              >
                                Отменить
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
            void queryClient.invalidateQueries({ queryKey: ["transfers-ready"] });
            void queryClient.invalidateQueries({ queryKey: ["transfers-history"] });
          }}
        />
      )}

      {editTransferRecord && (
        <EditTransferDialog
          transfer={editTransferRecord}
          onClose={() => setEditTransferRecord(null)}
          onSuccess={() => {
            setEditTransferRecord(null);
            void queryClient.invalidateQueries({ queryKey: ["transfers-ready"] });
            void queryClient.invalidateQueries({ queryKey: ["transfers-history"] });
          }}
        />
      )}
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

  const mutation = useMutation({
    mutationFn: () =>
      correctTransfer(transfer.transfer_id, {
        quantity,
        comment: comment || undefined,
      }),
    onSuccess: () => {
      toast({ variant: "success", title: "Количество изменено", description: `Передача ${transfer.transfer_no} успешно скорректирована` });
      onSuccess();
    },
    onError: (err: unknown) => {
      const message = getErrorMessage(err);
      setError(message);
    },
  });

  const oldQty = parseFloat(transfer.sent_quantity);
  const qtyNum = parseFloat(quantity || "0");
  const hasChanged = qtyNum !== oldQty;

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
              onClick={() => mutation.mutate()}
              disabled={mutation.isPending || qtyNum <= 0 || !hasChanged}
            >
              {mutation.isPending ? "Сохранение..." : "Сохранить"}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
