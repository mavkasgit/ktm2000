import { useEffect, useState } from "react";
import {
  ArrowDown,
  ArrowUp,
  CheckCircle2,
  Circle,
  History as HistoryIcon,
  Loader2,
  Route as RouteIcon,
  X,
} from "lucide-react";

import { Badge, Button, Dialog, DialogContent, DialogHeader, DialogTitle } from "@/shared/ui";
import {
  getRemainderHistory,
  type RemainderHistoryResponse,
  type RemainderHistoryMovement,
} from "@/shared/api/spg";
import { spgI18n } from "@/shared/i18n/spg";

interface RemainderHistoryDrawerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  spgId: number;
  remainderId: number | null;
}

const MOVEMENT_TYPE_LABELS: Record<string, { label: string; color: string; icon: "in" | "out" | "other" }> = {
  issue_to_work: { label: "Выдано в работу", color: "text-amber-700", icon: "out" },
  complete: { label: "Выполнено", color: "text-emerald-700", icon: "in" },
  transfer_send: { label: "Передано дальше", color: "text-blue-700", icon: "out" },
  transfer_receive: { label: "Принято с предыдущего", color: "text-blue-700", icon: "in" },
  reject: { label: "Забраковано", color: "text-red-700", icon: "out" },
  scrap: { label: "Списано", color: "text-red-700", icon: "out" },
  return_to_previous: { label: "Возврат на предыдущий", color: "text-purple-700", icon: "out" },
  final_release: { label: "Финальный выпуск", color: "text-emerald-700", icon: "in" },
  adjustment: { label: "Корректировка", color: "text-gray-700", icon: "other" },
  return_to_stock: { label: "Возврат на склад", color: "text-purple-700", icon: "in" },
  manual_in: { label: "Ручной приход", color: "text-emerald-700", icon: "in" },
  manual_out: { label: "Ручной расход", color: "text-amber-700", icon: "out" },
};

const MOVEMENT_ICONS = {
  in: <ArrowDown className="h-3.5 w-3.5" />,
  out: <ArrowUp className="h-3.5 w-3.5" />,
  other: <Circle className="h-3.5 w-3.5" />,
};

function fmtNum(v: number): string {
  return v % 1 === 0 ? String(v) : v.toFixed(2);
}

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatActor(
  userId: number | null | undefined,
  userName: string | null | undefined,
): string {
  if (userId != null) return userName ?? `Пользователь #${userId}`;
  if (userName) return `Удалённый пользователь: ${userName}`;
  return "Система";
}

function MovementRow({ m }: { m: RemainderHistoryMovement }) {
  const meta = MOVEMENT_TYPE_LABELS[m.movement_type] || {
    label: m.movement_type,
    color: "text-muted-foreground",
    icon: "other" as const,
  };
  return (
    <div className="flex items-start gap-3 py-2 border-b last:border-b-0">
      <div className={`mt-0.5 ${meta.color}`}>{MOVEMENT_ICONS[meta.icon]}</div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className={`text-sm font-medium ${meta.color}`}>{meta.label}</span>
          <Badge variant="outline" className="text-xs">
            {fmtNum(m.quantity)}
          </Badge>
        </div>
        <div className="text-xs text-muted-foreground mt-0.5">
          {fmtDate(m.performed_at || m.created_at)}
        </div>
        <div className="text-xs text-muted-foreground mt-1 space-y-0.5">
          <p>
            <span className="font-medium">{spgI18n.ru.createdBy}:</span>{" "}
            {formatActor(m.created_by, m.created_by_user_name)}
          </p>
          {m.executor_user_id !== m.created_by && (
            <p>
              <span className="font-medium">{spgI18n.ru.executedBy}:</span>{" "}
              {formatActor(m.executor_user_id, m.executor_user_name)}
            </p>
          )}
        </div>
        {(m.reason || m.comment) && (
          <div className="text-xs text-muted-foreground mt-0.5 truncate">
            {[m.reason, m.comment].filter(Boolean).join(" · ")}
          </div>
        )}
      </div>
    </div>
  );
}

export function RemainderHistoryDrawer({
  open,
  onOpenChange,
  spgId,
  remainderId,
}: RemainderHistoryDrawerProps) {
  const [data, setData] = useState<RemainderHistoryResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open && remainderId != null) {
      setLoading(true);
      setError(null);
      getRemainderHistory(spgId, remainderId)
        .then(setData)
        .catch((e: unknown) => {
          const msg = e && typeof e === "object" && "response" in e
            ? (e as { response?: { data?: { detail?: string } } }).response?.data?.detail
            : undefined;
          setError(msg || "Не удалось загрузить историю");
        })
        .finally(() => setLoading(false));
    } else if (!open) {
      setData(null);
      setError(null);
    }
  }, [open, spgId, remainderId]);

  const isNegative = data && data.remainder.remainder_quantity < 0;
  const isManual = data?.remainder.source === "manual";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="!left-auto !right-0 !top-0 !translate-x-0 !translate-y-0 h-screen max-h-screen w-[min(100vw,640px)] max-w-none rounded-none border-l p-0 flex flex-col gap-0">
        <div className="p-6 border-b flex items-start justify-between gap-4">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <HistoryIcon className="h-5 w-5" />
              История остатка
            </DialogTitle>
            {data && (
              <div className="text-sm text-muted-foreground mt-2">
                <div className="font-medium text-foreground">
                  {data.remainder.product_sku} — {data.remainder.product_name}
                </div>
                {data.remainder.section_name ? (
                  <div className="text-xs">
                    Участок: {data.remainder.section_code} — {data.remainder.section_name}
                  </div>
                ) : (
                  <div className="text-xs">
                    ГХП: {data.remainder.spg_name}
                  </div>
                )}
              </div>
            )}
          </DialogHeader>
          <Button variant="ghost" size="sm" onClick={() => onOpenChange(false)}>
            <X className="h-4 w-4" />
          </Button>
        </div>

        <div className="flex-1 overflow-auto p-6 space-y-6">
          {loading && (
            <div className="flex items-center gap-2 py-8 justify-center text-muted-foreground">
              <Loader2 className="h-5 w-5 animate-spin" />
              Загрузка истории...
            </div>
          )}

          {error && (
            <div className="text-sm text-destructive p-3 bg-destructive/10 rounded-md">
              {error}
            </div>
          )}

          {data && !loading && (
            <>
              {/* Summary card */}
              <div className="rounded-lg border bg-muted/20 p-4 space-y-2">
                <div className="grid grid-cols-2 gap-3 text-sm">
                  <div>
                    <div className="text-muted-foreground text-xs">Остаток</div>
                    <div className={`font-semibold text-lg ${isNegative ? "text-amber-700" : ""}`}>
                      {fmtNum(data.remainder.remainder_quantity)}
                      {isNegative && (
                        <Badge variant="destructive" className="ml-2 text-xs">
                          в минусе
                        </Badge>
                      )}
                    </div>
                  </div>
                  <div>
                    <div className="text-muted-foreground text-xs">Исходно</div>
                    <div className="font-semibold text-lg">{fmtNum(data.remainder.original_issued)}</div>
                  </div>
                  <div>
                    <div className="text-muted-foreground text-xs">Источник</div>
                    <div>
                      <Badge variant={isManual ? "default" : "secondary"} className="text-xs">
                        {isManual ? "Ручной" : "Из задачи"}
                      </Badge>
                    </div>
                  </div>
                  <div>
                    <div className="text-muted-foreground text-xs">Создан</div>
                    <div className="text-xs">{fmtDate(data.remainder.created_at)}</div>
                  </div>
                </div>
                {data.remainder.consumed_at && (
                  <div className="text-xs text-muted-foreground pt-2 border-t">
                    Использован: {fmtDate(data.remainder.consumed_at)}
                  </div>
                )}
                <div className="text-xs text-muted-foreground pt-2 border-t">
                  {spgI18n.ru.createdBy}: {formatActor(data.remainder.created_by, data.remainder.created_by_user_name)}
                </div>
              </div>

              {/* Origin */}
              {data.origin && (
                <div className="rounded-lg border p-4 space-y-2">
                  <div className="flex items-center gap-2">
                    <Badge variant="outline" className="text-xs">Источник</Badge>
                    <span className="text-sm font-medium">Задача #{data.origin.task_id}</span>
                    <Badge variant="secondary" className="text-xs">
                      {data.origin.task_status}
                    </Badge>
                  </div>
                  <div className="grid grid-cols-2 gap-2 text-xs text-muted-foreground">
                    <div>Операция: <span className="text-foreground">{data.origin.operation_name ?? "—"}</span></div>
                    <div>Этап: <span className="text-foreground">#{data.origin.sequence ?? "—"}</span></div>
                    <div>Запланировано: <span className="text-foreground">{fmtNum(data.origin.planned_quantity)}</span></div>
                    <div>Выдано: <span className="text-foreground">{fmtNum(data.origin.issued_quantity)}</span></div>
                    <div>Выполнено: <span className="text-foreground">{fmtNum(data.origin.completed_quantity)}</span></div>
                    <div>В работе: <span className="text-foreground">{fmtNum(data.origin.in_work_quantity)}</span></div>
                  </div>
                </div>
              )}

              {/* Route */}
              {data.route && (
                <div className="rounded-lg border p-4 space-y-3">
                  <div className="flex items-center gap-2">
                    <RouteIcon className="h-4 w-4 text-blue-600" />
                    <span className="text-sm font-medium">{data.route.route_name}</span>
                    {data.route.route_code && (
                      <Badge variant="outline" className="text-xs">{data.route.route_code}</Badge>
                    )}
                  </div>
                  <div className="space-y-1">
                    {data.route.steps.map((s) => {
                      const isCompleted = s.sequence <= data.route!.current_sequence;
                      const isCurrent = s.sequence === data.route!.current_sequence;
                      return (
                        <div
                          key={s.sequence}
                          className={`flex items-center gap-2 text-xs rounded px-2 py-1.5 ${
                            isCurrent
                              ? "bg-blue-50 border border-blue-200"
                              : isCompleted
                              ? "bg-emerald-50/50"
                              : "text-muted-foreground"
                          }`}
                        >
                          {isCompleted ? (
                            <CheckCircle2 className={`h-3.5 w-3.5 ${isCurrent ? "text-blue-600" : "text-emerald-600"}`} />
                          ) : (
                            <Circle className="h-3.5 w-3.5" />
                          )}
                          <span className="font-mono text-xs text-muted-foreground w-6">
                            #{s.sequence}
                          </span>
                          <span className="font-medium">{s.section_code}</span>
                          <span className="text-muted-foreground">·</span>
                          <span>{s.operation_name}</span>
                          {s.is_final && (
                            <Badge variant="outline" className="text-[10px] ml-auto">финал</Badge>
                          )}
                          {isCurrent && (
                            <Badge variant="default" className="text-[10px] ml-auto">текущий</Badge>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Consumed by */}
              {data.consumed_by && (
                <div className="rounded-lg border border-blue-200 bg-blue-50/50 p-3 text-sm space-y-1">
                  <div className="font-medium text-blue-900">Использован задачей #{data.consumed_by.task_id}</div>
                  <div className="text-xs text-blue-700">
                    {data.consumed_by.operation_name ?? "—"} · этап #{data.consumed_by.sequence ?? "—"} · {data.consumed_by.task_status}
                  </div>
                </div>
              )}

              {/* Completed stages */}
              {data.completed_stages.length > 0 && (
                <div className="rounded-lg border p-4 space-y-2">
                  <div className="text-sm font-medium">Пройденные этапы</div>
                  <div className="flex flex-wrap gap-1">
                    {data.completed_stages.map((s, idx) => (
                      <Badge key={idx} variant="secondary" className="text-xs">
                        #{s.sequence} {s.operation_name}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}

              {/* Movements timeline */}
              <div className="rounded-lg border">
                <div className="px-4 py-2 border-b bg-muted/30 text-sm font-medium">
                  История движений ({data.movements.length})
                </div>
                <div className="px-4 py-2 max-h-[400px] overflow-auto">
                  {data.movements.length === 0 ? (
                    <div className="text-sm text-muted-foreground py-4 text-center">
                      Движений не найдено
                    </div>
                  ) : (
                    data.movements.map((m) => <MovementRow key={m.id} m={m} />)
                  )}
                </div>
              </div>
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
