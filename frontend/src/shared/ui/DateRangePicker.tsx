import { useEffect, useId, useMemo, useRef, useState } from "react";
import { addMonths } from "date-fns";
import { CalendarRange, X, Check } from "lucide-react";

import { Button } from "./Button";
import { Popover, PopoverContent, PopoverTrigger } from "./Popover";
import { cn } from "@/shared/utils/cn";
import {
  defaultDateRangePresets,
  findActivePreset,
  formatDateRu,
  formatInputDigits,
  parseRuDate,
  type DateRangePreset,
  type DateRangeValue,
} from "./date-range-presets";

const MONTH_NAMES = [
  "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
  "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
];

const WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];

export type { DateRangePreset, DateRangeValue } from "./date-range-presets";
export { defaultDateRangePresets, findActivePreset, formatDateRu, parseRuDate } from "./date-range-presets";

export interface DateRangePickerProps {
  from: string;
  to: string;
  onChange: (range: DateRangeValue) => void;
  label?: string;
  className?: string;
  disabled?: boolean;
  placeholder?: string;
  align?: "start" | "center" | "end";
  presets?: DateRangePreset[];
  minDate?: string;
  maxDate?: string;
  numberOfMonths?: 1 | 2;
}

function isoFromParts(year: number, month: number, day: number): string {
  const m = String(month + 1).padStart(2, "0");
  const d = String(day).padStart(2, "0");
  return `${year}-${m}-${d}`;
}

function getDaysInMonth(year: number, month: number): number {
  return new Date(year, month + 1, 0).getDate();
}

function getFirstDayOfMonth(year: number, month: number): number {
  const day = new Date(year, month, 1).getDay();
  return day === 0 ? 6 : day - 1;
}

function isBeforeIso(a: string, b: string): boolean {
  if (!a || !b) return false;
  return a < b;
}

function isAfterIso(a: string, b: string): boolean {
  if (!a || !b) return false;
  return a > b;
}

function inRangeIso(iso: string, from: string, to: string): boolean {
  if (!iso || !from || !to) return false;
  return iso >= from && iso <= to;
}

function dayInDisabled(iso: string, minDate?: string, maxDate?: string): boolean {
  if (minDate && iso < minDate) return true;
  if (maxDate && iso > maxDate) return true;
  return false;
}

export function DateRangePicker({
  from,
  to,
  onChange,
  label,
  className,
  disabled = false,
  placeholder = "Выберите период",
  align = "end",
  presets = defaultDateRangePresets,
  minDate,
  maxDate,
  numberOfMonths = 2,
}: DateRangePickerProps) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [pendingFrom, setPendingFrom] = useState(from);
  const [pendingTo, setPendingTo] = useState(to);
  const [hoverIso, setHoverIso] = useState<string>("");
  const [fromInput, setFromInput] = useState(formatDateRu(from));
  const [toInput, setToInput] = useState(formatDateRu(to));
  const lastSyncedRef = useRef({ from, to });

  useEffect(() => {
    if (lastSyncedRef.current.from !== from || lastSyncedRef.current.to !== to) {
      lastSyncedRef.current = { from, to };
      setPendingFrom(from);
      setPendingTo(to);
      setFromInput(formatDateRu(from));
      setToInput(formatDateRu(to));
      setHoverIso("");
    }
  }, [from, to]);

  useEffect(() => {
    if (open) {
      setPendingFrom(from);
      setPendingTo(to);
      setFromInput(formatDateRu(from));
      setToInput(formatDateRu(to));
      setHoverIso("");
    }
  }, [open, from, to]);

  const activePreset = useMemo(() => findActivePreset({ from, to }, presets), [from, to, presets]);

  const triggerLabel = useMemo(() => {
    if (activePreset) {
      const fromFmt = formatDateRu(from);
      const toFmt = formatDateRu(to);
      if (fromFmt && toFmt && fromFmt === toFmt) {
        return `${activePreset.label} · ${fromFmt}`;
      }
      if (fromFmt && toFmt) {
        return `${activePreset.label} · ${fromFmt} — ${toFmt}`;
      }
      return activePreset.label;
    }
    if (from && to) {
      return `${formatDateRu(from)} — ${formatDateRu(to)}`;
    }
    if (from) {
      return `с ${formatDateRu(from)}`;
    }
    if (to) {
      return `по ${formatDateRu(to)}`;
    }
    return "";
  }, [activePreset, from, to]);

  const hasValue = Boolean(from || to);

  function commit(next: DateRangeValue) {
    const fromIso = next.from || "";
    const toIso = next.to || "";
    const safe =
      fromIso && toIso && isAfterIso(fromIso, toIso) ? { from: toIso, to: fromIso } : next;
    onChange({ from: safe.from, to: safe.to });
  }

  function applyPreset(preset: DateRangePreset) {
    const next = preset.getRange();
    setPendingFrom(next.from);
    setPendingTo(next.to);
    setFromInput(formatDateRu(next.from));
    setToInput(formatDateRu(next.to));
    setHoverIso("");
    if (next.from || next.to) {
      onChange(next);
      setOpen(false);
    } else {
      onChange({ from: "", to: "" });
      setOpen(false);
    }
  }

  function clearAll(e?: React.SyntheticEvent) {
    e?.stopPropagation();
    setPendingFrom("");
    setPendingTo("");
    setFromInput("");
    setToInput("");
    setHoverIso("");
    onChange({ from: "", to: "" });
  }

  function handleDayClick(iso: string) {
    if (dayInDisabled(iso, minDate, maxDate)) return;

    if (!pendingFrom || (pendingFrom && pendingTo)) {
      setPendingFrom(iso);
      setPendingTo("");
      setFromInput(formatDateRu(iso));
      setToInput("");
      setHoverIso("");
      return;
    }
    if (pendingFrom && !pendingTo) {
      const nextFrom = isBeforeIso(iso, pendingFrom) ? iso : pendingFrom;
      const nextTo = isBeforeIso(iso, pendingFrom) ? pendingFrom : iso;
      setPendingFrom(nextFrom);
      setPendingTo(nextTo);
      setFromInput(formatDateRu(nextFrom));
      setToInput(formatDateRu(nextTo));
      setHoverIso("");
      onChange({ from: nextFrom, to: nextTo });
      setOpen(false);
    }
  }

  function handleDayHover(iso: string) {
    if (pendingFrom && !pendingTo) {
      setHoverIso(iso);
    }
  }

  function handleFromInputChange(raw: string) {
    const formatted = formatInputDigits(raw);
    setFromInput(formatted);
    const iso = parseRuDate(formatted);
    if (iso) {
      setPendingFrom(iso);
      if (pendingTo && isBeforeIso(pendingTo, iso)) {
        setPendingTo("");
        setToInput("");
      }
      commit({ from: iso, to: pendingTo });
    }
  }

  function handleToInputChange(raw: string) {
    const formatted = formatInputDigits(raw);
    setToInput(formatted);
    const iso = parseRuDate(formatted);
    if (iso) {
      setPendingTo(iso);
      if (pendingFrom && isAfterIso(pendingFrom, iso)) {
        setPendingFrom("");
        setFromInput("");
      }
      commit({ from: pendingFrom, to: iso });
    }
  }

  const previewFrom = pendingFrom;
  const previewTo = pendingTo || (pendingFrom && hoverIso && !isBeforeIso(hoverIso, pendingFrom) ? hoverIso : "");

  return (
    <div className={cn("relative inline-block w-full sm:w-auto", className)}>
      {label && (
        <label htmlFor={id} className="text-sm font-medium whitespace-nowrap">
          {label}
        </label>
      )}
      <Popover open={open} onOpenChange={(o) => !disabled && setOpen(o)}>
        <PopoverTrigger asChild>
          <button
            id={id}
            type="button"
            disabled={disabled}
            aria-label={label || placeholder}
            className={cn(
              "flex h-9 w-full min-w-[180px] items-center gap-2 rounded-md border border-input bg-background px-3 text-sm",
              "transition-colors hover:bg-accent/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
              disabled && "opacity-50 pointer-events-none",
              hasValue && "border-primary/40"
            )}
          >
            <CalendarRange className="h-4 w-4 shrink-0 text-muted-foreground" />
            <span className={cn("flex-1 text-left truncate", !hasValue && "text-muted-foreground")}>
              {triggerLabel || placeholder}
            </span>
            {hasValue && (
              <span
                role="button"
                aria-label="Очистить период"
                className="flex h-5 w-5 shrink-0 items-center justify-center rounded-sm text-muted-foreground hover:bg-accent hover:text-foreground cursor-pointer"
                onClick={(e) => clearAll(e)}
              >
                <X className="h-3.5 w-3.5" />
              </span>
            )}
          </button>
        </PopoverTrigger>
        <PopoverContent
          align={align}
          sideOffset={6}
          className="w-auto p-0"
          onOpenAutoFocus={(e) => e.preventDefault()}
        >
          <div className="flex flex-col sm:flex-row">
            <div className="w-full sm:w-[180px] border-b sm:border-b-0 sm:border-r border-border p-2 max-h-[280px] sm:max-h-none overflow-y-auto">
              <div className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground px-2 py-1">
                Быстрый выбор
              </div>
              <div className="flex flex-col gap-0.5">
                {presets.map((preset) => {
                  const isActive = matchesPresetLocal({ from, to }, preset);
                  return (
                    <button
                      key={preset.key}
                      type="button"
                      onClick={() => applyPreset(preset)}
                      className={cn(
                        "flex items-center justify-between gap-2 rounded-sm px-2 py-1.5 text-left text-sm transition-colors",
                        "hover:bg-accent hover:text-accent-foreground",
                        isActive && "bg-primary/10 text-primary font-medium hover:bg-primary/15"
                      )}
                    >
                      <span className="truncate">{preset.label}</span>
                      {isActive && <Check className="h-3.5 w-3.5 shrink-0" />}
                    </button>
                  );
                })}
              </div>
            </div>

            <div className="p-3 flex-1">
              <MonthGrid
                count={numberOfMonths}
                startMonthDate={getAnchorMonth(from, to)}
                previewFrom={previewFrom}
                previewTo={previewTo}
                committedFrom={from}
                committedTo={to}
                minDate={minDate}
                maxDate={maxDate}
                onDayClick={handleDayClick}
                onDayHover={handleDayHover}
                onDayLeave={() => setHoverIso("")}
              />

              <div className="mt-3 flex items-end gap-2 border-t border-border pt-3">
                <div className="flex-1 min-w-0">
                  <label className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                    Начало
                  </label>
                  <input
                    type="text"
                    inputMode="numeric"
                    value={fromInput}
                    onChange={(e) => handleFromInputChange(e.target.value)}
                    placeholder="ДД.ММ.ГГГГ"
                    className="mt-0.5 flex h-8 w-full rounded-md border border-input bg-background px-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1"
                    maxLength={10}
                  />
                </div>
                <span className="pb-2 text-muted-foreground">—</span>
                <div className="flex-1 min-w-0">
                  <label className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                    Конец
                  </label>
                  <input
                    type="text"
                    inputMode="numeric"
                    value={toInput}
                    onChange={(e) => handleToInputChange(e.target.value)}
                    placeholder="ДД.ММ.ГГГГ"
                    className="mt-0.5 flex h-8 w-full rounded-md border border-input bg-background px-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1"
                    maxLength={10}
                  />
                </div>
              </div>

              <div className="mt-3 flex items-center justify-between gap-2 border-t border-border pt-2">
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-8 text-xs"
                  onClick={(e) => clearAll(e)}
                >
                  Сбросить
                </Button>
                <span className="text-[11px] text-muted-foreground">
                  Выбор применяется автоматически
                </span>
              </div>
            </div>
          </div>
        </PopoverContent>
      </Popover>
    </div>
  );
}

function matchesPresetLocal(range: DateRangeValue, preset: DateRangePreset): boolean {
  const expected = preset.getRange();
  if (preset.key === "all") return !range.from && !range.to;
  return range.from === expected.from && range.to === expected.to;
}

function getAnchorMonth(from: string, to: string): Date {
  const iso = from || to;
  if (iso) {
    const [y, m] = iso.split("-").map(Number);
    if (y && m) return new Date(y, m - 1, 1);
  }
  const now = new Date();
  return new Date(now.getFullYear(), now.getMonth(), 1);
}

interface MonthGridProps {
  count: 1 | 2;
  startMonthDate: Date;
  previewFrom: string;
  previewTo: string;
  committedFrom: string;
  committedTo: string;
  minDate?: string;
  maxDate?: string;
  onDayClick: (iso: string) => void;
  onDayHover: (iso: string) => void;
  onDayLeave: () => void;
}

function MonthGrid({
  count,
  startMonthDate,
  previewFrom,
  previewTo,
  committedFrom,
  committedTo,
  minDate,
  maxDate,
  onDayClick,
  onDayHover,
  onDayLeave,
}: MonthGridProps) {
  const [offset, setOffset] = useState(0);
  const baseMonth = useMemo(() => addMonths(startMonthDate, offset), [startMonthDate, offset]);

  const months = useMemo(() => {
    const arr: Date[] = [];
    for (let i = 0; i < count; i++) {
      arr.push(addMonths(baseMonth, i));
    }
    return arr;
  }, [count, baseMonth]);

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between mb-1">
        <button
          type="button"
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            setOffset((o) => o - 1);
          }}
          className="h-7 w-7 inline-flex items-center justify-center rounded-md text-primary hover:bg-accent"
          aria-label="Предыдущий месяц"
        >
          ‹
        </button>
        <span className="text-xs text-muted-foreground">
          {months
            .map((m) => `${MONTH_NAMES[m.getMonth()]} ${m.getFullYear()}`)
            .join(" — ")}
        </span>
        <button
          type="button"
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            setOffset((o) => o + 1);
          }}
          className="h-7 w-7 inline-flex items-center justify-center rounded-md text-primary hover:bg-accent"
          aria-label="Следующий месяц"
        >
          ›
        </button>
      </div>
      <div className={cn("grid gap-3", count === 2 ? "sm:grid-cols-2" : "grid-cols-1")}>
        {months.map((m, i) => (
          <MonthCalendar
            key={i}
            monthDate={m}
            previewFrom={previewFrom}
            previewTo={previewTo}
            committedFrom={committedFrom}
            committedTo={committedTo}
            minDate={minDate}
            maxDate={maxDate}
            onDayClick={onDayClick}
            onDayHover={onDayHover}
            onDayLeave={onDayLeave}
          />
        ))}
      </div>
    </div>
  );
}

interface MonthCalendarProps {
  monthDate: Date;
  previewFrom: string;
  previewTo: string;
  committedFrom: string;
  committedTo: string;
  minDate?: string;
  maxDate?: string;
  onDayClick: (iso: string) => void;
  onDayHover: (iso: string) => void;
  onDayLeave: () => void;
}

function MonthCalendar({
  monthDate,
  previewFrom,
  previewTo,
  committedFrom,
  committedTo,
  minDate,
  maxDate,
  onDayClick,
  onDayHover,
  onDayLeave,
}: MonthCalendarProps) {
  const year = monthDate.getFullYear();
  const month = monthDate.getMonth();
  const daysInMonth = getDaysInMonth(year, month);
  const firstDay = getFirstDayOfMonth(year, month);
  const showPreview = Boolean(previewFrom && previewTo && previewFrom !== committedFrom);

  return (
    <div>
      <div className="text-center text-xs font-semibold mb-1">
        {MONTH_NAMES[month]} {year}
      </div>
      <div className="grid grid-cols-7 gap-0.5 mb-1 text-center">
        {WEEKDAYS.map((d) => (
          <div key={d} className="text-[10px] font-semibold text-muted-foreground py-1">
            {d}
          </div>
        ))}
      </div>
      <div className="grid grid-cols-7 gap-0.5">
        {Array.from({ length: firstDay }).map((_, i) => (
          <div key={`empty-${i}`} className="aspect-square" />
        ))}
        {Array.from({ length: daysInMonth }).map((_, i) => {
          const day = i + 1;
          const iso = isoFromParts(year, month, day);
          const disabled = dayInDisabled(iso, minDate, maxDate);
          const isStart = iso === committedFrom;
          const isEnd = iso === committedTo;
          const inRange = inRangeIso(iso, committedFrom, committedTo);
          const inPreview = showPreview && inRangeIso(iso, previewFrom, previewTo);
          return (
            <button
              key={day}
              type="button"
              disabled={disabled}
              onClick={() => onDayClick(iso)}
              onMouseEnter={() => onDayHover(iso)}
              onMouseLeave={onDayLeave}
              className={cn(
                "relative aspect-square flex items-center justify-center text-xs transition-colors",
                "hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                disabled && "opacity-30 cursor-not-allowed hover:bg-transparent",
                inRange && "bg-primary/15 text-primary",
                inPreview && "bg-primary/10",
                isStart && isEnd && "rounded-md bg-primary text-primary-foreground hover:bg-primary",
                isStart && !isEnd && "rounded-l-md rounded-r-none bg-primary text-primary-foreground hover:bg-primary",
                isEnd && !isStart && "rounded-r-md rounded-l-none bg-primary text-primary-foreground hover:bg-primary",
                !isStart && !isEnd && "rounded-md"
              )}
            >
              {day}
            </button>
          );
        })}
      </div>
    </div>
  );
}
