import React from "react";
import { IconSearch, IconX } from "@tabler/icons-react";
import { Input } from "./Input";
import { Button } from "./Button";
import { cn } from "@/shared/utils/cn";

export interface TableToolbarProps {
  searchQuery: string;
  onSearchChange: (q: string) => void;
  onReset: () => void;
  hasActiveFilters?: boolean;
  placeholder?: string;
  children?: React.ReactNode;
  className?: string;
}

/**
 * Toolbar with search input, reset button, and slot for custom filter controls.
 * The reset button gets a filled background when there are active filters.
 */
export function TableToolbar({
  searchQuery,
  onSearchChange,
  onReset,
  hasActiveFilters,
  placeholder = "Поиск...",
  children,
  className,
}: TableToolbarProps) {
  const active = hasActiveFilters ?? searchQuery.trim().length > 0;

  return (
    <div className={cn("flex items-center gap-3 mb-3 flex-wrap", className)}>
      <div className="relative flex-1 min-w-[200px] max-w-md">
        <IconSearch className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <Input
          type="text"
          value={searchQuery}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder={placeholder}
          className="pl-9 h-9 text-sm"
        />
      </div>
      {children}
      {active && (
        <Button
          variant="default"
          size="sm"
          className="h-8 text-sm"
          onClick={onReset}
        >
          <IconX className="h-3.5 w-3.5 mr-1" />
          Сбросить
        </Button>
      )}
      {!active && (
        <Button
          variant="ghost"
          size="sm"
          className="h-8 text-sm text-muted-foreground"
          onClick={onReset}
        >
          <IconX className="h-3.5 w-3.5 mr-1" />
          Сбросить
        </Button>
      )}
    </div>
  );
}
