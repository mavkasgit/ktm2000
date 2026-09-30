import { DATA_TABLE_STYLES } from "@/shared/lib/dataTableStyles";
import { cn } from "@/shared/utils/cn";
import { TableHeaderResetCell } from "./TableHeaderResetCell";

/** Узкая колонка сброса в правом верхнем углу таблицы. */
export const TABLE_CORNER_RESET_TH_CLASS = "w-10 min-w-[2.5rem] p-1 text-right align-middle";
export const TABLE_CORNER_RESET_TD_CLASS = "w-10 min-w-[2.5rem] p-1";

export interface TableCornerResetHeaderProps {
  hasActiveFilters: boolean;
  onReset: () => void;
  className?: string;
  /** Стили шапки DATA_TABLE_STYLES (execution, plan и т.п.). */
  dataTableHeader?: boolean;
}

export function TableCornerResetHeader({
  hasActiveFilters,
  onReset,
  className,
  dataTableHeader = false,
}: TableCornerResetHeaderProps) {
  return (
    <th
      className={cn(
        dataTableHeader && DATA_TABLE_STYLES.headerRow,
        dataTableHeader && DATA_TABLE_STYLES.headerCell,
        TABLE_CORNER_RESET_TH_CLASS,
        className,
      )}
    >
      <TableHeaderResetCell hasActiveFilters={hasActiveFilters} onReset={onReset} />
    </th>
  );
}

export function TableCornerResetCell({ className }: { className?: string }) {
  return <td className={cn(TABLE_CORNER_RESET_TD_CLASS, className)} />;
}
