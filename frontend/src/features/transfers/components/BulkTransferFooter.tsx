import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Send, X } from "lucide-react";

import { useAuth } from "@/features/auth/hooks/useAuth";
import { listUsers } from "@/shared/api/users";
import type { ReadyToTransferTask } from "@/shared/api/transfers";
import {
  Button,
  DatePicker,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/shared/ui";
import { cn } from "@/shared/utils/cn";
import type { BulkRunnerProgress } from "@/shared/bulk";

function fmtQty(value: string | number | null | undefined): string {
  if (value == null) return "0";
  const n = parseFloat(String(value));
  if (!Number.isFinite(n)) return "0";
  return String(Math.round(n));
}

function nowLocalDateParts(): string {
  const d = new Date();
  const p = (v: number) => String(v).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

function isPastDate(dateStr: string): boolean {
  if (!dateStr) return false;
  const today = nowLocalDateParts();
  return dateStr < today;
}

export type BulkTransferSubmitData = {
  comment: string;
  executorUserId: number;
  performedAt: string;
  physicalHandoverAt?: string;
  postFactum: boolean;
};

interface BulkTransferFooterProps {
  selectedTasks: ReadyToTransferTask[];
  onSubmit: (data: BulkTransferSubmitData) => void;
  onExit: () => void;
  onClearSelection: () => void;
  pending: boolean;
  progress: BulkRunnerProgress | null;
}

export function BulkTransferFooter({
  selectedTasks,
  onSubmit,
  onExit,
  onClearSelection,
  pending,
  progress,
}: BulkTransferFooterProps) {
  const { user: me } = useAuth();
  const [performedDate, setPerformedDate] = useState(nowLocalDateParts);
  const [performedShift, setPerformedShift] = useState<"1" | "2">("1");
  const [executorUserId, setExecutorUserId] = useState<string>("");
  const [comment, setComment] = useState("");

  const isAdmin = me?.role === "admin";

  const { data: allUsers } = useQuery({
    queryKey: ["users", "list"],
    queryFn: listUsers,
    enabled: isAdmin,
    staleTime: 60_000,
  });

  const executorOptions = useMemo(() => {
    if (isAdmin && allUsers?.length) {
      return allUsers
        .filter((u) => u.is_active)
        .map((u) => ({ id: u.id, label: u.full_name || u.username }));
    }
    if (me) {
      return [{ id: me.id, label: me.full_name || me.username }];
    }
    return [];
  }, [isAdmin, allUsers, me]);

  useEffect(() => {
    if (executorUserId) return;
    if (me?.id) setExecutorUserId(String(me.id));
  }, [me?.id, executorUserId]);

  const totalQty = useMemo(
    () => selectedTasks.reduce((sum, t) => sum + (parseFloat(t.transferable_quantity) || 0), 0),
    [selectedTasks],
  );

  const running = Boolean(progress?.running);
  const canSubmit = selectedTasks.length > 0 && executorUserId && !pending && !running;

  const handleConfirm = () => {
    if (!canSubmit) return;

    const shiftTime = performedShift === "1" ? "08:00" : "20:00";
    const performedAt = `${performedDate}T${shiftTime}`;
    const postFactum = isPastDate(performedDate);

    onSubmit({
      comment: comment.trim(),
      executorUserId: Number(executorUserId),
      performedAt,
      physicalHandoverAt: postFactum ? performedAt : undefined,
      postFactum,
    });
  };

  return (
    <div className="fixed inset-x-0 bottom-0 z-40 border-t bg-background/95 backdrop-blur shadow-[0_-4px_24px_rgba(0,0,0,0.08)]">
      <div className="w-full px-6 py-4">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div className="min-w-0 flex-1 space-y-2">
            <div className="flex items-center gap-2">
              <Send className="h-4 w-4 text-primary shrink-0" />
              <span className="text-sm font-semibold">Групповая передача</span>
              <span className="text-sm text-muted-foreground">
                Выбрано: {selectedTasks.length} · {fmtQty(totalQty)} шт.
              </span>
            </div>

            {selectedTasks.length > 0 ? (
              <div className="max-h-24 overflow-y-auto rounded-md border bg-muted/30 p-2 text-xs space-y-1">
                {selectedTasks.map((task) => (
                  <div key={task.task_id} className="flex justify-between gap-3 border-b border-border/50 pb-1 last:border-0 last:pb-0">
                    <div className="min-w-0 truncate">
                      <span className="font-mono font-medium">#{task.task_id}</span>{" "}
                      <span className="text-muted-foreground">{task.product_sku}</span>
                      <span className="text-muted-foreground hidden sm:inline">
                        {" "}· {task.operation_name ?? "—"} → {task.next_operation_name ?? "—"}
                      </span>
                    </div>
                    <span className="shrink-0 font-medium tabular-nums">
                      {fmtQty(task.transferable_quantity)} шт.
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                Отметьте задания в таблице «Готово к передаче», чтобы отправить их на следующий этап.
              </p>
            )}
          </div>

          <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end lg:shrink-0">
            <DatePicker
              value={performedDate}
              onChange={setPerformedDate}
              label="Дата передачи"
              disabled={pending || running}
            />

            <div className="flex flex-col gap-1.5">
              <span className="text-sm font-medium">Смена</span>
              <div className="flex h-10 gap-1 rounded-md bg-muted p-0.5 items-center">
                {(["1", "2"] as const).map((shift) => (
                  <button
                    key={shift}
                    type="button"
                    disabled={pending || running}
                    onClick={() => setPerformedShift(shift)}
                    className={cn(
                      "px-3 h-8 text-sm font-medium rounded transition-all flex items-center justify-center",
                      performedShift === shift
                        ? "bg-background text-foreground shadow-sm"
                        : "text-muted-foreground hover:text-foreground",
                    )}
                  >
                    {shift === "1" ? "1-я" : "2-я"}
                  </button>
                ))}
              </div>
            </div>

            <div className="flex flex-col gap-1.5 min-w-[180px]">
              <span className="text-sm font-medium">Исполнитель</span>
              <Select
                value={executorUserId}
                onValueChange={setExecutorUserId}
                disabled={pending || running || executorOptions.length === 0}
              >
                <SelectTrigger className="h-10">
                  <SelectValue placeholder="Выберите исполнителя" />
                </SelectTrigger>
                <SelectContent>
                  {executorOptions.map((opt) => (
                    <SelectItem key={opt.id} value={String(opt.id)}>
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="flex flex-col gap-1.5 min-w-[200px]">
              <span className="text-sm font-medium">Комментарий</span>
              <Input
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                placeholder="Необязательно"
                disabled={pending || running}
                className="h-10"
              />
            </div>

            <div className="flex items-center gap-2 self-end">
              {running && progress && (
                <span className="text-xs text-muted-foreground whitespace-nowrap">
                  {progress.completed}/{progress.total}
                </span>
              )}
              <Button
                variant="outline"
                size="sm"
                onClick={onClearSelection}
                disabled={pending || running || selectedTasks.length === 0}
              >
                Сбросить
              </Button>
              <Button
                size="sm"
                onClick={handleConfirm}
                disabled={!canSubmit}
              >
                {pending || running ? "Отправка..." : `Передать все (${selectedTasks.length})`}
              </Button>
              <Button variant="ghost" size="sm" onClick={onExit} disabled={running}>
                <X className="h-4 w-4 mr-1" />
                Выйти
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}