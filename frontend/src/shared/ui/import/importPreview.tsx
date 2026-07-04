import { Loader2, Search, AlertCircle } from "lucide-react";

import { cn } from "@/shared/utils/cn";
import { Badge } from "../Badge";
import { Button } from "../Button";
import { Input } from "../Input";
import type { ImportRowExpansion } from "./importRawRows";
import { ImportRawRowsToggle } from "./importRawRows";

export type ImportPreviewErrorProps = {
  title?: string;
  message: string;
  className?: string;
};

export function ImportPreviewError({
  title = "Ошибка импорта",
  message,
  className,
}: ImportPreviewErrorProps) {
  if (!message) return null;

  return (
    <div
      className={cn(
        "shrink-0 flex items-start gap-2 rounded-lg border border-destructive/20 bg-destructive/10 p-3 text-xs text-destructive",
        className,
      )}
    >
      <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
      <div className="space-y-1">
        <span className="font-semibold block">{title}</span>
        <span className="leading-relaxed block whitespace-pre-wrap">{message}</span>
      </div>
    </div>
  );
}

export type ImportPreviewSheetTabsProps = {
  sheets: string[];
  selectedIndex: number;
  onSelect: (index: number) => void;
  disabled?: boolean;
  label?: string;
  size?: "sm" | "md";
  className?: string;
};

export function ImportPreviewSheetTabs({
  sheets,
  selectedIndex,
  onSelect,
  disabled,
  label,
  size = "sm",
  className,
}: ImportPreviewSheetTabsProps) {
  const btnClass =
    size === "sm"
      ? "px-2 py-0.5 text-xs rounded border transition-colors"
      : "px-3 py-1.5 text-xs rounded-md border transition-colors";

  return (
    <div className={cn("flex items-center gap-2 flex-wrap", className)}>
      {label ? (
        <span className="text-muted-foreground font-semibold uppercase text-xs">{label}</span>
      ) : null}
      <div className="flex gap-1 flex-wrap">
        {sheets.map((name, idx) => (
          <button
            key={idx}
            type="button"
            onClick={() => !disabled && onSelect(idx)}
            disabled={disabled}
            className={cn(
              btnClass,
              selectedIndex === idx
                ? "bg-primary text-primary-foreground border-primary font-medium"
                : "bg-background hover:bg-accent border-input text-foreground",
              disabled && "cursor-default opacity-90",
            )}
          >
            {name}
          </button>
        ))}
      </div>
    </div>
  );
}

export type ImportPreviewStatsProps = {
  badges?: { label: string; className?: string }[];
  children?: React.ReactNode;
  className?: string;
};

export function ImportPreviewStats({ badges, children, className }: ImportPreviewStatsProps) {
  if (!children && (!badges || badges.length === 0)) return null;

  return (
    <div className={cn("space-y-2 shrink-0", className)}>
      {children ?? (
        <div className="flex flex-wrap items-center gap-4 text-xs font-semibold">
          {badges!.map((badge, idx) => (
            <Badge key={idx} variant="outline" className={cn("bg-background px-2.5 py-1", badge.className)}>
              {badge.label}
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}

export type ImportPreviewFilterRowProps = {
  search?: string;
  onSearchChange?: (value: string) => void;
  searchPlaceholder?: string;
  filterSlot?: React.ReactNode;
  expansion?: ImportRowExpansion;
  rightSlot?: React.ReactNode;
  className?: string;
};

export function ImportPreviewFilterRow({
  search,
  onSearchChange,
  searchPlaceholder = "Поиск...",
  filterSlot,
  expansion,
  rightSlot,
  className,
}: ImportPreviewFilterRowProps) {
  const hasSearch = onSearchChange != null;
  const hasToggle = expansion != null;
  const hasRight = rightSlot != null || hasToggle;

  if (!hasSearch && !filterSlot && !hasRight) return null;

  return (
    <div className={cn("flex items-center justify-between gap-2", className)}>
      <div className="flex items-center gap-2 shrink-0">
        {hasSearch ? (
          <div className="relative">
            <Search className="absolute left-2 top-1.5 h-3.5 w-3.5 text-muted-foreground" />
            <Input
              value={search ?? ""}
              onChange={(e) => onSearchChange!(e.target.value)}
              placeholder={searchPlaceholder}
              className="h-7 pl-7 w-48 text-xs"
            />
          </div>
        ) : null}
        {filterSlot}
      </div>
      {rightSlot ??
        (hasToggle ? (
          <ImportRawRowsToggle
            active={expansion!.expandAllRaw}
            onToggle={() => expansion!.setExpandAllRaw(!expansion!.expandAllRaw)}
          />
        ) : null)}
    </div>
  );
}

export type ImportPreviewTableFrameProps = {
  loading?: boolean;
  loadingVariant?: "spinner" | "skeleton" | "custom" | "none";
  loadingContent?: React.ReactNode;
  loadingLabel?: string;
  isEmpty?: boolean;
  emptyContent?: React.ReactNode;
  onResetFilters?: () => void;
  children: React.ReactNode;
  className?: string;
};

export function ImportPreviewTableFrame({
  loading,
  loadingVariant = "spinner",
  loadingContent,
  loadingLabel = "Загрузка данных листа...",
  isEmpty,
  emptyContent,
  onResetFilters,
  children,
  className,
}: ImportPreviewTableFrameProps) {
  return (
    <div className={cn("flex-1 overflow-auto border rounded-xl bg-background", className)}>
      {loading ? (
        loadingContent ??
        (loadingVariant === "spinner" ? (
          <div className="p-8 flex flex-col items-center justify-center gap-2 text-muted-foreground h-full min-h-[200px]">
            <Loader2 className="h-6 w-6 animate-spin text-primary" />
            <span className="text-xs">{loadingLabel}</span>
          </div>
        ) : null)
      ) : isEmpty ? (
        <div className="p-8 text-center text-xs text-muted-foreground h-full flex flex-col items-center justify-center gap-2 min-h-[200px]">
          {emptyContent ?? (
            <>
              <span>Нет данных для отображения.</span>
              {onResetFilters ? (
                <Button variant="outline" size="sm" className="h-7 text-xs" onClick={onResetFilters}>
                  Сбросить фильтры
                </Button>
              ) : null}
            </>
          )}
        </div>
      ) : (
        children
      )}
    </div>
  );
}

export type ImportPreviewToolbarProps = {
  left: React.ReactNode;
  right?: React.ReactNode;
  className?: string;
};

export function ImportPreviewToolbar({ left, right, className }: ImportPreviewToolbarProps) {
  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-3 bg-muted/40 p-2.5 rounded-lg border shrink-0 text-xs",
        className,
      )}
    >
      {left}
      {right ? <div className="ml-auto flex items-center gap-2">{right}</div> : null}
    </div>
  );
}

export type ImportPreviewLayoutProps = {
  children: React.ReactNode;
  className?: string;
};

export function ImportPreviewLayout({ children, className }: ImportPreviewLayoutProps) {
  return (
    <div className={cn("h-full flex flex-col space-y-3 overflow-hidden", className)}>{children}</div>
  );
}

export const ImportPreview = {
  Layout: ImportPreviewLayout,
  Error: ImportPreviewError,
  SheetTabs: ImportPreviewSheetTabs,
  Stats: ImportPreviewStats,
  FilterRow: ImportPreviewFilterRow,
  TableFrame: ImportPreviewTableFrame,
  Toolbar: ImportPreviewToolbar,
};