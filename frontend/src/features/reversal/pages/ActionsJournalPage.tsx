import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  AMENDABLE_ACTION_TYPES,
  type ActionStatus,
  type JournalAction,
} from "@/shared/api/actions";
import { queryKeys } from "@/shared/api/queryKeys";
import {
  Badge,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  TablePaginationFooter,
} from "@/shared/ui";
import { usePaginatedTableQuery } from "@/shared/hooks/usePaginatedTableQuery";
import { useActionsList } from "../hooks/useActions";
import { JournalRowOperations } from "../components/JournalRowOperations";

const STATUS_BADGE: Record<
  ActionStatus,
  { label: string; variant: "success" | "secondary" | "warning" }
> = {
  active: { label: "Активно", variant: "success" },
  reversed: { label: "Отменено", variant: "secondary" },
  amended: { label: "Изменено", variant: "warning" },
};

function formatDateTime(value: string | null) {
  if (!value) return "—";
  const d = new Date(value);
  if (isNaN(d.getTime())) return value;
  return d.toLocaleString("ru-RU");
}

export function ActionsJournalPage() {
  const [typeFilter, setTypeFilter] = useState<string>("all");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const { page, setPage, limit, setLimit, limitOptions, totalPages, rangeLabel } =
    usePaginatedTableQuery({
      resetPageDeps: [typeFilter, statusFilter],
    });
  const queryClient = useQueryClient();

  const params = {
    page,
    page_size: limit,
    action_type: typeFilter === "all" ? null : typeFilter,
    status: statusFilter === "all" ? null : (statusFilter as ActionStatus),
  };
  const { data, isLoading } = useActionsList(params);

  const items = data?.items ?? [];
  const total = data?.total ?? 0;

  const refresh = () => {
    // Список журнала и деревья цепочки: инвалидируем оба префикса ключей.
    void queryClient.invalidateQueries({ queryKey: queryKeys.actions.all });
    void queryClient.invalidateQueries({
      queryKey: queryKeys.actions.tree(0).slice(0, -1),
    });
  };

  // Известные типы действий для фильтра: текущая страница + базовый набор.
  const knownTypes = Array.from(
    new Set([
      ...AMENDABLE_ACTION_TYPES,
      ...items.map((i: JournalAction) => i.action_type),
    ]),
  ).sort();

  return (
    <div className="space-y-4 p-6" data-testid="actions-journal-page">
      <div>
        <h1 className="text-xl font-bold text-slate-800">Отмена действий</h1>
        <p className="text-sm text-slate-500">
          Журнал обратимых операций (ADR-0019)
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <Select value={typeFilter} onValueChange={setTypeFilter}>
          <SelectTrigger className="w-56" data-testid="filter-type">
            <SelectValue placeholder="Тип действия" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Все типы</SelectItem>
            {knownTypes.map((t) => (
              <SelectItem key={t} value={t}>
                {t}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select value={statusFilter} onValueChange={setStatusFilter}>
          <SelectTrigger className="w-44" data-testid="filter-status">
            <SelectValue placeholder="Статус" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Все статусы</SelectItem>
            <SelectItem value="active">Активно</SelectItem>
            <SelectItem value="reversed">Отменено</SelectItem>
            <SelectItem value="amended">Изменено</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
        <table className="w-full border-separate border-spacing-0 text-sm">
          <thead>
            <tr className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
              <th className="px-3 py-2">ID</th>
              <th className="px-3 py-2">Действие</th>
              <th className="px-3 py-2">Объект</th>
              <th className="px-3 py-2">Инициатор</th>
              <th className="px-3 py-2">Статус</th>
              <th className="px-3 py-2">Создано</th>
              <th className="px-3 py-2 text-right">Операции</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {isLoading && items.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-3 py-6 text-center text-slate-400">
                  Загрузка…
                </td>
              </tr>
            ) : items.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-3 py-6 text-center text-slate-400">
                  Действия не найдены
                </td>
              </tr>
            ) : (
              items.map((action: JournalAction) => (
                <tr key={action.id} data-testid={`action-row-${action.id}`}>
                  <td className="px-3 py-2 font-mono">{action.id}</td>
                  <td className="px-3 py-2 font-medium">{action.action_type}</td>
                  <td className="px-3 py-2">
                    {action.ref_id != null ? `#${action.ref_id}` : "—"}
                  </td>
                  <td className="px-3 py-2">{action.actor ?? "—"}</td>
                  <td className="px-3 py-2">
                    <Badge variant={STATUS_BADGE[action.status].variant}>
                      {STATUS_BADGE[action.status].label}
                    </Badge>
                  </td>
                  <td className="px-3 py-2">{formatDateTime(action.created_at)}</td>
                  <td className="px-3 py-2 text-right">
                    <JournalRowOperations action={action} onChanged={refresh} />
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>

        <TablePaginationFooter
          page={page}
          totalPages={totalPages(total)}
          total={total}
          shownCount={items.length}
          limit={limit}
          limitOptions={[...limitOptions]}
          onPageChange={setPage}
          onLimitChange={setLimit}
          rangeLabel={rangeLabel(items.length, total)}
        />
      </div>
    </div>
  );
}
