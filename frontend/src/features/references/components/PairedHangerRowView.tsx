import React from "react";
import { Badge } from "@/shared/ui/badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/shared/ui/tooltip";
import { TableCornerResetCell } from "@/shared/ui";
import { cn } from "@/shared/utils/cn";
import type { HangerCalcResult } from "@/shared/api/hangerCalc";
import { lengthKey } from "@/shared/lib/hangerQuantity";
import { LIMITER_LABELS, type PairedHangerCalcRow } from "../lib/hangerCalcRows";
import { DashCell } from "./DashCell";

const chipClass = "inline-flex items-center rounded px-1.5 py-0.5 text-xs whitespace-nowrap";

/**
 * Парная строка «A+B» в таблице «Расчёт подвесов» (#58/#67).
 * Разбивка — по первой общей длине; периметр/габарит — суммы артикулов пары.
 * Инлайн-правка полей парной строки не поддерживается (правятся одиночные).
 */
export function PairedHangerRowView({
  row,
  byLength,
}: {
  row: PairedHangerCalcRow;
  byLength: Map<string, HangerCalcResult> | undefined;
}) {
  const rowInvalid = row.incompatibleReason != null;
  const primary = row.primaryResult;

  const breakdownReason = row.incompatibleReason
    ?? (!row.auto
      ? "Ручной режим: не оба артикула авто (нет периметра/габарита)"
      : row.primaryLength == null
        ? "Расчёт невозможен: у пары нет общих длин"
        : !primary || !primary.is_calculable
          ? "Расчёт невозможен: не хватает данных"
          : null);

  const showBreakdown = row.auto && !rowInvalid && !!primary?.is_calculable;
  const isZeroTotal = showBreakdown && primary!.total === 0;
  const dashCell = <DashCell reason={breakdownReason} danger={rowInvalid} />;

  const totalCell = (() => {
    if (isZeroTotal) {
      return (
        <DashCell
          reason="Итог 0: пара не помещается по лимитам — проверьте периметр и габариты"
          danger
        />
      );
    }
    if (showBreakdown) {
      return <span className="font-medium">{primary!.total}</span>;
    }
    if (!row.auto) {
      return row.total != null
        ? <span className="text-muted-foreground">{row.total}</span>
        : <DashCell reason={breakdownReason} />;
    }
    return dashCell;
  })();

  const perimeterSum =
    row.productA.perimeter_mm != null && row.productB.perimeter_mm != null
      ? Number((row.productA.perimeter_mm + row.productB.perimeter_mm).toFixed(2))
      : null;
  const widthSum =
    row.productA.mount_width_mm != null && row.productB.mount_width_mm != null
      ? Number((row.productA.mount_width_mm + row.productB.mount_width_mm).toFixed(2))
      : null;

  return (
    <tr className={cn("hover:bg-muted/50", rowInvalid && "bg-red-50 hover:bg-red-100/60")}>
      <td className="px-4 py-2">
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="font-medium">{row.label}</span>
          {row.auto
            ? <Badge variant="secondary" className="text-xs bg-emerald-100">авто</Badge>
            : <Badge variant="secondary" className="text-xs">ручное</Badge>}
          <Badge variant="secondary" className="text-xs bg-purple-100">Парная</Badge>
        </div>
      </td>
      <td className="px-4 py-2">
        {perimeterSum != null ? (
          <span
            className="text-muted-foreground"
            title={`Сумма периметров: ${row.productA.sku} + ${row.productB.sku}`}
          >
            {perimeterSum}
          </span>
        ) : dashCell}
      </td>
      <td className="px-4 py-2">
        {widthSum != null ? (
          <span
            className="text-muted-foreground"
            title={`Сумма габаритов: ${row.productA.sku} + ${row.productB.sku}`}
          >
            {widthSum}
          </span>
        ) : dashCell}
      </td>
      <td className="px-4 py-2">
        <PairedLengthChips row={row} byLength={byLength} />
      </td>
      <td className="px-4 py-2">
        {showBreakdown ? primary!.by_area : dashCell}
      </td>
      <td className="px-4 py-2">
        {showBreakdown ? primary!.by_size : dashCell}
      </td>
      <td className="px-4 py-2">{totalCell}</td>
      <td className="px-4 py-2">
        {showBreakdown && !isZeroTotal && primary!.limiter
          ? LIMITER_LABELS[primary!.limiter]
          : dashCell}
      </td>
      <td className="px-4 py-2">
        {showBreakdown && !isZeroTotal && primary!.area_m2 != null
          ? primary!.area_m2.toFixed(3)
          : dashCell}
      </td>
      <TableCornerResetCell />
    </tr>
  );
}

function PairedLengthChips({
  row,
  byLength,
}: {
  row: PairedHangerCalcRow;
  byLength: Map<string, HangerCalcResult> | undefined;
}) {
  if (row.lengths.length === 0) {
    return <span className="text-muted-foreground">—</span>;
  }
  const primary = row.primaryLength;
  return (
    <div className="flex flex-wrap gap-1">
      {row.lengths.map((len) => {
        const key = lengthKey(len);
        const isPrimary = primary != null && len === primary;
        const primaryMark = isPrimary ? (
          <span className="ml-1 rounded bg-primary px-1 py-0.5 text-[10px] font-semibold text-primary-foreground">
            основная
          </span>
        ) : null;
        if (!row.auto) {
          return (
            <span key={key} className={cn(chipClass, isPrimary ? "bg-primary/10 ring-1 ring-primary/40" : "bg-secondary text-secondary-foreground")}>
              {len} мм → {row.perHanger ?? "—"} шт
              {primaryMark}
            </span>
          );
        }
        if (row.incompatibleReason) {
          return (
            <Tooltip key={key}>
              <TooltipTrigger asChild>
                <span className={cn(chipClass, "bg-red-100 text-red-700")}>{len} мм → —{primaryMark}</span>
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
                <span className={cn(chipClass, "bg-amber-100 text-amber-800")}>{len} мм → —{primaryMark}</span>
              </TooltipTrigger>
              <TooltipContent>Расчёт невозможен: не хватает данных</TooltipContent>
            </Tooltip>
          );
        }
        const limiterNote = result.limiter ? ` · ${LIMITER_LABELS[result.limiter]}` : "";
        return (
          <Tooltip key={key}>
            <TooltipTrigger asChild>
              <span className={cn(chipClass, isPrimary ? "bg-primary/10 ring-1 ring-primary/40" : "bg-secondary text-secondary-foreground", "cursor-help")}>
                {len} мм → {result.total ?? "—"} шт{limiterNote}
                {primaryMark}
              </span>
            </TooltipTrigger>
            <TooltipContent>
              <div className="text-xs space-y-0.5">
                <div className="font-medium">Длина {len} мм (совместно){isPrimary ? " · основная" : ""}</div>
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
