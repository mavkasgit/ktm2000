import type { ExecutionSortField } from "./execution-utils";

export type ExecutionColumnId = ExecutionSortField | "actions";

export interface ExecutionTableColumn {
  id: ExecutionColumnId;
  label: string;
  width: string;
  sortField?: ExecutionSortField;
  hiddenWhenIdsHidden?: boolean;
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
    sortField: "id",
    hiddenWhenIdsHidden: true,
    colClassName: serviceColClass,
    headerClassName: serviceCellClass,
    cellClassName: `${serviceCellClass} font-mono text-muted-foreground`,
  },
  {
    id: "row",
    label: "№",
    width: "64px",
    sortField: "row",
    hiddenWhenIdsHidden: true,
    colClassName: serviceColClass,
    headerClassName: serviceCellClass,
    cellClassName: serviceCellClass,
  },
  {
    id: "plan",
    label: "План",
    width: "80px",
    sortField: "plan",
    hiddenWhenIdsHidden: true,
    colClassName: serviceColClass,
    headerClassName: serviceCellClass,
    cellClassName: serviceCellClass,
  },
  {
    id: "sku",
    label: "Артикул",
    width: "var(--execution-col-sku)",
    sortField: "sku",
    cellClassName: "font-mono",
  },
  {
    id: "qty",
    label: "Кол-во",
    width: "80px",
    sortField: "qty",
  },
  {
    id: "name",
    label: "Наименование",
    width: "auto",
    sortField: "name",
  },
  {
    id: "route",
    label: "Маршрут",
    width: "auto",
    sortField: "route",
    colClassName: "hidden min-[820px]:table-column",
    headerClassName: "hidden min-[820px]:table-cell",
    cellClassName: "hidden min-[820px]:table-cell",
  },
  {
    id: "status",
    label: "Статус",
    width: "var(--execution-col-status)",
    sortField: "status",
  },
  {
    id: "stage",
    label: "Этап",
    width: "var(--execution-col-stage)",
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

export function getExecutionTableColumns(hideColumnIds: boolean) {
  return executionTableColumns.filter((column) => !hideColumnIds || !column.hiddenWhenIdsHidden);
}
