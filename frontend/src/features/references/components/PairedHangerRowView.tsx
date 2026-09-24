import React from "react";
import { Badge } from "@/shared/ui/badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/shared/ui/tooltip";
import { TableCornerResetCell } from "@/shared/ui";
import { cn } from "@/shared/utils/cn";
import type { HangerCalcResult } from "@/shared/api/hangerCalc";
import { effectiveRawLength, lengthKey } from "@/shared/lib/hangerQuantity";
import { LIMITER_LABELS, type PairedHangerCalcRow } from "../lib/hangerCalcRows";
import { DashCell } from "./DashCell";

const chipClass = "inline-flex items-center rounded px-1.5 py-0.5 text-xs whitespace-nowrap";

export function PairedHangerRowView({ row, byLength }: { row: PairedHangerCalcRow; byLength: Map<string, HangerCalcResult> | undefined }) {
  const rowInvalid = row.incompatibleReason != null;
  const primary = row.primaryResult;
  const breakdownReason = row.incompatibleReason ?? (!row.auto ? "Ручной режим: не оба артикула в режиме авто" : row.primaryLength == null ? "Расчёт невозможен: у пары нет общих длин" : !primary || !primary.is_calculable ? "Расчёт невозможен: не хватает данных" : null);
  const showBreakdown = row.auto && !rowInvalid && !!primary?.is_calculable;
  const isZeroTotal = showBreakdown && primary!.total === 0;
  const dashCell = <DashCell reason={breakdownReason} danger={rowInvalid} />;
  const totalCell = isZeroTotal ? <DashCell reason="Итог 0: пара не помещается по лимитам — проверьте периметр и габариты" danger /> : showBreakdown ? <span className="font-medium">{primary!.total}</span> : !row.auto ? row.total != null ? <span className="text-muted-foreground">{row.total}</span> : <DashCell reason={breakdownReason} /> : dashCell;
  return <tr className={cn("hover:bg-muted/50", rowInvalid && "bg-red-50 hover:bg-red-100/60")}>
    <td className="px-4 py-2"><div className="flex items-center gap-1.5 flex-wrap"><span className="font-medium">{row.label}</span>{row.auto ? <Badge variant="secondary" className="text-xs bg-emerald-100">авто</Badge> : <Badge variant="secondary" className="text-xs">ручное</Badge>}<Badge variant="secondary" className="text-xs bg-purple-100">Парная</Badge></div></td>
    <td className="px-4 py-2">{row.perimeterSum != null ? <span className="text-muted-foreground">{row.perimeterSum}</span> : dashCell}</td>
    <td className="px-4 py-2">{row.widthSum != null ? <span className="text-muted-foreground">{row.widthSum}</span> : dashCell}</td>
    <td className="px-4 py-2"><PairedLengthChips row={row} byLength={byLength} /></td>
    <td className="px-4 py-2">{showBreakdown ? primary!.by_area : dashCell}</td>
    <td className="px-4 py-2">{showBreakdown ? primary!.by_size : dashCell}</td>
    <td className="px-4 py-2">{totalCell}</td>
    <td className="px-4 py-2">{showBreakdown && !isZeroTotal && primary!.limiter ? LIMITER_LABELS[primary!.limiter] : dashCell}</td>
    <td className="px-4 py-2">{showBreakdown && !isZeroTotal && primary!.area_m2 != null ? primary!.area_m2.toFixed(3) : dashCell}</td>
    <TableCornerResetCell />
  </tr>;
}

function PairedLengthChips({ row, byLength }: { row: PairedHangerCalcRow; byLength: Map<string, HangerCalcResult> | undefined }) {
  if (row.lengths.length === 0) return <span className="text-muted-foreground">—</span>;
  const primary = row.primaryLength;
  return <div className="flex flex-wrap gap-1">{row.lengths.map((len) => {
    const key = lengthKey(len);
    const recordA = (row.productA.lengths ?? []).find((length) => length.length_mm === len);
    const recordB = (row.productB.lengths ?? []).find((length) => length.length_mm === len);
    const rawA = recordA ? effectiveRawLength(recordA) : len;
    const rawB = recordB ? effectiveRawLength(recordB) : len;
    const isPrimary = primary != null && len === primary;
    const primaryMark = isPrimary ? <span className="ml-1 rounded bg-primary px-1 py-0.5 text-[10px] font-semibold text-primary-foreground">основная</span> : null;
    const label = rawA !== rawB ? `${len} / сырьё ${rawA} и ${rawB}` : recordA?.raw_length_mm != null ? `${len} / сырьё ${rawA}` : `${len}`;
    if (!row.auto) return <span key={key} className={cn(chipClass, isPrimary ? "bg-primary/10 ring-1 ring-primary/40" : "bg-secondary text-secondary-foreground")}>{label} мм → {row.manualPerLength[key] ?? "—"} шт{primaryMark}</span>;
    if (row.incompatibleReason) return <Tooltip key={key}><TooltipTrigger asChild><span className={cn(chipClass, "bg-red-100 text-red-700")}>{label} мм → —{primaryMark}</span></TooltipTrigger><TooltipContent>{row.incompatibleReason}</TooltipContent></Tooltip>;
    const result = byLength?.get(key);
    if (!result || !result.is_calculable) return <Tooltip key={key}><TooltipTrigger asChild><span className={cn(chipClass, "bg-amber-100 text-amber-800")}>{label} мм → —{primaryMark}</span></TooltipTrigger><TooltipContent>Расчёт невозможен: не хватает данных</TooltipContent></Tooltip>;
    return <Tooltip key={key}><TooltipTrigger asChild><span className={cn(chipClass, isPrimary ? "bg-primary/10 ring-1 ring-primary/40" : "bg-secondary text-secondary-foreground", "cursor-help")}>{label} мм → {result.total ?? "—"} шт{primaryMark}</span></TooltipTrigger><TooltipContent><div className="text-xs space-y-0.5"><div>Нормальная: {len} мм</div><div>Сырьё: {rawA} / {rawB} мм</div><div>Итог: {result.total ?? "—"}</div></div></TooltipContent></Tooltip>;
  })}</div>;
}
