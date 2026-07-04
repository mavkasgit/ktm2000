import { X } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/shared/utils/cn";
import { Button } from "./Button";

export interface TableHeaderResetCellProps {
  hasActiveFilters: boolean;
  onReset: () => void;
  label?: ReactNode;
  className?: string;
}

function ResetIconButton({
  onClick,
  hasActiveFilters,
  className,
}: {
  onClick: () => void;
  hasActiveFilters: boolean;
  className?: string;
}) {
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      className={cn(
        "h-6 w-6 shrink-0 rounded-md transition-colors",
        hasActiveFilters
          ? "bg-black text-white hover:bg-black/90 hover:text-white dark:bg-foreground dark:text-background dark:hover:bg-foreground/90"
          : "text-muted-foreground/45 hover:text-muted-foreground hover:bg-black/[0.04] dark:hover:bg-white/[0.06]",
        className,
      )}
      onClick={onClick}
      title="Сбросить фильтры"
      aria-label="Сбросить фильтры"
    >
      <X className="h-3 w-3" strokeWidth={hasActiveFilters ? 2.5 : 1.75} />
    </Button>
  );
}

/** Кнопка сброса фильтров, встроенная в ячейку шапки таблицы (обычно «Действия»). */
export function TableHeaderResetCell({
  hasActiveFilters,
  onReset,
  label,
  className,
}: TableHeaderResetCellProps) {
  if (!label) {
    return (
      <div className={cn("flex justify-end", className)}>
        <ResetIconButton hasActiveFilters={hasActiveFilters} onClick={onReset} />
      </div>
    );
  }

  return (
    <div className={cn("flex items-center justify-between gap-1 min-w-0", className)}>
      <span className="text-xs font-medium text-muted-foreground truncate">{label}</span>
      <ResetIconButton hasActiveFilters={hasActiveFilters} onClick={onReset} />
    </div>
  );
}