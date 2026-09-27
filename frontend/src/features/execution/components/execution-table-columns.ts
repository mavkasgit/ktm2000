import type { ExecutionSortableField } from "../lib/executionSortMapping";
import { formatDimensionsFilterValue } from "@/shared/api/stock";
import type { ColumnSpec } from "@/shared/lib/columnSpecs";
import { positionStatusLabels, type ExecutionSortField } from "./execution-utils";

export type ExecutionColumnId = ExecutionSortField | "actions";

export interface ExecutionTableColumn extends ColumnSpec<ExecutionSortField, ExecutionSortableField> {
  id: ExecutionColumnId;
  label: string;
  width: string;
  colClassName?: string;
  headerClassName?: string;
  cellClassName?: string;
}

const serviceColClass = "hidden min-[1400px]:table-column";
const serviceCellClass = "hidden min-[1400px]:table-cell";

export const executionTableColumns: ExecutionTableColumn[] = [
  {
    id: "id",
    label: "ID",
    width: "64px",
    filterField: "id",
    colClassName: serviceColClass,
    headerClassName: serviceCellClass,
    cellClassName: `${serviceCellClass} font-mono text-muted-foreground`,
  },
  {
    id: "row",
    label: "№ / План",
    width: "110px",
    filterField: "row",
    sortField: "row",
    colClassName: serviceColClass,
    headerClassName: serviceCellClass,
    cellClassName: serviceCellClass,
  },
  {
    id: "sku",
    label: "Артикул",
    width: "minmax(120px, 1fr)",
    filterField: "sku",
    sortField: "sku",
    cellClassName: "font-mono",
  },
  {
    id: "qty",
    label: "Кол-во",
    width: "var(--execution-col-qty)",
    filterField: "qty",
    sortField: "qty",
  },
  {
    id: "dimensions",
    label: "Размер",
    width: "110px",
    filterField: "dimensions",
    sortField: "dimensions",
    // «Размер» — выбор габарита из списка, а не поиск подстроки в подписи.
    exactMatch: true,
    valueLabel: formatDimensionsFilterValue,
    colClassName: "hidden min-[600px]:table-column",
    headerClassName: "hidden min-[600px]:table-cell",
    cellClassName: "hidden min-[600px]:table-cell",
  },
  {
    id: "name",
    label: "Наименование",
    width: "auto",
    filterField: "name",
  },
  {
    id: "route",
    label: "Маршрут",
    width: "minmax(160px, 1.2fr)",
    filterField: "route",
    colClassName: "hidden min-[820px]:table-column",
    headerClassName: "hidden min-[820px]:table-cell",
    cellClassName: "hidden min-[820px]:table-cell",
  },
  {
    id: "status",
    label: "Статус",
    width: "var(--execution-col-status)",
    filterField: "status",
    sortField: "status",
    valueLabel: (value: string) => positionStatusLabels[value] ?? value,
  },
  {
    id: "stage",
    label: "Этап",
    width: "var(--execution-col-stage)",
    filterField: "stage",
    sortField: "stage",
    colClassName: "hidden min-[700px]:table-column",
    headerClassName: "hidden min-[700px]:table-cell",
    cellClassName: "hidden min-[700px]:table-cell",
  },
  {
    id: "actions",
    label: "Действия",
    width: "var(--execution-col-actions)",
  },
];

export function getExecutionTableColumns() {
  return executionTableColumns;
}
