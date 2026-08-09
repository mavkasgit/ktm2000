import React from "react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/shared/ui/tooltip";
import { cn } from "@/shared/utils/cn";
import type { HangerCalcResult } from "@/shared/api/hangerCalc";
import { entryForLength, lengthKey } from "@/shared/lib/hangerQuantity";
import { LIMITER_LABELS, type HangerCalcRow } from "../lib/hangerCalcRows";

const chipClass = "inline-flex items-center rounded px-1.5 py-0.5 text-xs whitespace-nowrap";

export function LengthChips({
  row,
  byLength,
}: {
  row: HangerCalcRow;
  byLength: Map<string, HangerCalcResult> | undefined;
}) {
  if (row.lengths.length === 0) {
    return <span className="text-muted-foreground">—</span>;
  }
  return (
    <div className="flex flex-wrap gap-1">
      {row.lengths.map((len) => {
        const key = lengthKey(len);
        if (!row.auto) {
          const manual = entryForLength(row.product.quantity_per_hanger, len)?.manual ?? null;
          return (
            <span key={key} className={cn(chipClass, "bg-secondary text-secondary-foreground")}>
              {len} мм → {manual ?? "—"} шт
            </span>
          );
        }
        if (row.incompatibleReason) {
          return (
            <Tooltip key={key}>
              <TooltipTrigger asChild>
                <span className={cn(chipClass, "bg-red-100 text-red-700")}>{len} мм → —</span>
              </TooltipTrigger>
              <TooltipContent>{row.incompatibleReason}</TooltipContent>
            </Tooltip>
          );
        }
        const result = byLength?.get(key);
        if (!result || !result.is_calculable) {
          return (
            <Tooltip key={key}>
              <TooltipTrigger asChild>
                <span className={cn(chipClass, "bg-amber-100 text-amber-800")}>{len} мм → —</span>
              </TooltipTrigger>
              <TooltipContent>Расчёт невозможен: не хватает данных</TooltipContent>
            </Tooltip>
          );
        }
        const limiterNote = result.limiter ? ` · ${LIMITER_LABELS[result.limiter]}` : "";
        return (
          <Tooltip key={key}>
            <TooltipTrigger asChild>
              <span className={cn(chipClass, "bg-secondary text-secondary-foreground cursor-help")}>
                {len} мм → {result.total ?? "—"} шт{limiterNote}
              </span>
            </TooltipTrigger>
            <TooltipContent>
              <div className="text-xs space-y-0.5">
                <div className="font-medium">Длина {len} мм</div>
                <div>По площади: {result.by_area ?? "—"}</div>
                <div>По размеру: {result.by_size ?? "—"}</div>
                <div>Итог: {result.total ?? "—"}</div>
                <div>Лимитер: {result.limiter ? LIMITER_LABELS[result.limiter] : "—"}</div>
                <div>Площадь: {result.area_m2 != null ? `${result.area_m2.toFixed(3)} м²` : "—"}</div>
              </div>
            </TooltipContent>
          </Tooltip>
        );
      })}
    </div>
  );
}
