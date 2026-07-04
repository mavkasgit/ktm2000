import { useCallback, useMemo, useState } from "react";
import { Badge, SortableFilterHeader } from "@/shared/ui";
import { fmtQty } from "@/shared/utils/fmtQty";
import { type ProductionPlanningStage, type StatusHistoryEntry } from "@/shared/api/productionPlans";
import { translateStatusHistoryReason } from "@/features/planning/lib/plan-labels";
import {
  useTableQueryEngine,
  type SortConfig,
  type ColumnSortDef,
} from "@/shared/hooks/useTableQueryEngine";
import { nextMultiSortConfigs } from "@/shared/lib/multiSort";

const positionStatusLabels: Record<string, string> = {
  draft: "Черновик",
  invalid: "Ошибка",
  valid: "Валиден",
  approved: "Утверждён",
  released: "Запущен",
  cancelled: "Отменён",
  completed: "Завершён",
};

type EventSortField = "date" | "type" | "event" | "from" | "to" | "quantity";

export type ExecutionEventRow = {
  id: string;
  event_at: string | null;
  event_type: "status" | "operation";
  event_type_label: string;
  label: string;
  from_section_name: string;
  to_section_name: string;
  quantity: string;
  details: string;
};

interface ExecutionEventsTableProps {
  stages: ProductionPlanningStage[];
  statusHistory: StatusHistoryEntry[];
}

function fmtEventAt(value: string | null | undefined): string {
  if (!value) return "—";
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return "—";
  return dt.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function buildEventRows(
  stages: ProductionPlanningStage[],
  statusHistory: StatusHistoryEntry[],
): ExecutionEventRow[] {
  const rows: ExecutionEventRow[] = [];

  for (const entry of statusHistory) {
    const fromLabel = positionStatusLabels[entry.from_status] || entry.from_status;
    const toLabel = positionStatusLabels[entry.to_status] || entry.to_status;
    rows.push({
      id: `status-${entry.id}`,
      event_at: entry.changed_at,
      event_type: "status",
      event_type_label: "Статус",
      label: `${fromLabel} → ${toLabel}`,
      from_section_name: "—",
      to_section_name: "—",
      quantity: "—",
      details: translateStatusHistoryReason(entry.reason),
    });
  }

  for (const stage of stages) {
    const stageName = stage.section_name || stage.section_code || "—";
    for (const [idx, event] of stage.flow_events.entries()) {
      const details: string[] = [];
      if (event.manual_route_pass) details.push("ручной пропуск");
      if (event.task_id) details.push(`задача #${event.task_id}`);
      if (event.transfer_id) details.push(`передача #${event.transfer_id}`);

      const isTransfer = event.step === "transfer";
      rows.push({
        id: event.transfer_id ? `op-transfer-${event.transfer_id}` : `op-${stage.route_step_id}-${idx}`,
        event_at: event.event_at,
        event_type: "operation",
        event_type_label: "Операция",
        label: event.label,
        from_section_name: event.from_section_name ?? (isTransfer ? "—" : stageName),
        to_section_name: event.to_section_name ?? "—",
        quantity: fmtQty(event.quantity),
        details: details.length > 0 ? details.join(" · ") : "—",
      });
    }
  }

  rows.sort((a, b) => {
    const aTime = a.event_at ? new Date(a.event_at).getTime() : 0;
    const bTime = b.event_at ? new Date(b.event_at).getTime() : 0;
    return bTime - aTime;
  });

  return rows;
}

function getCellValue(row: ExecutionEventRow, field: EventSortField): string {
  switch (field) {
    case "date":
      return fmtEventAt(row.event_at);
    case "type":
      return row.event_type_label;
    case "event":
      return row.label;
    case "from":
      return row.from_section_name;
    case "to":
      return row.to_section_name;
    case "quantity":
      return row.quantity;
  }
}

export function ExecutionEventsTable({ stages, statusHistory }: ExecutionEventsTableProps) {
  const [sortConfigs, setSortConfigs] = useState<SortConfig<EventSortField>[]>([]);
  const [columnFilters, setColumnFilters] = useState<Partial<Record<EventSortField, Set<string>>>>({});

  const eventRows = useMemo(
    () => buildEventRows(stages, statusHistory),
    [stages, statusHistory],
  );

  const handleSortChange = useCallback((field: EventSortField) => {
    setSortConfigs((prev) => nextMultiSortConfigs(prev, field));
  }, []);

  const handleColumnFilterChange = useCallback((field: EventSortField, selected: Set<string>) => {
    setColumnFilters((prev) => ({ ...prev, [field]: selected }));
  }, []);

  const sortDefs = useMemo((): ColumnSortDef<ExecutionEventRow, EventSortField>[] => [
    {
      field: "date",
      getSortValue: (row) => (row.event_at ? new Date(row.event_at).getTime() : 0),
    },
    { field: "type", getSortValue: (row) => row.event_type_label },
    { field: "event", getSortValue: (row) => row.label },
    { field: "from", getSortValue: (row) => row.from_section_name },
    { field: "to", getSortValue: (row) => row.to_section_name },
    {
      field: "quantity",
      getSortValue: (row) => (row.quantity === "—" ? 0 : Number.parseFloat(row.quantity) || 0),
    },
  ], []);

  const filterPredicate = useMemo(() => {
    const hasFilters = Object.values(columnFilters).some((selected) => selected && selected.size > 0);
    if (!hasFilters) return null;
    return (row: ExecutionEventRow) => {
      for (const [field, selected] of Object.entries(columnFilters)) {
        if (selected && selected.size > 0) {
          const cellValue = getCellValue(row, field as EventSortField);
          if (!selected.has(cellValue)) return false;
        }
      }
      return true;
    };
  }, [columnFilters]);

  const uniqueValues = useMemo(
    () => ({
      date: [...new Set(eventRows.map((row) => getCellValue(row, "date")))].sort((a, b) =>
        a.localeCompare(b, "ru"),
      ),
      type: [...new Set(eventRows.map((row) => getCellValue(row, "type")))].sort((a, b) =>
        a.localeCompare(b, "ru"),
      ),
      event: [...new Set(eventRows.map((row) => getCellValue(row, "event")))].sort((a, b) =>
        a.localeCompare(b, "ru"),
      ),
      from: [...new Set(eventRows.map((row) => getCellValue(row, "from")))].sort((a, b) =>
        a.localeCompare(b, "ru"),
      ),
      to: [...new Set(eventRows.map((row) => getCellValue(row, "to")))].sort((a, b) =>
        a.localeCompare(b, "ru"),
      ),
      quantity: [...new Set(eventRows.map((row) => getCellValue(row, "quantity")))].sort(
        (a, b) => (Number.parseFloat(a) || 0) - (Number.parseFloat(b) || 0),
      ),
    }),
    [eventRows],
  );

  const { rows: filteredRows } = useTableQueryEngine({
    rows: eventRows,
    getId: (row) => row.id,
    searchQuery: "",
    filterPredicate,
    sortConfigs,
    sortDefs,
  });

  if (eventRows.length === 0) {
    return (
      <p className="p-4 text-sm text-muted-foreground text-center border rounded-lg">
        События отсутствуют
      </p>
    );
  }

  return (
    <div className="rounded-lg border overflow-auto">
      <table className="w-full text-sm">
        <thead className="border-b bg-muted/50">
          <tr>
            <th className="text-left p-2">
              <SortableFilterHeader
                field="date"
                label="Дата"
                currentSorts={sortConfigs}
                onSortChange={handleSortChange}
                values={uniqueValues.date}
                selectedValues={columnFilters.date ?? new Set()}
                onFilterChange={handleColumnFilterChange}
              />
            </th>
            <th className="text-left p-2">
              <SortableFilterHeader
                field="type"
                label="Тип"
                currentSorts={sortConfigs}
                onSortChange={handleSortChange}
                values={uniqueValues.type}
                selectedValues={columnFilters.type ?? new Set()}
                onFilterChange={handleColumnFilterChange}
              />
            </th>
            <th className="text-left p-2">
              <SortableFilterHeader
                field="event"
                label="Событие"
                currentSorts={sortConfigs}
                onSortChange={handleSortChange}
                values={uniqueValues.event}
                selectedValues={columnFilters.event ?? new Set()}
                onFilterChange={handleColumnFilterChange}
              />
            </th>
            <th className="text-left p-2">
              <SortableFilterHeader
                field="from"
                label="Откуда"
                currentSorts={sortConfigs}
                onSortChange={handleSortChange}
                values={uniqueValues.from}
                selectedValues={columnFilters.from ?? new Set()}
                onFilterChange={handleColumnFilterChange}
              />
            </th>
            <th className="text-left p-2">
              <SortableFilterHeader
                field="to"
                label="Куда"
                currentSorts={sortConfigs}
                onSortChange={handleSortChange}
                values={uniqueValues.to}
                selectedValues={columnFilters.to ?? new Set()}
                onFilterChange={handleColumnFilterChange}
              />
            </th>
            <th className="text-left p-2">
              <SortableFilterHeader
                field="quantity"
                label="Кол-во"
                currentSorts={sortConfigs}
                onSortChange={handleSortChange}
                values={uniqueValues.quantity}
                selectedValues={columnFilters.quantity ?? new Set()}
                onFilterChange={handleColumnFilterChange}
              />
            </th>
            <th className="text-left p-2">Детали</th>
          </tr>
        </thead>
        <tbody>
          {filteredRows.map((row) => (
            <tr key={row.id} className="border-b">
              <td className="p-2 align-top whitespace-nowrap">{fmtEventAt(row.event_at)}</td>
              <td className="p-2 align-top">
                <Badge variant={row.event_type === "status" ? "secondary" : "outline"} className="text-xs">
                  {row.event_type_label}
                </Badge>
              </td>
              <td className="p-2 align-top">
                <span className="font-medium">{row.label}</span>
              </td>
              <td className="p-2 align-top">{row.from_section_name}</td>
              <td className="p-2 align-top">{row.to_section_name}</td>
              <td className="p-2 align-top">{row.quantity === "—" ? "—" : `${row.quantity} шт.`}</td>
              <td className="p-2 align-top text-muted-foreground text-xs">{row.details}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}