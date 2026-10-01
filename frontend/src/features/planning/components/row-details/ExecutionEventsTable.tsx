import { useMemo } from "react";
import { Badge, DataTableColumnHeader, TableCornerResetCell, TableCornerResetHeader, DATA_TABLE_STYLES } from "@/shared/ui";
import { useFilterableTable } from "@/shared/hooks/useFilterableTable";
import { fmtQty } from "@/shared/lib/quantityFormat";
import { getAriaSort } from "@/shared/lib/multiSort";
import { type ProductionPlanningStage, type StatusHistoryEntry } from "@/shared/api/productionPlans";
import { translateStatusHistoryReason } from "@/features/planning/lib/plan-labels";
import { statusLabels } from "@/shared/lib/generated-labels";
import {
  useTableQueryEngine,
  type ColumnSortDef,
} from "@/shared/hooks/useTableQueryEngine";

import { eventColumns, type EventField } from "./executionEventsColumns";

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
    const fromLabel = statusLabels[entry.from_status] || entry.from_status;
    const toLabel = statusLabels[entry.to_status] || entry.to_status;
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

function getCellValue(row: ExecutionEventRow, field: EventField): string {
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

const headerCellClass = `${DATA_TABLE_STYLES.headerRow} ${DATA_TABLE_STYLES.headerCell}`;

export function ExecutionEventsTable({ stages, statusHistory }: ExecutionEventsTableProps) {
  const {
    bindColumn,
    buildFilterPredicate,
    sortConfigs,
    handleSort: handleSortChange,
    hasActiveFilters,
    resetAll: handleResetFilters,
  } = useFilterableTable<EventField>();

  const eventRows = useMemo(
    () => buildEventRows(stages, statusHistory),
    [stages, statusHistory],
  );

  const sortDefs = useMemo((): ColumnSortDef<ExecutionEventRow, EventField>[] => [
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

  const filterPredicate = useMemo(
    () => buildFilterPredicate(getCellValue),
    [buildFilterPredicate],
  );

  const uniqueValues = useMemo((): Record<EventField, string[]> => ({
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
  }), [eventRows]);

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
    <div className={DATA_TABLE_STYLES.container}>
      <table className="w-full text-sm">
        <thead>
          <tr>
            {eventColumns.map((column) => (
              <th
                key={column.id}
                className={`${headerCellClass} ${column.headerClassName ?? ""}`}
                aria-sort={column.sortField ? getAriaSort(sortConfigs, column.sortField) : undefined}
              >
                <DataTableColumnHeader
                  column={column}
                  bindColumn={bindColumn}
                  values={column.filterField ? uniqueValues[column.filterField] : undefined}
                  currentSorts={sortConfigs}
                  onSortChange={handleSortChange}
                />
              </th>
            ))}
            <TableCornerResetHeader
              hasActiveFilters={hasActiveFilters}
              onReset={handleResetFilters}
              dataTableHeader
            />
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
              <TableCornerResetCell />
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
