import { useCallback, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Send, X } from "lucide-react";

import { useAuth } from "@/features/auth/hooks/useAuth";
import { listUsers, type UserListItem } from "@/shared/api/users";
import type { ReadyToTransferTask } from "@/shared/api/transfers";
import { Button, ActionWithReason, BulkActionBar, DatePicker } from "@/shared/ui";
import type { BulkRunnerProgress } from "@/shared/bulk";
import { fmtQty } from "@/shared/lib/quantityFormat";
import type { ActionReasonCode } from "@/shared/lib/actionReasons";
import { enteredTransferQuantity } from "../lib/runTransferBatch";

function nowLocalDateParts(): string {
  const d = new Date();
  const p = (v: number) => String(v).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

function isPastDate(dateStr: string): boolean {
  if (!dateStr) return false;
  return dateStr < nowLocalDateParts();
}

type ExecutorProfile = {
  id?: number | null;
  full_name?: string | null;
  username?: string | null;
  is_break_glass?: boolean;
};

export function resolveDefaultExecutorId(
  me: ExecutorProfile | null,
  allUsers: UserListItem[] | undefined,
): number | null {
  if (!me || me.id == null) return null;
  if (!me.is_break_glass) return me.id;

  return allUsers?.find((user) => user.is_active && user.username === "system")?.id ?? null;
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
  /**
   * Введённые оператором количества по строкам (ключ — `readyRowIdentity`).
   * Итог «к передаче» считается по ним: оператор видит в футере то число,
   * которое набрал в строке. Строки без записи идут своим `transferable`.
   */
  quantities: Record<string, string>;
  onSubmit: (data: BulkTransferSubmitData) => void;
  /** Выход из массового режима — кнопка «Отмена» (и Escape). */
  onCancel: () => void;
  pending: boolean;
  progress: BulkRunnerProgress | null;
}

export function BulkTransferFooter({
  selectedTasks,
  quantities,
  onSubmit,
  onCancel,
  pending,
  progress,
}: BulkTransferFooterProps) {
  const { user: me } = useAuth();
  const [performedDate, setPerformedDate] = useState(nowLocalDateParts);

  const isAdmin = me?.role === "admin";

  const { data: allUsers } = useQuery({
    queryKey: ["users", "list"],
    queryFn: listUsers,
    enabled: isAdmin,
    staleTime: 60_000,
  });

  /**
   * Исполнителя форма не спрашивает (запрос владельца: «пока не нужно») —
   * подставляется тот же дефолт, что раньше предлагался списком: сам оператор,
   * а под аварийным доступом — служебный пользователь `system`.
   */
  const defaultExecutorId = resolveDefaultExecutorId(me, allUsers);

  const quantityOf = useCallback(
    (task: ReadyToTransferTask): string => enteredTransferQuantity(task, quantities),
    [quantities],
  );

  /**
   * Строки, которые реально уедут: с нулём отправлять нечего. Раскладка группы
   * оставляет нули в хвосте (введено меньше суммы) — это не ошибка ввода, и
   * держать из-за них всю пачку незачем: нулевые строки просто не входят.
   */
  const sendableTasks = useMemo(
    () => selectedTasks.filter((task) => (parseFloat(quantityOf(task)) || 0) > 0),
    [selectedTasks, quantityOf],
  );

  const totalQty = useMemo(
    () => sendableTasks.reduce((sum, task) => sum + (parseFloat(quantityOf(task)) || 0), 0),
    [sendableTasks, quantityOf],
  );

  const running = Boolean(progress?.running);
  const canSubmit =
    sendableTasks.length > 0 && defaultExecutorId != null && !pending && !running;
  /**
   * Причина, по которой «Передать все» не нажимается (#193). Временные
   * состояния (`pending`, `running`) причиной не считаются: о них говорит
   * надпись на кнопке.
   */
  const submitBlockReason: ActionReasonCode | null =
    pending || running
      ? null
      : selectedTasks.length === 0
        ? "no_tasks_selected"
        : sendableTasks.length === 0
          ? "zero_quantity"
          : defaultExecutorId != null
            ? null
            : "no_executor";

  const handleConfirm = () => {
    if (!canSubmit || defaultExecutorId == null) return;

    // Смену форма не спрашивает (запрос владельца): время — начало первой смены
    // выбранного дня, прошедший день уходит пост-фактумом.
    const performedAt = `${performedDate}T08:00`;
    const postFactum = isPastDate(performedDate);

    onSubmit({
      // Комментарий форма не собирает — та же причина.
      comment: "",
      executorUserId: defaultExecutorId,
      performedAt,
      physicalHandoverAt: postFactum ? performedAt : undefined,
      postFactum,
    });
  };

  return (
    <BulkActionBar
      summary={
        <div className="flex items-center justify-center gap-2 lg:justify-start">
          <Send className="h-4 w-4 text-primary shrink-0" />
          <span className="text-sm font-semibold">Групповая передача</span>
          <span className="text-sm text-muted-foreground">
            К передаче: {fmtQty(totalQty)} шт.
          </span>
        </div>
      }
      actions={
        <>
          {running && progress && (
            <span className="text-xs text-muted-foreground whitespace-nowrap">
              {progress.completed}/{progress.total}
            </span>
          )}
          {/* «Отмена» — тот же выход из массового режима, что и Escape:
              «Сбросить» и «Выйти» делали по половине этого действия (снять
              выделение / выйти), и обе кнопки читались как «что-то не то».
              Как на доске участка: одна «Отмена» рядом с подтверждением. */}
          <Button variant="outline" onClick={onCancel} disabled={running}>
            Отмена
          </Button>
          <ActionWithReason reason={submitBlockReason} layout="row">
            <Button onClick={handleConfirm} disabled={!canSubmit}>
              {pending || running ? "Отправка..." : `Передать все (${sendableTasks.length})`}
            </Button>
          </ActionWithReason>
        </>
      }
    >
      <DatePicker
        value={performedDate}
        onChange={setPerformedDate}
        label="Дата передачи"
        disabled={pending || running}
      />
    </BulkActionBar>
  );
}