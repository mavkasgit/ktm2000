import React from "react";
import { Badge } from "@/shared/ui/badge";
import { TableCornerResetCell } from "@/shared/ui";
import { cn } from "@/shared/utils/cn";
import { fmtQtyPrecise } from "@/shared/lib/quantityFormat";
import { LIMITER_LABELS, type HangerLengthLine, type PairedHangerCalcRow } from "../lib/hangerCalcRows";
import { DashCell } from "./DashCell";
import { HangerLineCell } from "./HangerLineCell";

/** Причина нулевого итога подстроки: пара не помещается по лимитам. */
const ZERO_TOTAL_REASON = "Итог 0: пара не помещается по лимитам — проверьте периметр и габариты";

/**
 * Парная строка A+B: одна на пару, внутри — подстроки по длинам пары
 * (ADR-0050). Правило то же, что у одиночной строки: разбивка печатается
 * по каждой длине, потому что считается от сырьевой длины этой подстроки.
 */
export function PairedHangerRowView({ row }: { row: PairedHangerCalcRow }) {
  const rowInvalid = row.incompatibleReason != null;
  const span = row.lines.length;

  const totalCell = (line: HangerLengthLine) => {
    if (line.total === 0) return <DashCell reason={ZERO_TOTAL_REASON} danger />;
    if (line.total != null) return <span className="font-medium">{fmtQtyPrecise(line.total)}</span>;
    return <DashCell reason={line.totalReason} danger={rowInvalid} />;
  };
  const breakdownCell = (line: HangerLengthLine, value: number | null | undefined) =>
    line.result ? fmtQtyPrecise(value) : <DashCell reason={line.breakdownReason} danger={rowInvalid} />;
  const limiterCell = (line: HangerLengthLine) =>
    line.result && line.total !== 0 && line.result.limiter
      ? LIMITER_LABELS[line.result.limiter]
      : <DashCell reason={line.breakdownReason} danger={rowInvalid} />;
  const areaCell = (line: HangerLengthLine) =>
    line.result && line.total !== 0 && line.result.area_m2 != null
      ? line.result.area_m2.toFixed(3)
      : <DashCell reason={line.breakdownReason} danger={rowInvalid} />;

  return (
    <tr className={cn("hover:bg-muted/50", rowInvalid && "bg-red-50 hover:bg-red-100/60")}>
      <td rowSpan={span} className="px-4 py-1 align-top">
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="font-medium">{row.label}</span>
          {row.auto ? <Badge variant="secondary" className="text-xs bg-emerald-100">авто</Badge> : <Badge variant="secondary" className="text-xs">ручное</Badge>}
          <Badge variant="secondary" className="text-xs bg-purple-100">Парная</Badge>
        </div>
      </td>
      <td rowSpan={span} className="px-4 py-1 align-top">
        {row.perimeterSum != null ? <span className="text-muted-foreground">{row.perimeterSum}</span> : <DashCell reason={row.incompatibleReason} danger={rowInvalid} />}
      </td>
      <td rowSpan={span} className="px-4 py-1 align-top">
        {row.widthSum != null ? <span className="text-muted-foreground">{row.widthSum}</span> : <DashCell reason={row.incompatibleReason} danger={rowInvalid} />}
      </td>
      <HangerLineCell
        lines={row.lines}
        render={(line) => (
          <span className="whitespace-nowrap">
            {line.lengthLabel}
            {line.isPrimary && (
              <span className="ml-1.5 rounded bg-primary px-1 py-0.5 text-[10px] font-semibold text-primary-foreground">основная</span>
            )}
          </span>
        )}
      />
      <HangerLineCell lines={row.lines} render={(line) => breakdownCell(line, line.result?.by_area)} />
      <HangerLineCell lines={row.lines} render={(line) => breakdownCell(line, line.result?.by_size)} />
      <HangerLineCell lines={row.lines} render={totalCell} />
      <HangerLineCell lines={row.lines} render={limiterCell} />
      <HangerLineCell lines={row.lines} render={areaCell} />
      <TableCornerResetCell />
    </tr>
  );
}
